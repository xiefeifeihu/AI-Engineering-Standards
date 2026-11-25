from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

from tests.test_baseline_sync_and_approval_governance import _copy_minimal_valid_project

from tools.standards_sync.cli import resolve_locked_standards_ref
from tools.standards_sync.core import (
    DEFAULT_OFFICIAL_REPO,
    analyze_consumer_impact,
    discover_latest_official_tag,
    deep_diff_schema,
    verify_consumer_ci_gate,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload):
        if isinstance(payload, bytes):
            self.payload = payload
        elif isinstance(payload, str):
            self.payload = payload.encode("utf-8")
        else:
            self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class ConsumerIntegrationContractTests(unittest.TestCase):
    def test_std020_git_helpers_preserve_non_ancestor_exit_code_semantics(self) -> None:
        import subprocess
        from unittest.mock import patch
        from tools.standards_sync import core as sync_core
        from tools import generate_engineering_baseline as baseline_gen
        from tools import generate_handoff as handoff_gen

        for module in (sync_core, baseline_gen, handoff_gen):
            with self.subTest(module=module.__name__, failure="execution_error"):
                with patch.object(module.subprocess, "run", side_effect=OSError("git executable unavailable")):
                    result = module.run_git(ROOT, ["merge-base", "--is-ancestor", "a" * 40, "b" * 40])
                self.assertEqual(result[0], 128, result)
            with self.subTest(module=module.__name__, failure="timeout"):
                timeout = subprocess.TimeoutExpired(cmd="git", timeout=1)
                with patch.object(module.subprocess, "run", side_effect=timeout):
                    result = module.run_git(ROOT, ["merge-base", "--is-ancestor", "a" * 40, "b" * 40])
                self.assertEqual(result[0], 124, result)

    def test_std020_missing_remote_git_object_is_not_false_non_ancestor(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import run_git as real_run_git

        refs = {
            "refs/heads/main": "0b309b82c37acdf6236296987a55de169f5ece30",
            "refs/tags/v3.0.0": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
            "refs/tags/v3.0.0^{}": "8b223019c254e0edeb94576b94af46c1e48b0316",
        }
        def simulated_git(repo, args, **kwargs):
            if args[:2] == ["merge-base", "--is-ancestor"]:
                return 128, "", "fatal: Not a valid commit name"
            return real_run_git(repo, args, **kwargs)
        with patch("tools.standards_sync.core.query_remote_ls_remote", return_value=("PASS", refs, "")):
            with patch("tools.standards_sync.core.run_git", side_effect=simulated_git):
                res = discover_latest_official_tag(standards_root=ROOT)
        self.assertEqual(res["status"], "NOT_VERIFIABLE", res)
        self.assertIn("MAIN_ANCESTRY_NOT_VERIFIABLE", res["reason"])
        self.assertNotIn("NOT_ON_MAIN_BRANCH", res["reason"])

    def test_std020_real_non_ancestor_remains_blocked(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import run_git as real_run_git
        refs = {
            "refs/heads/main": "0b309b82c37acdf6236296987a55de169f5ece30",
            "refs/tags/v3.0.0": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
            "refs/tags/v3.0.0^{}": "8b223019c254e0edeb94576b94af46c1e48b0316",
        }
        def simulated_git(repo, args, **kwargs):
            if args[:2] == ["merge-base", "--is-ancestor"]:
                return 1, "", ""
            return real_run_git(repo, args, **kwargs)
        with patch("tools.standards_sync.core.query_remote_ls_remote", return_value=("PASS", refs, "")):
            with patch("tools.standards_sync.core.run_git", side_effect=simulated_git):
                res = discover_latest_official_tag(standards_root=ROOT)
        self.assertEqual(res["status"], "BLOCK", res)
        self.assertIn("NOT_ON_MAIN_BRANCH", res["reason"])

    def test_std020_local_clone_never_claims_canonical_remote_main(self) -> None:
        from unittest.mock import patch
        refs = {
            "refs/heads/main": "8b223019c254e0edeb94576b94af46c1e48b0316",
            "refs/tags/v3.0.0": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
            "refs/tags/v3.0.0^{}": "8b223019c254e0edeb94576b94af46c1e48b0316",
        }
        with patch("tools.standards_sync.core.query_remote_ls_remote", return_value=("PASS", refs, "")):
            with patch("tools.standards_sync.core.check_remote_main_ci", return_value=("PASS", 42996232217, "CI confirmed")):
                res = discover_latest_official_tag(standards_root=ROOT, remote_url=str(ROOT))
        self.assertEqual(res["status"], "NOT_VERIFIABLE", res)
        self.assertEqual(res["remote_latest_status"], "NOT_VERIFIABLE")
        self.assertEqual(res["discovery_mode"], "LOCAL_CLONE_DISCOVERY")
        self.assertEqual(res["observed_main_source"], "LOCAL_CLONE_REFS")
        self.assertFalse(res["canonical_remote_verified"])

    def test_std020_guidance_scan_reports_pins_with_line_locations(self) -> None:
        from tools.standards_sync.core import scan_consumer_guidance_files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text(
                "Standards v2.11.0 is pinned\n"
                "standards commit 5e17c0ef560ab8abafe880b988d70f85f380a104\n"
                "Tools D:\\Projects\\AI-Engineering-Standards\\tools\n",
                encoding="utf-8",
            )
            (root / "CLAUDE.md").write_text(
                "Read AGENTS.md and standards.lock.json\n", encoding="utf-8"
            )
            report = scan_consumer_guidance_files(root)
        codes = {(f["file"], f["line"], f["code"]) for f in report["findings"]}
        self.assertIn(("AGENTS.md", 1, "HARDCODED_STANDARDS_VERSION"), codes)
        self.assertIn(("AGENTS.md", 2, "HARDCODED_STANDARDS_COMMIT"), codes)
        self.assertIn(("AGENTS.md", 3, "MACHINE_ABSOLUTE_PATH"), codes)
        self.assertIn(("AGENTS.md", 1, "MISSING_LOCK_REFERENCE"), codes)
        self.assertNotIn("CLAUDE.md", report["hardcoded"])

    def test_std020_guidance_scan_ignores_historical_references(self) -> None:
        from tools.standards_sync.core import scan_consumer_guidance_files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text(
                "<!-- Standards v2.10.0 comment ignored -->\n"
                "历史版本说明：过去使用 v2.11.0 锁定 (commit 5e17c0ef560ab8abafe880b988d70f85f380a104)\n"
                "遵循 standards.lock.json 锁定约束。\n",
                encoding="utf-8",
            )
            (root / "CLAUDE.md").write_text(
                "Read AGENTS.md and standards.lock.json\n", encoding="utf-8"
            )
            report = scan_consumer_guidance_files(root)
        self.assertEqual(report["hardcoded"], [])
        self.assertEqual(report["findings"], [])

    def test_std020_guidance_scan_handles_multiline_comments_and_custom_absolute_paths(self) -> None:
        from tools.standards_sync.core import scan_consumer_guidance_files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text(
                "<!--\n"
                "Standards v2.11.0 is historical text inside a block comment\n"
                "D:\\Projects\\AI-Engineering-Standards\\.standards\n"
                "-->\n"
                "Read standards.lock.json\n"
                "Custom checkout: C:\\Work\\AI-Engineering-Standards\\.standards\n"
                "UNC checkout: \\\\buildhost\\share\n",
                encoding="utf-8",
            )
            (root / "CLAUDE.md").write_text(
                "Read AGENTS.md and standards.lock.json\n", encoding="utf-8"
            )
            report = scan_consumer_guidance_files(root)
        findings = {(f["file"], f["line"], f["code"]) for f in report["findings"]}
        self.assertIn(("AGENTS.md", 6, "MACHINE_ABSOLUTE_PATH"), findings)
        self.assertIn(("AGENTS.md", 7, "MACHINE_ABSOLUTE_PATH"), findings)
        self.assertNotIn(("AGENTS.md", 2, "HARDCODED_STANDARDS_VERSION"), findings)
        self.assertNotIn(("AGENTS.md", 3, "MACHINE_ABSOLUTE_PATH"), findings)
        self.assertNotIn(("AGENTS.md", 1, "MISSING_LOCK_REFERENCE"), findings)

    def test_std020_dirty_consumer_worktree_is_not_verified(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync import core as sync_core
        real_run_git = sync_core.run_git
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def simulated_run_git(repo, args, **kwargs):
                if Path(repo).resolve() == root.resolve():
                    if args == ["rev-parse", "HEAD"]:
                        return 0, "a" * 40, ""
                    if args == ["status", "--porcelain"]:
                        return 0, " M docs/README.md", ""
                return real_run_git(repo, args, **kwargs)
            with patch("tools.standards_sync.core.run_git", side_effect=simulated_run_git):
                with patch("tools.standards_sync.core.run_collection_validation", return_value=(True, [])):
                    result = analyze_consumer_impact(
                        root, from_ref="v2.11.0", to_ref="v3.0.0", standards_root=ROOT
                    )
        self.assertEqual(result["CONSUMER_COMMIT"], "a" * 40)
        self.assertEqual(result["CONSUMER_WORKTREE_STATUS"], "DIRTY")
        self.assertEqual(result["CONSUMER_VERIFICATION_STATUS"], "NOT_VERIFIABLE")
        self.assertEqual(result["analysis_status"], "PARTIAL")
        self.assertNotEqual(result["compatibility_status"], "COMPATIBLE")

    def test_std020_historical_snapshot_requires_verified_ancestry(self) -> None:
        from unittest.mock import patch
        from tools import generate_engineering_baseline as baseline_gen
        from tools import generate_handoff as handoff_gen

        local_sha = "a" * 40
        remote_sha = "b" * 40
        branch_tip = "c" * 40
        current_branch = "feature/std-020-review"
        captured_at = "2020-01-01T00:00:00Z"
        tick = chr(96)
        baseline_text = (
            "## 8. Git 分支及 Commit 身份 (" + tick + "git_identity" + tick + ")\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-release-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{local_sha}{tick}\n"
            f"- **远端 main ({tick}remote_main_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 9. 最近 CI 事实\n"
            "### 19.3 Std-019 正式发布收口事实与治理追踪\n"
            f"- **发布状态**：{tick}RELEASE_STATUS=RELEASED{tick}\n"
            f"- **Git 快照观测时间**：{tick}{captured_at}{tick}\n"
        )
        handoff_text = (
            "TASK_ID=Std-019-V3-0-0-POST-RELEASE-CLOSEOUT\n"
            "STATUS=COMPLETED\n"
            f"CAPTURED_AT={captured_at}\n"
            "## 1. 当前 Git 状态与分支身份 (git_state)\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-release-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{local_sha}{tick}\n"
            f"- **远端 main ({tick}remote_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 2. 当前 Standards 锁定\n"
        )
        for module, kind, content in (
            (baseline_gen, "baseline", baseline_text),
            (handoff_gen, "handoff", handoff_text),
        ):
            for merge_base_rc, expected_code in ((1, "HISTORICAL_ANCESTRY_MISMATCH"), (128, "HISTORICAL_ANCESTRY_NOT_VERIFIABLE")):
                with self.subTest(generator=kind, merge_base_rc=merge_base_rc):
                    with tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        if kind == "baseline":
                            (root / "engineering-manifest.yaml").write_text(
                                "project:\n  id: ai-engineering-standards\n", encoding="utf-8"
                            )
                        def simulated_run_git(repo, args, **kwargs):
                            if args and args[0] == "merge-base":
                                return merge_base_rc, "fatal: missing commit object" if merge_base_rc == 128 else ""
                            if args and args[0] == "log":
                                return 0, "d" * 40 if args[-1] == branch_tip else "e" * 40
                            return 0, "", ""
                        with patch.object(module, "query_remote_main_head", return_value=remote_sha):
                            with patch.object(module, "resolve_snapshot_branch_tip", return_value=branch_tip):
                                with patch.object(module, "resolve_snapshot_branch_name", return_value=current_branch):
                                    with patch.object(module, "run_git", side_effect=simulated_run_git):
                                        errors = module.verify_git_snapshot_facts(root, content, kind)
                    self.assertTrue(any(expected_code in e for e in errors), errors)
                    self.assertTrue(any("GIT_SNAPSHOT_STALE" in e for e in errors), errors)

    def test_std020_historical_snapshot_accepts_exact_current_branch_head(self) -> None:
        from unittest.mock import patch
        from tools import generate_engineering_baseline as baseline_gen
        from tools import generate_handoff as handoff_gen

        local_sha = "a" * 40
        remote_sha = "b" * 40
        captured_at = "2020-01-01T00:00:00Z"
        tick = chr(96)
        baseline_text = (
            "## 8. Git 分支及 Commit 身份 (" + tick + "git_identity" + tick + ")\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-release-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{local_sha}{tick}\n"
            f"- **远端 main ({tick}remote_main_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 9. 最近 CI 事实\n"
            "### 19.3 Std-019 正式发布收口事实与治理追踪\n"
            f"- **发布状态**：{tick}RELEASE_STATUS=RELEASED{tick}\n"
            f"- **Git 快照观测时间**：{tick}{captured_at}{tick}\n"
        )
        handoff_text = (
            "TASK_ID=Std-019-V3-0-0-POST-RELEASE-CLOSEOUT\n"
            "STATUS=COMPLETED\n"
            f"CAPTURED_AT={captured_at}\n"
            "## 1. 当前 Git 状态与分支身份 (git_state)\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-release-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{local_sha}{tick}\n"
            f"- **远端 main ({tick}remote_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 2. 当前 Standards 锁定\n"
        )
        for module, kind, content in (
            (baseline_gen, "baseline", baseline_text),
            (handoff_gen, "handoff", handoff_text),
        ):
            with self.subTest(generator=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    if kind == "baseline":
                        (root / "engineering-manifest.yaml").write_text(
                            "project:\n  id: ai-engineering-standards\n", encoding="utf-8"
                        )
                    def simulated_run_git(repo, args, **kwargs):
                        if args and args[0] == "log":
                            return 0, local_sha if args[-1] == local_sha else remote_sha
                        raise AssertionError(f"Unexpected Git call for exact HEAD ancestry: {args}")
                    with patch.object(module, "query_remote_main_head", return_value=remote_sha):
                        with patch.object(module, "resolve_snapshot_branch_tip", return_value=local_sha):
                            with patch.object(module, "resolve_snapshot_branch_name", return_value="feature/current"):
                                with patch.object(module, "run_git", side_effect=simulated_run_git):
                                    errors = module.verify_git_snapshot_facts(root, content, kind)
                self.assertEqual(errors, [], errors)

    def test_std020_baseline_and_handoff_verify_only_succeeds_on_ancestor_feature_branch(self) -> None:
        import subprocess
        import sys
        res_b = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "generate_engineering_baseline.py"), "--project-root", str(ROOT), "--verify-only"],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(res_b.returncode, 0, f"Baseline verify-only failed: {res_b.stdout} {res_b.stderr}")
        self.assertIn("[PASS]", res_b.stdout)

        res_h = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "generate_handoff.py"), "--project-root", str(ROOT), "--task-id", "Std-020-CONSUMER-FEEDBACK-TOOLCHAIN-REMEDIATION", "--verify-only"],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(res_h.returncode, 0, f"Handoff verify-only failed: {res_h.stdout} {res_h.stderr}")
        self.assertIn("[PASS]", res_h.stdout)

    def test_f17_mainline_snapshot_first_parent_real_merge_graph_and_negative(self) -> None:
        """F17: Real Git repo with merge commit M(first-parent=A, second-parent=B) proves
        --first-parent recovers mainline A at captured_at while rejecting B as remote_main_head.
        """
        from datetime import datetime, timedelta, timezone
        from tools import generate_engineering_baseline as baseline_gen
        from tools import generate_handoff as handoff_gen

        now = datetime.now(timezone.utc).replace(microsecond=0)
        ts_a = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_b = (now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
        captured_at = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_m = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            remote_repo = tmp_path / "origin.git"
            local_repo = tmp_path / "local"
            subprocess.run(["git", "init", "--bare", "-q", str(remote_repo)], check=True)
            subprocess.run(["git", "init", "-q", "-b", "main", str(local_repo)], check=True)
            subprocess.run(["git", "-C", str(local_repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(local_repo), "config", "user.name", "Test User"], check=True)
            subprocess.run(["git", "-C", str(local_repo), "remote", "add", "origin", str(remote_repo)], check=True)

            def git_commit_at(msg: str, filename: str, content_txt: str, iso_ts: str) -> str:
                (local_repo / filename).write_text(content_txt, encoding="utf-8")
                subprocess.run(["git", "-C", str(local_repo), "add", filename], check=True)
                env = dict(os.environ, GIT_AUTHOR_DATE=iso_ts, GIT_COMMITTER_DATE=iso_ts)
                subprocess.run(["git", "-C", str(local_repo), "commit", "-q", "-m", msg], check=True, env=env)
                return subprocess.check_output(
                    ["git", "-C", str(local_repo), "rev-parse", "HEAD"], text=True
                ).strip()

            # Commit A on mainline
            commit_a = git_commit_at("main A", "file.txt", "main-A\n", ts_a)

            # Feature branch from A with Commit B (ts_b > ts_a and ts_b < captured_at)
            subprocess.run(["git", "-C", str(local_repo), "checkout", "-q", "-b", "feature/std-021-f17"], check=True)
            commit_b = git_commit_at("feature B", "feature.txt", "feature-B\n", ts_b)

            # Merge feature into main as Merge Commit M (ts_m > captured_at; first-parent=A, second-parent=B)
            subprocess.run(["git", "-C", str(local_repo), "checkout", "-q", "main"], check=True)
            merge_env = dict(os.environ, GIT_AUTHOR_DATE=ts_m, GIT_COMMITTER_DATE=ts_m)
            subprocess.run(
                ["git", "-C", str(local_repo), "merge", "--no-ff", "--no-edit", "feature/std-021-f17"],
                check=True,
                env=merge_env,
            )
            commit_m = subprocess.check_output(
                ["git", "-C", str(local_repo), "rev-parse", "HEAD"], text=True
            ).strip()
            self.assertEqual(
                subprocess.check_output(["git", "-C", str(local_repo), "rev-parse", f"{commit_m}^1"], text=True).strip(),
                commit_a,
            )
            self.assertEqual(
                subprocess.check_output(["git", "-C", str(local_repo), "rev-parse", f"{commit_m}^2"], text=True).strip(),
                commit_b,
            )
            subprocess.run(["git", "-C", str(local_repo), "push", "-q", "origin", "main"], check=True)

            # Switch back to feature branch at B (simulating pre-merge snapshot verification after PR merged to main)
            subprocess.run(["git", "-C", str(local_repo), "checkout", "-q", "feature/std-021-f17"], check=True)

            # Raw git log check proving why --first-parent is required
            plain_log = subprocess.check_output(
                ["git", "-C", str(local_repo), "log", "-1", "--format=%H", f"--before={captured_at}", commit_m],
                text=True,
            ).strip()
            self.assertEqual(plain_log, commit_b)
            first_parent_log = subprocess.check_output(
                [
                    "git", "-C", str(local_repo),
                    "log", "-1", "--first-parent", "--format=%H", f"--before={captured_at}", commit_m,
                ],
                text=True,
            ).strip()
            self.assertEqual(first_parent_log, commit_a)

            (local_repo / "engineering-manifest.yaml").write_text(
                "project:\n  id: ai-engineering-standards\n", encoding="utf-8"
            )
            tick = chr(96)

            def make_baseline(remote_sha: str, local_sha: str = commit_b) -> str:
                return (
                    f"## 8. Git 分支及 Commit 身份 ({tick}git_identity{tick})\n"
                    f"- **当前分支 ({tick}branch{tick})**：{tick}feature/std-021-f17{tick}\n"
                    f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{local_sha}{tick}\n"
                    f"- **远端 main ({tick}remote_main_head{tick})**：{tick}{remote_sha}{tick}\n"
                    f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
                    "## 9. 最近 CI 事实\n"
                    f"- **2. Git 快照观测时间 ({tick}git_snapshot_observed_at{tick})**：{tick}{captured_at}{tick}\n"
                )

            def make_handoff(remote_sha: str, local_sha: str = commit_b) -> str:
                return (
                    "TASK_ID=Std-021-MAINLINE-SNAPSHOT-FIRST-PARENT-FIX\n"
                    "STATUS=IN_PROGRESS\n"
                    f"CAPTURED_AT={captured_at}\n"
                    "## 1. 当前 Git 状态与分支身份 (git_state)\n"
                    f"- **当前分支 ({tick}branch{tick})**：{tick}feature/std-021-f17{tick}\n"
                    f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{local_sha}{tick}\n"
                    f"- **远端 main ({tick}remote_head{tick})**：{tick}{remote_sha}{tick}\n"
                    f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
                    "## 2. 当前 Standards 锁定\n"
                )

            # Positive: recorded remote_main_head = A passes for BOTH Baseline and Handoff
            self.assertEqual(
                baseline_gen.verify_git_snapshot_facts(local_repo, make_baseline(commit_a), "baseline"),
                [],
            )
            self.assertEqual(
                handoff_gen.verify_git_snapshot_facts(local_repo, make_handoff(commit_a), "handoff"),
                [],
            )

            # Negative: recorded remote_main_head = B (second-parent feature commit) MUST FAIL
            b_errs = baseline_gen.verify_git_snapshot_facts(local_repo, make_baseline(commit_b), "baseline")
            self.assertTrue(
                any("BASELINE_GIT_SNAPSHOT_REMOTE_MAIN_MISMATCH" in e for e in b_errs),
                f"Expected BASELINE_GIT_SNAPSHOT_REMOTE_MAIN_MISMATCH, got: {b_errs}",
            )
            h_errs = handoff_gen.verify_git_snapshot_facts(local_repo, make_handoff(commit_b), "handoff")
            self.assertTrue(
                any("HANDOFF_GIT_SNAPSHOT_REMOTE_MAIN_MISMATCH" in e for e in h_errs),
                f"Expected HANDOFF_GIT_SNAPSHOT_REMOTE_MAIN_MISMATCH, got: {h_errs}",
            )

            # Boundary: feature branch local_head check still detects wrong local_head
            b_loc_errs = baseline_gen.verify_git_snapshot_facts(
                local_repo, make_baseline(commit_a, local_sha=commit_a), "baseline"
            )
            self.assertTrue(
                any("BASELINE_GIT_SNAPSHOT_LOCAL_HEAD_MISMATCH" in e for e in b_loc_errs),
                f"Expected BASELINE_GIT_SNAPSHOT_LOCAL_HEAD_MISMATCH, got: {b_loc_errs}",
            )

    def test_std020_impact_preserves_unknown_consumer_head_as_not_verifiable(self) -> None:
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("tools.standards_sync.core.run_collection_validation",
                       return_value=(False, ["MISSING_DOCUMENT_INDEX"])):
                result = analyze_consumer_impact(
                    root, from_ref="v2.11.0", to_ref="v3.0.0", standards_root=ROOT
                )
        self.assertEqual(result["CONSUMER_COMMIT"], "NOT_VERIFIABLE")
        self.assertEqual(result["CONSUMER_WORKTREE_STATUS"], "NOT_VERIFIABLE")
        self.assertEqual(result["CONSUMER_VERIFICATION_STATUS"], "NOT_VERIFIABLE")
        self.assertEqual(result["analysis_status"], "PARTIAL")
        self.assertEqual(result["INPUT_STANDARDS_COMMIT"],
                         "5e17c0ef560ab8abafe880b988d70f85f380a104")
        self.assertEqual(result["TARGET_STANDARDS_COMMIT"],
                         "8b223019c254e0edeb94576b94af46c1e48b0316")

    def test_deep_schema_diff_detects_nested_tightening(self) -> None:
        old_schema = {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "minLength": 1}},
                }
            },
        }
        new_schema = {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "minLength": 5}},
                }
            },
        }
        breaking, _ = deep_diff_schema(old_schema, new_schema)
        self.assertTrue(any("minLength" in item for item in breaking), breaking)

    def test_deep_schema_diff_detects_pattern_and_composition_changes(self) -> None:
        old_schema = {"type": "object", "properties": {"code": {"type": "string", "pattern": "^[A-Z]+$"}}}
        new_schema = {"type": "object", "properties": {"code": {"type": "string", "pattern": "^[A-Z]{3}$"}}}
        breaking, _ = deep_diff_schema(old_schema, new_schema)
        self.assertTrue(any("pattern" in item for item in breaking), breaking)
        old_composition = {"allOf": [{"type": "object", "required": ["id"]}]}
        new_composition = {"allOf": [{"type": "object", "required": ["id", "name"]}]}
        composition_breaking, _ = deep_diff_schema(old_composition, new_composition)
        self.assertTrue(composition_breaking, composition_breaking)

    def test_schema_diff_does_not_flag_annotation_only_change(self) -> None:
        breaking, details = deep_diff_schema(
            {"type": "string", "description": "old"},
            {"type": "string", "description": "new"},
        )
        self.assertEqual(breaking, [])
        self.assertIn("annotation:description", details)

    def test_consumer_ci_gate_verifies_exact_run_and_job(self) -> None:
        import json
        from unittest.mock import patch

        repository = "example/consumer"
        commit = "a" * 40
        gate = {
            "status": "PASS",
            "command": "python -m unittest discover -s tests -v",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "raw_report": {
                "repository": repository,
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
                "exit_code": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
                "exit_code": 0,
                "evidence_log_ref": "https://github.com/example/consumer/actions/runs/12345/jobs/1/logs",
            },
        }
        run_payload = {
            "id": 12345,
            "event": "pull_request",
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [
                {
                    "id": 101,
                    "run_id": 12345,
                    "head_sha": commit,
                    "name": "Unit Tests",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success"},
                        {"name": "Run tests", "conclusion": "success"},
                    ],
                }
            ]
        }
        log_payload = b"Ran 10 tests in 0.5s\n\nOK\n"
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(log_payload)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "VERIFIED", errors)
        self.assertEqual(errors, [])

    def test_consumer_upgrade_requires_owner_reviewed_ci_job_mapping(self) -> None:
        manifest_schema = json.loads(
            (ROOT / "schemas" / "engineering-manifest.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("standards_validation", manifest_schema["properties"])
        core = (ROOT / "tools" / "standards_sync" / "core.py").read_text(encoding="utf-8")
        self.assertIn("MANIFEST_REQUIRED_CI_JOB_MAPPING_MISSING", core)
        self.assertIn("CONSUMER_CI_JOB_MAPPING_MISMATCH", core)

    def test_consumer_ci_gate_rejects_commit_mismatch_before_network(self) -> None:
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": "b" * 40,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, "a" * 40)
        self.assertEqual(status, "FAILED")
        self.assertIn("CONSUMER_CI_EVIDENCE_COMMIT_MISMATCH", errors)

    def test_consumer_ci_gate_rejects_missing_test_execution(self) -> None:
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": "a" * 40,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, "a" * 40)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_TEST_EXECUTION_MISSING" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_zero_tests_collected(self) -> None:
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": "a" * 40,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "test_execution": {
                "tests_collected": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, "a" * 40)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_ZERO_TESTS_COLLECTED" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_all_tests_skipped(self) -> None:
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": "a" * 40,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "test_execution": {
                "tests_collected": 5,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 5,
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, "a" * 40)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_NO_TESTS_PASSED" in e or "CONSUMER_CI_GATE_ALL_TESTS_SKIPPED" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_failed_tests(self) -> None:
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": "a" * 40,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 8,
                "tests_failed": 2,
                "tests_skipped": 0,
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, "a" * 40)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_HAS_FAILED_TESTS" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_test_counts_inconsistent(self) -> None:
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": "a" * 40,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 5,
                "tests_failed": 0,
                "tests_skipped": 1,
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, "a" * 40)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_TEST_COUNTS_INCONSISTENT" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_tests_passed_below_manifest_minimum(self) -> None:
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": "a" * 40,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, "a" * 40, min_tests_passed=15)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_TESTS_PASSED_BELOW_MINIMUM" in e for e in errors), errors)

    def test_consumer_ci_gate_unreachable_api_returns_not_verifiable(self) -> None:
        from unittest.mock import patch
        import urllib.error
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": "a" * 40,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "raw_report": {
                "repository": "example/consumer",
                "head_sha": "a" * 40,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
                "exit_code": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
                "exit_code": 0,
                "evidence_log_ref": "https://github.com/example/consumer/actions/runs/12345/jobs/1/logs",
            },
        }
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
            status, errors = verify_consumer_ci_gate("example/consumer", gate, "a" * 40)
        self.assertEqual(status, "NOT_VERIFIABLE")
        self.assertNotEqual(status, "PASS")
        self.assertTrue(any("CONSUMER_CI_API_NOT_VERIFIABLE" in e for e in errors), errors)

    def test_missing_lock_does_not_resolve_to_a_historical_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(resolve_locked_standards_ref(Path(tmp)))

    def test_missing_lock_blocks_implicit_impact_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = analyze_consumer_impact(Path(tmp), standards_root=ROOT)
        self.assertEqual(result.get("status"), "BLOCK")
        self.assertIn("MISSING_STANDARDS_LOCK", result.get("reason", ""))

    def test_non_official_remote_is_rejected_before_network_access(self) -> None:
        result = discover_latest_official_tag(
            standards_root=ROOT,
            repository=DEFAULT_OFFICIAL_REPO,
            remote_url="https://github.com/example/AI-Engineering-Standards.git",
        )
        self.assertEqual(result.get("status"), "BLOCK")
        self.assertIn("UNOFFICIAL_REMOTE_FORBIDDEN", result.get("reason", ""))

    def test_consumer_templates_do_not_pin_a_historical_latest_version(self) -> None:
        lock_template = (ROOT / "templates" / "standards.lock.template.json").read_text(encoding="utf-8")
        manifest_template = (
            ROOT / "governance" / "templates" / "engineering-manifest.template.yaml"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"version": "2.11.0"', lock_template)
        self.assertNotIn('version: "2.11.0"', manifest_template)
        self.assertIn('"version": "0.0.0"', lock_template)
        self.assertIn('"tag": "v0.0.0"', lock_template)
        self.assertIn("0000000000000000000000000000000000000000", lock_template)
        self.assertIn('version: "0.0.0"', manifest_template)


    def test_document_templates_never_preapprove_or_forge_provenance(self) -> None:
        templates = ROOT / "templates" / "documentation"
        for path in sorted(templates.glob("*.template.md")):
            content = path.read_text(encoding="utf-8")
            parts = content.split("---", 2)
            self.assertEqual(len(parts), 3, f"{path.name}: frontmatter missing")
            metadata = yaml.safe_load(parts[1])
            self.assertEqual(metadata.get("status"), "CANDIDATE", path.name)
            self.assertEqual(metadata.get("approval_status"), "NOT_SUBMITTED", path.name)
            self.assertIn(metadata.get("approval_scope"), ("AI_APPROVABLE", "OWNER_MANDATORY", "OWNER_APPROVAL_REQUIRED"), path.name)
            self.assertIsNone(metadata.get("source_commit"), path.name)
            self.assertIsNone(metadata.get("content_sha256"), path.name)
            self.assertIsNone(metadata.get("approval_evidence_ref"), path.name)

    def test_only_explicitly_adopted_consumers_are_subject_to_auto_upgrade(self) -> None:
        std034 = (
            ROOT / "standards" / "00-governance"
            / "STD-034-coding-agent-execution-governance.md"
        ).read_text(encoding="utf-8")
        self.assertIn("消费端接入与受控升级", std034)
        self.assertIn("不代表所有受管工程自动加入升级计划", std034)
        self.assertIn("AI-Engineering-Hub", std034)
        self.assertIn("AI-KB、VTIP、SideCar 不属于本轮迁移范围", std034)

    def test_rollback_plan_never_recommends_blind_docs_checkout(self) -> None:
        core = (ROOT / "tools" / "standards_sync" / "core.py").read_text(encoding="utf-8")
        self.assertNotIn("git checkout -- docs/ engineering-manifest.yaml", core)
        self.assertIn("does not revert docs/", core)

    def test_release_tag_workflow_preserves_existing_immutable_version_tags(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "standards-ci.yml").read_text(encoding="utf-8")
        self.assertIn("git merge-base --is-ancestor \"$peeled\" \"$current_sha\"", workflow)
        self.assertIn("TAG_ACTION=SKIPPED_EXISTING_RELEASE", workflow)
        self.assertIn("refusing to overwrite or reuse it", workflow)

    def test_only_ai_hub_is_the_first_consumer_pilot(self) -> None:
        guide = (
            ROOT / "docs" / "migration"
            / "MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md"
        ).read_text(encoding="utf-8")
        self.assertIn("AI-Engineering-Hub", guide)
        self.assertIn("AI-KB", guide)
        self.assertIn("OUT_OF_SCOPE", guide)
        self.assertIn("VTIP", guide)
        self.assertIn("SideCar", guide)


    def test_consumer_ci_gate_rejects_job_success_with_zero_raw_tests(self) -> None:
        commit = "a" * 40
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "raw_report": {
                "repository": "example/consumer",
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
                "exit_code": 0,
                "evidence_log_ref": "https://github.com/example/consumer/actions/runs/12345",
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_ZERO_TESTS_COLLECTED" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_job_success_with_all_tests_skipped_in_raw_report(self) -> None:
        commit = "a" * 40
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "raw_report": {
                "repository": "example/consumer",
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 5,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 5,
            },
            "test_execution": {
                "tests_collected": 5,
                "tests_passed": 5,
                "tests_failed": 0,
                "tests_skipped": 0,
                "exit_code": 0,
                "evidence_log_ref": "https://github.com/example/consumer/actions/runs/12345",
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_ALL_TESTS_SKIPPED" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_evidence_json_inflated_passed_count(self) -> None:
        commit = "a" * 40
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "raw_report": {
                "repository": "example/consumer",
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 5,
                "tests_passed": 5,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
                "exit_code": 0,
                "evidence_log_ref": "https://github.com/example/consumer/actions/runs/12345",
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_TEST_COUNT_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_raw_report_citing_different_commit(self) -> None:
        commit_a = "a" * 40
        commit_b = "b" * 40
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit_a,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "raw_report": {
                "repository": "example/consumer",
                "head_sha": commit_b,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
                "exit_code": 0,
                "evidence_log_ref": "https://github.com/example/consumer/actions/runs/12345",
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, commit_a)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_COMMIT_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_missing_raw_report(self) -> None:
        commit = "a" * 40
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
                "exit_code": 0,
                "evidence_log_ref": "https://github.com/example/consumer/actions/runs/12345",
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_RAW_REPORT_MISSING" in e for e in errors), errors)

    def test_consumer_ci_gate_supports_security_scan_and_release_gate_semantics(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"

        # Security Scan gate
        scan_gate = {
            "status": "PASS",
            "command": "pip-audit",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Security Scan",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {
                "repository": repository,
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Security Scan",
                "scanner": "pip-audit",
                "targets_scanned": 15,
                "vulnerabilities_found": 0,
                "exit_code": 0,
            },
            "scan_execution": {
                "scanner": "pip-audit",
                "targets_scanned": 15,
                "vulnerabilities_found": 0,
                "exit_code": 0,
                "evidence_log_ref": f"https://github.com/{repository}/actions/runs/12345",
            },
        }

        # Release Gate
        release_gate = {
            "status": "PASS",
            "command": "python tools/validate_release.py",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Release Gate",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {
                "repository": repository,
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Release Gate",
                "gate_name": "release-validation",
                "checks_passed": 5,
                "checks_failed": 0,
                "exit_code": 0,
            },
            "release_execution": {
                "gate_name": "release-validation",
                "checks_passed": 5,
                "checks_failed": 0,
                "exit_code": 0,
                "evidence_log_ref": f"https://github.com/{repository}/actions/runs/12345",
            },
        }

        run_payload = {
            "id": 12345,
            "event": "pull_request",
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_scan = {
            "jobs": [
                {
                    "id": 201,
                    "run_id": 12345,
                    "head_sha": commit,
                    "name": "Security Scan",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success"},
                        {"name": "Run pip-audit", "conclusion": "success"},
                    ],
                }
            ]
        }
        jobs_release = {
            "jobs": [
                {
                    "id": 202,
                    "run_id": 12345,
                    "head_sha": commit,
                    "name": "Release Gate",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success"},
                        {"name": "Run release checks", "conclusion": "success"},
                    ],
                }
            ]
        }
        scan_log = b"Scan complete: 15 targets scanned, 0 vulnerabilities found. SUCCESS\n"
        release_log = b"Release checks completed: 5 passed, 0 failed. SUCCESS\n"

        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_scan), FakeResponse(scan_log)]):
            s1, err1 = verify_consumer_ci_gate(repository, scan_gate, commit)
        self.assertEqual(s1, "VERIFIED", err1)

        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_release), FakeResponse(release_log)]):
            s2, err2 = verify_consumer_ci_gate(repository, release_gate, commit)
        self.assertEqual(s2, "VERIFIED", err2)

    def test_validate_upgrade_candidate_rejects_unapproved_manifest_gate_mapping_change(self) -> None:
        from tools.standards_sync.core import validate_upgrade_candidate
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            manifest_content = """schema_version: "1.3.0"
standards:
  repository: "xiefeifeihu/AI-Engineering-Standards"
  version: "2.11.0"
  tag: "v2.11.0"
  tag_object_sha: "2f4b4b54348a5ac8891e5a0b33c04635a27213a0"
  peeled_commit: "5e17c0ef560ab8abafe880b988d70f85f380a104"
  lock_file: "standards.lock.json"
project:
  id: "ai-engineering-standards"
  name: "AI Engineering Standards"
  purpose: "Single source of truth"
  repository: "xiefeifeihu/AI-Engineering-Standards"
  deployment_kind: "NON_RUNTIME_ARTIFACT"
  release_profile: "PERSONAL_LOCAL"
services: []
standards_validation:
  schema_version: "1.0.0"
  required_ci_jobs:
    unit_tests:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Unit Tests"
      command: "python -m unittest discover -s tests -v"
    integration_tests:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Integration Tests"
      command: "python -m unittest discover -s tests -p '*integration*'"
    release_gates:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Release Gates"
      command: "python tools/validate_release.py"
    security_scan:
      workflow_path: ".github/workflows/security.yml"
      job_name: "Secret and Dependency Scan"
      command: "python tools/security_scan.py"
    business_api:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Business API Regression"
      command: "python -m pytest tests/business"
"""
            (dst / "engineering-manifest.yaml").write_text(manifest_content, encoding="utf-8")
            res = validate_upgrade_candidate(project_root=dst, standards_root=ROOT, target_tag="v3.0.0")
            self.assertEqual(res.get("status"), "UPGRADE_BLOCKED")
            self.assertTrue(any("MANIFEST_CI_JOB_MAPPING_NOT_APPROVED" in e for e in res.get("errors", [])), res)

    def test_consumer_ci_gate_rejects_empty_raw_report(self) -> None:
        commit = "a" * 40
        gate = {
            "status": "PASS",
            "command": "python -m unittest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "raw_report": {},
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_EMPTY" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_arbitrary_string_raw_report(self) -> None:
        commit = "a" * 40
        gate = {
            "status": "PASS",
            "command": "python -m unittest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "raw_report": "some random non-test log line without test numbers",
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_UNPARSEABLE" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_raw_report_test_count_mismatch(self) -> None:
        commit = "a" * 40
        gate = {
            "status": "PASS",
            "command": "python -m unittest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "raw_report": {
                "repository": "example/consumer",
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 5,
                "tests_passed": 5,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_TEST_COUNT_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_raw_log_containing_failures(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        gate = {
            "status": "PASS",
            "command": "python -m unittest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {
                "repository": repository,
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        run_payload = {
            "id": 12345,
            "event": "pull_request",
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [
                {
                    "id": 101,
                    "run_id": 12345,
                    "head_sha": commit,
                    "name": "Unit Tests",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success"},
                        {"name": "Run tests", "conclusion": "success"},
                    ],
                }
            ]
        }
        failing_log = b"test_something (test.Test) ... FAIL\nFAILURES!\nRan 10 tests in 0.5s\n"
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(failing_log)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_LOG_CONTAINS_FAILURE" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_workflow_run_not_success(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        gate = {
            "status": "PASS",
            "command": "python -m unittest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {
                "repository": repository,
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        run_payload = {
            "id": 12345,
            "event": "pull_request",
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "failure",
        }
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RUN_NOT_SUCCESS" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_workflow_run_commit_mismatch(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        diff_commit = "b" * 40
        repository = "example/consumer"
        gate = {
            "status": "PASS",
            "command": "python -m unittest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {
                "repository": repository,
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        run_payload = {
            "id": 12345,
            "event": "pull_request",
            "repository": {"full_name": repository},
            "head_sha": diff_commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RUN_COMMIT_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_job_not_success(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        gate = {
            "status": "PASS",
            "command": "python -m unittest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {
                "repository": repository,
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        run_payload = {
            "id": 12345,
            "event": "pull_request",
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [
                {
                    "id": 101,
                    "run_id": 12345,
                    "head_sha": commit,
                    "name": "Unit Tests",
                    "status": "completed",
                    "conclusion": "failure",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success"},
                        {"name": "Run tests", "conclusion": "failure"},
                    ],
                }
            ]
        }
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_JOB_NOT_SUCCESS" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_job_name_not_found(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        gate = {
            "status": "PASS",
            "command": "python -m unittest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {
                "repository": repository,
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        run_payload = {
            "id": 12345,
            "event": "pull_request",
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [
                {
                    "id": 101,
                    "run_id": 12345,
                    "head_sha": commit,
                    "name": "Other Unrelated Job",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success"},
                        {"name": "Run other", "conclusion": "success"},
                    ],
                }
            ]
        }
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_JOB_NOT_UNIQUE_OR_MISSING" in e for e in errors), errors)

    def test_consumer_ci_gate_fails_or_not_verifiable_when_log_unfetchable(self) -> None:
        from unittest.mock import patch
        import urllib.error
        commit = "a" * 40
        repository = "example/consumer"
        gate = {
            "status": "PASS",
            "command": "python -m unittest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {
                "repository": repository,
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        run_payload = {
            "id": 12345,
            "event": "pull_request",
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [
                {
                    "id": 101,
                    "run_id": 12345,
                    "head_sha": commit,
                    "name": "Unit Tests",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success"},
                        {"name": "Run tests", "conclusion": "success"},
                    ],
                }
            ]
        }
        with patch("urllib.request.urlopen", side_effect=[
            FakeResponse(run_payload),
            FakeResponse(jobs_payload),
            urllib.error.HTTPError("https://api.github.com/...", 404, "Not Found", {}, None),
        ]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "NOT_VERIFIABLE")
        self.assertTrue(any("CONSUMER_CI_API_NOT_VERIFIABLE" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_raw_report_missing_required_fields(self) -> None:
        commit = "a" * 40
        gate = {
            "status": "PASS",
            "command": "python -m unittest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": "https://github.com/example/consumer/actions/runs/12345",
            "raw_report": {
                "repository": "example/consumer",
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 10,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
        }
        status, errors = verify_consumer_ci_gate("example/consumer", gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_MISSING_REQUIRED_FIELDS" in e for e in errors), errors)

    def test_validate_upgrade_candidate_rejects_agent_self_approval_on_gate_mapping(self) -> None:
        from tools.standards_sync.core import validate_upgrade_candidate
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            manifest_content = """schema_version: "1.3.0"
standards:
  repository: "xiefeifeihu/AI-Engineering-Standards"
  version: "2.11.0"
  tag: "v2.11.0"
  tag_object_sha: "2f4b4b54348a5ac8891e5a0b33c04635a27213a0"
  peeled_commit: "5e17c0ef560ab8abafe880b988d70f85f380a104"
  lock_file: "standards.lock.json"
project:
  id: "ai-engineering-standards"
  name: "AI Engineering Standards"
  purpose: "Single source of truth"
  repository: "xiefeifeihu/AI-Engineering-Standards"
  deployment_kind: "NON_RUNTIME_ARTIFACT"
  release_profile: "PERSONAL_LOCAL"
services: []
standards_validation:
  schema_version: "1.0.0"
  approval_evidence_ref: "docs/approvals/gate-mapping.json"
  approval_record:
    schema_version: "1.0.0"
    actor_role: "CODING_AGENT"
    approval_status: "OWNER_APPROVED"
    candidate_commit: "5ba4bc668417b68b384fd5e5a73cff9b870b6cb6"
    content_sha256: "sha256:1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
    approved_at: "2026-11-09T00:00:00Z"
    repository: "xiefeifeihu/AI-Engineering-Standards"
    approval_scope: "GATE_MAPPING"
  required_ci_jobs:
    unit_tests:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Unit Tests"
      command: "python -m unittest discover -s tests -v"
    integration_tests:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Integration Tests"
      command: "python -m unittest discover -s tests -p '*integration*'"
    release_gates:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Release Gates"
      command: "python tools/validate_release.py"
    security_scan:
      workflow_path: ".github/workflows/security.yml"
      job_name: "Secret and Dependency Scan"
      command: "python tools/security_scan.py"
    business_api:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Business API Regression"
      command: "python -m pytest tests/business"
"""
            (dst / "engineering-manifest.yaml").write_text(manifest_content, encoding="utf-8")
            res = validate_upgrade_candidate(project_root=dst, standards_root=ROOT, target_tag="v3.0.0")
            self.assertEqual(res.get("status"), "UPGRADE_BLOCKED")
            self.assertTrue(any("AGENT_SELF_APPROVAL_FORBIDDEN" in e for e in res.get("errors", [])), res)

    def test_validate_upgrade_candidate_rejects_gate_mapping_digest_mismatch(self) -> None:
        from tools.standards_sync.core import validate_upgrade_candidate
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            manifest_content = """schema_version: "1.3.0"
standards:
  repository: "xiefeifeihu/AI-Engineering-Standards"
  version: "2.11.0"
  tag: "v2.11.0"
  tag_object_sha: "2f4b4b54348a5ac8891e5a0b33c04635a27213a0"
  peeled_commit: "5e17c0ef560ab8abafe880b988d70f85f380a104"
  lock_file: "standards.lock.json"
project:
  id: "ai-engineering-standards"
  name: "AI Engineering Standards"
  purpose: "Single source of truth"
  repository: "xiefeifeihu/AI-Engineering-Standards"
  deployment_kind: "NON_RUNTIME_ARTIFACT"
  release_profile: "PERSONAL_LOCAL"
services: []
standards_validation:
  schema_version: "1.0.0"
  approval_evidence_ref: "docs/approvals/gate-mapping.json"
  approval_record:
    schema_version: "1.0.0"
    actor_role: "OWNER"
    approval_status: "OWNER_APPROVED"
    candidate_commit: "5ba4bc668417b68b384fd5e5a73cff9b870b6cb6"
    content_sha256: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    approved_at: "2026-11-09T00:00:00Z"
    repository: "xiefeifeihu/AI-Engineering-Standards"
    approval_scope: "GATE_MAPPING"
  required_ci_jobs:
    unit_tests:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Unit Tests"
      command: "python -m unittest discover -s tests -v"
    integration_tests:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Integration Tests"
      command: "python -m unittest discover -s tests -p '*integration*'"
    release_gates:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Release Gates"
      command: "python tools/validate_release.py"
    security_scan:
      workflow_path: ".github/workflows/security.yml"
      job_name: "Secret and Dependency Scan"
      command: "python tools/security_scan.py"
    business_api:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Business API Regression"
      command: "python -m pytest tests/business"
"""
            (dst / "engineering-manifest.yaml").write_text(manifest_content, encoding="utf-8")
            res = validate_upgrade_candidate(project_root=dst, standards_root=ROOT, target_tag="v3.0.0")
            self.assertEqual(res.get("status"), "UPGRADE_BLOCKED")
            self.assertTrue(any("MANIFEST_CI_JOB_MAPPING_DIGEST_MISMATCH" in e for e in res.get("errors", [])), res)

    def test_validate_upgrade_candidate_rejects_approval_commit_mismatch(self) -> None:
        from tools.standards_sync.core import validate_upgrade_candidate
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            manifest_content = """schema_version: "1.3.0"
standards:
  repository: "xiefeifeihu/AI-Engineering-Standards"
  version: "2.11.0"
  tag: "v2.11.0"
  tag_object_sha: "2f4b4b54348a5ac8891e5a0b33c04635a27213a0"
  peeled_commit: "5e17c0ef560ab8abafe880b988d70f85f380a104"
  lock_file: "standards.lock.json"
project:
  id: "ai-engineering-standards"
  name: "AI Engineering Standards"
  purpose: "Single source of truth"
  repository: "xiefeifeihu/AI-Engineering-Standards"
  deployment_kind: "NON_RUNTIME_ARTIFACT"
  release_profile: "PERSONAL_LOCAL"
services: []
standards_validation:
  schema_version: "1.0.0"
  approval_evidence_ref: "docs/approvals/gate-mapping.json"
  approval_record:
    schema_version: "1.0.0"
    actor_role: "OWNER"
    approval_status: "OWNER_APPROVED"
    candidate_commit: "0000000000000000000000000000000000000000"
    content_sha256: "sha256:1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
    approved_at: "2026-11-09T00:00:00Z"
    repository: "xiefeifeihu/AI-Engineering-Standards"
    approval_scope: "GATE_MAPPING"
  required_ci_jobs:
    unit_tests:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Unit Tests"
      command: "python -m unittest discover -s tests -v"
    integration_tests:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Integration Tests"
      command: "python -m unittest discover -s tests -p '*integration*'"
    release_gates:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Release Gates"
      command: "python tools/validate_release.py"
    security_scan:
      workflow_path: ".github/workflows/security.yml"
      job_name: "Secret and Dependency Scan"
      command: "python tools/security_scan.py"
    business_api:
      workflow_path: ".github/workflows/ci.yml"
      job_name: "Business API Regression"
      command: "python -m pytest tests/business"
"""
            (dst / "engineering-manifest.yaml").write_text(manifest_content, encoding="utf-8")
            res = validate_upgrade_candidate(project_root=dst, standards_root=ROOT, target_tag="v3.0.0")
            self.assertEqual(res.get("status"), "UPGRADE_BLOCKED")
            self.assertTrue(any("APPROVAL_COMMIT_MISMATCH" in e for e in res.get("errors", [])), res)



    def test_consumer_ci_gate_real_job_log_success_path(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"

        runner_log = f"commit: {commit}\nRan 8 tests in 0.234s\n\nOK\n".encode("utf-8")

        gate = {
            "status": "PASS",
            "command": "python -m unittest discover",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {
                "repository": repository,
                "head_sha": commit,
                "run_id": 12345,
                "job_name": "Unit Tests",
                "tests_collected": 8,
                "tests_passed": 8,
                "tests_failed": 0,
                "tests_skipped": 0,
            },
            "test_execution": {
                "tests_collected": 8,
                "tests_passed": 8,
                "tests_failed": 0,
                "tests_skipped": 0,
                "exit_code": 0,
                "evidence_log_ref": f"https://github.com/{repository}/actions/runs/12345",
            },
        }
        run_payload = {
            "id": 12345,
            "event": "pull_request",
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [
                {
                    "id": 101,
                    "run_id": 12345,
                    "head_sha": commit,
                    "name": "Unit Tests",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success"},
                        {"name": "Run tests", "conclusion": "success"},
                    ],
                }
            ]
        }
        with patch("urllib.request.urlopen", side_effect=[
            FakeResponse(run_payload),
            FakeResponse(jobs_payload),
            FakeResponse(runner_log),
        ]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "VERIFIED", errors)
        self.assertEqual(errors, [])

    def test_consumer_ci_gate_rejects_runner_log_unparseable(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"

        unparseable_log = b"Some random runner output without any summary line\nDone\n"

        gate = {
            "status": "PASS",
            "command": "python -m pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 1, "tests_passed": 1, "tests_failed": 0, "tests_skipped": 0},
            "test_execution": {"tests_collected": 1, "tests_passed": 1, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0, "evidence_log_ref": "ref"},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(unparseable_log)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "NOT_VERIFIABLE")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_UNPARSEABLE" in e for e in errors), errors)

    def test_pytest_parsing_5_passed_2_failed(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        log_bytes = b"= 5 passed, 2 failed in 0.12s ="
        gate = {
            "status": "PASS",
            "command": "pytest",
            "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345,
            "job_name": "Unit Tests",
            "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": log_bytes.decode("utf-8"),
            "test_execution": {"tests_collected": 7, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 2, "exit_code": 0, "evidence_log_ref": "ref"},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(log_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_HAS_FAILED_TESTS" in e for e in errors), errors)

    def test_pytest_parsing_5_passed_2_skipped_success_and_count_mismatch(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        log_bytes = b"= 5 passed, 2 skipped in 0.15s ="
        gate_matched = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": log_bytes.decode("utf-8"),
            "test_execution": {"tests_collected": 7, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 2, "exit_code": 0, "evidence_log_ref": "ref"},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(log_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate_matched, commit)
        self.assertEqual(status, "VERIFIED", errors)

        # Mismatch in claimed counts fails
        gate_mismatch = dict(gate_matched, test_execution={"tests_collected": 7, "tests_passed": 7, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0, "evidence_log_ref": "ref"})
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(log_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate_mismatch, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_TEST_COUNT_MISMATCH" in e for e in errors), errors)

    def test_pytest_parsing_0_passed(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        log_bytes = b"= 0 passed, 3 skipped in 0.05s ="
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": log_bytes.decode("utf-8"),
            "test_execution": {"tests_collected": 3, "tests_passed": 3, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0, "evidence_log_ref": "ref"},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(log_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_NO_TESTS_PASSED" in e for e in errors), errors)

    def test_pytest_parsing_collected_count_inconsistent(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        log_bytes = b"collected 10 items\n\n= 5 passed, 2 skipped in 0.12s ="
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": log_bytes.decode("utf-8"),
            "test_execution": {"tests_collected": 10, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 5, "exit_code": 0, "evidence_log_ref": "ref"},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(log_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_TEST_COUNTS_INCONSISTENT" in e for e in errors), errors)

    def test_pytest_parsing_job_success_but_log_has_failure(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        log_bytes = b"= FAILURES =\n___ test_broken ___\nassert 1 == 0\n= 10 passed in 0.5s ="
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": log_bytes.decode("utf-8"),
            "test_execution": {"tests_collected": 10, "tests_passed": 10, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0, "evidence_log_ref": "ref"},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(log_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_LOG_CONTAINS_FAILURE" in e for e in errors), errors)

    def test_pytest_parsing_continue_on_error_masks_failure(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        log_bytes = b"##[error]Process completed with exit code 1.\ncontinue-on-error: true\n= 5 passed in 0.12s ="
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": log_bytes.decode("utf-8"),
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0, "evidence_log_ref": "ref"},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(log_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_LOG_CONTAINS_FAILURE" in e for e in errors), errors)

    def test_pytest_parsing_incomplete_log_no_summary_returns_not_verifiable(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": "Ran 5 tests in 0.05s\n\nOK",
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0, "evidence_log_ref": "ref"},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        log_bytes = b"pytest running...\ntest_one.py .\ntest_two.py .\n"
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(log_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "NOT_VERIFIABLE")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_UNPARSEABLE" in e for e in errors), errors)

    def test_pytest_parsing_unrelated_ok_string_returns_not_verifiable(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": "Ran 5 tests in 0.05s\n\nOK",
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0, "evidence_log_ref": "ref"},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        log_bytes = b"Docker image build OK\nSystem setup OK\n"
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(log_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "NOT_VERIFIABLE")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_UNPARSEABLE" in e for e in errors), errors)


    def test_artifact_redirect_blocks_non_https(self) -> None:
        import urllib.request, urllib.error
        from tools.standards_sync.core import SafeGitHubRedirectHandler
        handler = SafeGitHubRedirectHandler(initial_host="api.github.com")
        req = urllib.request.Request("https://api.github.com/download", headers={"Authorization": "Bearer secret"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            handler.redirect_request(req, None, 302, "Found", {}, "http://pipelines.actions.githubusercontent.com/file.zip")
        self.assertIn("INSECURE_REDIRECT", str(ctx.exception))

    def test_artifact_redirect_blocks_untrusted_host(self) -> None:
        import urllib.request, urllib.error
        from tools.standards_sync.core import SafeGitHubRedirectHandler
        handler = SafeGitHubRedirectHandler(initial_host="api.github.com")
        req = urllib.request.Request("https://api.github.com/download", headers={"Authorization": "Bearer secret"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            handler.redirect_request(req, None, 302, "Found", {}, "https://attacker.evil.com/leak.zip")
        self.assertIn("UNTRUSTED_REDIRECT_HOST", str(ctx.exception))

    def test_artifact_redirect_strips_authorization_on_cross_origin(self) -> None:
        import urllib.request, urllib.error
        from tools.standards_sync.core import SafeGitHubRedirectHandler
        handler = SafeGitHubRedirectHandler(initial_host="api.github.com")
        req = urllib.request.Request("https://api.github.com/download", headers={"Authorization": "Bearer secret_token_12345"})
        new_req = handler.redirect_request(
            req, None, 302, "Found", {}, "https://pipelines.actions.githubusercontent.com/artifact.zip"
        )
        self.assertIsNotNone(new_req)
        self.assertFalse(new_req.has_header("Authorization"))

    def test_consumer_ci_gate_rejects_runner_log_test_count_mismatch(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        runner_log = f"commit: {commit}\nRan 5 tests in 0.1s\n\nOK\n".encode("utf-8")
        gate = {
            "status": "PASS", "command": "python -m unittest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 10, "tests_passed": 10},
            "test_execution": {"tests_collected": 10, "tests_passed": 10, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(runner_log)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_TEST_COUNT_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_runner_log_failed_tests(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        runner_log = f"commit: {commit}\nRan 10 tests in 0.5s\n\nFAILED (failures=2)\n".encode("utf-8")
        gate = {
            "status": "PASS", "command": "python -m unittest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 10, "tests_passed": 10},
            "test_execution": {"tests_collected": 10, "tests_passed": 10, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(runner_log)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_LOG_CONTAINS_FAILURE" in e for e in errors), errors)

    def test_consumer_ci_gate_job_id_mismatch_fails(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "job_id": 8888, "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 5, "tests_passed": 5},
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_JOB_ID_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_workflow_path_mismatch(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 5, "tests_passed": 5},
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/other.yml", "status": "completed", "conclusion": "success"}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RUN_WORKFLOW_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_runner_log_commit_mismatch(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        diff_commit = "b" * 40
        repository = "example/consumer"
        runner_log = f"commit: {diff_commit}\nRan 5 tests in 0.1s\n\nOK\n".encode("utf-8")
        gate = {
            "status": "PASS", "command": "python -m unittest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 5, "tests_passed": 5},
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(runner_log)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_COMMIT_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_supports_pytest_job_log_success_path(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"
        runner_log = f"commit: {commit}\ncollected 10 items\n=== 8 passed, 2 skipped in 0.5s ===\n".encode("utf-8")
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 10, "tests_passed": 8, "tests_skipped": 2},
            "test_execution": {"tests_collected": 10, "tests_passed": 8, "tests_failed": 0, "tests_skipped": 2, "exit_code": 0},
        }
        run_payload = {"id": 12345, "event": "pull_request", "repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "run_id": 12345, "head_sha": commit, "name": "Unit Tests", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout", "conclusion": "success"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(runner_log)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "VERIFIED", errors)
        self.assertEqual(errors, [])

    def test_log_parser_conflicting_multiple_summaries_returns_failed(self) -> None:
        from tools.standards_sync.core import parse_runner_test_log
        commit = "a" * 40
        log = "Ran 5 tests in 0.1s\n\nOK\ncollected 10 items\n=== 8 passed, 2 failed in 0.5s ==="
        status, errors = parse_runner_test_log(log, commit, 5, 5)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_LOG_CONFLICTING_SUMMARIES" in e for e in errors), errors)

    def test_log_parser_nonzero_exit_code_returns_failed(self) -> None:
        from tools.standards_sync.core import parse_runner_test_log
        commit = "a" * 40
        log = "Ran 5 tests in 0.1s\n\nOK\nProcess completed with exit code 1"
        status, errors = parse_runner_test_log(log, commit, 5, 5)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_LOG_CONTAINS_FAILURE" in e for e in errors), errors)


    def test_log_parser_unrelated_ok_and_missing_unittest_summary_returns_not_verifiable(self) -> None:
        from tools.standards_sync.core import parse_runner_test_log
        commit = "a" * 40
        # Step log has an unrelated OK, and unittest printed Ran 10 tests, but process crashed before outcome summary
        log = "[Profile OK] environment initialized\nRan 10 tests in 0.234s\n"
        status, errors = parse_runner_test_log(log, commit, 10, 10)
        self.assertEqual(status, "NOT_VERIFIABLE")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_UNPARSEABLE" in e for e in errors), errors)

    def test_log_parser_pytest_errors_returns_failed(self) -> None:
        from tools.standards_sync.core import parse_runner_test_log
        commit = "a" * 40
        log = "collected 8 items\n=== 5 passed, 1 skipped, 2 errors in 0.45s ==="
        status, errors = parse_runner_test_log(log, commit, 5, 8)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_GATE_HAS_FAILED_TESTS" in e for e in errors), errors)

    def test_log_parser_truncated_log_returns_not_verifiable(self) -> None:
        from tools.standards_sync.core import parse_runner_test_log
        commit = "a" * 40
        log = "pytest starting...\ncollected 12 items\ntest_core.py ..."
        status, errors = parse_runner_test_log(log, commit, 12, 12)
        self.assertEqual(status, "NOT_VERIFIABLE")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_UNPARSEABLE" in e for e in errors), errors)

    def test_log_parser_exit_code_inconsistent_returns_failed(self) -> None:
        from tools.standards_sync.core import parse_runner_test_log
        commit = "a" * 40
        log = "Ran 10 tests in 0.123s\n\nOK\nExit code 2\n"
        status, errors = parse_runner_test_log(log, commit, 10, 10)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_LOG_CONTAINS_FAILURE" in e for e in errors), errors)

    def test_std020_f07_document_index_frontmatter_consistency(self) -> None:
        """F07: Verify DOCUMENT-INDEX.md entries match actual document YAML frontmatter status and approval_status."""
        index_file = ROOT / "docs" / "DOCUMENT-INDEX.md"
        self.assertTrue(index_file.exists(), f"Missing index: {index_file}")
        index_text = index_file.read_text(encoding="utf-8")
        entries = []
        for line in index_text.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 7 and parts[1].isdigit():
                doc_type = parts[2].replace("`", "").strip()
                m = re.search(r"\[([^\]]+)\]", parts[3])
                path_str = m.group(1).replace("`", "").strip() if m else parts[3].replace("`", "").strip()
                doc_id = parts[4].replace("`", "").strip()
                status = parts[5].replace("`", "").strip()
                entries.append((doc_type, path_str, doc_id, status))

        self.assertEqual(len(entries), 12, f"Expected exactly 12 primary entrypoints in index, found {len(entries)}")

        for doc_type, path_str, doc_id, status in entries:
            target_path = ROOT / path_str
            self.assertTrue(target_path.exists(), f"Primary entrypoint document does not exist: {target_path}")
            content = target_path.read_text(encoding="utf-8")
            fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
            self.assertIsNotNone(fm_match, f"Document {path_str} missing YAML frontmatter")
            fm = yaml.safe_load(fm_match.group(1))

            self.assertTrue(fm.get("primary_entrypoint"), f"{path_str} primary_entrypoint is not True")
            self.assertEqual(fm.get("document_type"), doc_type, f"{path_str} document_type mismatch")
            self.assertEqual(fm.get("document_id"), doc_id, f"{path_str} document_id mismatch")
            self.assertEqual(fm.get("status"), status, f"{path_str} status '{fm.get('status')}' != index '{status}'")
            self.assertEqual(fm.get("approval_status"), "IN_REVIEW", f"{path_str} approval_status '{fm.get('approval_status')}' != IN_REVIEW")
            self.assertEqual(status, "IN_REVIEW", f"{path_str} index status must be IN_REVIEW")

    def test_std020_historical_snapshot_negative_1_local_head_mismatch_at_capture(self) -> None:
        """1. 历史快照 local_head 与 captured_at 对应的真实历史 Commit 不一致 -> BLOCK (LOCAL_HEAD_MISMATCH)"""
        from unittest.mock import patch
        from tools import generate_engineering_baseline as baseline_gen
        from tools import generate_handoff as handoff_gen

        recorded_local = "a" * 40
        different_commit_at_capture = "f" * 40
        remote_sha = "b" * 40
        captured_at = "2020-01-01T00:00:00Z"
        tick = chr(96)
        baseline_text = (
            "## 8. Git 分支及 Commit 身份 (" + tick + "git_identity" + tick + ")\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{recorded_local}{tick}\n"
            f"- **远端 main ({tick}remote_main_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 9. 最近 CI 事实\n"
            "### 19.3 Std-019 正式发布收口事实与治理追踪\n"
            f"- **发布状态**：{tick}RELEASE_STATUS=RELEASED{tick}\n"
            f"- **Git 快照观测时间**：{tick}{captured_at}{tick}\n"
        )
        handoff_text = (
            "TASK_ID=Std-019-V3-0-0-POST-RELEASE-CLOSEOUT\n"
            "STATUS=COMPLETED\n"
            f"CAPTURED_AT={captured_at}\n"
            "## 1. 当前 Git 状态与分支身份 (git_state)\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{recorded_local}{tick}\n"
            f"- **远端 main ({tick}remote_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 2. 当前 Standards 锁定\n"
        )
        for module, kind, content in ((baseline_gen, "baseline", baseline_text), (handoff_gen, "handoff", handoff_text)):
            with self.subTest(generator=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    if kind == "baseline":
                        (root / "engineering-manifest.yaml").write_text("project:\n  id: ai-engineering-standards\n", encoding="utf-8")
                    def simulated_run_git(repo, args, **kwargs):
                        if args and args[0] == "merge-base":
                            return 0, ""
                        if args and args[0] == "log":
                            if args[-1] == "branch-tip-sha":
                                return 0, different_commit_at_capture
                            return 0, remote_sha
                        return 0, ""
                    with patch.object(module, "query_remote_main_head", return_value=remote_sha):
                        with patch.object(module, "resolve_snapshot_branch_tip", return_value="branch-tip-sha"):
                            with patch.object(module, "resolve_snapshot_branch_name", return_value="feature/test"):
                                with patch.object(module, "run_git", side_effect=simulated_run_git):
                                    errors = module.verify_git_snapshot_facts(root, content, kind)
                self.assertTrue(any("LOCAL_HEAD_MISMATCH" in e for e in errors), errors)

    def test_std020_historical_snapshot_negative_2_remote_main_mismatch_at_capture(self) -> None:
        """2. recorded remote_main_head 与 captured_at 对应的真实远端历史 Commit 不一致 -> BLOCK (REMOTE_MAIN_MISMATCH)"""
        from unittest.mock import patch
        from tools import generate_engineering_baseline as baseline_gen
        from tools import generate_handoff as handoff_gen

        recorded_local = "a" * 40
        recorded_remote = "b" * 40
        different_remote_at_capture = "9" * 40
        captured_at = "2020-01-01T00:00:00Z"
        tick = chr(96)
        baseline_text = (
            "## 8. Git 分支及 Commit 身份 (" + tick + "git_identity" + tick + ")\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{recorded_local}{tick}\n"
            f"- **远端 main ({tick}remote_main_head{tick})**：{tick}{recorded_remote}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 9. 最近 CI 事实\n"
            "### 19.3 Std-019 正式发布收口事实与治理追踪\n"
            f"- **发布状态**：{tick}RELEASE_STATUS=RELEASED{tick}\n"
            f"- **Git 快照观测时间**：{tick}{captured_at}{tick}\n"
        )
        handoff_text = (
            "TASK_ID=Std-019-V3-0-0-POST-RELEASE-CLOSEOUT\n"
            "STATUS=COMPLETED\n"
            f"CAPTURED_AT={captured_at}\n"
            "## 1. 当前 Git 状态与分支身份 (git_state)\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{recorded_local}{tick}\n"
            f"- **远端 main ({tick}remote_head{tick})**：{tick}{recorded_remote}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 2. 当前 Standards 锁定\n"
        )
        for module, kind, content in ((baseline_gen, "baseline", baseline_text), (handoff_gen, "handoff", handoff_text)):
            with self.subTest(generator=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    if kind == "baseline":
                        (root / "engineering-manifest.yaml").write_text("project:\n  id: ai-engineering-standards\n", encoding="utf-8")
                    def simulated_run_git(repo, args, **kwargs):
                        if args and args[0] == "merge-base":
                            return 0, ""
                        if args and args[0] == "log":
                            if args[-1] == "branch-tip-sha":
                                return 0, recorded_local
                            if args[-1] == recorded_remote:
                                return 0, different_remote_at_capture
                        return 0, ""
                    with patch.object(module, "query_remote_main_head", return_value=recorded_remote):
                        with patch.object(module, "resolve_snapshot_branch_tip", return_value="branch-tip-sha"):
                            with patch.object(module, "resolve_snapshot_branch_name", return_value="feature/test"):
                                with patch.object(module, "run_git", side_effect=simulated_run_git):
                                    errors = module.verify_git_snapshot_facts(root, content, kind)
                self.assertTrue(any("REMOTE_MAIN_MISMATCH" in e for e in errors), errors)

    def test_std020_historical_snapshot_negative_3_unproven_ancestry_blocked(self) -> None:
        """3. 仅有 RELEASED 或 COMPLETED 标记，但无法证明祖先关系 -> BLOCK (HISTORICAL_ANCESTRY_MISMATCH)"""
        from unittest.mock import patch
        from tools import generate_engineering_baseline as baseline_gen
        from tools import generate_handoff as handoff_gen

        recorded_local = "a" * 40
        remote_sha = "b" * 40
        captured_at = "2020-01-01T00:00:00Z"
        tick = chr(96)
        baseline_text = (
            "## 8. Git 分支及 Commit 身份 (" + tick + "git_identity" + tick + ")\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{recorded_local}{tick}\n"
            f"- **远端 main ({tick}remote_main_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 9. 最近 CI 事实\n"
            "### 19.3 Std-019 正式发布收口事实与治理追踪\n"
            f"- **发布状态**：{tick}RELEASE_STATUS=RELEASED{tick}\n"
            f"- **Git 快照观测时间**：{tick}{captured_at}{tick}\n"
        )
        handoff_text = (
            "TASK_ID=Std-019-V3-0-0-POST-RELEASE-CLOSEOUT\n"
            "STATUS=COMPLETED\n"
            f"CAPTURED_AT={captured_at}\n"
            "## 1. 当前 Git 状态与分支身份 (git_state)\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{recorded_local}{tick}\n"
            f"- **远端 main ({tick}remote_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 2. 当前 Standards 锁定\n"
        )
        for module, kind, content in ((baseline_gen, "baseline", baseline_text), (handoff_gen, "handoff", handoff_text)):
            with self.subTest(generator=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    if kind == "baseline":
                        (root / "engineering-manifest.yaml").write_text("project:\n  id: ai-engineering-standards\n", encoding="utf-8")
                    def simulated_run_git(repo, args, **kwargs):
                        if args and args[0] == "merge-base":
                            return 1, ""  # confirmed non-ancestor
                        if args and args[0] == "log":
                            return 0, recorded_local
                        return 0, ""
                    with patch.object(module, "query_remote_main_head", return_value=remote_sha):
                        with patch.object(module, "resolve_snapshot_branch_tip", return_value="branch-tip-sha"):
                            with patch.object(module, "resolve_snapshot_branch_name", return_value="feature/test"):
                                with patch.object(module, "run_git", side_effect=simulated_run_git):
                                    errors = module.verify_git_snapshot_facts(root, content, kind)
                self.assertTrue(any("HISTORICAL_ANCESTRY_MISMATCH" in e for e in errors), errors)

    def test_std020_historical_snapshot_negative_4_git_history_unresolvable_not_verifiable(self) -> None:
        """4. Git 对象不存在或历史无法读取 -> NOT_VERIFIABLE (CAPTURE_COMMIT_NOT_VERIFIABLE)"""
        from unittest.mock import patch
        from tools import generate_engineering_baseline as baseline_gen
        from tools import generate_handoff as handoff_gen

        recorded_local = "a" * 40
        remote_sha = "b" * 40
        captured_at = "2020-01-01T00:00:00Z"
        tick = chr(96)
        baseline_text = (
            "## 8. Git 分支及 Commit 身份 (" + tick + "git_identity" + tick + ")\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{recorded_local}{tick}\n"
            f"- **远端 main ({tick}remote_main_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 9. 最近 CI 事实\n"
            "### 19.3 Std-019 正式发布收口事实与治理追踪\n"
            f"- **发布状态**：{tick}RELEASE_STATUS=RELEASED{tick}\n"
            f"- **Git 快照观测时间**：{tick}{captured_at}{tick}\n"
        )
        handoff_text = (
            "TASK_ID=Std-019-V3-0-0-POST-RELEASE-CLOSEOUT\n"
            "STATUS=COMPLETED\n"
            f"CAPTURED_AT={captured_at}\n"
            "## 1. 当前 Git 状态与分支身份 (git_state)\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{recorded_local}{tick}\n"
            f"- **远端 main ({tick}remote_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 2. 当前 Standards 锁定\n"
        )
        for module, kind, content in ((baseline_gen, "baseline", baseline_text), (handoff_gen, "handoff", handoff_text)):
            with self.subTest(generator=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    if kind == "baseline":
                        (root / "engineering-manifest.yaml").write_text("project:\n  id: ai-engineering-standards\n", encoding="utf-8")
                    def simulated_run_git(repo, args, **kwargs):
                        if args and args[0] == "merge-base":
                            return 0, ""
                        if args and args[0] == "log":
                            return 128, "fatal: bad object"
                        return 0, ""
                    with patch.object(module, "query_remote_main_head", return_value=remote_sha):
                        with patch.object(module, "resolve_snapshot_branch_tip", return_value="branch-tip-sha"):
                            with patch.object(module, "resolve_snapshot_branch_name", return_value="feature/test"):
                                with patch.object(module, "run_git", side_effect=simulated_run_git):
                                    errors = module.verify_git_snapshot_facts(root, content, kind)
                self.assertTrue(any("CAPTURE_COMMIT_NOT_VERIFIABLE" in e for e in errors), errors)

    def test_std020_historical_snapshot_positive_5_normal_ancestry_pass(self) -> None:
        """5. 正常历史祖先快照仍然 PASS -> errors == []"""
        from unittest.mock import patch
        from tools import generate_engineering_baseline as baseline_gen
        from tools import generate_handoff as handoff_gen

        recorded_local = "a" * 40
        remote_sha = "b" * 40
        captured_at = "2020-01-01T00:00:00Z"
        tick = chr(96)
        baseline_text = (
            "## 8. Git 分支及 Commit 身份 (" + tick + "git_identity" + tick + ")\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{recorded_local}{tick}\n"
            f"- **远端 main ({tick}remote_main_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 9. 最近 CI 事实\n"
            "### 19.3 Std-019 正式发布收口事实与治理追踪\n"
            f"- **发布状态**：{tick}RELEASE_STATUS=RELEASED{tick}\n"
            f"- **Git 快照观测时间**：{tick}{captured_at}{tick}\n"
        )
        handoff_text = (
            "TASK_ID=Std-019-V3-0-0-POST-RELEASE-CLOSEOUT\n"
            "STATUS=COMPLETED\n"
            f"CAPTURED_AT={captured_at}\n"
            "## 1. 当前 Git 状态与分支身份 (git_state)\n"
            f"- **当前分支 ({tick}branch{tick})**：{tick}old-branch{tick}\n"
            f"- **本地 HEAD ({tick}local_head{tick})**：{tick}{recorded_local}{tick}\n"
            f"- **远端 main ({tick}remote_head{tick})**：{tick}{remote_sha}{tick}\n"
            f"- **工作区干净状态 ({tick}worktree_clean{tick})**：{tick}true{tick}\n"
            "## 2. 当前 Standards 锁定\n"
        )
        for module, kind, content in ((baseline_gen, "baseline", baseline_text), (handoff_gen, "handoff", handoff_text)):
            with self.subTest(generator=kind):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    if kind == "baseline":
                        (root / "engineering-manifest.yaml").write_text("project:\n  id: ai-engineering-standards\n", encoding="utf-8")
                    def simulated_run_git(repo, args, **kwargs):
                        if args and args[0] == "merge-base":
                            return 0, ""
                        if args and args[0] == "log":
                            if args[-1] == "branch-tip-sha":
                                return 0, recorded_local
                            if args[-1] == remote_sha:
                                return 0, remote_sha
                        return 0, ""
                    with patch.object(module, "query_remote_main_head", return_value=remote_sha):
                        with patch.object(module, "resolve_snapshot_branch_tip", return_value="branch-tip-sha"):
                            with patch.object(module, "resolve_snapshot_branch_name", return_value="feature/test"):
                                with patch.object(module, "run_git", side_effect=simulated_run_git):
                                    errors = module.verify_git_snapshot_facts(root, content, kind)
                self.assertEqual(errors, [], errors)


class PackageAcceptanceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        (self.root / "VERSION").write_text("3.0.0\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _setup_valid_acceptance(self, task_id="TEST-TASK", version="3.0.0", run_id="run-123"):
        acc_dir = self.root / ".artifacts" / "acceptance" / task_id / f"v{version}"
        acc_dir.mkdir(parents=True, exist_ok=True)
        doc = acc_dir / "report.md"
        doc.write_text("# Test Report\n", encoding="utf-8")
        doc_sha = hashlib.sha256(doc.read_bytes()).hexdigest()
        manifest = {
            "task_id": task_id,
            "version": f"v{version}",
            "run_id": run_id,
            "created_at": "2026-11-17T02:00:00Z",
            "files": [
                {
                    "path": "report.md",
                    "size": doc.stat().st_size,
                    "sha256": doc_sha,
                }
            ],
        }
        (acc_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return acc_dir, manifest

    def test_01_valid_manifest_packaging_pass(self) -> None:
        from scripts.package_acceptance import package_acceptance
        acc_dir, _ = self._setup_valid_acceptance()
        res = package_acceptance("TEST-TASK", version="3.0.0", run_id="run-123", repo_root=self.root)
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["task_id"], "TEST-TASK")
        self.assertEqual(res["version"], "v3.0.0")
        self.assertEqual(res["run_id"], "run-123")
        self.assertEqual(res["files_verified"], 1)
        zip_path = self.root / res["zip_path"]
        sha_path = self.root / res["sha256_path"]
        self.assertTrue(zip_path.exists())
        self.assertTrue(sha_path.exists())
        self.assertIn(res["zip_sha256"], sha_path.read_text(encoding="utf-8"))

    def test_02_manifest_missing_run_id_rejected(self) -> None:
        from scripts.package_acceptance import validate_acceptance_manifest
        acc_dir, manifest = self._setup_valid_acceptance()
        del manifest["run_id"]
        (acc_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            validate_acceptance_manifest(acc_dir, expected_task_id="TEST-TASK", expected_version="3.0.0", repo_root=self.root)
        self.assertIn("missing required field: 'run_id'", str(ctx.exception))

    def test_03_manifest_missing_task_id_rejected(self) -> None:
        from scripts.package_acceptance import validate_acceptance_manifest
        acc_dir, manifest = self._setup_valid_acceptance()
        del manifest["task_id"]
        (acc_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            validate_acceptance_manifest(acc_dir, expected_task_id="TEST-TASK", expected_version="3.0.0", repo_root=self.root)
        self.assertIn("missing required field: 'task_id'", str(ctx.exception))

    def test_04_manifest_task_id_mismatch_rejected(self) -> None:
        from scripts.package_acceptance import validate_acceptance_manifest
        acc_dir, manifest = self._setup_valid_acceptance()
        with self.assertRaises(ValueError) as ctx:
            validate_acceptance_manifest(acc_dir, expected_task_id="OTHER-TASK", expected_version="3.0.0", repo_root=self.root)
        self.assertIn("task_id mismatch", str(ctx.exception))

    def test_05_manifest_version_mismatch_rejected(self) -> None:
        from scripts.package_acceptance import validate_acceptance_manifest
        acc_dir, manifest = self._setup_valid_acceptance(version="2.0.0")
        with self.assertRaises(ValueError) as ctx:
            validate_acceptance_manifest(acc_dir, expected_task_id="TEST-TASK", expected_version="3.0.0", repo_root=self.root)
        self.assertIn("version mismatch", str(ctx.exception))

    def test_06_run_id_persisted_to_manifest(self) -> None:
        from scripts.package_acceptance import package_acceptance
        acc_dir, manifest = self._setup_valid_acceptance(run_id="old-run")
        res = package_acceptance("TEST-TASK", version="3.0.0", run_id="new-ci-run-999", repo_root=self.root)
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["run_id"], "new-ci-run-999")
        updated_m = json.loads((acc_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(updated_m["run_id"], "new-ci-run-999")
        zip_p = self.root / res["zip_path"]
        with zipfile.ZipFile(zip_p, "r") as zf:
            zip_m = json.loads(zf.read("manifest.json").decode("utf-8"))
        self.assertEqual(zip_m["run_id"], "new-ci-run-999")

    def test_07_file_sha_mismatch_rejected(self) -> None:
        from scripts.package_acceptance import validate_acceptance_manifest
        acc_dir, manifest = self._setup_valid_acceptance()
        manifest["files"][0]["sha256"] = "0" * 64
        (acc_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            validate_acceptance_manifest(acc_dir, expected_task_id="TEST-TASK", expected_version="3.0.0", repo_root=self.root)
        self.assertIn("Integrity mismatch", str(ctx.exception))

    def test_08_zip_extraction_integrity_verification(self) -> None:
        from scripts.package_acceptance import package_acceptance, sha256_file as real_sha256_file
        from unittest.mock import patch
        acc_dir, _ = self._setup_valid_acceptance()
        def mocked_sha256(path):
            if ".verify_extract" in str(path):
                return "0" * 64
            return real_sha256_file(path)
        with patch("scripts.package_acceptance.sha256_file", side_effect=mocked_sha256):
            with self.assertRaises(ValueError) as ctx:
                package_acceptance("TEST-TASK", version="3.0.0", run_id="run-123", repo_root=self.root)
            self.assertIn("Extraction verification failed", str(ctx.exception))

    def test_09_package_acceptance_rejects_missing_task_id_in_manifest(self) -> None:
        from scripts.package_acceptance import package_acceptance
        acc_dir, manifest = self._setup_valid_acceptance()
        del manifest["task_id"]
        (acc_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            package_acceptance("TEST-TASK", version="3.0.0", run_id="run-123", repo_root=self.root)
        self.assertIn("missing required field: 'task_id'", str(ctx.exception))

    def test_10_package_acceptance_rejects_missing_version_in_manifest(self) -> None:
        from scripts.package_acceptance import package_acceptance
        acc_dir, manifest = self._setup_valid_acceptance()
        del manifest["version"]
        (acc_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            package_acceptance("TEST-TASK", version="3.0.0", run_id="run-123", repo_root=self.root)
        self.assertIn("missing required field: 'version'", str(ctx.exception))

    def test_11_package_acceptance_atomic_rollback_on_failure(self) -> None:
        from scripts.package_acceptance import package_acceptance
        acc_dir, manifest = self._setup_valid_acceptance()
        pkg_dir = self.root / ".artifacts" / "packages"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        old_zip = pkg_dir / "Acceptance-TEST-TASK-v3.0.0.zip"
        old_sha = pkg_dir / "Acceptance-TEST-TASK-v3.0.0.zip.sha256"
        old_zip.write_text("OLD_ZIP_CONTENT", encoding="utf-8")
        old_sha.write_text("OLD_SHA_CONTENT", encoding="utf-8")

        manifest["files"][0]["sha256"] = "0" * 64
        orig_manifest_content = json.dumps(manifest, indent=2)
        (acc_dir / "manifest.json").write_text(orig_manifest_content, encoding="utf-8")

        with self.assertRaises(ValueError):
            package_acceptance("TEST-TASK", version="3.0.0", run_id="new-run-fail", repo_root=self.root, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")

        self.assertEqual(old_zip.read_text(encoding="utf-8"), "OLD_ZIP_CONTENT")
        self.assertEqual(old_sha.read_text(encoding="utf-8"), "OLD_SHA_CONTENT")
        temp_files = list(pkg_dir.glob(".tmp_*"))
        self.assertEqual(len(temp_files), 0)


class BaselineGeneratorScopeContractTests(unittest.TestCase):
    """F10: Tests for Scope Separation in Baseline Generator (STD-035)."""

    def setUp(self) -> None:
        self.root = ROOT

    def _create_valid_consumer_project(self, dst: Path) -> None:
        _copy_minimal_valid_project(dst)
        rel_ev_dir = dst / "docs" / "release-evidence"
        if rel_ev_dir.exists():
            shutil.rmtree(rel_ev_dir)

    def test_f10_consumer_scope_default_passes(self) -> None:
        cp = subprocess.run(
            [sys.executable, str(self.root / "tools" / "generate_engineering_baseline.py"), "--project-root", str(self.root), "--verify-only"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cp.returncode, 0, f"stdout: {cp.stdout}\nstderr: {cp.stderr}")
        self.assertIn("[PASS] Engineering baseline verified against committed file", cp.stdout)

    def test_f10_standards_release_scope_passes(self) -> None:
        cp = subprocess.run(
            [sys.executable, str(self.root / "tools" / "generate_engineering_baseline.py"), "--project-root", str(self.root), "--scope", "standards-release", "--verify-only"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cp.returncode, 0, f"stdout: {cp.stdout}\nstderr: {cp.stderr}")
        self.assertIn("[PASS] Engineering baseline verified against committed file", cp.stdout)

    def test_f10_consumer_scope_skips_standards_release_evidence(self) -> None:
        """In consumer scope, missing standards release evidence files does not block verification."""
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            self._create_valid_consumer_project(dst)
            cp_cons = subprocess.run(
                [sys.executable, str(self.root / "tools" / "generate_engineering_baseline.py"), "--project-root", str(dst), "--scope", "consumer", "--verify-only"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(cp_cons.returncode, 0, f"stdout: {cp_cons.stdout}\nstderr: {cp_cons.stderr}")
            self.assertIn("[PASS] Engineering baseline verified against committed file", cp_cons.stdout)

            cp_std = subprocess.run(
                [sys.executable, str(self.root / "tools" / "generate_engineering_baseline.py"), "--project-root", str(dst), "--scope", "standards-release", "--verify-only"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(cp_std.returncode, 0)
            self.assertIn("release evidence", cp_std.stdout.lower() + cp_std.stderr.lower())


class HistoricalLockRollbackContractTests(unittest.TestCase):
    """F11: Tests for Initial Historical Lock Formal Rollback Contract (STD-034)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        _copy_minimal_valid_project(self.root)
        self.lock_path = self.root / "standards.lock.json"
        self.manifest_path = self.root / "engineering-manifest.yaml"
        self.v211_tag = "2f4b4b54348a5ac8891e5a0b33c04635a27213a0"
        self.v211_peeled = "5e17c0ef560ab8abafe880b988d70f85f380a104"
        self.consumer_sha = "c483a9366df653e0ec0e722a57aa8c41ecb2b719"
        self.sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": self.consumer_sha},
            "merged_at": "2026-11-17T00:00:00Z",
        }

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _setup_lock_with_previous(self, restored_lock: Dict[str, Any]) -> None:
        lock_data = json.loads(self.lock_path.read_text(encoding="utf-8"))
        lock_data["previous_locks"] = [restored_lock]
        self.lock_path.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "standards.lock.json"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "--allow-empty", "-m", "setup lock"], capture_output=True, check=True)
        self.consumer_sha = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        self.sim_pr["head"]["sha"] = self.consumer_sha

    def _create_valid_auth_file(
        self,
        rel_path: str = "docs/rollback-auth.json",
        scope: str = "LOCK_ROLLBACK",
        reviewer_type: str = "OWNER",
        actor_role: str = "REPOSITORY_OWNER",
        target_tag: str = "v2.11.0",
        peeled_commit: Optional[str] = None,
        tag_object_sha: Optional[str] = None,
        omit_commit_bindings: bool = False,
        omit_content_bindings: bool = False,
    ) -> Path:
        p_commit = peeled_commit or self.v211_peeled
        t_obj = tag_object_sha or self.v211_tag
        auth_file = self.root / rel_path
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        auth_data: Dict[str, Any] = {
            "schema_version": "1.0.0",
            "task_id": "ROLLBACK-TASK",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "candidate_commit": self.consumer_sha,
            "content_sha256": "sha256:" + "a" * 64,
            "decision_scope": scope,
            "approval_scope": scope,
            "reviewer_type": reviewer_type,
            "actor_role": actor_role,
            "review_result": "OWNER_APPROVED",
            "approval_status": "OWNER_APPROVED",
            "approved_at": "2026-11-17T00:00:00Z",
            "approval_reference": "https://github.com/xiefeifeihu/AI-Engineering-Standards/pull/99",
            "chatgpt_review": {
                "reviewer": "ChatGPT",
                "reviewed_at": "2026-11-17T00:00:00Z",
                "candidate_commit": self.consumer_sha,
                "content_sha256": "sha256:" + "a" * 64,
                "review_result": "READY_FOR_OWNER_MERGE",
                "review_reference": "REF-001",
                "summary": "Reviewed rollback",
            },
            "owner_approval": {
                "approver": "xiefeifeihu",
                "approval_channel": "GITHUB_PR_MERGE",
                "approved_at": "2026-11-17T00:00:00Z",
                "candidate_commit": self.consumer_sha,
                "content_sha256": "sha256:" + "a" * 64,
                "approved_decision_ids": ["D-RB-001"],
                "approval_reference": "REF-002",
                "decision": "OWNER_APPROVED",
            },
            "approval_event": {
                "event_id": "99",
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "actor_identity": {
                    "identity_id": "xiefeifeihu",
                    "identity_type": "GITHUB_USER",
                    "service_provenance_ref": "https://api.github.com/repos/xiefeifeihu/AI-Engineering-Standards/pulls/99",
                },
                "candidate_commit": self.consumer_sha,
                "content_sha256": "sha256:" + "a" * 64,
                "approval_scope": scope,
                "event_timestamp": "2026-11-17T00:00:00Z",
            },
        }
        if not omit_commit_bindings:
            cb = {
                "consumer": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "candidate_commit": self.consumer_sha,
                },
                "standards": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "target_tag": target_tag,
                    "tag_object_sha": t_obj,
                    "peeled_commit": p_commit,
                },
            }
            auth_data["commit_bindings"] = cb
            auth_data["approval_event"]["commit_bindings"] = cb
        if not omit_content_bindings:
            from tools.validate_approval_contract import compute_content_bindings
            cb_st, cnt, cb_errs = compute_content_bindings(self.root, git_commit=self.consumer_sha, prefer_git=True)
            if cb_st != "PASS" or cnt is None:
                raise AssertionError(f"Failed computing test content_bindings: {cb_st} {cb_errs}")
            auth_data["content_bindings"] = cnt
            auth_data["approval_event"]["content_bindings"] = cnt

        auth_file.write_text(json.dumps(auth_data, indent=2), encoding="utf-8")
        return auth_file

    def test_01_rollback_with_null_approval_evidence_ref_succeeds(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Bootstrap v2.11.0 lock",
            "approval_evidence_ref": None,
            "ci_verification_status": "NOT_VERIFIABLE",
        })
        self._create_valid_auth_file()
        res = rollback_lock(
            self.root,
            rollback_authorization_ref="docs/rollback-auth.json",
            standards_root=ROOT,
            simulate_provenance_data=self.sim_pr,
        )
        self.assertEqual(res["status"], "ROLLED_BACK")
        new_lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.assertEqual(new_lock["version"], "2.11.0")
        self.assertEqual(new_lock["tag"], "v2.11.0")
        self.assertIsNone(new_lock["approval_evidence_ref"])

    def test_02_rollback_preserves_historical_approval_truth(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-04-12T00:00:00Z",
            "lock_reason": "Prior official release v2.11.0",
            "approval_evidence_ref": "docs/release-evidence/v2.11.0-approval.json",
            "ci_verification_status": "PASS",
        })
        self._create_valid_auth_file()
        res = rollback_lock(
            self.root,
            rollback_authorization_ref="docs/rollback-auth.json",
            standards_root=ROOT,
            simulate_provenance_data=self.sim_pr,
        )
        self.assertEqual(res["status"], "ROLLED_BACK")
        new_lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.assertEqual(new_lock["approval_evidence_ref"], "docs/release-evidence/v2.11.0-approval.json")
        self.assertEqual(new_lock["ci_verification_status"], "PASS")

    def test_03_rollback_records_rollback_authorization_ref(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Bootstrap v2.11.0 lock",
            "approval_evidence_ref": None,
        })
        self._create_valid_auth_file()
        res = rollback_lock(
            self.root,
            rollback_authorization_ref="docs/rollback-auth.json",
            require_authorization=True,
            standards_root=ROOT,
            simulate_provenance_data=self.sim_pr,
        )
        self.assertEqual(res["status"], "ROLLED_BACK")
        new_lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.assertEqual(new_lock["rollback_authorization_ref"], "docs/rollback-auth.json")

    def test_04_rollback_missing_ci_status_defaults_to_not_verifiable(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "No ci status lock",
            "approval_evidence_ref": None,
        })
        self._create_valid_auth_file()
        res = rollback_lock(
            self.root,
            rollback_authorization_ref="docs/rollback-auth.json",
            standards_root=ROOT,
            simulate_provenance_data=self.sim_pr,
        )
        self.assertEqual(res["status"], "ROLLED_BACK")
        new_lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self.assertEqual(new_lock["ci_verification_status"], "NOT_VERIFIABLE")

    def test_05_rollback_rejects_non_official_repository(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "attacker/Fake-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Malicious lock",
            "approval_evidence_ref": None,
        })
        self._create_valid_auth_file()
        res = rollback_lock(self.root, rollback_authorization_ref="docs/rollback-auth.json", standards_root=ROOT, simulate_provenance_data=self.sim_pr)
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("INVALID_STANDARDS_REPOSITORY", res["reason"])

    def test_06_rollback_validates_target_annotated_tag_and_peeled_commit(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": "not-a-40-hex-sha",
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Bad sha lock",
            "approval_evidence_ref": None,
        })
        self._create_valid_auth_file()
        res = rollback_lock(self.root, rollback_authorization_ref="docs/rollback-auth.json", standards_root=ROOT, simulate_provenance_data=self.sim_pr)
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("CORRUPT_HISTORICAL_LOCK", res["reason"])

    def test_07_rollback_validates_authorization_scope(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Lock",
            "approval_evidence_ref": None,
        })
        self._create_valid_auth_file(rel_path="docs/bad-scope.json", scope="AI_APPROVABLE")
        res = rollback_lock(self.root, rollback_authorization_ref="docs/bad-scope.json", standards_root=ROOT, simulate_provenance_data=self.sim_pr)
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("INVALID_ROLLBACK_AUTHORIZATION_SCOPE", res["reason"])

    def test_08_rollback_validates_authorization_target_mismatch(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Lock",
            "approval_evidence_ref": None,
        })
        self._create_valid_auth_file(rel_path="docs/mismatch.json", target_tag="v1.0.0")
        res = rollback_lock(self.root, rollback_authorization_ref="docs/mismatch.json", standards_root=ROOT, simulate_provenance_data=self.sim_pr)
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("ROLLBACK_AUTHORIZATION_TARGET_MISMATCH", res["reason"])

    def test_09_rollback_atomic_transaction_reverts_on_failure(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Lock",
            "approval_evidence_ref": None,
        })
        self._create_valid_auth_file()
        pre_lock = self.lock_path.read_text(encoding="utf-8")
        pre_manifest = self.manifest_path.read_text(encoding="utf-8")

        call_count = 0
        def fault_replace(src: Path, target: Path) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("Simulated disk failure on manifest update")
            os.replace(src, target)

        res = rollback_lock(
            self.root,
            rollback_authorization_ref="docs/rollback-auth.json",
            replace_fn=fault_replace,
            standards_root=ROOT,
            simulate_provenance_data=self.sim_pr,
        )
        self.assertEqual(res["status"], "FAIL")
        self.assertEqual(self.lock_path.read_text(encoding="utf-8"), pre_lock)
        self.assertEqual(self.manifest_path.read_text(encoding="utf-8"), pre_manifest)

    def test_10_rollback_cli_execution(self) -> None:
        from unittest.mock import patch, MagicMock
        from tools.standards_sync.cli import main
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "CLI rollback lock",
            "approval_evidence_ref": None,
        })
        auth_file = self._create_valid_auth_file()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
            with patch("urllib.request.urlopen") as mock_url:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(self.sim_pr).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_url.return_value = mock_resp

                ret = main([
                    "rollback",
                    "--project-root", str(self.root),
                    "--rollback-authorization-ref", str(auth_file),
                    "--standards-root", str(ROOT),
                ])
                self.assertEqual(ret, 0)
                new_lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
                self.assertEqual(new_lock["version"], "2.11.0")

    def test_11_rollback_cli_missing_auth_fails(self) -> None:
        cp = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "standards_sync" / "cli.py"), "rollback", "--project-root", str(self.root)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cp.returncode, 2)
        self.assertIn("--rollback-authorization-ref", cp.stderr)

    def test_12_rollback_missing_auth_by_default_fails(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Lock",
            "approval_evidence_ref": None,
        })
        res = rollback_lock(self.root, standards_root=ROOT)
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("MISSING_ROLLBACK_AUTHORIZATION", res["reason"])

    def test_13_rollback_agent_self_approval_fails(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Lock",
            "approval_evidence_ref": None,
        })
        self._create_valid_auth_file(rel_path="docs/agent-auth.json", actor_role="CODING_AGENT")
        res = rollback_lock(self.root, rollback_authorization_ref="docs/agent-auth.json", standards_root=ROOT, simulate_provenance_data=self.sim_pr)
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("AGENT_SELF_APPROVAL_FORBIDDEN", res["reason"])

    def test_14_rollback_official_tag_remote_unreachable_returns_not_verifiable(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": self.v211_tag,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Lock",
            "approval_evidence_ref": None,
        })
        self._create_valid_auth_file()
        res = rollback_lock(
            self.root,
            rollback_authorization_ref="docs/rollback-auth.json",
            standards_root=ROOT,
            simulate_offline=True,
            simulate_provenance_data=self.sim_pr,
        )
        self.assertEqual(res["status"], "NOT_VERIFIABLE")
        self.assertIn("HISTORICAL_TAG_NOT_VERIFIABLE", res["reason"])

    def test_15_rollback_official_tag_mismatch_fails(self) -> None:
        from tools.standards_sync.core import rollback_lock
        self._setup_lock_with_previous({
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": "f" * 40,
            "peeled_commit": self.v211_peeled,
            "locked_at": "2026-05-01T00:00:00Z",
            "lock_reason": "Lock",
            "approval_evidence_ref": None,
        })
        self._create_valid_auth_file(tag_object_sha="f" * 40)
        res = rollback_lock(
            self.root,
            rollback_authorization_ref="docs/rollback-auth.json",
            standards_root=ROOT,
            simulate_provenance_data=self.sim_pr,
        )
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("HISTORICAL_TAG_VERIFICATION_FAILED", res["reason"])

    def test_16_promote_upgrade_preserves_not_verifiable_when_historical_ci_missing(self) -> None:
        from tools.standards_sync.core import promote_upgrade
        cur_lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        if "ci_verification_status" in cur_lock:
            del cur_lock["ci_verification_status"]
        cur_lock["version"] = "2.11.0"
        cur_lock["tag"] = "v2.11.0"
        cur_lock["tag_object_sha"] = self.v211_tag
        cur_lock["peeled_commit"] = self.v211_peeled
        cur_lock["previous_locks"] = []
        self.lock_path.write_text(json.dumps(cur_lock, indent=2), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "standards.lock.json"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "--allow-empty", "-m", "promote pre-state"], capture_output=True, check=True)
        self.consumer_sha = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

        from tools.validate_approval_contract import compute_content_bindings
        cb_st, real_cnt, cb_errs = compute_content_bindings(self.root, git_commit=self.consumer_sha, prefer_git=True)
        self.assertEqual(cb_st, "PASS", cb_errs)

        target_peeled = "8b223019c254e0edeb94576b94af46c1e48b0316"
        target_tag_obj = "8256bb384e62894219db0992a2cb57e16d4fa8cd"
        app_file = self.root / "docs" / "promote-app.json"
        app_file.parent.mkdir(parents=True, exist_ok=True)
        app_file.write_text(json.dumps({
            "schema_version": "1.0.0",
            "task_id": "PROMOTE-TASK",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "candidate_commit": self.consumer_sha,
            "content_sha256": "sha256:" + "a" * 64,
            "decision_scope": "STANDARDS_LOCK_PROMOTION",
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "reviewer_type": "OWNER",
            "actor_role": "REPOSITORY_OWNER",
            "review_result": "OWNER_APPROVED",
            "approval_status": "OWNER_APPROVED",
            "approved_at": "2026-11-17T00:00:00Z",
            "approval_reference": "https://github.com/xiefeifeihu/AI-Engineering-Standards/pull/12",
            "commit_bindings": {
                "consumer": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "candidate_commit": self.consumer_sha,
                },
                "standards": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "target_tag": "v3.0.0",
                    "tag_object_sha": target_tag_obj,
                    "peeled_commit": target_peeled,
                },
            },
            "content_bindings": real_cnt,
            "chatgpt_review": {
                "reviewer": "ChatGPT",
                "reviewed_at": "2026-11-17T00:00:00Z",
                "candidate_commit": self.consumer_sha,
                "content_sha256": "sha256:" + "a" * 64,
                "review_result": "READY_FOR_OWNER_MERGE",
                "review_reference": "REF-001",
                "summary": "Reviewed promotion",
            },
            "owner_approval": {
                "approver": "xiefeifeihu",
                "approval_channel": "GITHUB_PR_MERGE",
                "approved_at": "2026-11-17T00:00:00Z",
                "candidate_commit": self.consumer_sha,
                "content_sha256": "sha256:" + "a" * 64,
                "approved_decision_ids": ["D-001"],
                "approval_reference": "REF-002",
                "decision": "OWNER_APPROVED",
            },
            "approval_event": {
                "event_id": "12",
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "actor_identity": {
                    "identity_id": "xiefeifeihu",
                    "identity_type": "GITHUB_USER",
                    "service_provenance_ref": "https://api.github.com/repos/xiefeifeihu/AI-Engineering-Standards/pulls/12",
                },
                "candidate_commit": self.consumer_sha,
                "content_sha256": "sha256:" + "a" * 64,
                "approval_scope": "STANDARDS_LOCK_PROMOTION",
                "event_timestamp": "2026-11-17T00:00:00Z",
                "commit_bindings": {
                    "consumer": {
                        "repository": "xiefeifeihu/AI-Engineering-Standards",
                        "candidate_commit": self.consumer_sha,
                    },
                    "standards": {
                        "repository": "xiefeifeihu/AI-Engineering-Standards",
                        "target_tag": "v3.0.0",
                        "tag_object_sha": target_tag_obj,
                        "peeled_commit": target_peeled,
                    },
                },
                "content_bindings": real_cnt,
            },
        }), encoding="utf-8")

        from unittest.mock import patch, MagicMock
        sim_merge = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": self.consumer_sha},
            "merged_at": "2026-11-17T00:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
            with patch("tools.standards_sync.core.check_remote_main_ci", return_value=("PASS", 12345, "Mocked CI pass")):
                with patch("tools.standards_sync.core.validate_upgrade_candidate", return_value={"status": "PASS", "errors": []}):
                    with patch("urllib.request.urlopen") as mock_url:
                        mock_resp = MagicMock()
                        mock_resp.read.return_value = json.dumps(sim_merge).encode("utf-8")
                        mock_resp.__enter__.return_value = mock_resp
                        mock_url.return_value = mock_resp

                        res = promote_upgrade(
                            project_root=self.root,
                            target_tag="v3.0.0",
                            target_version="3.0.0",
                            target_tag_object_sha=target_tag_obj,
                            target_peeled_commit=target_peeled,
                            approval_file=app_file,
                            standards_root=ROOT,
                        )
                        self.assertEqual(res["status"], "PROMOTED")
                        prev = res["lock"]["previous_locks"]
                        self.assertEqual(len(prev), 1)
                        self.assertEqual(prev[0]["ci_verification_status"], "NOT_VERIFIABLE")


class DualCommitApprovalContractTests(unittest.TestCase):
    """F12: Tests for Option C Dual-Commit Approval Contract (STD-034)."""

    def test_f12_signed_owner_event_removed(self) -> None:
        from tools.validate_approval_contract import TRUSTED_PROVENANCE_TYPES
        self.assertNotIn("SIGNED_OWNER_EVENT", TRUSTED_PROVENANCE_TYPES)

    def test_f12_dual_commit_pr_merge_event_success(self) -> None:
        from unittest.mock import patch, MagicMock
        from tools.validate_approval_contract import verify_approval_event_provenance, compute_content_bindings

        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            consumer_sha = _copy_minimal_valid_project(dst)
            cb_st, real_cnt, cb_errs = compute_content_bindings(dst, git_commit=consumer_sha, prefer_git=True)
            self.assertEqual(cb_st, "PASS", cb_errs)

            standards_sha = "8b223019c254e0edeb94576b94af46c1e48b0316"
            event = {
                "event_id": "42",
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "actor_identity": {
                    "identity_id": "example-owner",
                    "identity_type": "GITHUB_USER",
                    "service_provenance_ref": "https://api.github.com/repos/example-owner/consumer-app/pulls/42",
                },
                "candidate_commit": consumer_sha,
                "content_sha256": "sha256:" + "e" * 64,
                "approval_scope": "STANDARDS_LOCK_PROMOTION",
                "event_timestamp": "2026-11-17T00:00:00Z",
                "commit_bindings": {
                    "consumer": {
                        "repository": "example-owner/consumer-app",
                        "candidate_commit": consumer_sha,
                    },
                    "standards": {
                        "repository": "xiefeifeihu/AI-Engineering-Standards",
                        "target_tag": "v3.0.0",
                        "tag_object_sha": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
                        "peeled_commit": standards_sha,
                    },
                },
                "content_bindings": real_cnt,
            }
            record = {
                "repository": "example-owner/consumer-app",
                "approval_status": "OWNER_APPROVED",
                "candidate_commit": consumer_sha,
                "content_sha256": "sha256:" + "e" * 64,
                "approval_scope": "STANDARDS_LOCK_PROMOTION",
                "approved_at": "2026-11-17T00:00:00Z",
                "commit_bindings": event["commit_bindings"],
                "content_bindings": real_cnt,
                "approval_event": event,
            }

            mock_pr_response = {
                "merged": True,
                "merged_by": {"login": "example-owner"},
                "base": {"ref": "main"},
                "head": {"sha": consumer_sha},
                "merged_at": "2026-11-17T00:00:00Z",
            }

            with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
                with patch("urllib.request.urlopen") as mock_urlopen:
                    mock_resp = MagicMock()
                    mock_resp.read.return_value = json.dumps(mock_pr_response).encode("utf-8")
                    mock_resp.__enter__.return_value = mock_resp
                    mock_urlopen.return_value = mock_resp

                    status, errors = verify_approval_event_provenance(record, project_root=dst)
                    self.assertEqual(status, "VERIFIED", f"Errors: {errors}")

    def test_f12_dual_commit_pr_merge_event_head_mismatch_fails(self) -> None:
        from unittest.mock import patch, MagicMock
        from tools.validate_approval_contract import verify_approval_event_provenance

        consumer_sha = "c" * 40
        standards_sha = "8b223019c254e0edeb94576b94af46c1e48b0316"
        event = {
            "event_id": "42",
            "event_type": "GITHUB_PR_MERGE_EVENT",
            "provenance_type": "GITHUB_PR_MERGE",
            "actor_identity": {
                "identity_id": "example-owner",
                "identity_type": "GITHUB_USER",
                "service_provenance_ref": "https://api.github.com/repos/example-owner/consumer-app/pulls/42",
            },
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "event_timestamp": "2026-11-17T00:00:00Z",
            "commit_bindings": {
                "consumer": {
                    "repository": "example-owner/consumer-app",
                    "candidate_commit": consumer_sha,
                },
                "standards": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "target_tag": "v3.0.0",
                    "tag_object_sha": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
                    "peeled_commit": standards_sha,
                },
            },
            "content_bindings": {
                "ci_job_mapping_sha256": "sha256:" + "e" * 64,
                "lock_manifest_sha256": "sha256:" + "f" * 64,
            },
        }
        record = {
            "repository": "example-owner/consumer-app",
            "approval_status": "OWNER_APPROVED",
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "approved_at": "2026-11-17T00:00:00Z",
            "commit_bindings": event["commit_bindings"],
            "content_bindings": event["content_bindings"],
            "approval_event": event,
        }

        mock_pr_response = {
            "merged": True,
            "merged_by": {"login": "example-owner"},
            "base": {"ref": "main"},
            "head": {"sha": "d" * 40},
            "merged_at": "2026-11-17T00:00:00Z",
        }

        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(mock_pr_response).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_urlopen.return_value = mock_resp

                status, errors = verify_approval_event_provenance(record)
                self.assertEqual(status, "FAILED")
                self.assertTrue(any("APPROVAL_PR_HEAD_COMMIT_MISMATCH" in e for e in errors))

    def test_f12_dual_commit_pr_merge_event_unmerged_pr_fails(self) -> None:
        from unittest.mock import patch, MagicMock
        from tools.validate_approval_contract import verify_approval_event_provenance

        consumer_sha = "c" * 40
        standards_sha = "8b223019c254e0edeb94576b94af46c1e48b0316"
        event = {
            "event_id": "42",
            "event_type": "GITHUB_PR_MERGE_EVENT",
            "provenance_type": "GITHUB_PR_MERGE",
            "actor_identity": {
                "identity_id": "example-owner",
                "identity_type": "GITHUB_USER",
                "service_provenance_ref": "https://api.github.com/repos/example-owner/consumer-app/pulls/42",
            },
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "event_timestamp": "2026-11-17T00:00:00Z",
            "commit_bindings": {
                "consumer": {"repository": "example-owner/consumer-app", "candidate_commit": consumer_sha},
                "standards": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "target_tag": "v3.0.0",
                    "tag_object_sha": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
                    "peeled_commit": standards_sha,
                },
            },
            "content_bindings": {
                "ci_job_mapping_sha256": "sha256:" + "e" * 64,
                "lock_manifest_sha256": "sha256:" + "f" * 64,
            },
        }
        record = {
            "repository": "example-owner/consumer-app",
            "approval_status": "OWNER_APPROVED",
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "approved_at": "2026-11-17T00:00:00Z",
            "commit_bindings": event["commit_bindings"],
            "content_bindings": event["content_bindings"],
            "approval_event": event,
        }
        mock_pr_response = {
            "merged": False,
            "merged_by": None,
            "base": {"ref": "main"},
            "head": {"sha": consumer_sha},
            "merged_at": None,
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(mock_pr_response).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_urlopen.return_value = mock_resp

                status, errors = verify_approval_event_provenance(record)
                self.assertEqual(status, "FAILED")
                self.assertTrue(any("APPROVAL_PR_NOT_MERGED" in e for e in errors))

    def test_f12_dual_commit_pr_merge_event_agent_merged_by_fails(self) -> None:
        from unittest.mock import patch, MagicMock
        from tools.validate_approval_contract import verify_approval_event_provenance

        consumer_sha = "c" * 40
        standards_sha = "8b223019c254e0edeb94576b94af46c1e48b0316"
        event = {
            "event_id": "42",
            "event_type": "GITHUB_PR_MERGE_EVENT",
            "provenance_type": "GITHUB_PR_MERGE",
            "actor_identity": {
                "identity_id": "coding-agent-bot",
                "identity_type": "GITHUB_USER",
                "service_provenance_ref": "https://api.github.com/repos/example-owner/consumer-app/pulls/42",
            },
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "event_timestamp": "2026-11-17T00:00:00Z",
            "commit_bindings": {
                "consumer": {"repository": "example-owner/consumer-app", "candidate_commit": consumer_sha},
                "standards": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "target_tag": "v3.0.0",
                    "tag_object_sha": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
                    "peeled_commit": standards_sha,
                },
            },
            "content_bindings": {
                "ci_job_mapping_sha256": "sha256:" + "e" * 64,
                "lock_manifest_sha256": "sha256:" + "f" * 64,
            },
        }
        record = {
            "repository": "example-owner/consumer-app",
            "approval_status": "OWNER_APPROVED",
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "approved_at": "2026-11-17T00:00:00Z",
            "commit_bindings": event["commit_bindings"],
            "content_bindings": event["content_bindings"],
            "approval_event": event,
        }
        mock_pr_response = {
            "merged": True,
            "merged_by": {"login": "CODING_AGENT"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_sha},
            "merged_at": "2026-11-17T00:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(mock_pr_response).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_urlopen.return_value = mock_resp

                status, errors = verify_approval_event_provenance(record)
                self.assertEqual(status, "FAILED")
                self.assertTrue(any("AGENT_SELF_APPROVAL_FORBIDDEN" in e for e in errors))

    def test_f12_dual_commit_pr_merge_event_base_not_main_fails(self) -> None:
        from unittest.mock import patch, MagicMock
        from tools.validate_approval_contract import verify_approval_event_provenance

        consumer_sha = "c" * 40
        standards_sha = "8b223019c254e0edeb94576b94af46c1e48b0316"
        event = {
            "event_id": "42",
            "event_type": "GITHUB_PR_MERGE_EVENT",
            "provenance_type": "GITHUB_PR_MERGE",
            "actor_identity": {
                "identity_id": "example-owner",
                "identity_type": "GITHUB_USER",
                "service_provenance_ref": "https://api.github.com/repos/example-owner/consumer-app/pulls/42",
            },
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "event_timestamp": "2026-11-17T00:00:00Z",
            "commit_bindings": {
                "consumer": {"repository": "example-owner/consumer-app", "candidate_commit": consumer_sha},
                "standards": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "target_tag": "v3.0.0",
                    "tag_object_sha": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
                    "peeled_commit": standards_sha,
                },
            },
            "content_bindings": {
                "ci_job_mapping_sha256": "sha256:" + "e" * 64,
                "lock_manifest_sha256": "sha256:" + "f" * 64,
            },
        }
        record = {
            "repository": "example-owner/consumer-app",
            "approval_status": "OWNER_APPROVED",
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "approved_at": "2026-11-17T00:00:00Z",
            "commit_bindings": event["commit_bindings"],
            "content_bindings": event["content_bindings"],
            "approval_event": event,
        }
        mock_pr_response = {
            "merged": True,
            "merged_by": {"login": "example-owner"},
            "base": {"ref": "feature/branch"},
            "head": {"sha": consumer_sha},
            "merged_at": "2026-11-17T00:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(mock_pr_response).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_urlopen.return_value = mock_resp

                status, errors = verify_approval_event_provenance(record)
                self.assertEqual(status, "FAILED")
                self.assertTrue(any("APPROVAL_PR_BASE_BRANCH_MISMATCH" in e for e in errors))

    def test_f12_dual_commit_event_timestamp_mismatch_fails(self) -> None:
        from unittest.mock import patch, MagicMock
        from tools.validate_approval_contract import verify_approval_event_provenance

        consumer_sha = "c" * 40
        standards_sha = "8b223019c254e0edeb94576b94af46c1e48b0316"
        event = {
            "event_id": "42",
            "event_type": "GITHUB_PR_MERGE_EVENT",
            "provenance_type": "GITHUB_PR_MERGE",
            "actor_identity": {
                "identity_id": "example-owner",
                "identity_type": "GITHUB_USER",
                "service_provenance_ref": "https://api.github.com/repos/example-owner/consumer-app/pulls/42",
            },
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "event_timestamp": "2026-11-17T01:00:00Z",
            "commit_bindings": {
                "consumer": {"repository": "example-owner/consumer-app", "candidate_commit": consumer_sha},
                "standards": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "target_tag": "v3.0.0",
                    "tag_object_sha": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
                    "peeled_commit": standards_sha,
                },
            },
            "content_bindings": {
                "ci_job_mapping_sha256": "sha256:" + "e" * 64,
                "lock_manifest_sha256": "sha256:" + "f" * 64,
            },
        }
        record = {
            "repository": "example-owner/consumer-app",
            "approval_status": "OWNER_APPROVED",
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "approved_at": "2026-11-17T00:00:00Z",
            "commit_bindings": event["commit_bindings"],
            "content_bindings": event["content_bindings"],
            "approval_event": event,
        }
        mock_pr_response = {
            "merged": True,
            "merged_by": {"login": "example-owner"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_sha},
            "merged_at": "2026-11-17T00:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(mock_pr_response).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_urlopen.return_value = mock_resp

                status, errors = verify_approval_event_provenance(record)
                self.assertEqual(status, "FAILED")
                self.assertTrue(any("APPROVAL_TIME_MISMATCH" in e for e in errors))

    def test_f12_dual_commit_binding_mismatch_between_record_and_event_fails(self) -> None:
        from unittest.mock import patch, MagicMock
        from tools.validate_approval_contract import verify_approval_event_provenance

        consumer_sha = "c" * 40
        standards_sha = "8b223019c254e0edeb94576b94af46c1e48b0316"
        event = {
            "event_id": "42",
            "event_type": "GITHUB_PR_MERGE_EVENT",
            "provenance_type": "GITHUB_PR_MERGE",
            "actor_identity": {
                "identity_id": "example-owner",
                "identity_type": "GITHUB_USER",
                "service_provenance_ref": "https://api.github.com/repos/example-owner/consumer-app/pulls/42",
            },
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "event_timestamp": "2026-11-17T00:00:00Z",
            "commit_bindings": {
                "consumer": {"repository": "example-owner/consumer-app", "candidate_commit": consumer_sha},
                "standards": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "target_tag": "v3.0.0",
                    "tag_object_sha": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
                    "peeled_commit": standards_sha,
                },
            },
            "content_bindings": {
                "ci_job_mapping_sha256": "sha256:" + "e" * 64,
                "lock_manifest_sha256": "sha256:" + "f" * 64,
            },
        }
        # Record has different target_tag in commit_bindings
        import copy
        rec_cb = copy.deepcopy(event["commit_bindings"])
        rec_cb["standards"]["target_tag"] = "v2.11.0"
        record = {
            "repository": "example-owner/consumer-app",
            "approval_status": "OWNER_APPROVED",
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "approved_at": "2026-11-17T00:00:00Z",
            "commit_bindings": rec_cb,
            "content_bindings": event["content_bindings"],
            "approval_event": event,
        }
        mock_pr_response = {
            "merged": True,
            "merged_by": {"login": "example-owner"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_sha},
            "merged_at": "2026-11-17T00:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(mock_pr_response).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_urlopen.return_value = mock_resp

                status, errors = verify_approval_event_provenance(record)
                self.assertEqual(status, "FAILED")
                self.assertTrue(any("COMMIT_BINDINGS_MISMATCH" in e for e in errors))

    def test_f12_missing_commit_bindings_in_promotion_fails(self) -> None:
        from unittest.mock import patch, MagicMock
        from tools.validate_approval_contract import verify_approval_event_provenance

        consumer_sha = "c" * 40
        event = {
            "event_id": "42",
            "event_type": "GITHUB_PR_MERGE_EVENT",
            "provenance_type": "GITHUB_PR_MERGE",
            "actor_identity": {
                "identity_id": "example-owner",
                "identity_type": "GITHUB_USER",
                "service_provenance_ref": "https://api.github.com/repos/example-owner/consumer-app/pulls/42",
            },
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "event_timestamp": "2026-11-17T00:00:00Z",
        }
        record = {
            "repository": "example-owner/consumer-app",
            "approval_status": "OWNER_APPROVED",
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "approved_at": "2026-11-17T00:00:00Z",
            "approval_event": event,
        }
        mock_pr_response = {
            "merged": True,
            "merged_by": {"login": "example-owner"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_sha},
            "merged_at": "2026-11-17T00:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(mock_pr_response).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_urlopen.return_value = mock_resp

                status, errors = verify_approval_event_provenance(record)
                self.assertEqual(status, "FAILED")
                self.assertTrue(any("LEGACY_SINGLE_COMMIT_BYPASS_FORBIDDEN" in e or "MISSING" in e for e in errors))

    def test_f12_legacy_single_commit_bypass_fails_for_promotion(self) -> None:
        from unittest.mock import patch, MagicMock
        from tools.validate_approval_contract import verify_approval_event_provenance

        consumer_sha = "c" * 40
        # No commit_bindings at all, only single candidate_commit
        event = {
            "event_id": "42",
            "event_type": "GITHUB_PR_MERGE_EVENT",
            "provenance_type": "GITHUB_PR_MERGE",
            "actor_identity": {
                "identity_id": "example-owner",
                "identity_type": "GITHUB_USER",
                "service_provenance_ref": "https://api.github.com/repos/example-owner/consumer-app/pulls/42",
            },
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "event_timestamp": "2026-11-17T00:00:00Z",
        }
        record = {
            "repository": "example-owner/consumer-app",
            "approval_status": "OWNER_APPROVED",
            "candidate_commit": consumer_sha,
            "content_sha256": "sha256:" + "e" * 64,
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "approved_at": "2026-11-17T00:00:00Z",
            "approval_event": event,
        }
        mock_pr_response = {
            "merged": True,
            "merged_by": {"login": "example-owner"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_sha},
            "merged_at": "2026-11-17T00:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "dummy-token"}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(mock_pr_response).encode("utf-8")
                mock_resp.__enter__.return_value = mock_resp
                mock_urlopen.return_value = mock_resp

                status, errors = verify_approval_event_provenance(record)
                self.assertEqual(status, "FAILED")
                self.assertTrue(any("LEGACY_SINGLE_COMMIT_BYPASS_FORBIDDEN" in e for e in errors))


class FinalBlockerClosureRound2Tests(unittest.TestCase):
    """Comprehensive Round 2 tests covering F11, F12 dual-commit, content bindings recomputation, and Acceptance multi-file transaction."""

    def _build_consumer_fixture(self, repo_name: str = "xiefeifeihu/AI-Engineering-Hub") -> tuple[Path, str]:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        _copy_minimal_valid_project(root)
        # Update repository name in engineering-manifest.yaml to simulate downstream consumer
        mf_path = root / "engineering-manifest.yaml"
        mf_data = yaml.safe_load(mf_path.read_text(encoding="utf-8"))
        mf_data["project"]["repository"] = repo_name
        mf_data.setdefault("standards_validation", {}).setdefault("required_ci_jobs", {
            "unit_tests": {"workflow_path": ".github/workflows/ci.yml", "job_name": "unit", "command": "pytest"}
        })
        mf_path.write_text(yaml.safe_dump(mf_data, sort_keys=False, allow_unicode=True), encoding="utf-8")

        # Set existing lock to v2.11.0
        lk_path = root / "standards.lock.json"
        lk = json.loads(lk_path.read_text(encoding="utf-8"))
        lk["version"] = "2.11.0"
        lk["tag"] = "v2.11.0"
        lk["tag_object_sha"] = "2f4b4b54348a5ac8891e5a0b33c04635a27213a0"
        lk["peeled_commit"] = "5e17c0ef560ab8abafe880b988d70f85f380a104"
        lk["previous_locks"] = []
        lk_path.write_text(json.dumps(lk, indent=2), encoding="utf-8")

        subprocess.run(["git", "-C", str(root), "add", "engineering-manifest.yaml", "standards.lock.json"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(root), "commit", "--allow-empty", "-m", "consumer fixture"], capture_output=True, check=True)
        commit_sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        return root, commit_sha

    def _make_promo_approval(
        self,
        root: Path,
        consumer_repo: str,
        consumer_commit: str,
        std_tag: str = "v3.0.0",
        std_tag_obj: str = "8256bb384e62894219db0992a2cb57e16d4fa8cd",
        std_peeled: str = "8b223019c254e0edeb94576b94af46c1e48b0316",
        content_bindings_override: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        from tools.validate_approval_contract import compute_content_bindings
        if content_bindings_override is None:
            st, cnt, errs = compute_content_bindings(root, git_commit=consumer_commit, prefer_git=True)
            if st != "PASS" or cnt is None:
                st, cnt, errs = compute_content_bindings(root)
            self.assertEqual(st, "PASS", errs)
            assert cnt is not None
        else:
            cnt = content_bindings_override
        cb = {
            "consumer": {
                "repository": consumer_repo,
                "candidate_commit": consumer_commit,
            },
            "standards": {
                "repository": "xiefeifeihu/AI-Engineering-Standards",
                "target_tag": std_tag,
                "tag_object_sha": std_tag_obj,
                "peeled_commit": std_peeled,
            },
        }
        owner_login = consumer_repo.split("/", 1)[0]
        return {
            "schema_version": "1.0.0",
            "task_id": "HUB-002-PROMO",
            "repository": consumer_repo,
            "candidate_commit": consumer_commit,
            "content_sha256": "sha256:" + "a" * 64,
            "decision_scope": "STANDARDS_LOCK_PROMOTION",
            "approval_scope": "STANDARDS_LOCK_PROMOTION",
            "reviewer_type": "OWNER",
            "actor_role": "REPOSITORY_OWNER",
            "review_result": "OWNER_APPROVED",
            "approval_status": "OWNER_APPROVED",
            "approved_at": "2026-11-18T00:00:00Z",
            "approval_reference": f"https://github.com/{consumer_repo}/pull/88",
            "commit_bindings": cb,
            "content_bindings": cnt,
            "chatgpt_review": {
                "reviewer": "ChatGPT",
                "reviewed_at": "2026-11-18T00:00:00Z",
                "candidate_commit": consumer_commit,
                "content_sha256": "sha256:" + "a" * 64,
                "review_result": "READY_FOR_OWNER_MERGE",
                "review_reference": "REF-R2-1",
                "summary": "Independent review",
            },
            "owner_approval": {
                "approver": owner_login,
                "approval_channel": "GITHUB_PR_MERGE",
                "approved_at": "2026-11-18T00:00:00Z",
                "candidate_commit": consumer_commit,
                "content_sha256": "sha256:" + "a" * 64,
                "approved_decision_ids": ["D-HUB-001"],
                "approval_reference": f"https://github.com/{consumer_repo}/pull/88",
                "decision": "OWNER_APPROVED",
            },
            "approval_event": {
                "event_id": "88",
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "actor_identity": {
                    "identity_id": owner_login,
                    "identity_type": "GITHUB_USER",
                    "service_provenance_ref": f"https://api.github.com/repos/{consumer_repo}/pulls/88",
                },
                "candidate_commit": consumer_commit,
                "content_sha256": "sha256:" + "a" * 64,
                "approval_scope": "STANDARDS_LOCK_PROMOTION",
                "event_timestamp": "2026-11-18T00:00:00Z",
                "commit_bindings": cb,
                "content_bindings": cnt,
            },
        }

    # --- A. Dual-Commit Tests ---
    def test_a1_dual_commit_distinct_promotion_passes(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import promote_upgrade

        root, consumer_commit = self._build_consumer_fixture("xiefeifeihu/AI-Engineering-Hub")
        std_peeled = "8b223019c254e0edeb94576b94af46c1e48b0316"
        std_tag_obj = "8256bb384e62894219db0992a2cb57e16d4fa8cd"
        self.assertNotEqual(consumer_commit, std_peeled)

        app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", consumer_commit)
        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_commit},
            "merged_at": "2026-11-18T00:00:00Z",
        }
        with patch("tools.standards_sync.core.check_remote_main_ci", return_value=("PASS", 99999, "Mock CI")):
            with patch("tools.standards_sync.core.validate_upgrade_candidate", return_value={"status": "PASS", "errors": []}):
                res = promote_upgrade(
                    project_root=root,
                    target_tag="v3.0.0",
                    target_version="3.0.0",
                    target_tag_object_sha=std_tag_obj,
                    target_peeled_commit=std_peeled,
                    approval_record=app,
                    standards_root=ROOT,
                    consumer_candidate_commit=consumer_commit,
                    simulate_provenance_data=sim_pr,
                )
        self.assertEqual(res["status"], "PROMOTED", res)
        self.assertEqual(res["lock"]["peeled_commit"], std_peeled)

    def test_a2_dual_commit_same_commit_confusion_blocks(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import promote_upgrade

        root, _ = self._build_consumer_fixture("xiefeifeihu/AI-Engineering-Hub")
        std_peeled = "8b223019c254e0edeb94576b94af46c1e48b0316"
        std_tag_obj = "8256bb384e62894219db0992a2cb57e16d4fa8cd"
        # Confuse consumer commit with standards peeled commit
        app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", std_peeled)
        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": std_peeled},
            "merged_at": "2026-11-18T00:00:00Z",
        }
        with patch("tools.standards_sync.core.check_remote_main_ci", return_value=("PASS", 99999, "Mock CI")):
            res = promote_upgrade(
                project_root=root,
                target_tag="v3.0.0",
                target_version="3.0.0",
                target_tag_object_sha=std_tag_obj,
                target_peeled_commit=std_peeled,
                approval_record=app,
                standards_root=ROOT,
                simulate_provenance_data=sim_pr,
            )
        self.assertEqual(res["status"], "UPGRADE_BLOCKED")
        self.assertIn("PROMOTION_COMMIT_CONFUSION_FORBIDDEN", res["reason"])

    def test_a3_dual_commit_wrong_consumer_commit_blocks(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import promote_upgrade

        root, consumer_commit = self._build_consumer_fixture("xiefeifeihu/AI-Engineering-Hub")
        std_peeled = "8b223019c254e0edeb94576b94af46c1e48b0316"
        std_tag_obj = "8256bb384e62894219db0992a2cb57e16d4fa8cd"
        app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", consumer_commit)
        # Actual PR HEAD differs from approved consumer candidate_commit
        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": "e" * 40},
            "merged_at": "2026-11-18T00:00:00Z",
        }
        with patch("tools.standards_sync.core.check_remote_main_ci", return_value=("PASS", 99999, "Mock CI")):
            res = promote_upgrade(
                project_root=root,
                target_tag="v3.0.0",
                target_version="3.0.0",
                target_tag_object_sha=std_tag_obj,
                target_peeled_commit=std_peeled,
                approval_record=app,
                standards_root=ROOT,
                simulate_provenance_data=sim_pr,
            )
        self.assertEqual(res["status"], "UPGRADE_BLOCKED")
        self.assertTrue(any("APPROVAL_PR_HEAD_COMMIT_MISMATCH" in e for e in res.get("errors", [])))

    def test_a4_dual_commit_wrong_standards_commit_blocks(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import promote_upgrade

        root, consumer_commit = self._build_consumer_fixture("xiefeifeihu/AI-Engineering-Hub")
        std_peeled = "8b223019c254e0edeb94576b94af46c1e48b0316"
        std_tag_obj = "8256bb384e62894219db0992a2cb57e16d4fa8cd"
        app = self._make_promo_approval(
            root,
            "xiefeifeihu/AI-Engineering-Hub",
            consumer_commit,
            std_peeled="f" * 40,
        )
        with patch("tools.standards_sync.core.check_remote_main_ci", return_value=("PASS", 99999, "Mock CI")):
            res = promote_upgrade(
                project_root=root,
                target_tag="v3.0.0",
                target_version="3.0.0",
                target_tag_object_sha=std_tag_obj,
                target_peeled_commit=std_peeled,
                approval_record=app,
                standards_root=ROOT,
            )
        self.assertEqual(res["status"], "UPGRADE_BLOCKED")
        self.assertIn("PROMOTION_BINDING_MISMATCH", res["reason"])

    def test_a5_dual_commit_wrong_tag_object_blocks(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import promote_upgrade

        root, consumer_commit = self._build_consumer_fixture("xiefeifeihu/AI-Engineering-Hub")
        std_peeled = "8b223019c254e0edeb94576b94af46c1e48b0316"
        std_tag_obj = "8256bb384e62894219db0992a2cb57e16d4fa8cd"
        app = self._make_promo_approval(
            root,
            "xiefeifeihu/AI-Engineering-Hub",
            consumer_commit,
            std_tag_obj="9" * 40,
        )
        with patch("tools.standards_sync.core.check_remote_main_ci", return_value=("PASS", 99999, "Mock CI")):
            res = promote_upgrade(
                project_root=root,
                target_tag="v3.0.0",
                target_version="3.0.0",
                target_tag_object_sha=std_tag_obj,
                target_peeled_commit=std_peeled,
                approval_record=app,
                standards_root=ROOT,
            )
        self.assertEqual(res["status"], "UPGRADE_BLOCKED")
        self.assertIn("PROMOTION_BINDING_MISMATCH", res["reason"])

    # --- B. Content Bindings Recomputation Tests ---
    def test_b1_content_bindings_exact_recomputation_passes(self) -> None:
        from tools.validate_approval_contract import verify_approval_event_provenance

        root, consumer_commit = self._build_consumer_fixture()
        app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", consumer_commit)
        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_commit},
            "merged_at": "2026-11-18T00:00:00Z",
        }
        status, errors = verify_approval_event_provenance(app, simulate_data=sim_pr, project_root=root)
        self.assertEqual(status, "VERIFIED", errors)

    def test_b2_content_bindings_wrong_digest_blocks(self) -> None:
        from tools.validate_approval_contract import verify_approval_event_provenance

        root, consumer_commit = self._build_consumer_fixture()
        fake_cnt = {
            "ci_job_mapping_sha256": "sha256:" + "1" * 64,
            "lock_manifest_sha256": "sha256:" + "2" * 64,
        }
        app = self._make_promo_approval(
            root,
            "xiefeifeihu/AI-Engineering-Hub",
            consumer_commit,
            content_bindings_override=fake_cnt,
        )
        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_commit},
            "merged_at": "2026-11-18T00:00:00Z",
        }
        status, errors = verify_approval_event_provenance(app, simulate_data=sim_pr, project_root=root)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONTENT_BINDING_DIGEST_MISMATCH" in e for e in errors))

    def test_b3_content_bindings_invalidated_when_manifest_modified(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import promote_upgrade

        root, consumer_commit = self._build_consumer_fixture()
        old_app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", consumer_commit)

        # Modify engineering-manifest.yaml required_ci_jobs in a new commit AFTER approval was issued
        mf_path = root / "engineering-manifest.yaml"
        mf_data = yaml.safe_load(mf_path.read_text(encoding="utf-8"))
        mf_data["standards_validation"]["required_ci_jobs"]["unit_tests"]["command"] = "pytest --skip-all"
        mf_path.write_text(yaml.safe_dump(mf_data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "engineering-manifest.yaml"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "modify manifest"], capture_output=True, check=True)
        new_sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

        # Rebind commit pointers to new_sha while retaining old content_bindings digests
        app = json.loads(json.dumps(old_app))
        app["candidate_commit"] = new_sha
        app["commit_bindings"]["consumer"]["candidate_commit"] = new_sha
        app["chatgpt_review"]["candidate_commit"] = new_sha
        app["owner_approval"]["candidate_commit"] = new_sha
        app["approval_event"]["candidate_commit"] = new_sha
        app["approval_event"]["commit_bindings"]["consumer"]["candidate_commit"] = new_sha

        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": new_sha},
            "merged_at": "2026-11-18T00:00:00Z",
        }
        with patch("tools.standards_sync.core.check_remote_main_ci", return_value=("PASS", 99999, "Mock CI")):
            res = promote_upgrade(
                project_root=root,
                target_tag="v3.0.0",
                target_version="3.0.0",
                target_tag_object_sha="8256bb384e62894219db0992a2cb57e16d4fa8cd",
                target_peeled_commit="8b223019c254e0edeb94576b94af46c1e48b0316",
                approval_record=app,
                standards_root=ROOT,
                simulate_provenance_data=sim_pr,
            )
        self.assertEqual(res["status"], "UPGRADE_BLOCKED")
        self.assertIn("CONTENT_BINDINGS_MISMATCH", res["reason"])

    def test_b4_content_bindings_invalidated_when_lock_modified(self) -> None:
        from tools.validate_approval_contract import verify_approval_event_provenance

        root, consumer_commit = self._build_consumer_fixture()
        old_app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", consumer_commit)

        # Modify standards.lock.json in a new commit AFTER approval was issued
        lk_path = root / "standards.lock.json"
        lk = json.loads(lk_path.read_text(encoding="utf-8"))
        lk["lock_reason"] = "Tampered reason"
        lk_path.write_text(json.dumps(lk, indent=2), encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "standards.lock.json"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "modify lock"], capture_output=True, check=True)
        new_sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

        app = json.loads(json.dumps(old_app))
        app["candidate_commit"] = new_sha
        app["commit_bindings"]["consumer"]["candidate_commit"] = new_sha
        app["approval_event"]["candidate_commit"] = new_sha
        app["approval_event"]["commit_bindings"]["consumer"]["candidate_commit"] = new_sha

        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": new_sha},
            "merged_at": "2026-11-18T00:00:00Z",
        }
        status, errors = verify_approval_event_provenance(app, simulate_data=sim_pr, project_root=root)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONTENT_BINDING_DIGEST_MISMATCH" in e and "lock_manifest_sha256" in e for e in errors))

    def test_b5_content_bindings_missing_file_returns_not_verifiable(self) -> None:
        from tools.validate_approval_contract import verify_approval_event_provenance

        root, consumer_commit = self._build_consumer_fixture()
        old_app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", consumer_commit)
        subprocess.run(["git", "-C", str(root), "rm", "-f", "standards.lock.json"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "remove lock"], capture_output=True, check=True)
        new_sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

        app = json.loads(json.dumps(old_app))
        app["candidate_commit"] = new_sha
        app["commit_bindings"]["consumer"]["candidate_commit"] = new_sha
        app["approval_event"]["candidate_commit"] = new_sha
        app["approval_event"]["commit_bindings"]["consumer"]["candidate_commit"] = new_sha

        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": new_sha},
            "merged_at": "2026-11-18T00:00:00Z",
        }
        status, errors = verify_approval_event_provenance(app, simulate_data=sim_pr, project_root=root)
        self.assertEqual(status, "NOT_VERIFIABLE")
        self.assertTrue(any("UNVERIFIABLE_CONTENT_BINDINGS" in e for e in errors))

        # Without project_root also returns NOT_VERIFIABLE
        status2, _ = verify_approval_event_provenance(app, simulate_data=sim_pr, project_root=None)
        self.assertEqual(status2, "NOT_VERIFIABLE")

    def test_b6_content_bindings_git_commit_mode_and_unreadable_commit(self) -> None:
        from tools.validate_approval_contract import compute_content_bindings, verify_content_bindings_digests

        root, head_sha = self._build_consumer_fixture()

        st, digests, errs = compute_content_bindings(root, git_commit=head_sha, prefer_git=True)
        self.assertEqual(st, "PASS", errs)
        assert digests is not None

        # Unreadable commit returns NOT_VERIFIABLE
        st_bad, _, errs_bad = compute_content_bindings(root, git_commit="0" * 40, prefer_git=True)
        self.assertEqual(st_bad, "NOT_VERIFIABLE")
        self.assertTrue(any("unreadable" in e.lower() for e in errs_bad))

        # Verify against valid commit passes
        app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", "c" * 40, content_bindings_override=digests)
        vst, verrs = verify_content_bindings_digests(app, app["approval_event"], project_root=root, git_commit=head_sha, prefer_git=True)
        self.assertEqual(vst, "PASS", verrs)

    # --- C. Rollback & Tag Verification Tests ---
    def test_c1_rollback_require_authorization_false_blocked(self) -> None:
        from tools.standards_sync.core import rollback_lock
        root, _ = self._build_consumer_fixture()
        # Even if an auth file is supplied, require_authorization=False MUST be blocked
        res = rollback_lock(
            root,
            rollback_authorization_ref="docs/any.json",
            require_authorization=False,
            standards_root=ROOT,
        )
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("ROLLBACK_AUTHORIZATION_BYPASS_FORBIDDEN", res["reason"])

    def test_c2_rollback_no_auth_blocked(self) -> None:
        from tools.standards_sync.core import rollback_lock
        root, _ = self._build_consumer_fixture()
        res = rollback_lock(root, rollback_authorization_ref=None, standards_root=ROOT)
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("MISSING_ROLLBACK_AUTHORIZATION", res["reason"])

    def test_c3_verify_tag_missing_version_blocks(self) -> None:
        from tools.standards_sync.core import verify_official_historical_tag
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "std"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@s.local"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], capture_output=True, check=True)
            # Commit WITHOUT VERSION file
            (repo / "README.md").write_text("no version file\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "no version"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "tag", "-a", "v1.0.0", "-m", "v1.0.0"], capture_output=True, check=True)
            peeled = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            tag_obj = subprocess.run(["git", "-C", str(repo), "rev-parse", "refs/tags/v1.0.0"], capture_output=True, text=True, check=True).stdout.strip()

            st, err = verify_official_historical_tag(
                standards_root=repo,
                tag="v1.0.0",
                tag_object_sha=tag_obj,
                peeled_commit=peeled,
                expected_version="1.0.0",
                simulate_remote_refs={
                    "refs/tags/v1.0.0": tag_obj,
                    "refs/tags/v1.0.0^{}": peeled,
                    "refs/heads/main": peeled,
                },
            )
            self.assertEqual(st, "FAIL")
            self.assertIn("VERSION_MISSING_OR_UNREADABLE", str(err))

    def test_c4_verify_tag_missing_standards_root_not_verifiable(self) -> None:
        from tools.standards_sync.core import verify_official_historical_tag
        sim_refs = {
            "refs/tags/v2.11.0": "2f4b4b54348a5ac8891e5a0b33c04635a27213a0",
            "refs/tags/v2.11.0^{}": "5e17c0ef560ab8abafe880b988d70f85f380a104",
            "refs/heads/main": "8b223019c254e0edeb94576b94af46c1e48b0316",
        }
        st1, err1 = verify_official_historical_tag(
            standards_root=None,
            tag="v2.11.0",
            tag_object_sha="2f4b4b54348a5ac8891e5a0b33c04635a27213a0",
            peeled_commit="5e17c0ef560ab8abafe880b988d70f85f380a104",
            simulate_remote_refs=sim_refs,
        )
        self.assertEqual(st1, "NOT_VERIFIABLE")
        self.assertIn("STANDARDS_ROOT_MISSING", str(err1))

        st2, err2 = verify_official_historical_tag(
            standards_root=Path("/nonexistent/standards_root_dir"),
            tag="v2.11.0",
            tag_object_sha="2f4b4b54348a5ac8891e5a0b33c04635a27213a0",
            peeled_commit="5e17c0ef560ab8abafe880b988d70f85f380a104",
            simulate_remote_refs=sim_refs,
        )
        self.assertEqual(st2, "NOT_VERIFIABLE")
        self.assertIn("STANDARDS_ROOT_MISSING", str(err2))

    def test_c5_verify_tag_missing_git_object_not_verifiable(self) -> None:
        from tools.standards_sync.core import verify_official_historical_tag
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "std"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@s.local"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], capture_output=True, check=True)
            (repo / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True, check=True)
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

            missing_peeled = "9" * 40
            st, err = verify_official_historical_tag(
                standards_root=repo,
                tag="v2.11.0",
                tag_object_sha="8" * 40,
                peeled_commit=missing_peeled,
                simulate_remote_refs={
                    "refs/tags/v2.11.0": "8" * 40,
                    "refs/tags/v2.11.0^{}": missing_peeled,
                    "refs/heads/main": head,
                },
            )
            self.assertEqual(st, "NOT_VERIFIABLE")
            self.assertIn("GIT_OBJECT_MISSING", str(err))

    def test_c6_verify_tag_remote_unreachable_not_verifiable(self) -> None:
        from tools.standards_sync.core import verify_official_historical_tag
        st, err = verify_official_historical_tag(
            standards_root=ROOT,
            tag="v2.11.0",
            tag_object_sha="2f4b4b54348a5ac8891e5a0b33c04635a27213a0",
            peeled_commit="5e17c0ef560ab8abafe880b988d70f85f380a104",
            simulate_offline=True,
        )
        self.assertEqual(st, "NOT_VERIFIABLE")
        self.assertIn("unreachable", str(err).lower())

    # --- D. Packager Multi-File Transaction Fault Injection Tests ---
    def _setup_pkg_fixture(self, with_existing_pkg: bool = True):
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        acc_dir = root / ".artifacts" / "acceptance" / "TX-TASK" / "v3.0.0"
        acc_dir.mkdir(parents=True, exist_ok=True)
        doc = acc_dir / "report.md"
        doc.write_text("# Report\nAll pass.\n", encoding="utf-8")
        doc_sha = hashlib.sha256(doc.read_bytes()).hexdigest()
        manifest = {
            "task_id": "TX-TASK",
            "version": "v3.0.0",
            "run_id": "orig-run",
            "created_at": "2026-11-18T00:00:00Z",
            "files": [{"path": "report.md", "size": doc.stat().st_size, "sha256": doc_sha}],
        }
        manifest_path = acc_dir / "manifest.json"
        orig_manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        manifest_path.write_bytes(orig_manifest_bytes)

        pkg_dir = root / ".artifacts" / "packages"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        zip_path = pkg_dir / "Acceptance-TX-TASK-v3.0.0.zip"
        sha_path = pkg_dir / "Acceptance-TX-TASK-v3.0.0.zip.sha256"
        if with_existing_pkg:
            zip_path.write_bytes(b"ORIGINAL_VALID_ZIP_BYTES")
            sha_path.write_bytes(b"ORIGINAL_VALID_SHA_BYTES")
        return root, manifest_path, zip_path, sha_path, pkg_dir, acc_dir

    def test_d1_packager_manifest_replace_failure_restores_all_three(self) -> None:
        from scripts.package_acceptance import package_acceptance
        root, manifest_path, zip_path, sha_path, pkg_dir, acc_dir = self._setup_pkg_fixture(True)
        orig_m = manifest_path.read_bytes()
        orig_z = zip_path.read_bytes()
        orig_s = sha_path.read_bytes()

        def fail_on_manifest(src: Path, dst: Path) -> None:
            if dst == manifest_path and ".tmp_manifest_" in src.name:
                raise OSError("Injected manifest replace failure")
            os.replace(src, dst)

        with self.assertRaises(OSError):
            package_acceptance("TX-TASK", version="3.0.0", run_id="new-run", repo_root=root, replace_fn=fail_on_manifest, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")

        self.assertEqual(manifest_path.read_bytes(), orig_m)
        self.assertEqual(zip_path.read_bytes(), orig_z)
        self.assertEqual(sha_path.read_bytes(), orig_s)
        self.assertEqual(list(pkg_dir.glob(".*")), [])
        self.assertEqual(list(acc_dir.glob(".*")), [])

    def test_d2_packager_zip_write_failure_restores_all_three(self) -> None:
        from unittest.mock import patch
        from scripts.package_acceptance import package_acceptance
        root, manifest_path, zip_path, sha_path, pkg_dir, acc_dir = self._setup_pkg_fixture(True)
        orig_m = manifest_path.read_bytes()
        orig_z = zip_path.read_bytes()
        orig_s = sha_path.read_bytes()

        with patch("scripts.package_acceptance.zipfile.ZipFile", side_effect=OSError("Injected ZIP write error")):
            with self.assertRaises(OSError):
                package_acceptance("TX-TASK", version="3.0.0", run_id="new-run", repo_root=root, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")

        self.assertEqual(manifest_path.read_bytes(), orig_m)
        self.assertEqual(zip_path.read_bytes(), orig_z)
        self.assertEqual(sha_path.read_bytes(), orig_s)
        self.assertEqual(list(pkg_dir.glob(".*")), [])
        self.assertEqual(list(acc_dir.glob(".*")), [])

    def test_d3_packager_zip_succeeds_sidecar_fails_restores_all_three_via_temp_replace(self) -> None:
        from scripts.package_acceptance import package_acceptance
        root, manifest_path, zip_path, sha_path, pkg_dir, acc_dir = self._setup_pkg_fixture(True)
        orig_m = manifest_path.read_bytes()
        orig_z = zip_path.read_bytes()
        orig_s = sha_path.read_bytes()

        replace_ops: List[tuple[str, Path]] = []
        def fail_on_sidecar(src: Path, dst: Path) -> None:
            replace_ops.append((src.name, dst))
            if dst == sha_path and ".tmp_Acceptance-" in src.name:
                raise PermissionError("Injected sidecar replace failure")
            os.replace(src, dst)

        with self.assertRaises(PermissionError):
            package_acceptance("TX-TASK", version="3.0.0", run_id="new-run", repo_root=root, replace_fn=fail_on_sidecar, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")

        # Verify restoration itself used temp files + atomic replace
        restore_calls = [src_name for src_name, _ in replace_ops if ".tmp_restore" in src_name]
        self.assertEqual(len(restore_calls), 3)
        self.assertEqual(manifest_path.read_bytes(), orig_m)
        self.assertEqual(zip_path.read_bytes(), orig_z)
        self.assertEqual(sha_path.read_bytes(), orig_s)
        self.assertEqual(list(pkg_dir.glob(".*")), [])
        self.assertEqual(list(acc_dir.glob(".*")), [])

        # Also test no pre-existing ZIP/Sidecar: new ZIP committed then Sidecar fails -> new ZIP must be removed
        root2, m2, z2, s2, p2, a2 = self._setup_pkg_fixture(False)
        orig_m2 = m2.read_bytes()
        def fail_on_s2(src: Path, dst: Path) -> None:
            if dst == s2 and ".tmp_Acceptance-" in src.name:
                raise PermissionError("Injected sidecar replace failure")
            os.replace(src, dst)
        with self.assertRaises(PermissionError):
            package_acceptance("TX-TASK", version="3.0.0", run_id="new-run-2", repo_root=root2, replace_fn=fail_on_s2)
        self.assertEqual(m2.read_bytes(), orig_m2)
        self.assertFalse(z2.exists())
        self.assertFalse(s2.exists())
        self.assertEqual(list(p2.glob(".*")), [])

    def test_d4_packager_original_recovery_failure_preserves_backups_and_journal(self) -> None:
        from scripts.package_acceptance import package_acceptance
        root, manifest_path, zip_path, sha_path, pkg_dir, _ = self._setup_pkg_fixture(True)

        def fail_sidecar_and_restore(src: Path, dst: Path) -> None:
            if dst == sha_path and ".tmp_Acceptance-" in src.name:
                raise OSError("Injected sidecar failure")
            if dst == zip_path and ".tmp_restore" in src.name:
                raise OSError("Injected zip recovery failure")
            os.replace(src, dst)

        with self.assertRaises(RuntimeError) as ctx:
            package_acceptance("TX-TASK", version="3.0.0", run_id="new-run", repo_root=root, replace_fn=fail_sidecar_and_restore, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")
        self.assertIn("TRANSACTION_RECOVERY_FAILED", str(ctx.exception))
        # Journal and backup must be preserved on recovery failure
        journals = list(pkg_dir.glob(".tx_journal_*"))
        self.assertEqual(len(journals), 1)
        jdata = json.loads(journals[0].read_text(encoding="utf-8"))
        self.assertEqual(jdata["state"], "RECOVERY_FAILED")
        self.assertTrue(list(pkg_dir.glob(".bak_*")))

    def test_d5_packager_temp_cleanup_failure_raises_without_corrupting_files(self) -> None:
        from scripts.package_acceptance import package_acceptance
        root, manifest_path, zip_path, sha_path, pkg_dir, _ = self._setup_pkg_fixture(True)
        orig_m = manifest_path.read_bytes()
        orig_z = zip_path.read_bytes()
        orig_s = sha_path.read_bytes()

        # Case 1: Rollback restores all 3 files, then cleanup of .bak fails
        def fail_sidecar_replace(src: Path, dst: Path) -> None:
            if dst == sha_path and ".tmp_Acceptance-" in src.name:
                raise OSError("Injected sidecar fail")
            os.replace(src, dst)

        def fail_bak_unlink(p: Path) -> None:
            if ".bak_" in p.name:
                raise PermissionError("Injected temp cleanup failure")
            p.unlink()

        with self.assertRaises(RuntimeError) as ctx1:
            package_acceptance(
                "TX-TASK",
                version="3.0.0",
                run_id="new-run",
                repo_root=root,
                replace_fn=fail_sidecar_replace,
                unlink_fn=fail_bak_unlink,
                allow_overwrite=True,
                overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL",
            )
        self.assertIn("TRANSACTION_ROLLED_BACK_CLEANUP_FAILED", str(ctx1.exception))
        # All 3 originals must still be intact
        self.assertEqual(manifest_path.read_bytes(), orig_m)
        self.assertEqual(zip_path.read_bytes(), orig_z)
        self.assertEqual(sha_path.read_bytes(), orig_s)


class F12RollbackCommitBindingTests(unittest.TestCase):
    """F12: Strict candidate_commit binding and no worktree bypass for rollback and promotion."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _init_git(self, repo_dir: Path) -> None:
        subprocess.run(["git", "-C", str(repo_dir), "init", "-b", "main"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "test@example.com"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "Test User"], capture_output=True, check=True)

    def _setup_rollback_env(self):
        std_root = self.base / "standards_repo"
        std_root.mkdir(parents=True, exist_ok=True)
        self._init_git(std_root)
        (std_root / "VERSION").write_text("2.11.0\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(std_root), "add", "VERSION"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(std_root), "commit", "-m", "v2.11.0"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(std_root), "tag", "-a", "v2.11.0", "-m", "Release v2.11.0"], capture_output=True, check=True)
        v211_peeled = subprocess.run(["git", "-C", str(std_root), "rev-parse", "v2.11.0^{commit}"], capture_output=True, text=True, check=True).stdout.strip()
        v211_tag_obj = subprocess.run(["git", "-C", str(std_root), "rev-parse", "v2.11.0"], capture_output=True, text=True, check=True).stdout.strip()

        (std_root / "VERSION").write_text("3.0.0\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(std_root), "add", "VERSION"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(std_root), "commit", "-m", "v3.0.0"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(std_root), "tag", "-a", "v3.0.0", "-m", "Release v3.0.0"], capture_output=True, check=True)
        v300_peeled = subprocess.run(["git", "-C", str(std_root), "rev-parse", "v3.0.0^{commit}"], capture_output=True, text=True, check=True).stdout.strip()
        v300_tag_obj = subprocess.run(["git", "-C", str(std_root), "rev-parse", "v3.0.0"], capture_output=True, text=True, check=True).stdout.strip()

        cons_root = self.base / "consumer_repo"
        cons_root.mkdir(parents=True, exist_ok=True)
        self._init_git(cons_root)
        _copy_minimal_valid_project(cons_root)
        mf_path = cons_root / "engineering-manifest.yaml"
        mf_data = yaml.safe_load(mf_path.read_text(encoding="utf-8"))
        mf_data["project"]["repository"] = "xiefeifeihu/AI-Engineering-Hub"
        mf_data["standards_validation"] = {
            "required_ci_jobs": {"gate": "validate-standards"}
        }
        mf_path.write_text(yaml.safe_dump(mf_data, allow_unicode=True, sort_keys=False), encoding="utf-8")

        lock_data = {
            "schema_version": "1.0.0",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "3.0.0",
            "tag": "v3.0.0",
            "tag_object_sha": v300_tag_obj,
            "peeled_commit": v300_peeled,
            "locked_at": "2026-11-18T00:00:00Z",
            "lock_reason": "Upgraded to v3.0.0",
            "approval_evidence_ref": "docs/promo-auth.json",
            "ci_verification_status": "PASS",
            "previous_locks": [
                {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "version": "2.11.0",
                    "tag": "v2.11.0",
                    "tag_object_sha": v211_tag_obj,
                    "peeled_commit": v211_peeled,
                    "locked_at": "2026-11-10T00:00:00Z",
                    "lock_reason": "Bootstrap v2.11.0",
                    "approval_evidence_ref": None,
                    "ci_verification_status": "NOT_VERIFIABLE",
                }
            ],
        }
        (cons_root / "standards.lock.json").write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
        subprocess.run(["git", "-C", str(cons_root), "add", "engineering-manifest.yaml", "standards.lock.json"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(cons_root), "commit", "-m", "consumer head"], capture_output=True, check=True)
        cons_sha = subprocess.run(["git", "-C", str(cons_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

        sim_refs = {
            "refs/tags/v2.11.0": v211_tag_obj,
            "refs/tags/v2.11.0^{}": v211_peeled,
            "refs/tags/v3.0.0": v300_tag_obj,
            "refs/tags/v3.0.0^{}": v300_peeled,
            "refs/heads/main": v300_peeled,
        }
        return std_root, cons_root, cons_sha, v211_tag_obj, v211_peeled, sim_refs

    def _build_auth(
        self,
        cons_root: Path,
        cons_sha: str,
        tag: str,
        tag_obj: str,
        peeled: str,
        content_bindings: Dict[str, str],
        scope: str = "LOCK_ROLLBACK",
        repo: str = "xiefeifeihu/AI-Engineering-Hub",
        pr_head_sha: Optional[str] = None,
    ):
        auth = {
            "schema_version": "1.0.0",
            "task_id": "F12-PARITY-01",
            "repository": repo,
            "candidate_commit": cons_sha,
            "content_sha256": "sha256:" + "a" * 64,
            "decision_scope": scope,
            "approval_scope": scope,
            "reviewer_type": "OWNER",
            "actor_role": "REPOSITORY_OWNER",
            "review_result": "OWNER_APPROVED",
            "approval_status": "OWNER_APPROVED",
            "approved_at": "2026-11-18T00:00:00Z",
            "approval_reference": f"https://github.com/{repo}/pull/101",
            "commit_bindings": {
                "consumer": {"repository": repo, "candidate_commit": cons_sha},
                "standards": {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "target_tag": tag,
                    "tag_object_sha": tag_obj,
                    "peeled_commit": peeled,
                },
            },
            "content_bindings": dict(content_bindings),
            "chatgpt_review": {
                "reviewer": "ChatGPT",
                "reviewed_at": "2026-11-18T00:00:00Z",
                "candidate_commit": cons_sha,
                "content_sha256": "sha256:" + "a" * 64,
                "review_result": "READY_FOR_OWNER_MERGE",
                "review_reference": "REF-PARITY",
                "summary": "Independent review",
            },
            "owner_approval": {
                "approver": "xiefeifeihu",
                "approval_channel": "GITHUB_PR_MERGE",
                "approved_at": "2026-11-18T00:00:00Z",
                "candidate_commit": cons_sha,
                "content_sha256": "sha256:" + "a" * 64,
                "approved_decision_ids": ["D-01"],
                "approval_reference": f"https://github.com/{repo}/pull/101",
                "decision": "OWNER_APPROVED",
            },
            "approval_event": {
                "event_id": "101",
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "actor_identity": {
                    "identity_id": "xiefeifeihu",
                    "identity_type": "GITHUB_USER",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/101",
                },
                "candidate_commit": cons_sha,
                "content_sha256": "sha256:" + "a" * 64,
                "approval_scope": scope,
                "event_timestamp": "2026-11-18T00:00:00Z",
                "commit_bindings": {
                    "consumer": {"repository": repo, "candidate_commit": cons_sha},
                    "standards": {
                        "repository": "xiefeifeihu/AI-Engineering-Standards",
                        "target_tag": tag,
                        "tag_object_sha": tag_obj,
                        "peeled_commit": peeled,
                    },
                },
                "content_bindings": dict(content_bindings),
            },
        }
        sim_pr = {
            "number": 101,
            "merged": True,
            "merged_at": "2026-11-18T00:00:00Z",
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": pr_head_sha or cons_sha},
            "user": {"login": "xiefeifeihu"},
        }
        auth_file = cons_root / "docs" / "auth-record.json"
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        auth_file.write_text(json.dumps(auth, indent=2), encoding="utf-8")
        return auth_file, auth, sim_pr

    def test_a1_rollback_content_bindings_match_candidate_commit_passes(self) -> None:
        from tools.standards_sync.core import rollback_lock
        from tools.validate_approval_contract import compute_content_bindings

        std_root, cons_root, cons_sha, v211_tag, v211_peeled, sim_refs = self._setup_rollback_env()
        st, digests, errs = compute_content_bindings(cons_root, git_commit=cons_sha, prefer_git=True)
        self.assertEqual(st, "PASS", errs)
        assert digests is not None

        auth_file, _, sim_pr = self._build_auth(cons_root, cons_sha, "v2.11.0", v211_tag, v211_peeled, digests)
        res = rollback_lock(
            cons_root,
            rollback_authorization_ref=str(auth_file),
            standards_root=std_root,
            simulate_provenance_data=sim_pr,
            simulate_remote_refs=sim_refs,
        )
        self.assertEqual(res["status"], "ROLLED_BACK", res)
        lock_after = json.loads((cons_root / "standards.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock_after["version"], "2.11.0")

    def test_a2_rollback_worktree_matches_but_candidate_commit_differs_blocks_without_bypass(self) -> None:
        from tools.standards_sync.core import rollback_lock
        from tools.validate_approval_contract import compute_content_bindings, verify_approval_event_provenance

        std_root, cons_root, cons_sha, v211_tag, v211_peeled, sim_refs = self._setup_rollback_env()
        orig_lock = (cons_root / "standards.lock.json").read_text(encoding="utf-8")

        # Mutate working tree ONLY (uncommitted) and compute digests from worktree
        mf_path = cons_root / "engineering-manifest.yaml"
        mf_data = yaml.safe_load(mf_path.read_text(encoding="utf-8"))
        mf_data["standards_validation"] = {"required_ci_jobs": {"gate": "tampered-worktree-job"}}
        mf_path.write_text(yaml.safe_dump(mf_data, allow_unicode=True, sort_keys=False), encoding="utf-8")

        st_wt, wt_digests, errs_wt = compute_content_bindings(cons_root, prefer_git=False)
        self.assertEqual(st_wt, "PASS", errs_wt)
        assert wt_digests is not None

        auth_file, auth_dict, sim_pr = self._build_auth(
            cons_root, cons_sha, "v2.11.0", v211_tag, v211_peeled, wt_digests
        )
        # rollback_lock must verify strictly against cons_sha (prefer_git=True), NOT worktree!
        res = rollback_lock(
            cons_root,
            rollback_authorization_ref=str(auth_file),
            standards_root=std_root,
            simulate_provenance_data=sim_pr,
            simulate_remote_refs=sim_refs,
        )
        self.assertEqual(res["status"], "FAIL", res)
        self.assertIn("CONTENT_BINDINGS_MISMATCH", res["reason"])
        self.assertEqual((cons_root / "standards.lock.json").read_text(encoding="utf-8"), orig_lock)

        # Direct provenance call on LOCK_ROLLBACK must ALSO refuse worktree fallback
        pst, perrs = verify_approval_event_provenance(auth_dict, simulate_data=sim_pr, project_root=cons_root)
        self.assertEqual(pst, "FAILED")
        self.assertTrue(any("CONTENT_BINDING_DIGEST_MISMATCH" in e for e in perrs), perrs)

    def test_a3_rollback_forged_digest_equal_in_record_and_event_fails(self) -> None:
        from tools.standards_sync.core import rollback_lock

        std_root, cons_root, cons_sha, v211_tag, v211_peeled, sim_refs = self._setup_rollback_env()
        forged = {"ci_job_mapping_sha256": "sha256:" + "f" * 64, "lock_manifest_sha256": "sha256:" + "e" * 64}
        auth_file, _, sim_pr = self._build_auth(cons_root, cons_sha, "v2.11.0", v211_tag, v211_peeled, forged)
        res = rollback_lock(
            cons_root,
            rollback_authorization_ref=str(auth_file),
            standards_root=std_root,
            simulate_provenance_data=sim_pr,
            simulate_remote_refs=sim_refs,
        )
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("CONTENT_BINDINGS_MISMATCH", str(res))

    def test_a4_rollback_unreadable_consumer_commit_returns_not_verifiable(self) -> None:
        from tools.standards_sync.core import rollback_lock

        std_root, cons_root, _, v211_tag, v211_peeled, sim_refs = self._setup_rollback_env()
        fake_sha = "d" * 40
        forged = {"ci_job_mapping_sha256": "sha256:" + "1" * 64, "lock_manifest_sha256": "sha256:" + "2" * 64}
        auth_file, _, sim_pr = self._build_auth(cons_root, fake_sha, "v2.11.0", v211_tag, v211_peeled, forged)
        res = rollback_lock(
            cons_root,
            rollback_authorization_ref=str(auth_file),
            standards_root=std_root,
            simulate_provenance_data=sim_pr,
            simulate_remote_refs=sim_refs,
        )
        self.assertEqual(res["status"], "NOT_VERIFIABLE", res)

    def test_a5_rollback_pr_head_sha_mismatch_fails(self) -> None:
        from tools.standards_sync.core import rollback_lock
        from tools.validate_approval_contract import compute_content_bindings

        std_root, cons_root, cons_sha, v211_tag, v211_peeled, sim_refs = self._setup_rollback_env()
        _, digests, _ = compute_content_bindings(cons_root, git_commit=cons_sha, prefer_git=True)
        assert digests is not None
        auth_file, _, sim_pr = self._build_auth(
            cons_root, cons_sha, "v2.11.0", v211_tag, v211_peeled, digests, pr_head_sha="9" * 40
        )
        res = rollback_lock(
            cons_root,
            rollback_authorization_ref=str(auth_file),
            standards_root=std_root,
            simulate_provenance_data=sim_pr,
            simulate_remote_refs=sim_refs,
        )
        self.assertEqual(res["status"], "FAIL", res)
        self.assertIn("APPROVAL_PR_HEAD_COMMIT_MISMATCH", res["reason"])

    def test_a6_promote_and_rollback_parity_against_candidate_commit(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import promote_upgrade
        from tools.validate_approval_contract import compute_content_bindings

        promo_root = self.base / "promo_consumer_repo"
        promo_root.mkdir(parents=True, exist_ok=True)
        self._init_git(promo_root)
        _copy_minimal_valid_project(promo_root)

        mf_path = promo_root / "engineering-manifest.yaml"
        mf_data = yaml.safe_load(mf_path.read_text(encoding="utf-8"))
        mf_data["project"]["repository"] = "xiefeifeihu/AI-Engineering-Hub"
        mf_path.write_text(yaml.safe_dump(mf_data, allow_unicode=True, sort_keys=False), encoding="utf-8")

        promo_lock = {
            "schema_version": "1.0.0",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "version": "2.11.0",
            "tag": "v2.11.0",
            "tag_object_sha": "2f4b4b54348a5ac8891e5a0b33c04635a27213a0",
            "peeled_commit": "5e17c0ef560ab8abafe880b988d70f85f380a104",
            "locked_at": "2026-11-10T00:00:00Z",
            "lock_reason": "Bootstrap v2.11.0 for promote parity test",
            "approval_evidence_ref": None,
            "ci_verification_status": "NOT_VERIFIABLE",
            "previous_locks": [],
        }
        (promo_root / "standards.lock.json").write_text(
            json.dumps(promo_lock, indent=2) + "\n", encoding="utf-8"
        )

        subprocess.run(["git", "-C", str(promo_root), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(promo_root), "commit", "-m", "promo consumer head"], capture_output=True, check=True)
        cons_sha = subprocess.run(
            ["git", "-C", str(promo_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()

        v300_tag = "8256bb384e62894219db0992a2cb57e16d4fa8cd"
        v300_peeled = "8b223019c254e0edeb94576b94af46c1e48b0316"
        real_refs = {
            "refs/tags/v3.0.0": v300_tag,
            "refs/tags/v3.0.0^{}": v300_peeled,
            "refs/heads/main": v300_peeled,
        }

        # Mutate schema-valid working tree differently from cons_sha (changes lock_manifest_sha256)
        mf_data["project"]["description"] = "wt-only-modified"
        mf_path.write_text(yaml.safe_dump(mf_data, allow_unicode=True, sort_keys=False), encoding="utf-8")

        _, wt_digests, _ = compute_content_bindings(promo_root, prefer_git=False)
        _, commit_digests, _ = compute_content_bindings(promo_root, git_commit=cons_sha, prefer_git=True)
        assert wt_digests is not None and commit_digests is not None

        with patch("tools.standards_sync.core.check_remote_main_ci", return_value=("PASS", 99999, "Mock CI")), \
             patch("tools.standards_sync.core.validate_upgrade_candidate", return_value={"status": "PASS", "errors": []}):
            # Worktree-only digest MUST fail promote_upgrade
            _, app_wt, sim_pr = self._build_auth(
                promo_root, cons_sha, "v3.0.0", v300_tag, v300_peeled, wt_digests, scope="STANDARDS_LOCK_PROMOTION"
            )
            res_fail = promote_upgrade(
                promo_root,
                target_tag="v3.0.0",
                target_version="3.0.0",
                target_tag_object_sha=v300_tag,
                target_peeled_commit=v300_peeled,
                approval_record=app_wt,
                standards_root=ROOT,
                consumer_candidate_commit=cons_sha,
                simulate_provenance_data=sim_pr,
                simulate_remote_refs=real_refs,
            )
            self.assertEqual(res_fail["status"], "UPGRADE_BLOCKED", res_fail)

            # Commit-bound digest MUST pass promote_upgrade even with dirty worktree
            _, app_ok, sim_pr_ok = self._build_auth(
                promo_root, cons_sha, "v3.0.0", v300_tag, v300_peeled, commit_digests, scope="STANDARDS_LOCK_PROMOTION"
            )
            res_ok = promote_upgrade(
                promo_root,
                target_tag="v3.0.0",
                target_version="3.0.0",
                target_tag_object_sha=v300_tag,
                target_peeled_commit=v300_peeled,
                approval_record=app_ok,
                standards_root=ROOT,
                consumer_candidate_commit=cons_sha,
                simulate_provenance_data=sim_pr_ok,
                simulate_remote_refs=real_refs,
            )
            self.assertEqual(res_ok["status"], "PROMOTED", res_ok)


class PackagerPathSecurityTests(unittest.TestCase):
    """Strict whitelist, SemVer, resolved containment, and symlink rejection for package_acceptance."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "VERSION").write_text("3.0.0\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_acceptance(self, task_id: str = "SEC-TASK", version: str = "v3.0.0") -> Path:
        acc_dir = self.repo / ".artifacts" / "acceptance" / task_id / version
        acc_dir.mkdir(parents=True, exist_ok=True)
        rpt = acc_dir / "acceptance_report.md"
        rpt.write_text("# Report\nOVERALL=PASS\n", encoding="utf-8")
        log = acc_dir / "test_results.txt"
        log.write_text("Ran 1 test in 0.01s\nOK\n", encoding="utf-8")
        files = []
        for name, p in [("acceptance_report.md", rpt), ("test_results.txt", log)]:
            data = p.read_bytes()
            files.append({
                "path": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            })
        manifest = {
            "task_id": task_id,
            "version": version,
            "run_id": "sec-run-1",
            "created_at": "2026-11-18T00:00:00Z",
            "status": "PASS",
            "files": files,
        }
        (acc_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return acc_dir

    def test_p1_rejects_traversal_and_absolute_task_ids_without_creating_files(self) -> None:
        from scripts.package_acceptance import package_acceptance, validate_task_id

        outside = self.base / "outside"
        outside.mkdir(parents=True, exist_ok=True)

        bad_ids = [
            "../outside",
            "../../../outside",
            "../../../../outside",
            "/abs/path",
            "C:\\drive\\bad",
            "\\\\server\\share",
            "foo/bar",
            "foo\\bar",
            "",
            "bad task",
            "bad:id",
        ]
        for bad in bad_ids:
            with self.subTest(bad_task_id=bad):
                with self.assertRaises(ValueError):
                    validate_task_id(bad)
                with self.assertRaises(ValueError):
                    package_acceptance(bad, version="3.0.0", repo_root=self.repo)

        # Must create ZERO packages/acceptance files when preflight rejects
        self.assertFalse((self.repo / ".artifacts").exists())
        self.assertEqual(list(outside.iterdir()), [])

    def test_p2_rejects_bad_versions_and_accepts_strict_semver(self) -> None:
        from scripts.package_acceptance import normalize_version, package_acceptance

        bad_versions = [
            "../3.0.0",
            "3.0.0/foo",
            "3.0.0\\foo",
            "3.0",
            "03.0.0",
            "3.0.0-alpha",
            "v3.0.0.1",
            "v03.0.0",
            "",
            "3.0.0 ",
        ]
        for bad_v in bad_versions:
            with self.subTest(bad_version=bad_v):
                with self.assertRaises(ValueError):
                    normalize_version(bad_v, self.repo)
                with self.assertRaises(ValueError):
                    package_acceptance("SEC-TASK", version=bad_v, repo_root=self.repo)
        self.assertFalse((self.repo / ".artifacts").exists())

        self._seed_acceptance("SEC-TASK", "v3.0.0")
        res = package_acceptance("SEC-TASK", version="3.0.0", run_id="ok-1", repo_root=self.repo)
        self.assertTrue((self.repo / res["zip_path"]).exists())
        self._seed_acceptance("SEC-TASK-PREFIX", "v3.0.0")
        res2 = package_acceptance("SEC-TASK-PREFIX", version="v3.0.0", run_id="ok-2", repo_root=self.repo)
        self.assertTrue((self.repo / res2["zip_path"]).exists())

    def test_p3_symlink_escape_rejected(self) -> None:
        from unittest.mock import patch
        from scripts.package_acceptance import package_acceptance

        acc_dir = self._seed_acceptance("SYM-TASK", "v3.0.0")
        pkg_dir = self.repo / ".artifacts" / "packages"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        outside = self.base / "outside_target"
        outside.mkdir(parents=True, exist_ok=True)

        symlink_supported = True
        sym_acc = self.repo / ".artifacts" / "acceptance" / "SYM-ESCAPE"
        try:
            os.symlink(str(outside), str(sym_acc), target_is_directory=True)
        except OSError:
            symlink_supported = False

        if symlink_supported:
            with self.assertRaises(ValueError) as ctx_s:
                package_acceptance("SYM-ESCAPE", version="3.0.0", repo_root=self.repo)
            self.assertIn("Symlink", str(ctx_s.exception))
        else:
            # Verify symlink rejection deterministically even without Windows SeCreateSymbolicLinkPrivilege
            orig_is_symlink = Path.is_symlink

            def fake_is_symlink(p: Path) -> bool:
                if p.name == "packages" or p.name == "SYM-TASK":
                    return True
                return orig_is_symlink(p)

            with patch.object(Path, "is_symlink", fake_is_symlink):
                with self.assertRaises(ValueError) as ctx_m:
                    package_acceptance("SYM-TASK", version="3.0.0", repo_root=self.repo)
                self.assertIn("Symlink", str(ctx_m.exception))
        self.assertTrue((acc_dir / "manifest.json").exists())


class PackagerCrashRecoveryAndConcurrencyTests(unittest.TestCase):
    """Real OS subprocess crash injection (os._exit), recovery states, and multiprocess locking."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "VERSION").write_text("3.0.0\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_task(self, task_id: str = "CRASH-TASK", version: str = "v3.0.0", run_id: str = "orig-run") -> tuple[Path, Path, Path]:
        acc_dir = self.repo / ".artifacts" / "acceptance" / task_id / version
        acc_dir.mkdir(parents=True, exist_ok=True)
        rpt = acc_dir / "acceptance_report.md"
        rpt.write_text("# Acceptance\nSTATUS=PASS\n", encoding="utf-8")
        log = acc_dir / "test_results.txt"
        log.write_text("Ran 5 tests\nOK\n", encoding="utf-8")
        files = []
        for name, p in [("acceptance_report.md", rpt), ("test_results.txt", log)]:
            data = p.read_bytes()
            files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
        manifest = {
            "task_id": task_id,
            "version": version,
            "run_id": run_id,
            "created_at": "2026-11-18T00:00:00Z",
            "status": "PASS",
            "files": files,
        }
        (acc_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        manifest_path = acc_dir / "manifest.json"
        pkg_dir = self.repo / ".artifacts" / "packages"
        zip_path = pkg_dir / f"Acceptance-{task_id}-{version}.zip"
        sha_path = pkg_dir / f"Acceptance-{task_id}-{version}.zip.sha256"
        return manifest_path, zip_path, sha_path

    def _spawn_worker(self, code: str) -> subprocess.Popen[str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _crash_child_code(self, task_id: str, version: str, run_id: str, crash_mode: str) -> str:
        return f"""
import json, os, sys
from pathlib import Path
from scripts import package_acceptance as pa

repo = Path({repr(str(self.repo))})
task_id = {repr(task_id)}
version = {repr(version)}
crash_mode = {repr(crash_mode)}

manifest_target = (repo / ".artifacts" / "acceptance" / task_id / version / "manifest.json").resolve()
pkg_dir = (repo / ".artifacts" / "packages").resolve()
zip_target = pkg_dir / f"Acceptance-{{task_id}}-{{version}}.zip"
sha_target = pkg_dir / f"Acceptance-{{task_id}}-{{version}}.zip.sha256"
journal_target = pkg_dir / f".tx_journal_{{task_id}}_{{version}}.json"

def crash_replace(src: Path, dst: Path) -> None:
    src_r = Path(src).resolve()
    dst_r = Path(dst).resolve()
    if crash_mode == "during_tmp_journal_init" and dst_r == journal_target:
        os._exit(99)
    os.replace(src, dst)
    if crash_mode == "after_manifest_replace" and dst_r == manifest_target:
        os._exit(99)
    if crash_mode == "after_zip_replace" and dst_r == zip_target:
        os._exit(99)
    if crash_mode == "after_sha_replace_before_committed" and dst_r == sha_target:
        os._exit(99)
    if crash_mode == "during_initializing_backup" and dst_r == journal_target:
        j = json.loads(dst_r.read_text(encoding="utf-8"))
        if j.get("state") == "INITIALIZING":
            os._exit(99)
    if crash_mode == "after_committed_before_cleanup" and dst_r == journal_target:
        j = json.loads(dst_r.read_text(encoding="utf-8"))
        if j.get("state") == "COMMITTED":
            os._exit(99)

pa.package_acceptance(task_id, version=version, run_id={repr(run_id)}, repo_root=repo, replace_fn=crash_replace, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")
"""

    def test_c1_real_os_crash_during_committing_points_recovers_originals_and_succeeds(self) -> None:
        from scripts.package_acceptance import package_acceptance, recover_incomplete_package_transactions

        for mode in ("after_manifest_replace", "after_zip_replace", "after_sha_replace_before_committed"):
            with self.subTest(crash_mode=mode):
                task_id = f"TX-{mode[:10].upper().replace('_', '-')}"
                manifest_path, zip_path, sha_path = self._seed_task(task_id, "v3.0.0", "orig-run")
                package_acceptance(task_id, version="3.0.0", run_id="orig-run", repo_root=self.repo)
                orig_m = manifest_path.read_bytes()
                orig_z = zip_path.read_bytes()
                orig_s = sha_path.read_bytes()

                proc = self._spawn_worker(self._crash_child_code(task_id, "v3.0.0", "crashed-run", mode))
                _, err = proc.communicate(timeout=20)
                self.assertEqual(proc.returncode, 99, f"Expected os._exit(99), got {proc.returncode}: {err}")

                pkg_dir = self.repo / ".artifacts" / "packages"
                self.assertTrue((pkg_dir / f".tx_journal_{task_id}_v3.0.0.json").exists())

                # Explicit recovery restores all 3 original files and cleans artifacts
                rec = recover_incomplete_package_transactions(self.repo, task_id=task_id, version="3.0.0")
                self.assertEqual(rec["status"], "RECOVERED", rec)
                self.assertEqual(manifest_path.read_bytes(), orig_m)
                self.assertEqual(zip_path.read_bytes(), orig_z)
                self.assertEqual(sha_path.read_bytes(), orig_s)
                self.assertFalse((pkg_dir / f".tx_journal_{task_id}_v3.0.0.json").exists())

                # Repeat crash and recover automatically via startup recovery inside next package_acceptance call
                proc2 = self._spawn_worker(self._crash_child_code(task_id, "v3.0.0", "crashed-run-2", mode))
                proc2.communicate(timeout=20)
                self.assertEqual(proc2.returncode, 99)

                res_next = package_acceptance(task_id, version="3.0.0", run_id="final-run", repo_root=self.repo, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")
                self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["run_id"], "final-run")
                with zipfile.ZipFile(zip_path, "r") as zf:
                    self.assertEqual(json.loads(zf.read("manifest.json").decode("utf-8"))["run_id"], "final-run")
                self.assertIn(res_next["zip_sha256"], sha_path.read_text(encoding="utf-8"))

    def test_c2_crash_after_committed_and_tampered_committed_target(self) -> None:
        from scripts.package_acceptance import package_acceptance, recover_incomplete_package_transactions

        manifest_path, zip_path, sha_path = self._seed_task("COM-TASK", "v3.0.0", "orig-run")
        package_acceptance("COM-TASK", version="3.0.0", run_id="orig-run", repo_root=self.repo)

        proc = self._spawn_worker(
            self._crash_child_code("COM-TASK", "v3.0.0", "committed-run", "after_committed_before_cleanup")
        )
        proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 99)

        # Startup recovery must verify all 3 committed targets match staged_sha256 and preserve committed state
        rec = recover_incomplete_package_transactions(self.repo, task_id="COM-TASK", version="3.0.0")
        self.assertEqual(rec["status"], "RECOVERED", rec)
        self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["run_id"], "committed-run")
        pkg_dir = self.repo / ".artifacts" / "packages"
        self.assertEqual(list(pkg_dir.glob(".bak_*")), [])
        self.assertEqual(list(pkg_dir.glob(".tx_journal_*")), [])

        # If COMMITTED journal exists but target ZIP was corrupted, recovery must BLOCK
        proc2 = self._spawn_worker(
            self._crash_child_code("COM-TASK", "v3.0.0", "committed-run-2", "after_committed_before_cleanup")
        )
        proc2.communicate(timeout=20)
        self.assertEqual(proc2.returncode, 99)
        zip_path.write_bytes(b"corrupted zip bytes")
        blk = recover_incomplete_package_transactions(self.repo, task_id="COM-TASK", version="3.0.0")
        self.assertEqual(blk["status"], "BLOCKED", blk)
        self.assertIn("COMMITTED_STATE_MISMATCH", blk["reason"])

    def test_c3_interrupted_init_corrupt_journal_missing_backup_and_malicious_journal(self) -> None:
        from scripts.package_acceptance import package_acceptance, recover_incomplete_package_transactions

        manifest_path, _, _ = self._seed_task("EDGE-TASK", "v3.0.0", "orig-run")
        package_acceptance("EDGE-TASK", version="3.0.0", run_id="orig-run", repo_root=self.repo)
        orig_m = manifest_path.read_bytes()
        pkg_dir = self.repo / ".artifacts" / "packages"

        # 1) Crash during INITIALIZING tmp_journal write -> safe cleanup of .tx_journal_tmp_*
        proc_tmp = self._spawn_worker(self._crash_child_code("EDGE-TASK", "v3.0.0", "init-tmp", "during_tmp_journal_init"))
        proc_tmp.communicate(timeout=20)
        self.assertEqual(proc_tmp.returncode, 99)
        self.assertTrue(list(pkg_dir.glob(".tx_journal_tmp_EDGE-TASK_v3.0.0_*")))
        rec_tmp = recover_incomplete_package_transactions(self.repo, task_id="EDGE-TASK", version="3.0.0")
        self.assertEqual(rec_tmp["status"], "RECOVERED", rec_tmp)
        self.assertEqual(manifest_path.read_bytes(), orig_m)

        # 2) Crash while INITIALIZING journal is active -> cleans INITIALIZING journal safely
        proc_init = self._spawn_worker(self._crash_child_code("EDGE-TASK", "v3.0.0", "init-run", "during_initializing_backup"))
        proc_init.communicate(timeout=20)
        self.assertEqual(proc_init.returncode, 99)
        rec_init = recover_incomplete_package_transactions(self.repo, task_id="EDGE-TASK", version="3.0.0")
        self.assertEqual(rec_init["status"], "RECOVERED", rec_init)
        self.assertEqual(manifest_path.read_bytes(), orig_m)

        # 3) Missing backup during COMMITTING -> BLOCKED (BACKUP_MISSING_OR_CORRUPT)
        proc_bak = self._spawn_worker(self._crash_child_code("EDGE-TASK", "v3.0.0", "bak-miss", "after_manifest_replace"))
        proc_bak.communicate(timeout=20)
        self.assertEqual(proc_bak.returncode, 99)
        for bf in pkg_dir.glob(".bak_manifest_EDGE-TASK_v3.0.0_*"):
            bf.unlink()
        blk_bak = recover_incomplete_package_transactions(self.repo, task_id="EDGE-TASK", version="3.0.0")
        self.assertEqual(blk_bak["status"], "BLOCKED", blk_bak)
        self.assertIn("BACKUP_MISSING_OR_CORRUPT", blk_bak["reason"])

        # 4) Corrupt JSON journal -> BLOCKED (CORRUPT_JOURNAL)
        jpath = pkg_dir / ".tx_journal_EDGE-TASK_v3.0.0.json"
        jpath.write_text("{bad json", encoding="utf-8")
        blk_corrupt = recover_incomplete_package_transactions(self.repo, task_id="EDGE-TASK", version="3.0.0")
        self.assertEqual(blk_corrupt["status"], "BLOCKED", blk_corrupt)
        self.assertIn("CORRUPT_JOURNAL", blk_corrupt["reason"])

        # 5) Malicious traversal path inside journal -> BLOCKED (CORRUPT_OR_MALICIOUS_JOURNAL)
        evil_j = {
            "tx_id": "tx1",
            "task_id": "EDGE-TASK",
            "version": "v3.0.0",
            "run_id": "r1",
            "state": "COMMITTING",
            "orig_existed": {"manifest": True, "zip": True, "sha": True},
            "orig_sha256": {"manifest": "a" * 64, "zip": "b" * 64, "sha": "c" * 64},
            "targets": {
                "manifest": "../../etc/passwd",
                "zip": ".artifacts/packages/Acceptance-EDGE-TASK-v3.0.0.zip",
                "sha": ".artifacts/packages/Acceptance-EDGE-TASK-v3.0.0.zip.sha256",
            },
            "backups": {
                "manifest": ".artifacts/packages/.bak_manifest_EDGE-TASK_v3.0.0_tx1.json",
                "zip": ".artifacts/packages/.bak_Acceptance-EDGE-TASK-v3.0.0.zip_tx1.zip",
                "sha": ".artifacts/packages/.bak_Acceptance-EDGE-TASK-v3.0.0.zip_tx1.sha256",
            },
        }
        jpath.write_text(json.dumps(evil_j), encoding="utf-8")
        blk_mal = recover_incomplete_package_transactions(self.repo, task_id="EDGE-TASK", version="3.0.0")
        self.assertEqual(blk_mal["status"], "BLOCKED", blk_mal)
        self.assertIn("CORRUPT_OR_MALICIOUS_JOURNAL", blk_mal["reason"])

    def test_c4_recovery_failed_preserved_and_repeated_recovery_idempotent(self) -> None:
        from scripts.package_acceptance import package_acceptance, recover_incomplete_package_transactions

        self._seed_task("IDEM-TASK", "v3.0.0", "orig-run")
        package_acceptance("IDEM-TASK", version="3.0.0", run_id="orig-run", repo_root=self.repo)
        # Crash then recover once
        proc = self._spawn_worker(self._crash_child_code("IDEM-TASK", "v3.0.0", "r2", "after_zip_replace"))
        proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 99)

        rec1 = recover_incomplete_package_transactions(self.repo, task_id="IDEM-TASK", version="3.0.0")
        self.assertEqual(rec1["status"], "RECOVERED")
        # Repeated calls are strictly idempotent
        rec2 = recover_incomplete_package_transactions(self.repo, task_id="IDEM-TASK", version="3.0.0")
        self.assertEqual(rec2["status"], "CLEAN")
        rec3 = recover_incomplete_package_transactions(self.repo)
        self.assertEqual(rec3["status"], "CLEAN")

        # RECOVERY_FAILED preserves journal and blocks further recovery/packaging
        pkg_dir = self.repo / ".artifacts" / "packages"
        jpath = pkg_dir / ".tx_journal_IDEM-TASK_v3.0.0.json"
        rf_j = {
            "tx_id": "txrf",
            "task_id": "IDEM-TASK",
            "version": "v3.0.0",
            "run_id": "r3",
            "state": "RECOVERY_FAILED",
            "orig_existed": {"manifest": True, "zip": True, "sha": True},
            "orig_sha256": {"manifest": "a" * 64, "zip": "b" * 64, "sha": "c" * 64},
            "targets": {
                "manifest": ".artifacts/acceptance/IDEM-TASK/v3.0.0/manifest.json",
                "zip": ".artifacts/packages/Acceptance-IDEM-TASK-v3.0.0.zip",
                "sha": ".artifacts/packages/Acceptance-IDEM-TASK-v3.0.0.zip.sha256",
            },
            "backups": {
                "manifest": ".artifacts/packages/.bak_manifest_IDEM-TASK_v3.0.0_txrf.json",
                "zip": ".artifacts/packages/.bak_Acceptance-IDEM-TASK-v3.0.0.zip_txrf.zip",
                "sha": ".artifacts/packages/.bak_Acceptance-IDEM-TASK-v3.0.0.zip_txrf.sha256",
            },
        }
        jpath.write_text(json.dumps(rf_j), encoding="utf-8")
        blk_rf = recover_incomplete_package_transactions(self.repo, task_id="IDEM-TASK", version="3.0.0")
        self.assertEqual(blk_rf["status"], "BLOCKED")
        self.assertIn("RECOVERY_FAILED", blk_rf["reason"])
        self.assertTrue(jpath.exists())
        with self.assertRaises(RuntimeError) as ctx_rf:
            package_acceptance("IDEM-TASK", version="3.0.0", run_id="r4", repo_root=self.repo, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")
        self.assertIn("TRANSACTION_RECOVERY_BLOCKED", str(ctx_rf.exception))

    def test_c5_multiprocess_os_lock_serialization_and_timeout_block(self) -> None:
        from scripts.package_acceptance import package_acceptance

        manifest_path, zip_path, sha_path = self._seed_task("CONC-TASK", "v3.0.0", "init")
        package_acceptance("CONC-TASK", version="3.0.0", run_id="init", repo_root=self.repo)

        # 1) Two real concurrent OS processes serialize cleanly via OS lock
        code_a = f"""
import os, time
from pathlib import Path
from scripts.package_acceptance import package_acceptance
repo = Path({repr(str(self.repo))})
def slow_replace(src, dst):
    if Path(dst).name == "manifest.json":
        time.sleep(0.4)
    os.replace(src, dst)
package_acceptance("CONC-TASK", version="3.0.0", run_id="proc-A", repo_root=repo, replace_fn=slow_replace, lock_timeout=15.0, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")
"""
        code_b = f"""
from pathlib import Path
from scripts.package_acceptance import package_acceptance
repo = Path({repr(str(self.repo))})
package_acceptance("CONC-TASK", version="3.0.0", run_id="proc-B", repo_root=repo, lock_timeout=15.0, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")
"""
        p_a = self._spawn_worker(code_a)
        p_b = self._spawn_worker(code_b)
        out_a, err_a = p_a.communicate(timeout=25)
        out_b, err_b = p_b.communicate(timeout=25)
        self.assertEqual(p_a.returncode, 0, f"proc A failed: {out_a} {err_a}")
        self.assertEqual(p_b.returncode, 0, f"proc B failed: {out_b} {err_b}")

        # Verify zero torn state: disk manifest, ZIP internal manifest, and .sha256 sidecar must match identically
        disk_run = json.loads(manifest_path.read_text(encoding="utf-8"))["run_id"]
        self.assertIn(disk_run, ("proc-A", "proc-B"))
        with zipfile.ZipFile(zip_path, "r") as zf:
            zip_run = json.loads(zf.read("manifest.json").decode("utf-8"))["run_id"]
        self.assertEqual(disk_run, zip_run)
        zip_hash = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        self.assertIn(zip_hash, sha_path.read_text(encoding="utf-8"))

        # 2) Explicit lock contention timeout blocks cleanly with TRANSACTION_CONCURRENCY_BLOCKED
        holder_code = f"""
import os, sys, time
from pathlib import Path
from scripts.package_acceptance import package_acceptance
repo = Path({repr(str(self.repo))})
def hold_lock(src, dst):
    if Path(dst).name == "manifest.json":
        print("LOCK_HELD", flush=True)
        time.sleep(1.5)
    os.replace(src, dst)
package_acceptance("CONC-TASK", version="3.0.0", run_id="holder", repo_root=repo, replace_fn=hold_lock, lock_timeout=10.0, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")
"""
        p_hold = self._spawn_worker(holder_code)
        try:
            assert p_hold.stdout is not None
            ready_line = p_hold.stdout.readline().strip()
            self.assertEqual(ready_line, "LOCK_HELD")
            with self.assertRaises(RuntimeError) as ctx_blk:
                package_acceptance("CONC-TASK", version="3.0.0", run_id="contender", repo_root=self.repo, lock_timeout=0.15, allow_overwrite=True, overwrite_reason="TEST-AUTHORIZED-CRASH-RECOVERY-RESEAL")
            self.assertIn("TRANSACTION_CONCURRENCY_BLOCKED", str(ctx_blk.exception))
        finally:
            _, hold_err = p_hold.communicate(timeout=20)
            self.assertEqual(p_hold.returncode, 0, hold_err)


class Std024ConsumerCiProvenanceHardeningTests(unittest.TestCase):
    """T01-T08: Runner Image Provisioner isolation & strict consumer CI provenance tests (STD-024)."""

    RUNNER_PROV_COMMIT = "b8a594ea514ff44cadb5342986c68b1eac6e22ed"
    CONSUMER_COMMIT = "a7acc7967f2ea84d1711bf137428b594893e47fd"
    STANDARDS_SUB_COMMIT = "4facfdcd17a3003f04e7deaa3dbdcb320ff82afa"
    ALT_COMMIT = "c" * 40
    REPO = "xiefeifeihu/AI-Engineering-Hub"

    @classmethod
    def _build_gha_log(
        cls,
        *,
        provisioner_commit: Optional[str] = RUNNER_PROV_COMMIT,
        checkout_ref: Optional[str] = CONSUMER_COMMIT,
        git_log_commit: Optional[str] = CONSUMER_COMMIT,
        expected_sha_env: Optional[str] = CONSUMER_COMMIT,
        submodule_commit: Optional[str] = STANDARDS_SUB_COMMIT,
        include_identity_step: bool = True,
        exec_body: str = "2026-11-24T05:00:10Z collected 12 items\n2026-11-24T05:00:11Z === 12 passed in 1.25s ===",
        extra_tail: str = "",
    ) -> str:
        lines = [
            "2026-11-24T05:00:00Z Current runner version: '2.333.1'",
            "2026-11-24T05:00:00Z ##[group]Runner Image Provisioner",
            "2026-11-24T05:00:00Z Hosted Compute Agent",
        ]
        if provisioner_commit:
            lines.append(f"2026-11-24T05:00:00Z Commit: {provisioner_commit}")
        lines.extend([
            "2026-11-24T05:00:00Z Build Date: 2026-11-16",
            "2026-11-24T05:00:00Z ##[endgroup]",
            "2026-11-24T05:00:01Z Download action repository 'actions/checkout@v4' (SHA:34e114876b0b11c390a56381ad16ebd13914f8d5)",
        ])
        if checkout_ref is not None:
            lines.extend([
                "2026-11-24T05:00:02Z ##[group]Run actions/checkout@v4",
                "2026-11-24T05:00:02Z with:",
                "2026-11-24T05:00:02Z   submodules: recursive",
                "2026-11-24T05:00:02Z ##[endgroup]",
                "2026-11-24T05:00:03Z [command]/usr/bin/git checkout --progress --force refs/remotes/pull/35/merge",
            ])
        if git_log_commit is not None:
            lines.extend([
                "2026-11-24T05:00:04Z [command]/usr/bin/git log -1 --format=%H",
                f"2026-11-24T05:00:04Z {git_log_commit}",
            ])
        if submodule_commit is not None:
            lines.extend([
                "2026-11-24T05:00:05Z ##[group]Fetching submodules",
                f"2026-11-24T05:00:05Z Submodule path '.standards': checked out '{submodule_commit}'",
                "2026-11-24T05:00:05Z ##[endgroup]",
            ])
        if include_identity_step and expected_sha_env is not None:
            lines.extend([
                "2026-11-24T05:00:06Z ##[group]Run test \"$(git rev-parse HEAD)\" = \"$EXPECTED_SHA\"",
                "2026-11-24T05:00:06Z test \"$(git rev-parse HEAD)\" = \"$EXPECTED_SHA\"",
                "2026-11-24T05:00:06Z env:",
                f"2026-11-24T05:00:06Z   EXPECTED_SHA: {expected_sha_env}",
                "2026-11-24T05:00:06Z ##[endgroup]",
            ])
        if exec_body:
            lines.append(exec_body)
        if extra_tail:
            lines.append(extra_tail)
        return "\n".join(lines) + "\n"

    def _build_gate(
        self,
        *,
        run_id: int = 45310932802,
        job_id: int = 138166184154,
        job_name: str = "Unit & Contract Tests (Ubuntu)",
        head_sha: str = CONSUMER_COMMIT,
        workflow_path: str = ".github/workflows/ci-governance.yml",
        event: str = "pull_request",
        collected: int = 12,
        passed: int = 12,
        failed: int = 0,
        skipped: int = 0,
    ) -> Dict[str, Any]:
        return {
            "status": "PASS",
            "command": "pytest -q",
            "workflow_path": workflow_path,
            "event": event,
            "run_id": run_id,
            "job_id": job_id,
            "job_name": job_name,
            "head_sha": head_sha,
            "evidence_ref": f"https://github.com/{self.REPO}/actions/runs/{run_id}",
            "raw_report": {
                "repository": self.REPO,
                "event": event,
                "run_id": run_id,
                "job_id": job_id,
                "job_name": job_name,
                "head_sha": head_sha,
                "tests_collected": collected,
                "tests_passed": passed,
                "tests_failed": failed,
                "tests_skipped": skipped,
            },
            "test_execution": {
                "tests_collected": collected,
                "tests_passed": passed,
                "tests_failed": failed,
                "tests_skipped": skipped,
                "exit_code": 0,
                "evidence_log_ref": f"https://github.com/{self.REPO}/actions/runs/{run_id}",
            },
        }

    @staticmethod
    def _mock_urlopen(run_payload: Dict[str, Any], jobs_payload: Dict[str, Any], log_text: str):
        def _handler(req, timeout=12):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "/jobs/" in url and url.endswith("/logs"):
                return FakeResponse(log_text.encode("utf-8"))
            if "/jobs" in url:
                return FakeResponse(jobs_payload)
            return FakeResponse(run_payload)
        return _handler

    def test_t01_runner_image_commit_isolated_from_consumer_commit(self) -> None:
        from tools.standards_sync.core import (
            extract_runner_log_commit_provenance,
            parse_runner_test_log,
        )

        # Log with Runner Image Provisioner commit, action download SHA, .standards submodule SHA,
        # and NO authoritative consumer source commit must NEVER pass source provenance or be confused with Consumer Commit.
        prov_only_log = self._build_gha_log(
            provisioner_commit=self.RUNNER_PROV_COMMIT,
            checkout_ref=None,
            git_log_commit=None,
            expected_sha_env=None,
            include_identity_step=False,
        )
        prov = extract_runner_log_commit_provenance(prov_only_log)
        self.assertIn(self.RUNNER_PROV_COMMIT, prov["runner_image_provisioner_commits"])
        self.assertIn("34e114876b0b11c390a56381ad16ebd13914f8d5", prov["non_source_commits"]["action_download"])
        self.assertIn(self.STANDARDS_SUB_COMMIT, prov["non_source_commits"]["submodule"])
        self.assertEqual(prov["authoritative_source_commits"], [])
        self.assertEqual(prov["structured_commit_headers"], [])

        st, errs = parse_runner_test_log(
            prov_only_log,
            expected_commit=self.CONSUMER_COMMIT,
            claimed_passed=12,
            claimed_collected=12,
            claimed_failed=0,
            claimed_skipped=0,
            require_source_identity=True,
        )
        self.assertEqual(st, "NOT_VERIFIABLE", errs)
        self.assertNotEqual(st, "VERIFIED")
        self.assertTrue(any("CONSUMER_CI_SOURCE_IDENTITY_MISSING" in e for e in errs), errs)

        # Even if expected_commit were set to Runner Image Provisioner commit, provisioner SHA is NOT source identity!
        st_prov_exp, _ = parse_runner_test_log(
            prov_only_log,
            expected_commit=self.RUNNER_PROV_COMMIT,
            claimed_passed=12,
            claimed_collected=12,
            claimed_failed=0,
            claimed_skipped=0,
            require_source_identity=True,
        )
        self.assertEqual(st_prov_exp, "NOT_VERIFIABLE")

    def test_t02_correct_consumer_commit_verified_offline_and_api_path(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import parse_runner_test_log

        log_text = self._build_gha_log()
        snapshot = str(log_text)
        st_parse, errs_parse = parse_runner_test_log(
            log_text,
            expected_commit=self.CONSUMER_COMMIT,
            claimed_passed=12,
            claimed_collected=12,
            claimed_failed=0,
            claimed_skipped=0,
            require_source_identity=True,
        )
        self.assertEqual(st_parse, "VERIFIED", errs_parse)
        self.assertEqual(log_text, snapshot)

        gate = self._build_gate()
        run_payload = {
            "id": 45310932802,
            "event": "pull_request",
            "repository": {"full_name": self.REPO},
            "head_sha": self.CONSUMER_COMMIT,
            "path": ".github/workflows/ci-governance.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [
                {
                    "id": 138166184154,
                    "run_id": 45310932802,
                    "head_sha": self.CONSUMER_COMMIT,
                    "name": "Unit & Contract Tests (Ubuntu)",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": "Checkout repository", "conclusion": "success"},
                        {"name": "Verify pull_request event source commit", "conclusion": "success"},
                        {"name": "Run tests", "conclusion": "success"},
                    ],
                }
            ]
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(run_payload, jobs_payload, log_text)):
            st_api, errs_api = verify_consumer_ci_gate(self.REPO, gate, self.CONSUMER_COMMIT)
        self.assertEqual(st_api, "VERIFIED", errs_api)
        self.assertEqual(errs_api, [])

    def test_t03_conflicting_authoritative_source_commit_returns_failed(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import (
            parse_runner_release_log,
            parse_runner_scan_log,
            parse_runner_test_log,
        )

        # Authoritative git log -1 outputs ALT_COMMIT even though Runner Provisioner or env mentions something else
        bad_git_log = self._build_gha_log(
            git_log_commit=self.ALT_COMMIT,
            expected_sha_env=self.CONSUMER_COMMIT,
        )
        st, errs = parse_runner_test_log(
            bad_git_log,
            expected_commit=self.CONSUMER_COMMIT,
            claimed_passed=12,
            claimed_collected=12,
            claimed_failed=0,
            claimed_skipped=0,
            require_source_identity=True,
        )
        self.assertEqual(st, "FAILED", errs)
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_COMMIT_MISMATCH" in e for e in errs), errs)

        bad_scan_log = self._build_gha_log(
            git_log_commit=self.ALT_COMMIT,
            exec_body="2026-11-24T05:00:10Z 5 targets scanned\n2026-11-24T05:00:11Z 0 vulnerabilities found",
        )
        st_scan, errs_scan = parse_runner_scan_log(bad_scan_log, expected_commit=self.CONSUMER_COMMIT, claimed_targets=5)
        self.assertEqual(st_scan, "FAILED", errs_scan)

        bad_rel_log = self._build_gha_log(
            git_log_commit=self.ALT_COMMIT,
            exec_body="2026-11-24T05:00:10Z 3 checks passed\n2026-11-24T05:00:11Z OVERALL=PASS",
        )
        st_rel, errs_rel = parse_runner_release_log(bad_rel_log, expected_commit=self.CONSUMER_COMMIT, claimed_checks_passed=3)
        self.assertEqual(st_rel, "FAILED", errs_rel)

        # String raw_report pre-check and fetched job log must both reject conflicting source commit
        gate = self._build_gate()
        gate["raw_report"] = bad_git_log
        st_gate, errs_gate = verify_consumer_ci_gate(self.REPO, gate, self.CONSUMER_COMMIT)
        self.assertEqual(st_gate, "FAILED", errs_gate)

        gate_obj = self._build_gate()
        run_payload = {
            "id": 45310932802,
            "event": "pull_request",
            "repository": {"full_name": self.REPO},
            "head_sha": self.CONSUMER_COMMIT,
            "path": ".github/workflows/ci-governance.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [
                {
                    "id": 138166184154,
                    "run_id": 45310932802,
                    "head_sha": self.CONSUMER_COMMIT,
                    "name": "Unit & Contract Tests (Ubuntu)",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [{"name": "Checkout repository", "conclusion": "success"}],
                }
            ]
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(run_payload, jobs_payload, bad_git_log)):
            st_api, errs_api = verify_consumer_ci_gate(self.REPO, gate_obj, self.CONSUMER_COMMIT)
        self.assertEqual(st_api, "FAILED", errs_api)
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_COMMIT_MISMATCH" in e for e in errs_api), errs_api)

    def test_t04_api_head_sha_event_and_ids_mismatch_return_failed(self) -> None:
        from unittest.mock import patch

        valid_log = self._build_gha_log()
        base_run = {
            "id": 45310932802,
            "event": "pull_request",
            "repository": {"full_name": self.REPO},
            "head_sha": self.CONSUMER_COMMIT,
            "path": ".github/workflows/ci-governance.yml",
            "status": "completed",
            "conclusion": "success",
        }
        base_job = {
            "id": 138166184154,
            "run_id": 45310932802,
            "head_sha": self.CONSUMER_COMMIT,
            "name": "Unit & Contract Tests (Ubuntu)",
            "status": "completed",
            "conclusion": "success",
            "steps": [{"name": "Checkout repository", "conclusion": "success"}],
        }

        cases = [
            ("run_head_sha", {**base_run, "head_sha": self.ALT_COMMIT}, base_job, "CONSUMER_CI_RUN_COMMIT_MISMATCH"),
            ("job_head_sha", base_run, {**base_job, "head_sha": self.ALT_COMMIT}, "CONSUMER_CI_JOB_COMMIT_MISMATCH"),
            ("run_event_mismatch", {**base_run, "event": "push"}, base_job, "CONSUMER_CI_RUN_EVENT_MISMATCH"),
            ("run_event_untrusted", {**base_run, "event": "issue_comment"}, base_job, "CONSUMER_CI_RUN_EVENT_MISMATCH"),
            ("run_id_mismatch", {**base_run, "id": 999}, base_job, "CONSUMER_CI_RUN_ID_MISMATCH"),
            ("job_run_id_mismatch", base_run, {**base_job, "run_id": 999}, "CONSUMER_CI_JOB_RUN_ID_MISMATCH"),
            ("job_id_mismatch", base_run, {**base_job, "id": 999}, "CONSUMER_CI_GATE_JOB_ID_MISMATCH"),
        ]
        for label, r_pay, j_pay, expected_err in cases:
            with self.subTest(case=label):
                gate = self._build_gate()
                if label == "run_event_untrusted":
                    gate["event"] = "issue_comment"
                    gate["raw_report"]["event"] = "issue_comment"
                    expected_err = "CONSUMER_CI_RUN_EVENT_UNTRUSTED"
                with patch(
                    "urllib.request.urlopen",
                    side_effect=self._mock_urlopen(r_pay, {"jobs": [j_pay]}, valid_log),
                ):
                    st, errs = verify_consumer_ci_gate(self.REPO, gate, self.CONSUMER_COMMIT)
                self.assertEqual(st, "FAILED", f"{label}: {errs}")
                self.assertTrue(any(expected_err in e for e in errs), f"{label}: {errs}")

    def test_t05_empty_log_missing_identity_and_bare_ok_cannot_verify(self) -> None:
        from unittest.mock import patch
        import urllib.error
        from tools.standards_sync.core import (
            parse_runner_release_log,
            parse_runner_scan_log,
            parse_runner_test_log,
        )

        for empty in ("", "   \n\t  "):
            self.assertEqual(parse_runner_test_log(empty, self.CONSUMER_COMMIT, 1, 1)[0], "NOT_VERIFIABLE")
            self.assertEqual(parse_runner_scan_log(empty, self.CONSUMER_COMMIT, 1)[0], "NOT_VERIFIABLE")
            self.assertEqual(parse_runner_release_log(empty, self.CONSUMER_COMMIT, 1)[0], "NOT_VERIFIABLE")

        # Bare "OK" or "SUCCESS" without anchored summary MUST NOT pass scan or release logs
        bare_scan = self._build_gha_log(exec_body="2026-11-24T05:00:10Z OK\n2026-11-24T05:00:11Z SUCCESS")
        st_scan, errs_scan = parse_runner_scan_log(bare_scan, self.CONSUMER_COMMIT)
        self.assertEqual(st_scan, "NOT_VERIFIABLE", errs_scan)

        bare_rel = self._build_gha_log(exec_body="2026-11-24T05:00:10Z OK\n2026-11-24T05:00:11Z SUCCESS")
        st_rel, errs_rel = parse_runner_release_log(bare_rel, self.CONSUMER_COMMIT)
        self.assertEqual(st_rel, "NOT_VERIFIABLE", errs_rel)

        # API/network unreachable must return NOT_VERIFIABLE, never VERIFIED
        gate = self._build_gate()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("API unavailable")):
            st_api, errs_api = verify_consumer_ci_gate(self.REPO, gate, self.CONSUMER_COMMIT)
        self.assertEqual(st_api, "NOT_VERIFIABLE", errs_api)
        self.assertTrue(any("CONSUMER_CI_API_NOT_VERIFIABLE" in e for e in errs_api), errs_api)

        # Missing checkout/source identity in both job steps and log returns NOT_VERIFIABLE
        no_id_log = self._build_gha_log(checkout_ref=None, git_log_commit=None, expected_sha_env=None, include_identity_step=False)
        run_payload = {
            "id": 45310932802,
            "event": "pull_request",
            "repository": {"full_name": self.REPO},
            "head_sha": self.CONSUMER_COMMIT,
            "path": ".github/workflows/ci-governance.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [
                {
                    "id": 138166184154,
                    "run_id": 45310932802,
                    "head_sha": self.CONSUMER_COMMIT,
                    "name": "Unit & Contract Tests (Ubuntu)",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [{"name": "Run tests", "conclusion": "success"}],
                }
            ]
        }
        with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(run_payload, jobs_payload, no_id_log)):
            st_no_id, errs_no_id = verify_consumer_ci_gate(self.REPO, gate, self.CONSUMER_COMMIT)
        self.assertEqual(st_no_id, "NOT_VERIFIABLE", errs_no_id)

    def test_t06_continue_on_error_and_masked_step_failures_fail(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import (
            parse_runner_release_log,
            parse_runner_scan_log,
            parse_runner_test_log,
        )

        masked_test_log = self._build_gha_log(
            exec_body="2026-11-24T05:00:10Z ##[error]Process completed with exit code 1.\n"
            "2026-11-24T05:00:11Z === 1 failed, 11 passed in 1.25s ==="
        )
        self.assertEqual(
            parse_runner_test_log(masked_test_log, self.CONSUMER_COMMIT, 11, 12, 0, 0)[0],
            "FAILED",
        )
        self.assertEqual(
            parse_runner_scan_log(masked_test_log, self.CONSUMER_COMMIT)[0],
            "FAILED",
        )
        self.assertEqual(
            parse_runner_release_log(masked_test_log, self.CONSUMER_COMMIT)[0],
            "FAILED",
        )

        # String raw_report containing failure must fail BEFORE network
        gate_str = self._build_gate()
        gate_str["raw_report"] = self._build_gha_log(exec_body="2026-11-24T05:00:10Z === 2 failed, 10 passed in 1.0s ===")
        st_pre, _ = verify_consumer_ci_gate(self.REPO, gate_str, self.CONSUMER_COMMIT)
        self.assertEqual(st_pre, "FAILED")

        # API step failure masked by continue-on-error even if job conclusion == success and test log looks green
        green_log = self._build_gha_log()
        run_payload = {
            "id": 45310932802,
            "event": "pull_request",
            "repository": {"full_name": self.REPO},
            "head_sha": self.CONSUMER_COMMIT,
            "path": ".github/workflows/ci-governance.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [
                {
                    "id": 138166184154,
                    "run_id": 45310932802,
                    "head_sha": self.CONSUMER_COMMIT,
                    "name": "Unit & Contract Tests (Ubuntu)",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": "Checkout repository", "conclusion": "success"},
                        {"name": "Run pytest", "conclusion": "failure"},
                    ],
                }
            ]
        }
        gate = self._build_gate()
        with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(run_payload, jobs_payload, green_log)):
            st_masked, errs_masked = verify_consumer_ci_gate(self.REPO, gate, self.CONSUMER_COMMIT)
        self.assertEqual(st_masked, "FAILED", errs_masked)
        self.assertTrue(any("CONSUMER_CI_JOB_STEP_FAILED_MASKED" in e for e in errs_masked), errs_masked)

    def test_t07_forged_and_non_executing_commit_and_summary_text_rejected(self) -> None:
        from tools.standards_sync.core import parse_runner_test_log

        forged_echo = "\n".join([
            f'echo "Commit: {self.CONSUMER_COMMIT}"',
            'echo "=== 12 passed in 0.50s ==="',
        ])
        st_e, errs_e = parse_runner_test_log(forged_echo, self.CONSUMER_COMMIT, 12, 12, 0, 0)
        self.assertEqual(st_e, "FAILED", errs_e)

        forged_comment_and_fence = "\n".join([
            f"# source_commit: {self.CONSUMER_COMMIT}",
            f'QUOTE: HEAD={self.CONSUMER_COMMIT}',
            "```text",
            f"commit: {self.CONSUMER_COMMIT}",
            "Ran 12 tests in 0.25s",
            "",
            "OK",
            "```",
        ])
        st_f, errs_f = parse_runner_test_log(forged_comment_and_fence, self.CONSUMER_COMMIT, 12, 12, 0, 0)
        self.assertEqual(st_f, "FAILED", errs_f)

    def test_t08_hub_run_45310932802_five_jobs_full_regression_and_verbatim_if_present(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import (
            parse_runner_release_log,
            parse_runner_scan_log,
            parse_runner_test_log,
        )

        hub_jobs = [
            {
                "key": "unit_tests",
                "job_id": 138166184154,
                "job_name": "Unit & Contract Tests (Ubuntu)",
                "evidence_type": "test_execution",
                "command": "python -m pytest tests/contract tests/test_standards_bootstrap.py tests/test_operational_v2.py -v",
                "collected": 308,
                "passed": 287,
                "skipped": 21,
                "sha256": "e6e77db4deed2edbe23da276e99d13ef92aa4e9b170a7e2c7ad3d4da89eea3b2",
                "extra": "",
            },
            {
                "key": "integration_tests",
                "job_id": 138166184471,
                "job_name": "Integration Tests (Ubuntu)",
                "evidence_type": "test_execution",
                "command": "python -m pytest tests/integration -v",
                "collected": 9,
                "passed": 9,
                "skipped": 0,
                "sha256": "beb5bcc4f38e7338e3c7d54aeaba47326f3b15122ca7e78d420d50b31739054f",
                "extra": "",
            },
            {
                "key": "security_scan",
                "job_id": 138166184081,
                "job_name": "Security & Isolation Tests (Ubuntu)",
                "evidence_type": "scan_execution",
                "command": "python -m pytest tests/security -v",
                "scanner": "pytest-security",
                "targets_scanned": 36,
                "collected": 37,
                "passed": 36,
                "skipped": 1,
                "sha256": "866dc7bcd20889ea1e75a7390e552c3c9a536cdde971da55ba415397b25da2df",
                "extra": "",
            },
            {
                "key": "business_api",
                "job_id": 138166184067,
                "job_name": "Business API & Runtime Tests (Ubuntu)",
                "evidence_type": "test_execution",
                "command": "python -m pytest tests/runtime -v",
                "collected": 149,
                "passed": 111,
                "skipped": 38,
                "sha256": "dcbbd320fe03c6b6758fc25eb1ee7469b5621738198fc926e188854aa2001788",
                "extra": "2026-11-24T05:00:09Z tests/test_foo.py::test_hex[aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb] PASSED",
            },
            {
                "key": "runtime_acceptance",
                "job_id": 138166183598,
                "job_name": "Runtime Acceptance (Docker + Playwright Chromium)",
                "evidence_type": "test_execution",
                "command": "python -m pytest tests/e2e/test_hub002_standards_v300_playwright.py -v",
                "collected": 5,
                "passed": 5,
                "skipped": 0,
                "sha256": "6d68b68282359aa5ff5dcb8835a876ec0e2b331d808b743b64133af15953064c",
                "extra": '2026-11-24T05:00:08Z #10 FROM docker.io/library/python:3.11@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n2026-11-24T05:00:09Z {"standards_commit": "4facfdcd17a3003f04e7deaa3dbdcb320ff82afa"}',
            },
            {
                "key": "release_gates",
                "job_id": 138166184132,
                "job_name": "Agent Governance, Unit/Contract/Integration Tests & Delivery Gate",
                "evidence_type": "release_execution",
                "command": "python scripts/ci/verify_delivery_contract.py --mode DEVELOPMENT --run-pytest",
                "gate_name": "delivery-contract-G01-G12",
                "checks_passed": 10,
                "checks_na": 2,
                "sha256": "d2548105b206e42076a5292c5ce0b105c3b1cb895cab08dff96a9d8a64fdf6e0",
                "extra": "",
            },
        ]

        run_payload = {
            "id": 45310932802,
            "event": "pull_request",
            "repository": {"full_name": self.REPO},
            "head_sha": self.CONSUMER_COMMIT,
            "path": ".github/workflows/ci-governance.yml",
            "status": "completed",
            "conclusion": "success",
        }

        def _make_gate_for_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
            ev_url = f"https://github.com/{self.REPO}/actions/runs/45310932802"
            g: Dict[str, Any] = {
                "status": "PASS",
                "command": spec["command"],
                "workflow_path": ".github/workflows/ci-governance.yml",
                "event": "pull_request",
                "run_id": 45310932802,
                "job_id": spec["job_id"],
                "job_name": spec["job_name"],
                "head_sha": self.CONSUMER_COMMIT,
                "evidence_ref": ev_url,
            }
            if spec["evidence_type"] == "test_execution":
                g["raw_report"] = {
                    "repository": self.REPO,
                    "event": "pull_request",
                    "run_id": 45310932802,
                    "job_id": spec["job_id"],
                    "job_name": spec["job_name"],
                    "head_sha": self.CONSUMER_COMMIT,
                    "tests_collected": spec["collected"],
                    "tests_passed": spec["passed"],
                    "tests_failed": 0,
                    "tests_skipped": spec["skipped"],
                }
                g["test_execution"] = {
                    "tests_collected": spec["collected"],
                    "tests_passed": spec["passed"],
                    "tests_failed": 0,
                    "tests_skipped": spec["skipped"],
                    "exit_code": 0,
                    "evidence_log_ref": ev_url,
                }
            elif spec["evidence_type"] == "scan_execution":
                g["raw_report"] = {
                    "repository": self.REPO,
                    "event": "pull_request",
                    "run_id": 45310932802,
                    "job_id": spec["job_id"],
                    "job_name": spec["job_name"],
                    "head_sha": self.CONSUMER_COMMIT,
                    "scanner": spec["scanner"],
                    "targets_scanned": spec["targets_scanned"],
                    "vulnerabilities_found": 0,
                    "exit_code": 0,
                }
                g["scan_execution"] = {
                    "scanner": spec["scanner"],
                    "targets_scanned": spec["targets_scanned"],
                    "vulnerabilities_found": 0,
                    "exit_code": 0,
                    "evidence_log_ref": ev_url,
                }
            else:
                g["raw_report"] = {
                    "repository": self.REPO,
                    "event": "pull_request",
                    "run_id": 45310932802,
                    "job_id": spec["job_id"],
                    "job_name": spec["job_name"],
                    "head_sha": self.CONSUMER_COMMIT,
                    "gate_name": spec["gate_name"],
                    "checks_passed": spec["checks_passed"],
                    "checks_failed": 0,
                    "exit_code": 0,
                }
                g["release_execution"] = {
                    "gate_name": spec["gate_name"],
                    "checks_passed": spec["checks_passed"],
                    "checks_failed": 0,
                    "exit_code": 0,
                    "evidence_log_ref": ev_url,
                }
            return g

        # 1) Offline structural 6-job regression ALWAYS runs on Windows & Ubuntu CI without private repo access
        for spec in hub_jobs:
            with self.subTest(mode="offline_fixture", job=spec["key"]):
                if spec["evidence_type"] == "release_execution":
                    gates_json = {
                        "overall_status": "PASS",
                        "gates": [
                            {"gate_id": f"G{idx:02d}", "status": "PASS", "detail": {"source_commit": self.CONSUMER_COMMIT}}
                            for idx in (1, 2, 3, 4, 6, 7, 8, 9, 10, 11)
                        ]
                        + [
                            {"gate_id": "G05", "status": "NOT_APPLICABLE", "detail": {"note": "DEVELOPMENT mode"}},
                            {"gate_id": "G12", "status": "NOT_APPLICABLE", "detail": {"note": "DEVELOPMENT mode"}},
                        ],
                    }
                    exec_body = (
                        f"2026-11-24T05:00:09Z ##[group]Run {spec['command']}\n"
                        f"2026-11-24T05:00:09Z {spec['command']}\n"
                        "2026-11-24T05:00:09Z ##[endgroup]\n"
                        + json.dumps(gates_json, indent=2)
                    )
                else:
                    summary_parts = [f"{spec['passed']} passed"]
                    if spec["skipped"]:
                        summary_parts.append(f"{spec['skipped']} skipped")
                    exec_body = (
                        f"2026-11-24T05:00:08Z ##[group]Run {spec['command']}\n"
                        f"2026-11-24T05:00:08Z {spec['command']}\n"
                        "2026-11-24T05:00:08Z ##[endgroup]\n"
                        + (f"{spec['extra']}\n" if spec["extra"] else "")
                        + f"2026-11-24T05:00:10Z collected {spec['collected']} items\n"
                        + f"2026-11-24T05:00:12Z === {', '.join(summary_parts)} in 2.34s ==="
                    )
                synth_log = self._build_gha_log(exec_body=exec_body)
                if spec["evidence_type"] == "test_execution":
                    st_p, errs_p = parse_runner_test_log(
                        synth_log,
                        expected_commit=self.CONSUMER_COMMIT,
                        claimed_passed=spec["passed"],
                        claimed_collected=spec["collected"],
                        claimed_failed=0,
                        claimed_skipped=spec["skipped"],
                        require_source_identity=True,
                        expected_command=spec["command"],
                        expected_repository=self.REPO,
                    )
                elif spec["evidence_type"] == "scan_execution":
                    st_p, errs_p = parse_runner_scan_log(
                        synth_log,
                        expected_commit=self.CONSUMER_COMMIT,
                        claimed_targets=spec["targets_scanned"],
                        claimed_vulns=0,
                        require_source_identity=True,
                        expected_command=spec["command"],
                        expected_repository=self.REPO,
                    )
                else:
                    st_p, errs_p = parse_runner_release_log(
                        synth_log,
                        expected_commit=self.CONSUMER_COMMIT,
                        claimed_checks_passed=spec["checks_passed"],
                        claimed_checks_failed=0,
                        require_source_identity=True,
                        expected_command=spec["command"],
                        expected_repository=self.REPO,
                        claimed_checks_not_applicable=spec["checks_na"],
                    )
                self.assertEqual(st_p, "VERIFIED", errs_p)

                gate = _make_gate_for_spec(spec)
                jobs_payload = {
                    "jobs": [
                        {
                            "id": spec["job_id"],
                            "run_id": 45310932802,
                            "head_sha": self.CONSUMER_COMMIT,
                            "name": spec["job_name"],
                            "status": "completed",
                            "conclusion": "success",
                            "steps": [
                                {"name": "Checkout Hub Repository", "conclusion": "success"},
                                {"name": "Verify pull_request event source commit", "conclusion": "success"},
                                {"name": spec["job_name"], "conclusion": "success"},
                            ],
                        }
                    ]
                }
                with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(run_payload, jobs_payload, synth_log)):
                    st_g, errs_g = verify_consumer_ci_gate(self.REPO, gate, self.CONSUMER_COMMIT)
                self.assertEqual(st_g, "VERIFIED", errs_g)

        # 2) Verbatim 6-job disk replay (mandatory when STD024_REQUIRE_VERBATIM_REPLAY=1)
        require_verbatim = os.environ.get("STD024_REQUIRE_VERBATIM_REPLAY") == "1"
        replay_dir = ROOT / ".artifacts" / "acceptance" / "Std-024-consumer-ci-provenance-hardening" / "v3.0.2" / "hub_ci_replay"
        if require_verbatim:
            self.assertTrue(replay_dir.is_dir(), f"Missing mandatory 6-job replay directory: {replay_dir}")
            self.assertTrue((replay_dir / "run_45310932802.json").is_file(), "Missing run_45310932802.json")
            self.assertTrue((replay_dir / "jobs_45310932802.json").is_file(), "Missing jobs_45310932802.json")
        if replay_dir.is_dir() and (replay_dir / "run_45310932802.json").is_file() and (replay_dir / "jobs_45310932802.json").is_file():
            disk_run = json.loads((replay_dir / "run_45310932802.json").read_text(encoding="utf-8-sig"))
            disk_jobs = json.loads((replay_dir / "jobs_45310932802.json").read_text(encoding="utf-8-sig"))
            for spec in hub_jobs:
                log_file = replay_dir / f"{spec['key']}_{spec['job_id']}.log"
                if require_verbatim:
                    self.assertTrue(log_file.is_file(), f"Missing mandatory replay log: {log_file}")
                elif not log_file.is_file():
                    continue
                with self.subTest(mode="verbatim_replay", job=spec["key"]):
                    raw_bytes = log_file.read_bytes()
                    self.assertEqual(hashlib.sha256(raw_bytes).hexdigest(), spec["sha256"])
                    raw_text = raw_bytes.decode("utf-8", errors="replace")
                    if spec["evidence_type"] == "test_execution":
                        st_vp, errs_vp = parse_runner_test_log(
                            raw_text,
                            expected_commit=self.CONSUMER_COMMIT,
                            claimed_passed=spec["passed"],
                            claimed_collected=spec["collected"],
                            claimed_failed=0,
                            claimed_skipped=spec["skipped"],
                            require_source_identity=True,
                            expected_command=spec["command"],
                            expected_repository=self.REPO,
                        )
                    elif spec["evidence_type"] == "scan_execution":
                        st_vp, errs_vp = parse_runner_scan_log(
                            raw_text,
                            expected_commit=self.CONSUMER_COMMIT,
                            claimed_targets=spec["targets_scanned"],
                            claimed_vulns=0,
                            require_source_identity=True,
                            expected_command=spec["command"],
                            expected_repository=self.REPO,
                        )
                    else:
                        st_vp, errs_vp = parse_runner_release_log(
                            raw_text,
                            expected_commit=self.CONSUMER_COMMIT,
                            claimed_checks_passed=spec["checks_passed"],
                            claimed_checks_failed=0,
                            require_source_identity=True,
                            expected_command=spec["command"],
                            expected_repository=self.REPO,
                            claimed_checks_not_applicable=spec["checks_na"],
                        )
                    self.assertEqual(st_vp, "VERIFIED", errs_vp)
                    gate = _make_gate_for_spec(spec)
                    with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(disk_run, disk_jobs, raw_text)):
                        st_vg, errs_vg = verify_consumer_ci_gate(self.REPO, gate, self.CONSUMER_COMMIT)
                    self.assertEqual(st_vg, "VERIFIED", errs_vg)

    def test_t14_missing_required_api_identity_fields_fail_closed(self) -> None:
        from unittest.mock import patch

        log_text = self._build_gha_log()
        base_run = {
            "id": 45310932802,
            "event": "pull_request",
            "repository": {"full_name": self.REPO},
            "head_sha": self.CONSUMER_COMMIT,
            "path": ".github/workflows/ci-governance.yml",
            "status": "completed",
            "conclusion": "success",
        }
        base_job = {
            "id": 138166184154,
            "run_id": 45310932802,
            "head_sha": self.CONSUMER_COMMIT,
            "name": "Unit & Contract Tests (Ubuntu)",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": "Checkout repository", "conclusion": "success"},
                {"name": "Verify event source commit", "conclusion": "success"},
                {"name": "Run tests", "conclusion": "success"},
            ],
        }
        cases = [
            ("missing_run_id", {k: v for k, v in base_run.items() if k != "id"}, base_job, "FAILED", "CONSUMER_CI_RUN_ID_MISSING"),
            ("missing_run_event", {k: v for k, v in base_run.items() if k != "event"}, base_job, "FAILED", "CONSUMER_CI_RUN_EVENT_MISSING"),
            ("missing_job_run_id", base_run, {k: v for k, v in base_job.items() if k != "run_id"}, "FAILED", "CONSUMER_CI_JOB_RUN_ID_MISSING"),
            ("missing_job_head_sha", base_run, {k: v for k, v in base_job.items() if k != "head_sha"}, "FAILED", "CONSUMER_CI_JOB_COMMIT_MISSING"),
            ("missing_job_steps", base_run, {k: v for k, v in base_job.items() if k != "steps"}, "NOT_VERIFIABLE", "CONSUMER_CI_JOB_STEPS_METADATA_MISSING"),
            ("empty_job_steps", base_run, dict(base_job, steps=[]), "NOT_VERIFIABLE", "CONSUMER_CI_JOB_STEPS_METADATA_MISSING"),
        ]
        for label, rp, jp, exp_st, exp_code in cases:
            with self.subTest(case=label):
                gate = self._build_gate()
                if label == "missing_run_event":
                    gate.pop("event", None)
                with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(rp, {"jobs": [jp]}, log_text)):
                    st, errs = verify_consumer_ci_gate(self.REPO, gate, self.CONSUMER_COMMIT)
                self.assertEqual(st, exp_st, f"{label}: {errs}")
                self.assertNotEqual(st, "VERIFIED")
                self.assertTrue(any(exp_code in e for e in errs), f"{label}: {errs}")

    def test_t15_missing_or_skipped_checkout_identity_or_execution_steps_fail(self) -> None:
        from unittest.mock import patch

        run_payload = {
            "id": 45310932802,
            "event": "pull_request",
            "repository": {"full_name": self.REPO},
            "head_sha": self.CONSUMER_COMMIT,
            "path": ".github/workflows/ci-governance.yml",
            "status": "completed",
            "conclusion": "success",
        }
        good_log = self._build_gha_log()
        no_git_log = self._build_gha_log(checkout_ref=None, git_log_commit=None, expected_sha_env=None, include_identity_step=False)

        # 1. Skipped checkout step -> FAILED
        jobs_skip_co = {"jobs": [{"id": 138166184154, "run_id": 45310932802, "head_sha": self.CONSUMER_COMMIT, "name": "Unit & Contract Tests (Ubuntu)", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout repository", "conclusion": "skipped"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(run_payload, jobs_skip_co, good_log)):
            st1, e1 = verify_consumer_ci_gate(self.REPO, self._build_gate(), self.CONSUMER_COMMIT)
        self.assertEqual(st1, "FAILED", e1)
        self.assertTrue(any("CONSUMER_CI_CHECKOUT_STEP_NOT_SUCCESS" in x for x in e1), e1)

        # 2. Skipped source identity verification step -> FAILED
        jobs_skip_id = {"jobs": [{"id": 138166184154, "run_id": 45310932802, "head_sha": self.CONSUMER_COMMIT, "name": "Unit & Contract Tests (Ubuntu)", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout repository", "conclusion": "success"}, {"name": "Verify event source commit", "conclusion": "skipped"}, {"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(run_payload, jobs_skip_id, good_log)):
            st2, e2 = verify_consumer_ci_gate(self.REPO, self._build_gate(), self.CONSUMER_COMMIT)
        self.assertEqual(st2, "FAILED", e2)
        self.assertTrue(any("CONSUMER_CI_SOURCE_IDENTITY_STEP_NOT_SUCCESS" in x for x in e2), e2)

        # 3. Missing checkout step AND no authoritative source commit in log -> NOT_VERIFIABLE
        jobs_no_co = {"jobs": [{"id": 138166184154, "run_id": 45310932802, "head_sha": self.CONSUMER_COMMIT, "name": "Unit & Contract Tests (Ubuntu)", "status": "completed", "conclusion": "success", "steps": [{"name": "Run tests", "conclusion": "success"}]}]}
        with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(run_payload, jobs_no_co, no_git_log)):
            st3, e3 = verify_consumer_ci_gate(self.REPO, self._build_gate(), self.CONSUMER_COMMIT)
        self.assertEqual(st3, "NOT_VERIFIABLE", e3)
        self.assertTrue(any("CONSUMER_CI_SOURCE_IDENTITY_MISSING" in x for x in e3), e3)

        # 4. All execution steps skipped -> FAILED
        jobs_skip_exec = {"jobs": [{"id": 138166184154, "run_id": 45310932802, "head_sha": self.CONSUMER_COMMIT, "name": "Unit & Contract Tests (Ubuntu)", "status": "completed", "conclusion": "success", "steps": [{"name": "Checkout repository", "conclusion": "success"}, {"name": "Verify event source commit", "conclusion": "success"}, {"name": "Run tests", "conclusion": "skipped"}]}]}
        with patch("urllib.request.urlopen", side_effect=self._mock_urlopen(run_payload, jobs_skip_exec, good_log)):
            st4, e4 = verify_consumer_ci_gate(self.REPO, self._build_gate(), self.CONSUMER_COMMIT)
        self.assertEqual(st4, "FAILED", e4)
        self.assertTrue(any("CONSUMER_CI_EXECUTION_STEPS_SKIPPED" in x for x in e4), e4)

    def test_t16_checkout_wrong_repository_or_invalid_path_rejected(self) -> None:
        from tools.standards_sync.core import parse_runner_test_log

        # 1. Checkout points to a different repository
        wrong_repo_log = "\n".join([
            "Current runner version: '2.333.1'",
            "##[group]Run actions/checkout@v4",
            "with:",
            "  repository: evil/other-repo",
            "##[endgroup]",
            "Syncing repository: evil/other-repo",
            "[command]/usr/bin/git log -1 --format=%H",
            self.CONSUMER_COMMIT,
            "=== 12 passed in 0.5s ===",
        ])
        st_r, e_r = parse_runner_test_log(wrong_repo_log, self.CONSUMER_COMMIT, 12, 12, expected_repository=self.REPO)
        self.assertEqual(st_r, "FAILED", e_r)
        self.assertTrue(any("CONSUMER_CI_CHECKOUT_REPOSITORY_MISMATCH" in x for x in e_r), e_r)

        # 2. Checkout points to traversal path or unused sub-path
        traversal_log = "\n".join([
            "Current runner version: '2.333.1'",
            "##[group]Run actions/checkout@v4",
            "with:",
            "  path: ../escape-dir",
            "##[endgroup]",
            "[command]/usr/bin/git log -1 --format=%H",
            self.CONSUMER_COMMIT,
            "=== 12 passed in 0.5s ===",
        ])
        st_t, e_t = parse_runner_test_log(traversal_log, self.CONSUMER_COMMIT, 12, 12, expected_repository=self.REPO)
        self.assertEqual(st_t, "FAILED", e_t)
        self.assertTrue(any("CONSUMER_CI_CHECKOUT_INVALID_PATH" in x for x in e_t), e_t)

        wrong_path_log = "\n".join([
            "Current runner version: '2.333.1'",
            "##[group]Run actions/checkout@v4",
            "with:",
            f"  repository: {self.REPO}",
            "  path: unused-checkout-dir",
            "##[endgroup]",
            "[command]/usr/bin/git log -1 --format=%H",
            self.CONSUMER_COMMIT,
            "=== 12 passed in 0.5s ===",
        ])
        st_p, e_p = parse_runner_test_log(wrong_path_log, self.CONSUMER_COMMIT, 12, 12, expected_repository=self.REPO)
        self.assertEqual(st_p, "FAILED", e_p)
        self.assertTrue(any("CONSUMER_CI_CHECKOUT_PATH_MISMATCH" in x for x in e_p), e_p)

        # 3. Only .standards auxiliary checkout (no primary repo checkout) cannot pass source identity
        sub_only_log = "\n".join([
            "Current runner version: '2.333.1'",
            "##[group]Run actions/checkout@v4",
            "with:",
            "  path: .standards",
            f"  ref: {self.CONSUMER_COMMIT}",
            "##[endgroup]",
            "[command]/usr/bin/git log -1 --format=%H",
            self.CONSUMER_COMMIT,
            "=== 12 passed in 0.5s ===",
        ])
        st_s, e_s = parse_runner_test_log(sub_only_log, self.CONSUMER_COMMIT, 12, 12, expected_repository=self.REPO)
        self.assertEqual(st_s, "NOT_VERIFIABLE", e_s)
        self.assertTrue(any("CONSUMER_CI_SOURCE_IDENTITY_MISSING" in x for x in e_s), e_s)

    def test_t17_expected_sha_or_checkout_ref_without_actual_git_proof_not_verifiable(self) -> None:
        from tools.standards_sync.core import parse_runner_test_log

        ref_only_log = "\n".join([
            "Current runner version: '2.333.1'",
            "##[group]Run actions/checkout@v4",
            "with:",
            f"  ref: {self.CONSUMER_COMMIT}",
            "##[endgroup]",
            "=== 12 passed in 0.5s ===",
        ])
        st1, e1 = parse_runner_test_log(ref_only_log, self.CONSUMER_COMMIT, 12, 12, require_source_identity=True)
        self.assertEqual(st1, "NOT_VERIFIABLE", e1)
        self.assertTrue(any("CONSUMER_CI_SOURCE_IDENTITY_MISSING" in x for x in e1), e1)

        env_only_log = "\n".join([
            "Current runner version: '2.333.1'",
            '##[group]Run test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"',
            'test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"',
            "env:",
            f"  EXPECTED_SHA: {self.CONSUMER_COMMIT}",
            "##[endgroup]",
            "=== 12 passed in 0.5s ===",
        ])
        st2, e2 = parse_runner_test_log(env_only_log, self.CONSUMER_COMMIT, 12, 12, require_source_identity=True)
        self.assertEqual(st2, "NOT_VERIFIABLE", e2)
        self.assertTrue(any("CONSUMER_CI_SOURCE_IDENTITY_MISSING" in x for x in e2), e2)

    def test_t18_scan_and_release_strict_reconciliation_and_mixed_logs(self) -> None:
        from tools.standards_sync.core import parse_runner_release_log, parse_runner_scan_log

        # 1. Unrelated pytest success CANNOT satisfy a non-test scanner (pip-audit)
        pytest_log_for_scan = self._build_gha_log(
            exec_body=(
                "##[group]Run python -m pytest tests/unit -v\n"
                "python -m pytest tests/unit -v\n"
                "##[endgroup]\n"
                "collected 15 items\n"
                "=== 15 passed in 0.25s ===\n"
            )
        )
        st_s1, e_s1 = parse_runner_scan_log(
            pytest_log_for_scan,
            self.CONSUMER_COMMIT,
            claimed_targets=15,
            claimed_vulns=0,
            expected_command="pip-audit",
        )
        self.assertNotEqual(st_s1, "VERIFIED", e_s1)

        # 2. Security test suite counting skipped tests in targets_scanned MUST FAIL
        sec_skip_log = self._build_gha_log(
            exec_body=(
                "##[group]Run python -m pytest tests/security -v\n"
                "python -m pytest tests/security -v\n"
                "##[endgroup]\n"
                "collected 37 items\n"
                "=== 36 passed, 1 skipped in 0.80s ===\n"
            )
        )
        st_s2, e_s2 = parse_runner_scan_log(
            sec_skip_log,
            self.CONSUMER_COMMIT,
            claimed_targets=37,
            claimed_vulns=0,
            expected_command="python -m pytest tests/security -v",
        )
        self.assertEqual(st_s2, "FAILED", e_s2)
        self.assertTrue(any("CONSUMER_CI_GATE_SCAN_COUNT_MISMATCH" in x for x in e_s2), e_s2)

        # 3. Scan zero targets / all skipped / mixed failure
        all_skip_scan = self._build_gha_log(
            exec_body=(
                "##[group]Run python -m pytest tests/security -v\n"
                "python -m pytest tests/security -v\n"
                "##[endgroup]\n"
                "collected 5 items\n"
                "=== 0 passed, 5 skipped in 0.05s ===\n"
            )
        )
        st_s3, _ = parse_runner_scan_log(all_skip_scan, self.CONSUMER_COMMIT, claimed_targets=5, expected_command="python -m pytest tests/security -v")
        self.assertEqual(st_s3, "FAILED")

        # 4. Release gate claiming checks_passed=12 when 2 are NOT_APPLICABLE MUST FAIL
        g01_12_obj = {
            "overall_status": "PASS",
            "gates": [{"gate_id": f"G{i:02d}", "status": "PASS"} for i in (1, 2, 3, 4, 6, 7, 8, 9, 10, 11)]
            + [
                {"gate_id": "G05", "status": "NOT_APPLICABLE", "detail": {"note": "dev mode"}},
                {"gate_id": "G12", "status": "NOT_APPLICABLE", "detail": {"note": "dev mode"}},
            ],
        }
        rel_log = self._build_gha_log(
            exec_body=(
                "##[group]Run python scripts/ci/verify_delivery_contract.py --mode DEVELOPMENT --run-pytest\n"
                "python scripts/ci/verify_delivery_contract.py --mode DEVELOPMENT --run-pytest\n"
                "##[endgroup]\n"
                + json.dumps(g01_12_obj, indent=2)
            )
        )
        st_r1, e_r1 = parse_runner_release_log(
            rel_log,
            self.CONSUMER_COMMIT,
            claimed_checks_passed=12,
            claimed_checks_failed=0,
            expected_command="python scripts/ci/verify_delivery_contract.py --mode DEVELOPMENT --run-pytest",
        )
        self.assertEqual(st_r1, "FAILED", e_r1)
        self.assertTrue(any("CONSUMER_CI_GATE_RELEASE_COUNT_MISMATCH" in x for x in e_r1), e_r1)

        # 5. Unjustified NOT_APPLICABLE or all NOT_APPLICABLE MUST FAIL
        unjustified_na_log = self._build_gha_log(
            exec_body=json.dumps({"overall_status": "PASS", "gates": [{"gate_id": "G01", "status": "PASS"}, {"gate_id": "G05", "status": "NOT_APPLICABLE"}]})
        )
        st_r2, e_r2 = parse_runner_release_log(unjustified_na_log, self.CONSUMER_COMMIT, claimed_checks_passed=1)
        self.assertEqual(st_r2, "FAILED", e_r2)
        self.assertTrue(any("CONSUMER_CI_GATE_RELEASE_UNJUSTIFIED_NA" in x for x in e_r2), e_r2)

        all_na_log = self._build_gha_log(
            exec_body=json.dumps({"overall_status": "PASS", "gates": [{"gate_id": "G05", "status": "NOT_APPLICABLE", "note": "skipped"}]})
        )
        st_r3, e_r3 = parse_runner_release_log(all_na_log, self.CONSUMER_COMMIT, claimed_checks_passed=1)
        self.assertEqual(st_r3, "FAILED", e_r3)
        self.assertTrue(any("CONSUMER_CI_GATE_RELEASE_ZERO_CHECKS" in x for x in e_r3), e_r3)

        # 6. Bare OVERALL=PASS or unrelated pytest CANNOT pass release gate
        st_r4, _ = parse_runner_release_log(self._build_gha_log(exec_body="OVERALL=PASS\n"), self.CONSUMER_COMMIT, claimed_checks_passed=5)
        self.assertEqual(st_r4, "NOT_VERIFIABLE")
        st_r5, _ = parse_runner_release_log(self._build_gha_log(exec_body="=== 5 passed in 0.1s ===\n"), self.CONSUMER_COMMIT, claimed_checks_passed=5)
        self.assertEqual(st_r5, "NOT_VERIFIABLE")

        # 7. Mixed PASS/FAIL summary in log MUST FAIL
        mixed_log = self._build_gha_log(exec_body="=== 10 passed in 0.5s ===\n=== 2 passed, 1 failed in 0.1s ===\n")
        st_m, _ = parse_runner_scan_log(mixed_log, self.CONSUMER_COMMIT, claimed_targets=10)
        self.assertEqual(st_m, "FAILED")
        st_mr, _ = parse_runner_release_log(mixed_log, self.CONSUMER_COMMIT, claimed_checks_passed=10)
        self.assertEqual(st_mr, "FAILED")


class Std024ConsumerBaselineHardeningTests(unittest.TestCase):
    """T09, T10, T13: Consumer baseline scope isolation, multi-level Chinese links, and PR #15 compatibility."""

    def _create_consumer_project(self, dst: Path, nested_chinese: bool = False) -> tuple[Path, bytes]:
        head = _copy_minimal_valid_project(dst)
        rel_ev_dir = dst / "docs" / "release-evidence"
        if rel_ev_dir.exists():
            shutil.rmtree(rel_ev_dir)
        di_clean_p = dst / "docs" / "DOCUMENT-INDEX.md"
        if di_clean_p.exists():
            di_lines = [
                ln for ln in di_clean_p.read_text(encoding="utf-8").splitlines()
                if "./release-evidence/" not in ln
            ]
            di_clean_p.write_text("\n".join(di_lines) + "\n", encoding="utf-8")

        manifest = yaml.safe_load((dst / "engineering-manifest.yaml").read_text(encoding="utf-8"))
        manifest["project"]["id"] = "ai-engineering-hub"
        manifest["project"]["name"] = "AI Engineering Hub"
        manifest["project"]["repository"] = "xiefeifeihu/AI-Engineering-Hub"
        manifest["project"]["purpose"] = "Consumer Governance Platform"
        manifest["standards_validation"] = {
            "schema_version": "1.0.0",
            "required_ci_jobs": {
                "unit_tests": {
                    "workflow_path": ".github/workflows/ci-governance.yml",
                    "job_name": "Unit Tests",
                    "command": "pytest -q",
                },
                "integration_tests": {
                    "workflow_path": ".github/workflows/ci-governance.yml",
                    "job_name": "Integration Tests",
                    "command": "pytest tests/integration",
                },
                "release_gates": {
                    "workflow_path": ".github/workflows/ci-governance.yml",
                    "job_name": "Release Gates",
                    "command": "python tools/release_gates.py",
                },
                "security_scan": {
                    "workflow_path": ".github/workflows/ci-governance.yml",
                    "job_name": "Security Scan",
                    "command": "pytest tests/security",
                },
                "business_api": {
                    "workflow_path": ".github/workflows/ci-governance.yml",
                    "job_name": "Business API",
                    "command": "pytest tests/api",
                },
                "runtime_acceptance": {
                    "workflow_path": ".github/workflows/ci-governance.yml",
                    "job_name": "Runtime Acceptance",
                    "command": "pytest tests/runtime",
                },
            },
        }
        (dst / "engineering-manifest.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        wf_dir = dst / ".github" / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        (wf_dir / "ci-governance.yml").write_text("name: Consumer Governance CI\n", encoding="utf-8")

        from tools.validate_approval_contract import compute_canonical_document_sha256

        # Update project_id and source_commit in all copied docs cleanly
        for md_file in sorted((dst / "docs").rglob("*.md")):
            txt = re.sub(r'project_id:\s*"[^"]+"', 'project_id: "ai-engineering-hub"', md_file.read_text(encoding="utf-8"))
            md_file.write_text(txt, encoding="utf-8")

        if nested_chinese:
            proto_src = dst / "docs" / "PROTOTYPE-UX.md"
            proto_txt = proto_src.read_text(encoding="utf-8")
            proto_txt = proto_txt.replace("../standards/14-ui-diagnostics/STD-018-ui-diagnostics-enum-presentation.md", "./PROTOTYPE-UX.md")
            proto_txt = proto_txt.replace("# Prototype", "# 原型交互设计\n\n## 页面交互\n内容")
            if "## 页面交互" not in proto_txt:
                proto_txt += "\n## 页面交互\n页面交互详细说明\n"
            proto_src.unlink()
            proto_dst = dst / "docs" / "01-架构设计" / "原型" / "v0.21.1-调用诊断" / "PROTOTYPE-UX.md"
            proto_dst.parent.mkdir(parents=True, exist_ok=True)

            api_src = dst / "docs" / "API-CONTRACT.md"
            api_txt = api_src.read_text(encoding="utf-8")
            api_txt = (
                api_txt.replace("../schemas/", "../../../schemas/")
                .replace("../governance/", "../../../governance/")
                .replace("./Standards消费端接入与工具使用协议.md", "../../Standards消费端接入与工具使用协议.md")
            )
            if "## 核心接口" not in api_txt:
                api_txt += "\n## 核心接口\n核心接口契约说明\n"
            api_src.unlink()
            api_dst = dst / "docs" / "02-接口契约" / "核心" / "API-CONTRACT.md"
            api_dst.parent.mkdir(parents=True, exist_ok=True)

            pb_path = dst / "docs" / "PRODUCT-BASELINE.md"
            pb_txt = pb_path.read_text(encoding="utf-8")
            inserted_bullets = (
                "\n## 产品概述\n产品核心能力说明\n\n"
                "- 查看 [核心接口规范](02-%E6%8E%A5%E5%8F%A3%E5%A5%91%E7%BA%A6%2F%E6%A0%B8%E5%BF%83%2FAPI-CONTRACT.md#%E6%A0%B8%E5%BF%83%E6%8E%A5%E5%8F%A3)\n"
                "- 跳转 [产品概述](#产品概述)\n"
                "- 查看 [调用诊断原型](docs/01-架构设计/原型/v0.21.1-调用诊断/PROTOTYPE-UX.md#页面交互) 以及 `[忽略示例](./missing.md)`\n"
            )
            if "## 1. 当前正式交付能力清单" in pb_txt:
                pb_txt = pb_txt.replace("## 1. 当前正式交付能力清单", f"{inserted_bullets}\n## 1. 当前正式交付能力清单", 1)
            else:
                pb_txt += inserted_bullets

            dec_src = dst / "docs" / "DECISION-RECORD.md"
            dec_txt = dec_src.read_text(encoding="utf-8")
            dec_txt = dec_txt.replace("./migration/", "../../migration/")
            dec_src.unlink()
            dec_dst = dst / "docs" / "03-决策记录" / "ADR" / "DECISION-RECORD.md"
            dec_dst.parent.mkdir(parents=True, exist_ok=True)

            # Move to subdirectory relative to docs and fix doc index links
            doc_index = dst / "docs" / "DOCUMENT-INDEX.md"
            di_txt = doc_index.read_text(encoding="utf-8")
            di_txt = (
                di_txt.replace("./PROTOTYPE-UX.md", "./01-架构设计/原型/v0.21.1-调用诊断/PROTOTYPE-UX.md")
                .replace("docs/PROTOTYPE-UX.md", "docs/01-架构设计/原型/v0.21.1-调用诊断/PROTOTYPE-UX.md")
                .replace("./API-CONTRACT.md", "./02-接口契约/核心/API-CONTRACT.md")
                .replace("docs/API-CONTRACT.md", "docs/02-接口契约/核心/API-CONTRACT.md")
                .replace("./DECISION-RECORD.md", "./03-决策记录/ADR/DECISION-RECORD.md")
                .replace("docs/DECISION-RECORD.md", "docs/03-决策记录/ADR/DECISION-RECORD.md")
            )

            handoff_p = dst / "docs" / "CROSS-SESSION-HANDOFF.md"
            h_txt = handoff_p.read_text(encoding="utf-8")
            h_txt = (
                h_txt.replace("docs/PROTOTYPE-UX.md", "docs/01-架构设计/原型/v0.21.1-调用诊断/PROTOTYPE-UX.md")
                .replace("docs/API-CONTRACT.md", "docs/02-接口契约/核心/API-CONTRACT.md")
                .replace("docs/DECISION-RECORD.md", "docs/03-决策记录/ADR/DECISION-RECORD.md")
            )

            updates = [
                (proto_dst, proto_txt),
                (api_dst, api_txt),
                (pb_path, pb_txt),
                (dec_dst, dec_txt),
                (doc_index, di_txt),
                (handoff_p, h_txt),
            ]
            for target_p, raw_t in updates:
                new_sha = compute_canonical_document_sha256(raw_t)
                fixed_t = re.sub(r'content_sha256:\s*"[^"]+"', f'content_sha256: "{new_sha}"', raw_t)
                target_p.write_text(fixed_t, encoding="utf-8")

        subprocess.run(["git", "-C", str(dst), "add", "-A"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(dst), "commit", "-m", "consumer fixture"], capture_output=True, check=True)
        head = subprocess.run(["git", "-C", str(dst), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        for md_file in sorted((dst / "docs").rglob("*.md")):
            raw_t = md_file.read_text(encoding="utf-8")
            raw_t = re.sub(r'source_commit:\s*"[0-9a-f]{40}"', f'source_commit: "{head}"', raw_t)
            new_sha = compute_canonical_document_sha256(raw_t)
            raw_t = re.sub(r'content_sha256:\s*"[^"]+"', f'content_sha256: "{new_sha}"', raw_t)
            md_file.write_text(raw_t, encoding="utf-8")
        subprocess.run(["git", "-C", str(dst), "add", "-A"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(dst), "commit", "-m", "sync source_commit"], capture_output=True, check=True)
        dec_path = next((dst / "docs").rglob("DECISION-RECORD.md"))
        return dec_path, dec_path.read_bytes()

    def test_t09_consumer_scope_isolates_standards_internal_state_and_preserves_adrs(self) -> None:
        from tools.generate_engineering_baseline import build_engineering_baseline

        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            dec_path, orig_dec_bytes = self._create_consumer_project(dst, nested_chinese=False)
            for scope_arg in (None, "consumer"):
                with self.subTest(scope=scope_arg):
                    ok, errs, payload, md = build_engineering_baseline(
                        project_root=dst,
                        standards_root=ROOT,
                        observed_at="2026-11-24T06:00:00Z",
                        scope=scope_arg,
                    )
                    self.assertTrue(ok, errs)
                    assert payload is not None and md is not None
                    ci_det = payload["recent_ci_facts"]["details"]
                    self.assertEqual(payload["recent_ci_facts"]["source_path"], ".github/workflows/ci-governance.yml")
                    self.assertEqual(payload["recent_ci_facts"]["verification_status"], "NOT_VERIFIABLE")
                    self.assertEqual(ci_det["last_verified_ci_commit"], "NOT_VERIFIABLE")
                    self.assertEqual(ci_det["workflow"], "ci-governance.yml")
                    self.assertEqual(ci_det["historical_ci_runs"], [])
                    self.assertNotIn("candidate_pr", ci_det)
                    self.assertEqual(payload["open_issues"], [])
                    self.assertEqual(payload["pending_approvals"], [])
                    self.assertEqual(payload["architecture_boundaries"]["read_only_boundaries"], [])

                    for forbidden in (
                        "standards-ci.yml",
                        "PR #8",
                        "PR #9",
                        "PR #10",
                        "AIHUB-FIRST-CONSUMER-PILOT-001",
                        "PR-REVIEW-STANDARDS-V3-001",
                        "vtip-platform-catalog",
                        "vtip-ai-sidecar",
                        "PR9_HISTORICAL_RELEASE_EVIDENCE",
                        "STD018_CURRENT_SNAPSHOT",
                        "STD019_FINAL_RELEASE",
                        "CURRENT_CANDIDATE_PR",
                    ):
                        self.assertNotIn(forbidden, md, f"Leaked '{forbidden}' into consumer baseline")
                    self.assertEqual(dec_path.read_bytes(), orig_dec_bytes)

    def test_t10_chinese_multilevel_encoded_and_anchored_relative_links_resolve(self) -> None:
        from tools.generate_engineering_baseline import build_engineering_baseline
        from tools.standards_sync.core import run_collection_validation

        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            self._create_consumer_project(dst, nested_chinese=True)

            # 1) Default output docs/当前权威基线.md
            default_out = dst / "docs" / "当前权威基线.md"
            ok, errs, payload, md = build_engineering_baseline(
                project_root=dst,
                standards_root=ROOT,
                observed_at="2026-11-24T06:00:00Z",
                scope="consumer",
                output_path=default_out,
            )
            self.assertTrue(ok, errs)
            assert md is not None
            default_out.write_text(md, encoding="utf-8")

            self.assertIn("(./01-架构设计/原型/v0.21.1-调用诊断/PROTOTYPE-UX.md)", md)
            self.assertIn("(./02-接口契约/核心/API-CONTRACT.md)", md)
            self.assertIn("(./02-接口契约/核心/API-CONTRACT.md#核心接口)", md)
            self.assertIn("(./03-决策记录/ADR/DECISION-RECORD.md)", md)
            self.assertIn("(./PRODUCT-BASELINE.md#产品概述)", md)
            self.assertIn("(./01-架构设计/原型/v0.21.1-调用诊断/PROTOTYPE-UX.md#页面交互)", md)
            self.assertIn("`[忽略示例](./missing.md)`", md)
            self.assertNotIn("(./PROTOTYPE-UX.md)", md)
            self.assertNotIn("docs/docs/", md)
            self.assertNotIn("%E6%", md)

            # Every non-code markdown link must resolve to an existing file on disk
            cleaned = re.sub(r"`[^`]*`", "", md)
            for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", cleaned):
                target = match.group(1).partition("#")[0]
                if target:
                    self.assertTrue((default_out.parent / target).is_file(), f"Broken link: {target}")

            # Ensure source doc itself uses unencoded UTF-8 link when running collection validator on full tree
            from tools.validate_approval_contract import compute_canonical_document_sha256
            pb_p = dst / "docs" / "PRODUCT-BASELINE.md"
            pb_plain = pb_p.read_text(encoding="utf-8").replace(
                "02-%E6%8E%A5%E5%8F%A3%E5%A5%91%E7%BA%A6%2F%E6%A0%B8%E5%BF%83%2FAPI-CONTRACT.md#%E6%A0%B8%E5%BF%83%E6%8E%A5%E5%8F%A3",
                "02-接口契约/核心/API-CONTRACT.md#核心接口",
            )
            pb_plain = re.sub(
                r'content_sha256:\s*"[^"]+"',
                f'content_sha256: "{compute_canonical_document_sha256(pb_plain)}"',
                pb_plain,
            )
            pb_p.write_text(pb_plain, encoding="utf-8")

            col_ok, col_errs = run_collection_validation(
                project_root=dst,
                schema_path=ROOT / "schemas" / "documentation-metadata.schema.json",
                standards_root=ROOT,
                check_templates=False,
                verify_source_paths=False,
            )
            self.assertTrue(col_ok, f"Collection validation failed on nested Chinese links: {col_errs}")

            # 2) Deeply nested --output docs/子目录/多级视图/基线视图.md via CLI
            nested_rel = Path("docs") / "子目录" / "多级视图" / "基线视图.md"
            cp = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "generate_engineering_baseline.py"),
                    "--project-root", str(dst),
                    "--standards-root", str(ROOT),
                    "--scope", "consumer",
                    "--observed-at", "2026-11-24T06:00:00Z",
                    "--output", str(nested_rel),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(cp.returncode, 0, f"{cp.stdout}\n{cp.stderr}")
            nested_out = dst / nested_rel
            nested_md = nested_out.read_text(encoding="utf-8")
            self.assertIn("(../../01-架构设计/原型/v0.21.1-调用诊断/PROTOTYPE-UX.md)", nested_md)
            self.assertIn("(../../02-接口契约/核心/API-CONTRACT.md#核心接口)", nested_md)
            self.assertIn("(../../PRODUCT-BASELINE.md#产品概述)", nested_md)
            self.assertNotIn("docs/docs/", nested_md)
            nested_clean = re.sub(r"`[^`]*`", "", nested_md)
            for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", nested_clean):
                target = match.group(1).partition("#")[0]
                if target:
                    self.assertTrue((nested_out.parent / target).is_file(), f"Broken nested link: {target}")

    def test_t13_standards_release_scope_preserves_pr15_evidence_behavior(self) -> None:
        from tools.generate_engineering_baseline import build_engineering_baseline, extract_scope_content

        ok, errs, payload, md = build_engineering_baseline(
            project_root=ROOT,
            standards_root=ROOT,
            observed_at="2026-11-24T06:00:00Z",
            scope="standards-release",
            final_evidence_path="docs/release-evidence/std019-final-release.json",
        )
        self.assertTrue(ok, errs)
        assert payload is not None and md is not None
        eb_schema = json.loads((ROOT / "schemas" / "engineering-baseline.schema.json").read_text(encoding="utf-8"))
        import jsonschema
        jsonschema.validate(instance=payload, schema=eb_schema)
        for scope_name in ("PR9_HISTORICAL_RELEASE_EVIDENCE", "STD018_CURRENT_SNAPSHOT", "STD019_FINAL_RELEASE", "CURRENT_CANDIDATE_PR"):
            _, s_errs = extract_scope_content(md, scope_name)
            self.assertEqual(s_errs, [], f"{scope_name}: {s_errs}")


class Std024PackagerOverwriteProtectionTests(unittest.TestCase):
    """T11-T12: Historical Acceptance ZIP default overwrite guard & authorized overwrite audit tests."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        (self.repo / "VERSION").write_text("3.0.1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_acceptance(self, task_id: str = "HIST-TASK", version: str = "v3.0.1", content: str = "REPORT-V1") -> tuple[Path, Path, Path, Path]:
        acc_dir = self.repo / ".artifacts" / "acceptance" / task_id / version
        acc_dir.mkdir(parents=True, exist_ok=True)
        rpt = acc_dir / "acceptance_report.md"
        rpt.write_text(f"# Acceptance\n{content}\n", encoding="utf-8")
        data = rpt.read_bytes()
        manifest = {
            "task_id": task_id,
            "version": version,
            "run_id": f"run-{content}",
            "created_at": "2026-11-24T06:00:00Z",
            "status": "PASS",
            "files": [{"path": "acceptance_report.md", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}],
        }
        manifest_path = acc_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        pkg_dir = self.repo / ".artifacts" / "packages"
        zip_path = pkg_dir / f"Acceptance-{task_id}-{version}.zip"
        sha_path = pkg_dir / f"Acceptance-{task_id}-{version}.zip.sha256"
        return acc_dir, manifest_path, zip_path, sha_path

    def test_t11_existing_zip_sidecar_checksum_and_concurrent_race_blocked_by_default(self) -> None:
        from scripts.package_acceptance import package_acceptance

        _, manifest_path, zip_path, sha_path = self._seed_acceptance("HIST-TASK", "v3.0.1", "V1")
        res1 = package_acceptance("HIST-TASK", version="3.0.1", run_id="run-1", repo_root=self.repo)
        self.assertEqual(res1["status"], "PASS")
        self.assertFalse(res1["overwritten"])

        orig_zip = zip_path.read_bytes()
        orig_sha = sha_path.read_bytes()
        orig_man = manifest_path.read_bytes()

        # Re-seed modified V2 report and try default overwrite -> MUST fail without mutating anything
        self._seed_acceptance("HIST-TASK", "v3.0.1", "V2")
        mod_man = manifest_path.read_bytes()
        with self.assertRaises(FileExistsError) as ctx:
            package_acceptance("HIST-TASK", version="3.0.1", run_id="run-2", repo_root=self.repo)
        self.assertIn("ACCEPTANCE_PACKAGE_OVERWRITE_FORBIDDEN", str(ctx.exception))
        self.assertEqual(zip_path.read_bytes(), orig_zip)
        self.assertEqual(sha_path.read_bytes(), orig_sha)
        self.assertEqual(manifest_path.read_bytes(), mod_man)
        pkg_dir = self.repo / ".artifacts" / "packages"
        self.assertEqual(list(pkg_dir.glob(".tmp_*")), [])
        self.assertEqual(list(pkg_dir.glob(".bak_*")), [])
        self.assertEqual(list(pkg_dir.glob(".tx_journal_*")), [])
        self.assertNotEqual(orig_man, b"")

        # Also block when ONLY .sha256 sidecar exists
        zip_path.unlink()
        with self.assertRaises(FileExistsError):
            package_acceptance("HIST-TASK", version="3.0.1", run_id="run-2", repo_root=self.repo)
        self.assertEqual(sha_path.read_bytes(), orig_sha)
        self.assertFalse(zip_path.exists())

        # Also block when ONLY CHECKSUMS.txt references the package filename
        sha_path.unlink()
        chk_path = pkg_dir / "CHECKSUMS.txt"
        chk_path.write_text(f"{'a'*64}  Acceptance-HIST-TASK-v3.0.1.zip\n", encoding="utf-8")
        orig_chk = chk_path.read_bytes()
        with self.assertRaises(FileExistsError):
            package_acceptance("HIST-TASK", version="3.0.1", run_id="run-2", repo_root=self.repo)
        self.assertEqual(chk_path.read_bytes(), orig_chk)

        # CLI invocation without --allow-overwrite on existing ZIP returns non-zero structured BLOCKED JSON
        chk_path.unlink()
        self._seed_acceptance("CLI-HIST", "v3.0.1", "V1")
        package_acceptance("CLI-HIST", version="3.0.1", run_id="run-1", repo_root=self.repo)
        cli_zip = pkg_dir / "Acceptance-CLI-HIST-v3.0.1.zip"
        cli_orig = cli_zip.read_bytes()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        cp = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "package_acceptance.py"),
                "--task-id", "CLI-HIST",
                "--version", "3.0.1",
                "--run-id", "run-2",
                "--repo-root", str(self.repo),
            ],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(cp.returncode, 0, f"stdout={cp.stdout}\nstderr={cp.stderr}")
        self.assertIn("ACCEPTANCE_PACKAGE_OVERWRITE_FORBIDDEN", cp.stdout, f"stdout={cp.stdout}\nstderr={cp.stderr}")
        self.assertEqual(cli_zip.read_bytes(), cli_orig)

        # Concurrent race under allow_overwrite=False: 2 processes race -> 1 passes, 1 blocked
        self._seed_acceptance("RACE-TASK", "v3.0.1", "R1")
        worker_code = f"""
from pathlib import Path
from scripts.package_acceptance import package_acceptance
package_acceptance('RACE-TASK', version='3.0.1', run_id='race-run', repo_root=Path({repr(str(self.repo))}), lock_timeout=15.0)
"""
        p1 = subprocess.Popen([sys.executable, "-c", worker_code], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        p2 = subprocess.Popen([sys.executable, "-c", worker_code], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        _, e1 = p1.communicate(timeout=20)
        _, e2 = p2.communicate(timeout=20)
        rcs = sorted([p1.returncode, p2.returncode])
        self.assertEqual(rcs[0], 0, f"One racer must succeed: {e1} / {e2}")
        self.assertNotEqual(rcs[1], 0, "Second racer must be blocked without --allow-overwrite")
        self.assertIn("ACCEPTANCE_PACKAGE_OVERWRITE_FORBIDDEN", e1 + e2)

    def test_t12_authorized_overwrite_audits_hashes_and_incomplete_evidence_still_blocks(self) -> None:
        from scripts.package_acceptance import package_acceptance

        acc_dir, manifest_path, zip_path, sha_path = self._seed_acceptance("AUTH-TASK", "v3.0.1", "V1")
        res1 = package_acceptance("AUTH-TASK", version="3.0.1", run_id="run-1", repo_root=self.repo)
        v1_zip_bytes = zip_path.read_bytes()
        v1_sha_bytes = sha_path.read_bytes()
        v1_zip_sha = res1["zip_sha256"]

        # Incomplete evidence MUST still fail even when allow_overwrite=True and never damage historical V1 ZIP
        self._seed_acceptance("AUTH-TASK", "v3.0.1", "BAD-V2")
        bad_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bad_manifest["files"][0]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(bad_manifest, indent=2), encoding="utf-8")
        bad_man_bytes = manifest_path.read_bytes()
        with self.assertRaises(ValueError):
            package_acceptance(
                "AUTH-TASK",
                version="3.0.1",
                run_id="run-bad",
                repo_root=self.repo,
                allow_overwrite=True,
                overwrite_reason="SHOULD_ROLL_BACK",
            )
        self.assertEqual(zip_path.read_bytes(), v1_zip_bytes)
        self.assertEqual(sha_path.read_bytes(), v1_sha_bytes)
        self.assertEqual(manifest_path.read_bytes(), bad_man_bytes)
        self.assertFalse((self.repo / ".artifacts" / "packages" / "overwrite_audit.jsonl").exists())

        # Valid authorized overwrite with explicit reason records previous & new SHA-256 without self-reference in manifest
        self._seed_acceptance("AUTH-TASK", "v3.0.1", "V2")
        res2 = package_acceptance(
            "AUTH-TASK",
            version="3.0.1",
            run_id="run-2",
            repo_root=self.repo,
            allow_overwrite=True,
            overwrite_reason="TASK-AUTH-STD-024-RESEAL",
        )
        self.assertEqual(res2["status"], "PASS")
        self.assertTrue(res2["overwritten"])
        audit = res2["overwrite_audit"]
        self.assertEqual(audit["reason"], "TASK-AUTH-STD-024-RESEAL")
        self.assertEqual(audit["previous_zip_sha256"], v1_zip_sha)
        self.assertEqual(audit["new_zip_sha256"], res2["zip_sha256"])
        self.assertNotEqual(audit["previous_zip_sha256"], audit["new_zip_sha256"])
        audit_lines = (self.repo / ".artifacts" / "packages" / "overwrite_audit.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(audit_lines), 1)
        self.assertEqual(json.loads(audit_lines[0])["new_zip_sha256"], res2["zip_sha256"])
        final_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertNotIn("zip_sha256", final_manifest)

    def test_t19_authorized_overwrite_requires_real_non_default_reason(self) -> None:
        from scripts.package_acceptance import package_acceptance

        _, manifest_path, zip_path, sha_path = self._seed_acceptance("REASON-TASK", "v3.0.2", "V1")
        package_acceptance("REASON-TASK", version="3.0.2", run_id="run-1", repo_root=self.repo)
        orig_zip = zip_path.read_bytes()
        orig_sha = sha_path.read_bytes()

        self._seed_acceptance("REASON-TASK", "v3.0.2", "V2")
        mod_man = manifest_path.read_bytes()
        for bad_reason in (None, "", "   ", "EXPLICIT_ALLOW_OVERWRITE_FLAG", "--allow-overwrite", "short"):
            with self.subTest(bad_reason=bad_reason):
                with self.assertRaises(ValueError) as ctx:
                    package_acceptance(
                        "REASON-TASK",
                        version="3.0.2",
                        run_id="run-2",
                        repo_root=self.repo,
                        allow_overwrite=True,
                        overwrite_reason=bad_reason,
                    )
                self.assertIn("ACCEPTANCE_PACKAGE_OVERWRITE_REASON_REQUIRED", str(ctx.exception))
                self.assertEqual(zip_path.read_bytes(), orig_zip)
                self.assertEqual(sha_path.read_bytes(), orig_sha)
                self.assertEqual(manifest_path.read_bytes(), mod_man)

        # CLI --allow-overwrite without --overwrite-reason must fail with non-zero JSON BLOCKED
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        cp = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "package_acceptance.py"),
                "--task-id", "REASON-TASK",
                "--version", "3.0.2",
                "--run-id", "run-2",
                "--repo-root", str(self.repo),
                "--allow-overwrite",
            ],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(cp.returncode, 0, cp.stdout)
        self.assertIn("ACCEPTANCE_PACKAGE_OVERWRITE_REASON_REQUIRED", cp.stdout)
        self.assertEqual(zip_path.read_bytes(), orig_zip)

    def test_t20_audit_write_failure_and_replace_failure_preserve_historical_evidence(self) -> None:
        from scripts.package_acceptance import package_acceptance, recover_incomplete_package_transactions

        _, manifest_path, zip_path, sha_path = self._seed_acceptance("AUDIT-TX", "v3.0.2", "V1")
        package_acceptance("AUDIT-TX", version="3.0.2", run_id="run-1", repo_root=self.repo)
        pkg_dir = self.repo / ".artifacts" / "packages"

        # Perform one authorized overwrite first so overwrite_audit.jsonl already exists with V1->V2 record
        self._seed_acceptance("AUDIT-TX", "v3.0.2", "V2")
        package_acceptance(
            "AUDIT-TX",
            version="3.0.2",
            run_id="run-2",
            repo_root=self.repo,
            allow_overwrite=True,
            overwrite_reason="AUTHORIZED-RESEAL-BASELINE-V2",
        )
        v2_man = manifest_path.read_bytes()
        v2_zip = zip_path.read_bytes()
        v2_sha = sha_path.read_bytes()
        v2_audit = (pkg_dir / "overwrite_audit.jsonl").read_bytes()

        # 1) Audit staging write failure -> zero damage to V2 ZIP/sidecar/manifest/audit, zero stray files
        self._seed_acceptance("AUDIT-TX", "v3.0.2", "V3")
        v3_man_staged = manifest_path.read_bytes()

        def fail_audit_write(p: Path, data: bytes) -> None:
            raise OSError("Injected audit disk write failure")

        with self.assertRaises(OSError):
            package_acceptance(
                "AUDIT-TX",
                version="3.0.2",
                run_id="run-3",
                repo_root=self.repo,
                allow_overwrite=True,
                overwrite_reason="AUTHORIZED-RESEAL-FAIL-AUDIT-STAGE",
                audit_write_fn=fail_audit_write,
            )
        self.assertEqual(manifest_path.read_bytes(), v3_man_staged)
        self.assertEqual(zip_path.read_bytes(), v2_zip)
        self.assertEqual(sha_path.read_bytes(), v2_sha)
        self.assertEqual((pkg_dir / "overwrite_audit.jsonl").read_bytes(), v2_audit)
        self.assertEqual(list(pkg_dir.glob(".*")), [])

        # 2) Audit atomic replace failure AFTER manifest/ZIP/sidecar already replaced -> full rollback restores all 4!
        manifest_path.write_bytes(v2_man)
        self._seed_acceptance("AUDIT-TX", "v3.0.2", "V3-REPLACE-FAIL")
        v3_man_before_tx = manifest_path.read_bytes()

        def fail_audit_replace(src: Path, dst: Path) -> None:
            if dst.name == "overwrite_audit.jsonl" and ".tmp_audit_" in src.name:
                raise PermissionError("Injected audit replace failure")
            os.replace(src, dst)

        with self.assertRaises(PermissionError):
            package_acceptance(
                "AUDIT-TX",
                version="3.0.2",
                run_id="run-3b",
                repo_root=self.repo,
                replace_fn=fail_audit_replace,
                allow_overwrite=True,
                overwrite_reason="AUTHORIZED-RESEAL-FAIL-AUDIT-REPLACE",
            )
        self.assertEqual(manifest_path.read_bytes(), v3_man_before_tx)
        self.assertEqual(zip_path.read_bytes(), v2_zip)
        self.assertEqual(sha_path.read_bytes(), v2_sha)
        self.assertEqual((pkg_dir / "overwrite_audit.jsonl").read_bytes(), v2_audit)
        self.assertEqual(list(pkg_dir.glob(".*")), [])

        # 3) Crash recovery in COMMITTED_CLEANUP_PENDING verifies both original & new identities in audit
        manifest_path.write_bytes(v2_man)
        self._seed_acceptance("AUDIT-TX", "v3.0.2", "V4")
        v4_res = package_acceptance(
            "AUDIT-TX",
            version="3.0.2",
            run_id="run-4",
            repo_root=self.repo,
            allow_overwrite=True,
            overwrite_reason="AUTHORIZED-RESEAL-V4-IDENTITY",
        )
        v4_audit_rec = v4_res["overwrite_audit"]
        j_path = pkg_dir / ".tx_journal_AUDIT-TX_v3.0.2.json"
        committed_journal = {
            "tx_id": v4_audit_rec["tx_id"],
            "task_id": "AUDIT-TX",
            "version": "v3.0.2",
            "run_id": "run-4",
            "state": "COMMITTED_CLEANUP_PENDING",
            "overwrite_authorized": True,
            "overwrite_reason": v4_audit_rec["reason"],
            "orig_existed": {"manifest": True, "zip": True, "sha": True, "audit": True},
            "orig_sha256": {
                "manifest": v4_audit_rec["previous_manifest_sha256"],
                "zip": v4_audit_rec["previous_zip_sha256"],
                "sha": v4_audit_rec["previous_sha256_sidecar_sha256"],
                "audit": v4_audit_rec["previous_audit_sha256"],
            },
            "staged_sha256": {
                "manifest": v4_audit_rec["new_manifest_sha256"],
                "zip": v4_audit_rec["new_zip_sha256"],
                "sha": v4_audit_rec["new_sha256_sidecar_sha256"],
                "audit": hashlib.sha256((pkg_dir / "overwrite_audit.jsonl").read_bytes()).hexdigest(),
            },
            "targets": {
                "manifest": ".artifacts/acceptance/AUDIT-TX/v3.0.2/manifest.json",
                "zip": ".artifacts/packages/Acceptance-AUDIT-TX-v3.0.2.zip",
                "sha": ".artifacts/packages/Acceptance-AUDIT-TX-v3.0.2.zip.sha256",
                "audit": ".artifacts/packages/overwrite_audit.jsonl",
            },
            "backups": {
                "manifest": f".artifacts/packages/.bak_manifest_AUDIT-TX_v3.0.2_{v4_audit_rec['tx_id']}.json",
                "zip": f".artifacts/packages/.bak_Acceptance-AUDIT-TX-v3.0.2.zip_{v4_audit_rec['tx_id']}.zip",
                "sha": f".artifacts/packages/.bak_Acceptance-AUDIT-TX-v3.0.2.zip_{v4_audit_rec['tx_id']}.sha256",
                "audit": f".artifacts/packages/.bak_audit_AUDIT-TX_v3.0.2_{v4_audit_rec['tx_id']}.jsonl",
            },
        }
        # Tampered previous_zip_sha256 in journal vs audit must BLOCK recovery
        bad_j = dict(committed_journal, orig_sha256=dict(committed_journal["orig_sha256"], zip="0" * 64))
        j_path.write_text(json.dumps(bad_j, indent=2), encoding="utf-8")
        blk_rec = recover_incomplete_package_transactions(self.repo, task_id="AUDIT-TX", version="3.0.2")
        self.assertEqual(blk_rec["status"], "BLOCKED", blk_rec)
        self.assertIn("COMMITTED_AUDIT_IDENTITY_MISMATCH", blk_rec["reason"])

        # Valid identities pass recovery and clean up journal cleanly
        j_path.write_text(json.dumps(committed_journal, indent=2), encoding="utf-8")
        ok_rec = recover_incomplete_package_transactions(self.repo, task_id="AUDIT-TX", version="3.0.2")
        self.assertEqual(ok_rec["status"], "RECOVERED", ok_rec)
        self.assertFalse(j_path.exists())


if __name__ == "__main__":
    unittest.main()

