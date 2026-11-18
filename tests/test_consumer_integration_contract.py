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
from typing import Any, Dict

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
            [sys.executable, str(ROOT / "tools" / "generate_handoff.py"), "--project-root", str(ROOT), "--task-id", "Std-019-V3-0-0-POST-RELEASE-CLOSEOUT", "--verify-only"],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(res_h.returncode, 0, f"Handoff verify-only failed: {res_h.stdout} {res_h.stderr}")
        self.assertIn("[PASS]", res_h.stdout)

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
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]
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
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_scan = {"jobs": [{"id": 201, "name": "Security Scan", "status": "completed", "conclusion": "success"}]}
        jobs_release = {"jobs": [{"id": 202, "name": "Release Gate", "status": "completed", "conclusion": "success"}]}
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
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]
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
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "failure"}]
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
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [{"id": 101, "name": "Other Unrelated Job", "status": "completed", "conclusion": "success"}]
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
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]
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
            "repository": {"full_name": repository},
            "head_sha": commit,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }
        jobs_payload = {
            "jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/other.yml", "status": "completed", "conclusion": "success"}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
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
            package_acceptance("TEST-TASK", version="3.0.0", run_id="new-run-fail", repo_root=self.root)

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
            cb_st, cnt, cb_errs = compute_content_bindings(self.root)
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

        from tools.validate_approval_contract import compute_content_bindings
        cb_st, real_cnt, cb_errs = compute_content_bindings(self.root)
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
            _copy_minimal_valid_project(dst)
            cb_st, real_cnt, cb_errs = compute_content_bindings(dst)
            self.assertEqual(cb_st, "PASS", cb_errs)

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
        return root, "d" * 40

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
        app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", consumer_commit)

        # Modify engineering-manifest.yaml required_ci_jobs AFTER approval was issued
        mf_path = root / "engineering-manifest.yaml"
        mf_data = yaml.safe_load(mf_path.read_text(encoding="utf-8"))
        mf_data["standards_validation"]["required_ci_jobs"]["unit_tests"]["command"] = "pytest --skip-all"
        mf_path.write_text(yaml.safe_dump(mf_data, sort_keys=False, allow_unicode=True), encoding="utf-8")

        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_commit},
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
        app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", consumer_commit)

        # Modify standards.lock.json AFTER approval was issued
        lk_path = root / "standards.lock.json"
        lk = json.loads(lk_path.read_text(encoding="utf-8"))
        lk["lock_reason"] = "Tampered reason"
        lk_path.write_text(json.dumps(lk, indent=2), encoding="utf-8")

        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_commit},
            "merged_at": "2026-11-18T00:00:00Z",
        }
        status, errors = verify_approval_event_provenance(app, simulate_data=sim_pr, project_root=root)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONTENT_BINDING_DIGEST_MISMATCH" in e and "lock_manifest_sha256" in e for e in errors))

    def test_b5_content_bindings_missing_file_returns_not_verifiable(self) -> None:
        from tools.validate_approval_contract import verify_approval_event_provenance

        root, consumer_commit = self._build_consumer_fixture()
        app = self._make_promo_approval(root, "xiefeifeihu/AI-Engineering-Hub", consumer_commit)
        (root / "standards.lock.json").unlink()

        sim_pr = {
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": consumer_commit},
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

        root, _ = self._build_consumer_fixture()
        subprocess.run(["git", "-C", str(root), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "bind state"], capture_output=True, check=True)
        head_sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

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
        root = Path(tempfile.mkdtemp())
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
            package_acceptance("TX-TASK", version="3.0.0", run_id="new-run", repo_root=root, replace_fn=fail_on_manifest)

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
                package_acceptance("TX-TASK", version="3.0.0", run_id="new-run", repo_root=root)

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
            package_acceptance("TX-TASK", version="3.0.0", run_id="new-run", repo_root=root, replace_fn=fail_on_sidecar)

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
            package_acceptance("TX-TASK", version="3.0.0", run_id="new-run", repo_root=root, replace_fn=fail_sidecar_and_restore)
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
            )
        self.assertIn("TRANSACTION_ROLLED_BACK_CLEANUP_FAILED", str(ctx1.exception))
        # All 3 originals must still be intact
        self.assertEqual(manifest_path.read_bytes(), orig_m)
        self.assertEqual(zip_path.read_bytes(), orig_z)
        self.assertEqual(sha_path.read_bytes(), orig_s)


if __name__ == "__main__":
    unittest.main()

