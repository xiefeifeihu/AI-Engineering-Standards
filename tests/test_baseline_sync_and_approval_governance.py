#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comprehensive automated test suite for Standards v3.0.0 Baseline, Sync, and Approval Governance.

Covers Section 12 test requirements:
  A. Schema Tests (all schemas valid, 12 templates conform, positive/negative samples)
  B. Document Collection & ENGINEERING_BASELINE Tests (17 checks, determinism, source conflicts)
  C. Standards Sync Tool Tests (discover, SemVer sort, annotated Tag, VERSION, CI gate, timeout, drift, untagged, downgrade, unpublished commit, promote, rollback)
  D. Approval Authenticity Tests (anti-self-approval, ChatGPT review binding, Owner chat approval binding, hash/commit invalidation)
  E. Cross-Platform Tests (no hardcoded local paths, cross-OS path normalization)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import Optional
from unittest.mock import patch
import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.generate_engineering_baseline import (
    build_engineering_baseline,
    compute_deterministic_baseline_sha256,
    verify_baseline_semantic_facts,
)
from tools.generate_handoff import (
    build_handoff_payload,
    write_handoff_files,
    verify_handoff_semantic_facts,
)
from tools.release_evidence import (
    load_release_evidence,
    resolve_release_evidence_path,
    verify_git_tag,
    verify_github_ci_runs,
    verify_single_github_run,
)
from tools.standards_sync.core import (
    analyze_consumer_impact,
    check_remote_main_ci,
    compare_versions_and_artifacts,
    discover_latest_official_tag,
    parse_semver,
    prepare_upgrade_candidate,
    promote_upgrade,
    acquire_transaction_lock,
    release_transaction_lock,
    detect_interrupted_transaction,
    execute_transactional_two_file_update,
    recover_interrupted_transaction,
    _validate_journal_target,
    rollback_lock,
    validate_upgrade_candidate,
    verify_project_lock,
)
from tools.validate_approval_contract import (
    compute_canonical_document_sha256,
    compute_markdown_body_sha256,
    validate_approval_record,
    verify_approval_event_provenance,
)
from tools.validate_documentation_collection_bridge import (
    run_collection_validation,
    validate_templates_directory,
)

SCHEMAS_DIR = ROOT / "schemas"
TEMPLATES_DOC_DIR = ROOT / "templates" / "documentation"
BASELINE_COMMIT = "5e17c0ef560ab8abafe880b988d70f85f380a104"
PROJECT_SOURCE_COMMIT = "9687f961b22df612c4311961e06fc1c1fd508c37"
BASELINE_TAG_OBJ = "2f4b4b54348a5ac8891e5a0b33c04635a27213a0"


def _copy_minimal_valid_project(dst: Path) -> str:
    """Copy AI-Engineering-Standards' own valid docs, manifest, VERSION, and lock into dst."""
    shutil.copy2(ROOT / "VERSION", dst / "VERSION")
    shutil.copy2(ROOT / "engineering-manifest.yaml", dst / "engineering-manifest.yaml")
    shutil.copy2(ROOT / "standards.lock.json", dst / "standards.lock.json")
    shutil.copy2(ROOT / "CHANGELOG.md", dst / "CHANGELOG.md")
    shutil.copytree(ROOT / "docs", dst / "docs")
    shutil.copytree(ROOT / "schemas", dst / "schemas")
    shutil.copytree(ROOT / "governance", dst / "governance")
    shutil.copytree(ROOT / "standards", dst / "standards")
    shutil.copytree(ROOT / "tools", dst / "tools")
    if (ROOT / ".github").exists():
        shutil.copytree(ROOT / ".github", dst / ".github")
    # Initialize git repo with all files
    subprocess.run(["git", "init", str(dst)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(dst), "config", "user.email", "test@standards.local"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(dst), "config", "user.name", "Standards Test"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(dst), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(dst), "commit", "-m", "init"], capture_output=True, check=True)
    head = subprocess.run(
        ["git", "-C", str(dst), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    # Rebind document provenance to a commit that exists in this isolated fixture.
    for md in (dst / "docs").rglob("*.md"):
        txt = md.read_text(encoding="utf-8")
        if not txt.startswith("---\n"):
            continue
        parts = txt.split("---\n", 2)
        if len(parts) != 3:
            continue
        updated_frontmatter = re.sub(
            r'(?m)^source_commit:\s*"[0-9a-f]{40}"\s*$',
            f'source_commit: "{head}"',
            parts[1],
        )
        if updated_frontmatter != parts[1]:
            replaced = "---\n" + updated_frontmatter + "---\n" + parts[2]
            c_sha = compute_canonical_document_sha256(replaced)
            replaced = re.sub(
                r'(?m)^content_sha256:\s*(?:null|"[^"]+")\s*$',
                f'content_sha256: "{c_sha}"',
                replaced,
                count=1,
            )
            md.write_text(replaced, encoding="utf-8")

    # Commit the updated docs so that docs in repo match working tree.
    subprocess.run(["git", "-C", str(dst), "add", "docs"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(dst), "commit", "-m", "update docs source commit"], capture_output=True, check=True)

    # Give this isolated fixture a local origin/main and a truthful time-bound snapshot.
    branch = subprocess.run(
        ["git", "-C", str(dst), "branch", "--show-current"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.strip()
    snapshot_head = subprocess.run(
        ["git", "-C", str(dst), "rev-parse", "HEAD"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.strip()
    snapshot_epoch = int(subprocess.run(
        ["git", "-C", str(dst), "show", "-s", "--format=%ct", "HEAD"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.strip())
    captured_at = datetime.fromtimestamp(snapshot_epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    future_commit_date = datetime.fromtimestamp(snapshot_epoch + 2, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    remote_path = dst.parent / (dst.name + "-origin.git")
    subprocess.run(["git", "init", "--bare", str(remote_path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(dst), "remote", "add", "origin", str(remote_path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(dst), "push", "origin", "HEAD:refs/heads/main"],
        capture_output=True, check=True,
    )

    def replace_section_line(
        text: str,
        section_start: str,
        section_end: Optional[str],
        line_prefix: str,
        replacement: str,
        label: str,
    ) -> str:
        lines = text.splitlines()
        starts = [i for i, line in enumerate(lines) if line.startswith(section_start)]
        if len(starts) != 1:
            raise AssertionError(f"Fixture section missing or duplicated: {label}")
        start = starts[0]
        if section_end is None:
            ends = [i for i in range(start + 1, len(lines)) if lines[i].startswith("### ")]
        else:
            ends = [i for i in range(start + 1, len(lines)) if lines[i].startswith(section_end)]
        end = ends[0] if ends else len(lines)
        matches = [i for i in range(start, end) if lines[i].startswith(line_prefix)]
        if len(matches) != 1:
            raise AssertionError(f"Fixture field missing or duplicated: {label} (count={len(matches)})")
        lines[matches[0]] = replacement
        return "\n".join(lines) + "\n"

    def refresh_frontmatter_digest(text: str) -> str:
        parts = text.split("---\n", 2)
        if len(parts) != 3:
            raise AssertionError("Fixture document frontmatter is malformed")
        metadata_lines = parts[1].splitlines()
        digest_indexes = [i for i, line in enumerate(metadata_lines) if line.startswith("content_sha256:")]
        if len(digest_indexes) != 1:
            raise AssertionError("Fixture document content_sha256 field is missing or duplicated")
        digest = compute_canonical_document_sha256(text)
        metadata_lines[digest_indexes[0]] = f'content_sha256: "{digest}"'
        return "---\n" + "\n".join(metadata_lines) + "\n---\n" + parts[2]

    tick = chr(96)
    baseline_path = dst / "docs" / "当前权威基线.md"
    baseline_text = baseline_path.read_text(encoding="utf-8")
    baseline_text = replace_section_line(
        baseline_text, "## 8. Git 分支及 Commit 身份", "## 9.",
        "- **当前分支", "- **当前分支 (" + tick + "branch" + tick + ")**：" + tick + branch + tick,
        "baseline branch",
    )
    baseline_text = replace_section_line(
        baseline_text, "## 8. Git 分支及 Commit 身份", "## 9.",
        "- **本地 HEAD", "- **本地 HEAD (" + tick + "local_head" + tick + ")**：" + tick + snapshot_head + tick,
        "baseline local_head",
    )
    baseline_text = replace_section_line(
        baseline_text, "## 8. Git 分支及 Commit 身份", "## 9.",
        "- **远端 main", "- **远端 main (" + tick + "remote_main_head" + tick + ")**：" + tick + snapshot_head + tick,
        "baseline remote_main_head",
    )
    baseline_text = replace_section_line(
        baseline_text, "### 19.3 Std-019 正式发布收口事实与治理追踪", None,
        "  7. **当前分支与 HEAD**：",
        "  7. **当前分支与 HEAD**：分支 " + tick + branch + tick + "，本地 HEAD " + tick + snapshot_head + tick + "，worktree_clean=true。",
        "baseline current branch summary",
    )
    baseline_text = replace_section_line(
        baseline_text, "### 19.3 Std-019 正式发布收口事实与治理追踪", None,
        "  9. **Git 快照观测时间**：",
        "  9. **Git 快照观测时间**：" + tick + captured_at + tick + "（快照有效时间 24 小时；过期事实标记 STALE 或 NOT_VERIFIABLE）。",
        "baseline capture time",
    )
    baseline_text = refresh_frontmatter_digest(baseline_text)
    baseline_path.write_text(baseline_text, encoding="utf-8")

    handoff_path = dst / "docs" / "CROSS-SESSION-HANDOFF.md"
    handoff_text = handoff_path.read_text(encoding="utf-8")
    handoff_lines = handoff_text.splitlines()
    capture_indexes = [i for i, line in enumerate(handoff_lines) if line.startswith("CAPTURED_AT=")]
    if len(capture_indexes) != 1:
        raise AssertionError("Fixture handoff CAPTURED_AT is missing or duplicated")
    handoff_lines[capture_indexes[0]] = f"CAPTURED_AT={captured_at}"
    handoff_text = "\n".join(handoff_lines) + "\n"
    handoff_text = replace_section_line(
        handoff_text, "## 1. 当前 Git 状态与分支身份", "## 2.",
        "- **当前分支", "- **当前分支 (" + tick + "branch" + tick + ")**：" + tick + branch + tick,
        "handoff branch",
    )
    handoff_text = replace_section_line(
        handoff_text, "## 1. 当前 Git 状态与分支身份", "## 2.",
        "- **当前快照 Commit", "- **当前快照 Commit (" + tick + "snapshot_commit" + tick + ")**：" + tick + snapshot_head + tick,
        "handoff snapshot commit",
    )
    handoff_text = replace_section_line(
        handoff_text, "## 1. 当前 Git 状态与分支身份", "## 2.",
        "- **本地 HEAD", "- **本地 HEAD (" + tick + "local_head" + tick + ")**：" + tick + snapshot_head + tick,
        "handoff local head",
    )
    handoff_text = replace_section_line(
        handoff_text, "## 1. 当前 Git 状态与分支身份", "## 2.",
        "- **远端 main", "- **远端 main (" + tick + "remote_head" + tick + ")**：" + tick + snapshot_head + tick,
        "handoff remote main",
    )
    handoff_text = refresh_frontmatter_digest(handoff_text)
    handoff_path.write_text(handoff_text, encoding="utf-8")

    subprocess.run(["git", "-C", str(dst), "add", "docs"], capture_output=True, check=True)
    commit_env = os.environ.copy()
    commit_env["GIT_AUTHOR_DATE"] = future_commit_date
    commit_env["GIT_COMMITTER_DATE"] = future_commit_date
    subprocess.run(
        ["git", "-C", str(dst), "commit", "-m", "bind Git snapshot facts to isolated fixture"],
        capture_output=True, check=True, env=commit_env,
    )
    return head



class FakeResponse:
    def __init__(self, data: dict):
        self.data = json.dumps(data).encode("utf-8")
    def read(self):
        return self.data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

class TestBaselineSyncAndApprovalGovernance(unittest.TestCase):
    # =========================================================================
    # A. Schema Tests
    # =========================================================================
    def test_a1_all_schemas_valid_and_manifest_schemas_unified(self) -> None:
        schema_files = sorted(SCHEMAS_DIR.glob("*.schema.json"))
        self.assertGreaterEqual(len(schema_files), 31)
        for sf in schema_files:
            data = json.loads(sf.read_text(encoding="utf-8"))
            jsonschema.validators.validator_for(data).check_schema(data)
        # Byte-level identity check between schemas/ and governance/
        m1 = (SCHEMAS_DIR / "engineering-manifest.schema.json").read_bytes()
        m2 = (ROOT / "governance" / "engineering-manifest-schema.json").read_bytes()
        self.assertEqual(m1, m2, "schemas/ and governance/ manifest schemas must be byte-level identical")

    def test_a2_all_12_templates_conform_to_schema(self) -> None:
        doc_schema = json.loads((SCHEMAS_DIR / "documentation-metadata.schema.json").read_text(encoding="utf-8"))
        errs = validate_templates_directory(TEMPLATES_DOC_DIR, doc_schema)
        self.assertEqual(errs, [], f"Template validation errors: {errs}")
        templates = list(TEMPLATES_DOC_DIR.glob("*.template.md"))
        self.assertEqual(len(templates), 12)

    def test_a3_positive_samples_for_all_new_schemas(self) -> None:
        # 1. standards-lock.schema.json
        lock_schema = json.loads((SCHEMAS_DIR / "standards-lock.schema.json").read_text(encoding="utf-8"))
        root_lock = json.loads((ROOT / "standards.lock.json").read_text(encoding="utf-8"))
        jsonschema.validate(instance=root_lock, schema=lock_schema)

        # 2. engineering-baseline.schema.json
        ok, errs, payload, _ = build_engineering_baseline(
            project_root=ROOT,
            standards_root=ROOT,
            observed_at="2026-11-05T10:00:00Z",
            source_commit_override=PROJECT_SOURCE_COMMIT,
        )
        self.assertTrue(ok, f"Baseline build failed: {errs}")
        eb_schema = json.loads((SCHEMAS_DIR / "engineering-baseline.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(instance=payload, schema=eb_schema)

        # 3. consumer-validation-evidence.schema.json
        evidence_schema = json.loads((SCHEMAS_DIR / "consumer-validation-evidence.schema.json").read_text(encoding="utf-8"))
        evidence_template = json.loads(
            (ROOT / "templates" / "consumer-project" / "consumer-validation-evidence.template.json").read_text(encoding="utf-8")
        )
        jsonschema.validate(instance=evidence_template, schema=evidence_schema)
        bad_evidence = dict(evidence_template)
        bad_evidence["consumer_commit"] = "short-sha"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_evidence, schema=evidence_schema)

        # 3. cross-session-handoff.schema.json
        h_ok, h_errs, h_payload, _ = build_handoff_payload(
            project_root=ROOT,
            task_id="STANDARDS-BASELINE-SYNC-GOVERNANCE-IMPLEMENTATION-001",
            version="3.0.0",
            captured_at="2026-11-05T10:00:00Z",
            source_commit_override=PROJECT_SOURCE_COMMIT,
            standards_root=ROOT,
        )
        self.assertTrue(h_ok, f"Handoff build failed: {h_errs}")
        h_schema = json.loads((SCHEMAS_DIR / "cross-session-handoff.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(instance=h_payload, schema=h_schema)

    def test_a4_negative_samples_blocked_including_historical_archive(self) -> None:
        doc_schema = json.loads((SCHEMAS_DIR / "documentation-metadata.schema.json").read_text(encoding="utf-8"))
        # HISTORICAL_ARCHIVE must be rejected as a formal document_type
        bad_hist = {
            "document_id": "DOC-HIST-001",
            "document_version": "1.0.0",
            "project_id": "ai-engineering-standards",
            "document_type": "HISTORICAL_ARCHIVE",
            "status": "ARCHIVED",
            "applies_to_release": "v2.11.0",
            "last_updated": "2026-11-05",
            "change_summary": "Legacy type test",
            "primary_entrypoint": False,
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_hist, schema=doc_schema)

        # ARCHIVED doc with primary_entrypoint=True must be rejected by schema allOf
        bad_archived_primary = dict(bad_hist)
        bad_archived_primary["document_type"] = "DECISION_RECORD"
        bad_archived_primary["primary_entrypoint"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_archived_primary, schema=doc_schema)

    # =========================================================================
    # B. Document Collection & ENGINEERING_BASELINE Tests
    # =========================================================================
    def test_b0_repository_docs_collection_passes(self) -> None:
        ok, errs = run_collection_validation(project_root=ROOT, standards_root=ROOT, check_templates=True)
        self.assertTrue(ok, f"Repository docs collection failed: {errs}")

    def test_b1_delete_document_index_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            (dst / "docs" / "DOCUMENT-INDEX.md").unlink()
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("MISSING_DOCUMENT_INDEX" in e for e in errs), f"Got: {errs}")

    def test_b2_delete_engineering_baseline_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            (dst / "docs" / "当前权威基线.md").unlink()
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("MISSING_ENGINEERING_BASELINE" in e for e in errs), f"Got: {errs}")

    def test_b3_missing_unique_primary_entrypoint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            p = dst / "docs" / "API-CONTRACT.md"
            p.write_text(p.read_text(encoding="utf-8").replace("primary_entrypoint: true", "primary_entrypoint: false"), encoding="utf-8")
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("MISSING_ACTIVE_PRIMARY_ENTRYPOINT" in e and "API_CONTRACT" in e for e in errs), f"Got: {errs}")

    def test_b4_multiple_primary_entrypoints_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            p = dst / "docs" / "API-CONTRACT.md"
            dup = dst / "docs" / "API-CONTRACT-DUP.md"
            dup.write_text(
                p.read_text(encoding="utf-8").replace("DOC-STANDARDS-API-CONTRACT", "DOC-STANDARDS-API-CONTRACT-DUP"),
                encoding="utf-8",
            )
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("MULTIPLE_ACTIVE_PRIMARY_ENTRYPOINTS" in e and "API_CONTRACT" in e for e in errs), f"Got: {errs}")

    def test_b5_broken_markdown_link_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            p = dst / "docs" / "PRODUCT-BASELINE.md"
            p.write_text(p.read_text(encoding="utf-8") + "\nSee [missing](./DOES-NOT-EXIST.md)\n", encoding="utf-8")
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("BROKEN_MARKDOWN_LINK" in e for e in errs), f"Got: {errs}")

    def test_b6_broken_markdown_anchor_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            p = dst / "docs" / "PRODUCT-BASELINE.md"
            p.write_text(p.read_text(encoding="utf-8") + "\nSee [bad anchor](./API-CONTRACT.md#non-existent-heading-xyz)\n", encoding="utf-8")
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("BROKEN_MARKDOWN_ANCHOR" in e for e in errs), f"Got: {errs}")

    def test_b7_wrong_project_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            p = dst / "docs" / "PRODUCT-BASELINE.md"
            p.write_text(
                p.read_text(encoding="utf-8").replace('project_id: "ai-engineering-standards"', 'project_id: "wrong-project-id"'),
                encoding="utf-8",
            )
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("PROJECT_ID_MISMATCH" in e for e in errs), f"Got: {errs}")

    def test_b8_archived_doc_marked_as_primary_entrypoint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            arch_dir = dst / "docs" / "archive" / "v2.11.0"
            arch_dir.mkdir(parents=True, exist_ok=True)
            p = dst / "docs" / "DECISION-RECORD.md"
            arch_file = arch_dir / "OLD-DECISION.md"
            arch_file.write_text(
                p.read_text(encoding="utf-8")
                .replace("DOC-STANDARDS-DECISION-RECORD", "DOC-OLD-DECISION")
                .replace('status: "ACTIVE"', 'status: "ARCHIVED"'),
                encoding="utf-8",
            )
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("ARCHIVED_DOC_CANNOT_BE_PRIMARY" in e for e in errs), f"Got: {errs}")

    def test_b9_missing_approval_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            p = dst / "docs" / "PRODUCT-BASELINE.md"
            from tools.validate_approval_contract import compute_canonical_document_sha256
            txt = (
                p.read_text(encoding="utf-8")
                .replace('approval_status: "IN_REVIEW"', 'approval_status: "OWNER_APPROVED"')
                .replace('status: "IN_REVIEW"', 'status: "ACTIVE"')
            )
            c_sha = compute_canonical_document_sha256(txt)
            txt = re.sub(r'content_sha256:\s*"[^"]+"', f'content_sha256: "{c_sha}"', txt)
            p.write_text(txt, encoding="utf-8")
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("MISSING_APPROVAL_EVIDENCE" in e for e in errs), f"Got: {errs}")

    def test_b10_inconsistent_or_unverifiable_source_commit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            # Create a second commit in dst so it is verifiable in git but mismatches other docs
            (dst / "VERSION").write_text("3.0.1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(dst), "add", "VERSION"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(dst), "commit", "-m", "second"], capture_output=True, check=True)
            second_head = subprocess.run(
                ["git", "-C", str(dst), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            ).stdout.strip()
            p = dst / "docs" / "PRODUCT-BASELINE.md"
            txt = p.read_text(encoding="utf-8")
            import re
            txt = re.sub(r'source_commit: "[0-9a-f]{40}"', f'source_commit: "{second_head}"', txt)
            p.write_text(txt, encoding="utf-8")
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("SOURCE_COMMIT_MISMATCH" in e for e in errs), f"Got: {errs}")

    def test_b11_engineering_baseline_deterministic_and_conflict_blocked(self) -> None:
        # 1. Determinism across different timestamps
        ok1, _, p1, _ = build_engineering_baseline(
            project_root=ROOT,
            standards_root=ROOT,
            observed_at="2026-11-05T08:00:00Z",
            source_commit_override=PROJECT_SOURCE_COMMIT,
        )
        ok2, _, p2, _ = build_engineering_baseline(
            project_root=ROOT,
            standards_root=ROOT,
            observed_at="2026-11-05T19:59:59Z",
            source_commit_override=PROJECT_SOURCE_COMMIT,
        )
        self.assertTrue(ok1 and ok2)
        assert p1 is not None and p2 is not None
        self.assertEqual(p1["content_sha256"], p2["content_sha256"])

        # 2. Source conflict blocks generation
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            # Introduce version conflict between standards.lock.json and engineering-manifest.yaml
            lk = json.loads((dst / "standards.lock.json").read_text(encoding="utf-8"))
            lk["version"] = "9.9.9"
            (dst / "standards.lock.json").write_text(json.dumps(lk), encoding="utf-8")
            ok_conflict, c_errs, _, _ = build_engineering_baseline(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok_conflict)
            self.assertTrue(any("BASELINE_CONFLICT_STANDARDS_VERSION" in e for e in c_errs), f"Got: {c_errs}")

        # 3. Verify semantic negative checks on baseline
        baseline_fixture = """
## 9. 最近 CI 事实
- **核验状态 (`verification_status`)**：`PASS`
- 1. 基线生成源 Commit (`source_commit`)：`9687f961b22df612c4311961e06fc1c1fd508c37`
- 3. 最近一次已验证 CI Commit (`last_verified_ci_commit`)：`4538b8ba29cb9413782c4197e73bddab64849d82`
- 4. 代码候选 Commit (`candidate_commit`)：`60a03bc1ca03e03ad1e88f3036ec06bcbe748837`
- 5. 文档快照 Commit (`snapshot_commit`)：`4538b8ba29cb9413782c4197e73bddab64849d82`
- 事实说明：PR CI 已通过 (Run: 42783497089 Push / 42783504258 PR #9 双平台 PASS, 216 tests)，等待合并及 main CI 和 Tag 重建

## 19. 当前候选状态与消费端试点
  - 远端旧 Tag v3.0.0 已删除 (OLD_TAG_DELETED=true)，新 Tag 尚未创建。
  3. **最近一次已经验证的 CI Commit (`last_verified_ci_commit`)**：`4538b8ba29cb9413782c4197e73bddab64849d82`（Run 42783497089 Push / Run 42783504258 PR #9 双平台全绿，216 tests PASS）。
  4. **代码候选 Commit (`code_candidate_commit`)**：`60a03bc1ca03e03ad1e88f3036ec06bcbe748837`
  PR 状态：DRAFT
  发布流程状态：IN_PROGRESS
"""
        # Negative 1: Old CI Run ID fails
        self.assertTrue(bool(verify_baseline_semantic_facts(baseline_fixture, {"ci_run_id": "42772211734"})))
        # Negative 2: Wrong CI Commit fails
        self.assertTrue(bool(verify_baseline_semantic_facts(baseline_fixture, {"ci_commit": "1111111111111111111111111111111111111111"})))
        # Negative 3: PASS changed to NOT_VERIFIABLE fails
        self.assertTrue(bool(verify_baseline_semantic_facts(baseline_fixture, {"ci_status": "NOT_VERIFIABLE"})))
        # Negative 4: 216 tests changed to 215 tests fails
        self.assertTrue(bool(verify_baseline_semantic_facts(baseline_fixture, {"test_count": 215})))
        # Negative 5: Old candidate commit fails
        self.assertTrue(bool(verify_baseline_semantic_facts(baseline_fixture, {"candidate_commit": "c52f97a52c9080bc76e05684f996fd89653e1fa8"})))
        # Negative 6: Old tag status changed to not deleted fails
        self.assertTrue(bool(verify_baseline_semantic_facts(baseline_fixture, {"old_tag_deleted": False})))

    def test_b12_release_evidence_verify_only_integrity_and_12_cli_negative_checks(self) -> None:
        """STD-034 / STD-035: Comprehensive verification of release evidence single-source
        and 12 real CLI negative checks + proof test against self-proving markdown modification.
        """
        evidence_file = ROOT / "docs" / "release-evidence" / "v3.0.0-reissue.json"
        self.assertTrue(evidence_file.exists(), f"Evidence file missing: {evidence_file}")
        valid_ev_data = json.loads(evidence_file.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)

            # --- Negative 1: Missing evidence file blocks verify-only ---
            non_existent_ev = tmp / "missing-evidence.json"
            res = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "generate_engineering_baseline.py"), "--project-root", str(ROOT), "--release-evidence", str(non_existent_ev), "--verify-only"],
                capture_output=True, text=True, encoding="utf-8"
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("RELEASE_EVIDENCE_NOT_FOUND", res.stdout + res.stderr)

            res_h = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "generate_handoff.py"), "--project-root", str(ROOT), "--release-evidence", str(non_existent_ev), "--verify-only"],
                capture_output=True, text=True, encoding="utf-8"
            )
            self.assertNotEqual(res_h.returncode, 0)
            self.assertIn("RELEASE_EVIDENCE_NOT_FOUND", res_h.stdout + res_h.stderr)

            # --- Negative 2: Corrupted evidence JSON blocks verify-only ---
            corrupt_ev = tmp / "corrupt-evidence.json"
            corrupt_ev.write_text("{bad_json: True", encoding="utf-8")
            res_c = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "generate_engineering_baseline.py"), "--project-root", str(ROOT), "--release-evidence", str(corrupt_ev), "--verify-only"],
                capture_output=True, text=True, encoding="utf-8"
            )
            self.assertNotEqual(res_c.returncode, 0)
            self.assertIn("RELEASE_EVIDENCE_CORRUPT", res_c.stdout + res_c.stderr)

            # Helper to run CLI with modified evidence
            def run_baseline_with_evidence(mod_ev: Dict[str, Any]) -> subprocess.CompletedProcess:
                p = tmp / "test-ev.json"
                p.write_text(json.dumps(mod_ev, ensure_ascii=False), encoding="utf-8")
                return subprocess.run(
                    [sys.executable, str(ROOT / "tools" / "generate_engineering_baseline.py"), "--project-root", str(ROOT), "--release-evidence", str(p), "--verify-only"],
                    capture_output=True, text=True, encoding="utf-8"
                )

            # --- Negative 3: Old Push Run ID fails ---
            ev3 = dict(valid_ev_data, push_run_id="42772211734")
            res3 = run_baseline_with_evidence(ev3)
            self.assertNotEqual(res3.returncode, 0)
            self.assertTrue("ci_run_id" in res3.stdout or "push_run_id" in res3.stdout)

            # --- Negative 4: Old PR Run ID fails ---
            ev4 = dict(valid_ev_data, pr_run_id="42772217074")
            res4 = run_baseline_with_evidence(ev4)
            self.assertNotEqual(res4.returncode, 0)
            self.assertIn("pr_run_id", res4.stdout)

            # --- Negative 5: Wrong CI Commit fails ---
            ev5 = dict(valid_ev_data, last_verified_ci_commit="e187b498faf376170b5c11d46377398be988fb38")
            res5 = run_baseline_with_evidence(ev5)
            self.assertNotEqual(res5.returncode, 0)
            self.assertIn("last_verified_ci_commit", res5.stdout)

            # --- Negative 6: Wrong Candidate Commit fails ---
            ev6 = dict(valid_ev_data, candidate_commit="c52f97a52c9080bc76e05684f996fd89653e1fa8")
            res6 = run_baseline_with_evidence(ev6)
            self.assertNotEqual(res6.returncode, 0)
            self.assertIn("candidate_commit", res6.stdout)

            # --- Negative 7: PASS changed to NOT_VERIFIABLE fails ---
            ev7 = dict(valid_ev_data, ci_status="NOT_VERIFIABLE")
            res7 = run_baseline_with_evidence(ev7)
            self.assertNotEqual(res7.returncode, 0)
            self.assertTrue("ci_status" in res7.stdout or "ci verification_status" in res7.stdout)

            # --- Negative 8: 216 tests changed to 215 tests fails ---
            ev8 = dict(valid_ev_data, test_count=215 if valid_ev_data.get("test_count") != 215 else 214)
            res8 = run_baseline_with_evidence(ev8)
            self.assertNotEqual(res8.returncode, 0)
            self.assertTrue("test_count" in res8.stdout or "test count" in res8.stdout)

            # --- Negative 9: Windows Job failed in CI check ---
            sim_windows_fail = {
                "id": int(valid_ev_data["push_run_id"]),
                "name": "Standards CI",
                "headSha": valid_ev_data["last_verified_ci_commit"],
                "event": "push",
                "status": "completed",
                "conclusion": "failure",
                "path": ".github/workflows/standards-ci.yml",
                "head_branch": "feat/standards-baseline-sync-governance",
                "repository": {"full_name": valid_ev_data["repository"]},
                "jobs": [
                    {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "success"},
                    {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "failure"},
                ],
            }
            st9, errs9, _ = verify_single_github_run(
                repo=valid_ev_data["repository"],
                run_id=valid_ev_data["push_run_id"],
                expected_event="push",
                expected_head_sha=valid_ev_data["last_verified_ci_commit"],
                simulate_data=sim_windows_fail,
            )
            self.assertEqual(st9, "FAIL")
            self.assertTrue(any("Windows job conclusion" in e for e in errs9))

            # --- Negative 10: Ubuntu Job failed in CI check ---
            sim_ubuntu_fail = {
                "id": int(valid_ev_data["push_run_id"]),
                "name": "Standards CI",
                "headSha": valid_ev_data["last_verified_ci_commit"],
                "event": "push",
                "status": "completed",
                "conclusion": "failure",
                "path": ".github/workflows/standards-ci.yml",
                "head_branch": "feat/standards-baseline-sync-governance",
                "repository": {"full_name": valid_ev_data["repository"]},
                "jobs": [
                    {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "failure"},
                    {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "success"},
                ],
            }
            st10, errs10, _ = verify_single_github_run(
                repo=valid_ev_data["repository"],
                run_id=valid_ev_data["push_run_id"],
                expected_event="push",
                expected_head_sha=valid_ev_data["last_verified_ci_commit"],
                simulate_data=sim_ubuntu_fail,
            )
            self.assertEqual(st10, "FAIL")
            self.assertTrue(any("Ubuntu job conclusion" in e for e in errs10))

            # --- Negative 11: Wrong PR status fails ---
            wrong_st = "DRAFT" if valid_ev_data.get("pr_status") == "MERGED" else "MERGED"
            ev11 = dict(valid_ev_data, pr_status=wrong_st)
            res11 = run_baseline_with_evidence(ev11)
            self.assertNotEqual(res11.returncode, 0)
            self.assertIn("pr_status", res11.stdout)

            # --- Negative 12: OLD_TAG_DELETED wrong fails ---
            ev12 = dict(valid_ev_data, old_tag_deleted=False)
            res12 = run_baseline_with_evidence(ev12)
            self.assertNotEqual(res12.returncode, 0)
            self.assertTrue("old_tag_deleted" in res12.stdout or "OLD_TAG_DELETED" in res12.stdout)

            # --- Proof Test: Modifying Commit or Run ID in markdown under test STILL FAILS ---
            # Even if content_sha256 is correctly recalculated!
            from tools.validate_approval_contract import compute_canonical_document_sha256

            # Modify baseline markdown: tamper push run id
            base_md = (ROOT / "docs" / "当前权威基线.md").read_text(encoding="utf-8")
            tampered_base_md = base_md.replace(str(valid_ev_data["push_run_id"]), "42772211734")
            new_sha_base = compute_canonical_document_sha256(tampered_base_md)
            tampered_base_md = re.sub(r'content_sha256:\s*"[^"]+"', f'content_sha256: "{new_sha_base}"', tampered_base_md)
            tampered_base_path = tmp / "tampered_baseline.md"
            tampered_base_path.write_text(tampered_base_md, encoding="utf-8")

            res_tamper_b = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "generate_engineering_baseline.py"), "--project-root", str(ROOT), "--output", str(tampered_base_path), "--verify-only"],
                capture_output=True, text=True, encoding="utf-8"
            )
            self.assertNotEqual(res_tamper_b.returncode, 0, "Tampered baseline MUST fail verify-only even with matching content_sha256")
            self.assertIn("mismatches", res_tamper_b.stdout)

            # Modify handoff markdown: tamper CI commit
            handoff_md = (ROOT / "docs" / "CROSS-SESSION-HANDOFF.md").read_text(encoding="utf-8")
            tampered_h_md = handoff_md.replace(valid_ev_data["last_verified_ci_commit"], "e187b498faf376170b5c11d46377398be988fb38")
            new_sha_h = compute_canonical_document_sha256(tampered_h_md)
            tampered_h_md = re.sub(r'content_sha256:\s*"[^"]+"', f'content_sha256: "{new_sha_h}"', tampered_h_md)
            tampered_h_path = tmp / "CROSS-SESSION-HANDOFF.md"
            tampered_h_path.write_text(tampered_h_md, encoding="utf-8")

            # Verify tampered handoff against project root fails verify-only
            res_tamper_h = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "generate_handoff.py"), "--project-root", str(ROOT), "--output", str(tampered_h_path), "--verify-only"],
                capture_output=True, text=True, encoding="utf-8"
            )
            self.assertNotEqual(res_tamper_h.returncode, 0, "Tampered handoff MUST fail verify-only even with matching content_sha256")
            self.assertIn("mismatches", res_tamper_h.stdout)

    def test_b13_github_ci_authenticity_gate_12_negative_tests(self) -> None:
        """STD-014 / STD-034: 12 negative authenticity tests proving all identity mismatches,
        incomplete runs, failed conclusions, missing/failed jobs, and API unreachability
        can NEVER return PASS.
        """
        canonical_repo = "xiefeifeihu/AI-Engineering-Standards"
        canonical_push_id = "42800374434"
        canonical_pr_id = "42800383714"
        canonical_head_sha = "70f7554feacfaa6c61b0fa571454f468aaa6d844"
        canonical_branch = "feat/standards-baseline-sync-governance"
        canonical_path = ".github/workflows/standards-ci.yml"

        base_push_data = {
            "id": int(canonical_push_id),
            "name": "Standards Schema Validation & Governance CI (STD-034)",
            "head_sha": canonical_head_sha,
            "headSha": canonical_head_sha,
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "path": canonical_path,
            "head_branch": canonical_branch,
            "headBranch": canonical_branch,
            "repository": {"full_name": canonical_repo, "name": "AI-Engineering-Standards"},
            "jobs": [
                {
                    "name": "Validate Schemas, Docs, Baseline, Handoff, Sync & Approval Contracts (ubuntu-latest)",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": "Validate Schemas, Docs, Baseline, Handoff, Sync & Approval Contracts (windows-latest)",
                    "status": "completed",
                    "conclusion": "success",
                },
            ],
        }

        base_pr_data = {
            "id": int(canonical_pr_id),
            "name": "Standards Schema Validation & Governance CI (STD-034)",
            "head_sha": canonical_head_sha,
            "headSha": canonical_head_sha,
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "path": canonical_path,
            "head_branch": canonical_branch,
            "headBranch": canonical_branch,
            "repository": {"full_name": canonical_repo, "name": "AI-Engineering-Standards"},
            "pull_requests": [
                {
                    "number": 9,
                    "head": {"ref": canonical_branch, "sha": canonical_head_sha},
                    "base": {"ref": "main", "sha": "1d5cbbd6710bef749c8f79e9c1fd21dd14223b1b"},
                }
            ],
            "jobs": [
                {
                    "name": "Validate Schemas, Docs, Baseline, Handoff, Sync & Approval Contracts (ubuntu-latest)",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": "Validate Schemas, Docs, Baseline, Handoff, Sync & Approval Contracts (windows-latest)",
                    "status": "completed",
                    "conclusion": "success",
                },
            ],
        }

        # 1. Repository 不匹配
        sim1 = dict(base_push_data, repository={"full_name": "attacker/AI-Engineering-Standards"})
        st1, errs1, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim1,
        )
        self.assertEqual(st1, "FAIL")
        self.assertNotEqual(st1, "PASS")
        self.assertTrue(any("repository mismatch" in e.lower() for e in errs1))

        # 2. Run ID 不匹配
        sim2 = dict(base_push_data, id=99999999999)
        st2, errs2, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim2,
        )
        self.assertEqual(st2, "FAIL")
        self.assertNotEqual(st2, "PASS")
        self.assertTrue(any("id mismatch" in e.lower() for e in errs2))

        # 3. Workflow path 不匹配
        sim3 = dict(base_push_data, path=".github/workflows/untrusted-other.yml")
        st3, errs3, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim3,
        )
        self.assertEqual(st3, "FAIL")
        self.assertNotEqual(st3, "PASS")
        self.assertTrue(any("workflow path mismatch" in e.lower() for e in errs3))

        # 4. Event 不匹配
        sim4 = dict(base_push_data, event="workflow_dispatch")
        st4, errs4, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim4,
        )
        self.assertEqual(st4, "FAIL")
        self.assertNotEqual(st4, "PASS")
        self.assertTrue(any("event mismatch" in e.lower() for e in errs4))

        # 5. head_sha 不匹配
        sim5 = dict(base_push_data, head_sha="1111111111111111111111111111111111111111", headSha="1111111111111111111111111111111111111111")
        st5, errs5, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim5,
        )
        self.assertEqual(st5, "FAIL")
        self.assertNotEqual(st5, "PASS")
        self.assertTrue(any("head_sha mismatch" in e.lower() for e in errs5))

        # 6. PR number 不匹配
        sim6 = dict(base_pr_data, pull_requests=[{"number": 999, "head": {"ref": canonical_branch}, "base": {"ref": "main"}}])
        st6, errs6, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_pr_id,
            expected_event="pull_request",
            expected_head_sha=canonical_head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            simulate_data=sim6,
        )
        self.assertEqual(st6, "FAIL")
        self.assertNotEqual(st6, "PASS")
        self.assertTrue(any("pr number mismatch" in e.lower() for e in errs6))

        # 7. base branch 不匹配
        sim7 = dict(base_pr_data, pull_requests=[{"number": 9, "head": {"ref": canonical_branch}, "base": {"ref": "release-v2"}}])
        st7, errs7, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_pr_id,
            expected_event="pull_request",
            expected_head_sha=canonical_head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            simulate_data=sim7,
        )
        self.assertEqual(st7, "FAIL")
        self.assertNotEqual(st7, "PASS")
        self.assertTrue(any("base ref mismatch" in e.lower() for e in errs7))

        # 8. Run 未完成
        sim8 = dict(base_push_data, status="in_progress")
        st8, errs8, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim8,
        )
        self.assertEqual(st8, "FAIL")
        self.assertNotEqual(st8, "PASS")
        self.assertTrue(any("status was 'in_progress'" in e.lower() for e in errs8))

        # 9. Run conclusion 失败
        sim9 = dict(base_push_data, conclusion="failure")
        st9, errs9, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim9,
        )
        self.assertEqual(st9, "FAIL")
        self.assertNotEqual(st9, "PASS")
        self.assertTrue(any("conclusion was 'failure'" in e.lower() for e in errs9))

        # 10. Ubuntu Job 缺失或失败
        # 10a: 缺失
        sim10a = dict(base_push_data, jobs=[{"name": "Validate (windows-latest)", "status": "completed", "conclusion": "success"}])
        st10a, errs10a, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim10a,
        )
        self.assertEqual(st10a, "FAIL")
        self.assertNotEqual(st10a, "PASS")
        self.assertTrue(any("missing ubuntu" in e.lower() for e in errs10a))

        # 10b: 失败
        sim10b = dict(base_push_data, jobs=[
            {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "failure"},
            {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "success"},
        ])
        st10b, errs10b, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim10b,
        )
        self.assertEqual(st10b, "FAIL")
        self.assertNotEqual(st10b, "PASS")
        self.assertTrue(any("ubuntu job conclusion was 'failure'" in e.lower() for e in errs10b))

        # 11. Windows Job 缺失或失败
        # 11a: 缺失
        sim11a = dict(base_push_data, jobs=[{"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "success"}])
        st11a, errs11a, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim11a,
        )
        self.assertEqual(st11a, "FAIL")
        self.assertNotEqual(st11a, "PASS")
        self.assertTrue(any("missing windows" in e.lower() for e in errs11a))

        # 11b: 失败
        sim11b = dict(base_push_data, jobs=[
            {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "success"},
            {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "failure"},
        ])
        st11b, errs11b, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=canonical_push_id,
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            expected_head_branch=canonical_branch,
            simulate_data=sim11b,
        )
        self.assertEqual(st11b, "FAIL")
        self.assertNotEqual(st11b, "PASS")
        self.assertTrue(any("windows job conclusion was 'failure'" in e.lower() for e in errs11b))

        # 12. API 不可达 (网络异常/无权限/离线)
        st12, errs12, meta12 = verify_single_github_run(
            repo="unreachable/repo",
            run_id="00000000",
            expected_event="push",
            expected_head_sha=canonical_head_sha,
            timeout=1,
            simulate_data=None,
        )
        self.assertEqual(st12, "NOT_VERIFIABLE")
        self.assertNotEqual(st12, "PASS")
        self.assertTrue(any("not accessible" in e.lower() for e in errs12))
        self.assertNotIn("ghp_", str(meta12))
        self.assertNotIn("ghs_", str(meta12))

    def test_b14_github_ci_runs_main_workflow_branch_binding_and_regression_tests(self) -> None:
        """STD-015 / STD-034: Verify push_head_branch binding under main workflow context,
        proving main CI no longer mistakenly requires historical feature branch Push Run to be on main,
        and regression tests for all 11 failure/offline paths on verify_github_ci_runs().
        """
        canonical_repo = "xiefeifeihu/AI-Engineering-Standards"
        push_id = "42835602231"
        pr_id = "42835611644"
        head_sha = "18a71b920c0dc162ae4f4c1ce35aad901bdba9d2"
        feat_branch = "feat/standards-baseline-sync-governance"
        workflow_path = ".github/workflows/standards-ci.yml"

        valid_evidence = {
            "repository": canonical_repo,
            "version": "3.0.0",
            "pr_number": 9,
            "pr_status": "DRAFT",
            "main_head": "1d5cbbd6710bef749c8f79e9c1fd21dd14223b1b",
            "candidate_commit": head_sha,
            "snapshot_commit": head_sha,
            "last_verified_ci_commit": head_sha,
            "push_run_id": push_id,
            "push_head_branch": feat_branch,
            "pr_run_id": pr_id,
            "ci_status": "PASS",
            "test_count": 218,
            "test_failed": 0,
            "test_skipped": 0,
            "windows_status": "PASS",
            "ubuntu_status": "PASS",
            "old_tag_deleted": True,
            "old_tag_object": "325008af90a1e6dcc88ff714c9ec4e7ecee86ec6",
            "old_tag_peeled_commit": "1d5cbbd6710bef749c8f79e9c1fd21dd14223b1b",
            "old_tag_bundle_sha256": "45bc3e455fc06b96a669ba9d7c44195f5dfb4e42e55397d795200942e434ebfc",
            "release_flow_status": "IN_PROGRESS",
            "task_id": "Std-015-V3-0-0-REISSUE-MAIN-CI-BRANCH-BINDING",
        }

        base_push_sim = {
            "id": int(push_id),
            "name": "Standards Schema Validation & Governance CI (STD-034)",
            "head_sha": head_sha,
            "headSha": head_sha,
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "path": workflow_path,
            "head_branch": feat_branch,
            "headBranch": feat_branch,
            "repository": {"full_name": canonical_repo, "name": "AI-Engineering-Standards"},
            "jobs": [
                {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "success"},
                {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "success"},
            ],
        }

        base_pr_sim = {
            "id": int(pr_id),
            "name": "Standards Schema Validation & Governance CI (STD-034)",
            "head_sha": head_sha,
            "headSha": head_sha,
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "path": workflow_path,
            "head_branch": feat_branch,
            "headBranch": feat_branch,
            "repository": {"full_name": canonical_repo, "name": "AI-Engineering-Standards"},
            "pull_requests": [
                {
                    "number": 9,
                    "head": {"ref": feat_branch, "sha": head_sha},
                    "base": {"ref": "main", "sha": "1d5cbbd6710bef749c8f79e9c1fd21dd14223b1b"},
                }
            ],
            "jobs": [
                {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "success"},
                {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "success"},
            ],
        }

        sim_map = {push_id: base_push_sim, pr_id: base_pr_sim}

        # --- Primary Test: GITHUB_REF_NAME=main context ---
        # When workflow runs on main, historical Push Run has head_branch=feat/standards-baseline-sync-governance
        # Expected: PASS (proving main workflow no longer mistakenly requires historical Push Run to be on main)
        orig_ref_name = os.environ.get("GITHUB_REF_NAME")
        orig_head_ref = os.environ.get("GITHUB_HEAD_REF")
        try:
            os.environ["GITHUB_REF_NAME"] = "main"
            os.environ["GITHUB_HEAD_REF"] = ""
            st_main, errs_main, meta_main = verify_github_ci_runs(valid_evidence, simulate_data_map=sim_map)
            self.assertEqual(st_main, "PASS", f"main workflow context verification must PASS, got: {errs_main}")
            self.assertEqual(errs_main, [])
            self.assertEqual(meta_main["push_head_branch"], feat_branch)
        finally:
            if orig_ref_name is not None:
                os.environ["GITHUB_REF_NAME"] = orig_ref_name
            else:
                os.environ.pop("GITHUB_REF_NAME", None)
            if orig_head_ref is not None:
                os.environ["GITHUB_HEAD_REF"] = orig_head_ref
            else:
                os.environ.pop("GITHUB_HEAD_REF", None)

        # --- 1. push_head_branch 缺失 -> FAIL ---
        ev_no_branch = dict(valid_evidence)
        del ev_no_branch["push_head_branch"]
        st1, errs1, _ = verify_github_ci_runs(ev_no_branch, simulate_data_map=sim_map)
        self.assertEqual(st1, "FAIL")
        self.assertTrue(any("push_head_branch" in e.lower() for e in errs1))

        # --- 2. push_head_branch 错误 (空串/None) -> FAIL ---
        ev_empty_branch = dict(valid_evidence, push_head_branch="")
        st2, errs2, _ = verify_github_ci_runs(ev_empty_branch, simulate_data_map=sim_map)
        self.assertEqual(st2, "FAIL")
        self.assertTrue(any("push_head_branch" in e.lower() for e in errs2))

        # --- 3. 实际 Push Run 分支与证据不一致 -> FAIL ---
        sim_push_wrong_branch = dict(base_push_sim, head_branch="feat/other-unrelated-branch", headBranch="feat/other-unrelated-branch")
        sim_map_wrong_branch = {push_id: sim_push_wrong_branch, pr_id: base_pr_sim}
        st3, errs3, _ = verify_github_ci_runs(valid_evidence, simulate_data_map=sim_map_wrong_branch)
        self.assertEqual(st3, "FAIL")
        self.assertTrue(any("head_branch mismatch" in e.lower() for e in errs3))

        # --- 4. PR #9 错误 -> FAIL ---
        sim_pr_wrong_num = dict(base_pr_sim, pull_requests=[{"number": 999, "head": {"ref": feat_branch}, "base": {"ref": "main"}}])
        sim_map_wrong_pr = {push_id: base_push_sim, pr_id: sim_pr_wrong_num}
        st4, errs4, _ = verify_github_ci_runs(valid_evidence, simulate_data_map=sim_map_wrong_pr)
        self.assertEqual(st4, "FAIL")
        self.assertTrue(any("pr number mismatch" in e.lower() for e in errs4))

        # --- 5. PR base 非 main -> FAIL ---
        sim_pr_wrong_base = dict(base_pr_sim, pull_requests=[{"number": 9, "head": {"ref": feat_branch}, "base": {"ref": "develop"}}])
        sim_map_wrong_base = {push_id: base_push_sim, pr_id: sim_pr_wrong_base}
        st5, errs5, _ = verify_github_ci_runs(valid_evidence, simulate_data_map=sim_map_wrong_base)
        self.assertEqual(st5, "FAIL")
        self.assertTrue(any("base ref mismatch" in e.lower() for e in errs5))

        # --- 6. Workflow path 错误 -> FAIL ---
        sim_push_wrong_path = dict(base_push_sim, path=".github/workflows/other.yml")
        sim_map_wrong_path = {push_id: sim_push_wrong_path, pr_id: base_pr_sim}
        st6, errs6, _ = verify_github_ci_runs(valid_evidence, simulate_data_map=sim_map_wrong_path)
        self.assertEqual(st6, "FAIL")
        self.assertTrue(any("workflow path mismatch" in e.lower() for e in errs6))

        # --- 7. Repository 错误 -> FAIL ---
        sim_push_wrong_repo = dict(base_push_sim, repository={"full_name": "malicious/AI-Engineering-Standards"})
        sim_map_wrong_repo = {push_id: sim_push_wrong_repo, pr_id: base_pr_sim}
        st7, errs7, _ = verify_github_ci_runs(valid_evidence, simulate_data_map=sim_map_wrong_repo)
        self.assertEqual(st7, "FAIL")
        self.assertTrue(any("repository mismatch" in e.lower() for e in errs7))

        # --- 8. Run 未完成 -> FAIL ---
        sim_push_in_progress = dict(base_push_sim, status="in_progress")
        sim_map_in_progress = {push_id: sim_push_in_progress, pr_id: base_pr_sim}
        st8, errs8, _ = verify_github_ci_runs(valid_evidence, simulate_data_map=sim_map_in_progress)
        self.assertEqual(st8, "FAIL")
        self.assertTrue(any("status was 'in_progress'" in e.lower() for e in errs8))

        # --- 9. Ubuntu Job 失败 -> FAIL ---
        sim_push_ubuntu_fail = dict(base_push_sim, jobs=[
            {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "failure"},
            {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "success"},
        ])
        sim_map_u_fail = {push_id: sim_push_ubuntu_fail, pr_id: base_pr_sim}
        st9, errs9, _ = verify_github_ci_runs(valid_evidence, simulate_data_map=sim_map_u_fail)
        self.assertEqual(st9, "FAIL")
        self.assertTrue(any("ubuntu job conclusion was 'failure'" in e.lower() for e in errs9))

        # --- 10. Windows Job 失败 -> FAIL ---
        sim_push_windows_fail = dict(base_push_sim, jobs=[
            {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "success"},
            {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "failure"},
        ])
        sim_map_w_fail = {push_id: sim_push_windows_fail, pr_id: base_pr_sim}
        st10, errs10, _ = verify_github_ci_runs(valid_evidence, simulate_data_map=sim_map_w_fail)
        self.assertEqual(st10, "FAIL")
        self.assertTrue(any("windows job conclusion was 'failure'" in e.lower() for e in errs10))

        # --- 11. API 不可达 -> NOT_VERIFIABLE ---
        ev_unreachable = dict(valid_evidence, push_run_id="99999999999", pr_run_id="99999999998")
        st11, errs11, _ = verify_github_ci_runs(ev_unreachable, timeout=1, simulate_data_map=None)
        self.assertEqual(st11, "NOT_VERIFIABLE")
        self.assertTrue(any("not accessible" in e.lower() for e in errs11))

    def test_b15_merged_pr_run_fallback_and_pr_identity_binding(self) -> None:
        """STD-016 / STD-034: Verification of historical PR Run fallback when pull_requests is empty,
        6-point identity verification contract against GitHub PR API, and real main workflow CLI integration.
        """
        canonical_repo = "xiefeifeihu/AI-Engineering-Standards"
        push_id = "42843755347"
        pr_id = "42843964061"
        head_sha = "336114861b2c720106a6076956eef08c9cd6ded7"
        feat_branch = "feat/standards-baseline-sync-governance"
        workflow_path = ".github/workflows/standards-ci.yml"

        valid_evidence = {
            "repository": canonical_repo,
            "version": "3.0.0",
            "pr_number": 9,
            "pr_status": "MERGED",
            "main_head": "3cd42b69049b148bceea1324d4f8212393cb96df",
            "candidate_commit": head_sha,
            "snapshot_commit": head_sha,
            "last_verified_ci_commit": head_sha,
            "push_run_id": push_id,
            "push_head_branch": feat_branch,
            "pr_run_id": pr_id,
            "ci_status": "PASS",
            "test_count": 219,
            "test_failed": 0,
            "test_skipped": 0,
            "windows_status": "PASS",
            "ubuntu_status": "PASS",
            "old_tag_deleted": True,
            "old_tag_object": "325008af90a1e6dcc88ff714c9ec4e7ecee86ec6",
            "old_tag_peeled_commit": "1d5cbbd6710bef749c8f79e9c1fd21dd14223b1b",
            "old_tag_bundle_sha256": "45bc3e455fc06b96a669ba9d7c44195f5dfb4e42e55397d795200942e434ebfc",
            "release_flow_status": "IN_PROGRESS",
            "task_id": "Std-016-V3-0-0-REISSUE-MERGED-PR-RUN-FALLBACK",
        }

        base_push_sim = {
            "id": int(push_id),
            "name": "Standards Schema Validation & Governance CI (STD-034)",
            "head_sha": head_sha,
            "headSha": head_sha,
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "path": workflow_path,
            "head_branch": feat_branch,
            "headBranch": feat_branch,
            "repository": {"full_name": canonical_repo, "name": "AI-Engineering-Standards"},
            "jobs": [
                {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "success"},
                {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "success"},
            ],
        }

        # PR Run with empty pull_requests (merged PR simulation)
        base_pr_sim_empty = {
            "id": int(pr_id),
            "name": "Standards Schema Validation & Governance CI (STD-034)",
            "head_sha": head_sha,
            "headSha": head_sha,
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "path": workflow_path,
            "head_branch": feat_branch,
            "headBranch": feat_branch,
            "pull_requests": [],
            "repository": {"full_name": canonical_repo, "name": "AI-Engineering-Standards"},
            "jobs": [
                {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "success"},
                {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "success"},
            ],
        }

        # Valid PR API response
        valid_pr_api_data = {
            "number": 9,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-11-11T00:44:16Z",
            "base": {"ref": "main"},
            "head": {"ref": feat_branch, "sha": head_sha},
        }

        # 1. PR OPEN 且 Run.pull_requests 正常存在：PASS
        pr_sim_open = dict(
            base_pr_sim_empty,
            pull_requests=[{"number": 9, "head": {"ref": feat_branch}, "base": {"ref": "main"}}],
        )
        st1, errs1, meta1 = verify_single_github_run(
            repo=canonical_repo,
            run_id=pr_id,
            expected_event="pull_request",
            expected_head_sha=head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            expected_pr_status="OPEN",
            simulate_data=pr_sim_open,
        )
        self.assertEqual(st1, "PASS")
        self.assertEqual(errs1, [])
        self.assertFalse(meta1.get("pr_fallback_verified", False))

        # 2. PR MERGED 且 Run.pull_requests 为空：使用 PR API fallback，PASS
        st2, errs2, meta2 = verify_single_github_run(
            repo=canonical_repo,
            run_id=pr_id,
            expected_event="pull_request",
            expected_head_sha=head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            expected_pr_status="MERGED",
            simulate_data=base_pr_sim_empty,
            simulate_pr_data=valid_pr_api_data,
        )
        self.assertEqual(st2, "PASS")
        self.assertEqual(errs2, [])
        self.assertTrue(meta2.get("pr_fallback_verified"))
        self.assertEqual(meta2.get("actual_pr_number"), 9)

        # 3. PR 当前 head.sha 与历史 Run head_sha 不一致：FAIL
        pr_wrong_head_sha = dict(valid_pr_api_data, head={"ref": feat_branch, "sha": "1111111111111111111111111111111111111111"})
        st3, errs3, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=pr_id,
            expected_event="pull_request",
            expected_head_sha=head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            expected_pr_status="MERGED",
            simulate_data=base_pr_sim_empty,
            simulate_pr_data=pr_wrong_head_sha,
        )
        self.assertEqual(st3, "FAIL")
        self.assertTrue(any("head.sha mismatch" in e.lower() for e in errs3))

        # 4. PR base.ref 非 main：FAIL
        pr_wrong_base = dict(valid_pr_api_data, base={"ref": "develop"})
        st4, errs4, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=pr_id,
            expected_event="pull_request",
            expected_head_sha=head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            expected_pr_status="MERGED",
            simulate_data=base_pr_sim_empty,
            simulate_pr_data=pr_wrong_base,
        )
        self.assertEqual(st4, "FAIL")
        self.assertTrue(any("base ref mismatch" in e.lower() for e in errs4))

        # 5. PR number 不匹配：FAIL
        pr_wrong_num = dict(valid_pr_api_data, number=99)
        st5, errs5, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=pr_id,
            expected_event="pull_request",
            expected_head_sha=head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            expected_pr_status="MERGED",
            simulate_data=base_pr_sim_empty,
            simulate_pr_data=pr_wrong_num,
        )
        self.assertEqual(st5, "FAIL")
        self.assertTrue(any("number mismatch" in e.lower() for e in errs5))

        # 6. PR head.ref 与历史 Run head_branch 不匹配：FAIL
        pr_wrong_head_ref = dict(valid_pr_api_data, head={"ref": "feature/unrelated", "sha": head_sha})
        st6, errs6, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=pr_id,
            expected_event="pull_request",
            expected_head_sha=head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            expected_pr_status="MERGED",
            simulate_data=base_pr_sim_empty,
            simulate_pr_data=pr_wrong_head_ref,
        )
        self.assertEqual(st6, "FAIL")
        self.assertTrue(any("head.ref mismatch" in e.lower() for e in errs6))

        # 7. PR merged=true 但 merged_at 为空：FAIL
        pr_empty_merged_at = dict(valid_pr_api_data, merged_at=None)
        st7, errs7, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=pr_id,
            expected_event="pull_request",
            expected_head_sha=head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            expected_pr_status="MERGED",
            simulate_data=base_pr_sim_empty,
            simulate_pr_data=pr_empty_merged_at,
        )
        self.assertEqual(st7, "FAIL")
        self.assertTrue(any("merged_at is empty" in e.lower() for e in errs7))

        # 8. PR API 不可达：NOT_VERIFIABLE
        st8, errs8, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=pr_id,
            expected_event="pull_request",
            expected_head_sha=head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            expected_pr_status="MERGED",
            simulate_data=base_pr_sim_empty,
            simulate_pr_error="Connection timed out",
        )
        self.assertEqual(st8, "NOT_VERIFIABLE")
        self.assertTrue(any("not accessible" in e.lower() for e in errs8))

        # 9. PR API 返回 404：NOT_VERIFIABLE，不得 PASS
        st9, errs9, _ = verify_single_github_run(
            repo=canonical_repo,
            run_id=pr_id,
            expected_event="pull_request",
            expected_head_sha=head_sha,
            expected_pr_number=9,
            expected_base_ref="main",
            expected_pr_status="MERGED",
            simulate_data=base_pr_sim_empty,
            simulate_pr_error="HTTP 404: Not Found",
        )
        self.assertEqual(st9, "NOT_VERIFIABLE")
        self.assertNotEqual(st9, "PASS")
        self.assertTrue(any("not accessible" in e.lower() for e in errs9))

        # --- verify_github_ci_runs 组合测试与模拟调用路径 ---
        sim_data_map = {push_id: base_push_sim, pr_id: base_pr_sim_empty}
        sim_pr_map = {"9": valid_pr_api_data}
        st_comb, errs_comb, meta_comb = verify_github_ci_runs(
            valid_evidence,
            simulate_data_map=sim_data_map,
            simulate_pr_data_map=sim_pr_map,
        )
        self.assertEqual(st_comb, "PASS")
        self.assertEqual(errs_comb, [])
        self.assertTrue(meta_comb.get("pr_fallback_verified"))

        # --- 真实 CLI 集成测试：模拟当前运行于 main Workflow (GITHUB_REF_NAME=main) ---
        # 正式调用 verify_github_ci_runs()，直连 GitHub Actions 真实 Run 42843964061 与真实 PR #9 API
        orig_ref_name = os.environ.get("GITHUB_REF_NAME")
        orig_head_ref = os.environ.get("GITHUB_HEAD_REF")
        try:
            os.environ["GITHUB_REF_NAME"] = "main"
            os.environ["GITHUB_HEAD_REF"] = ""

            ok_ev, ev_errors, real_evidence = load_release_evidence(ROOT, ROOT / "docs" / "release-evidence" / "v3.0.0-reissue.json")
            self.assertTrue(ok_ev, f"Failed to load real release evidence: {ev_errors}")
            self.assertEqual(real_evidence["pr_status"], "MERGED")
            self.assertEqual(str(real_evidence["pr_run_id"]), pr_id)

            real_st, real_errs, real_details = verify_github_ci_runs(real_evidence)
            self.assertEqual(real_st, "PASS", f"Real CI authenticity verification failed: {real_errs}")
            self.assertEqual(real_errs, [])
            self.assertTrue(real_details.get("pr_fallback_verified"))
            self.assertEqual(real_details["pr_run"]["actual_pr_number"], 9)
            self.assertEqual(real_details["pr_run"]["actual_base_ref"], "main")
            self.assertEqual(real_details["pr_run"]["actual_head_ref"], feat_branch)
            self.assertEqual(real_details["pr_run"]["actual_pr_head_sha"], head_sha)
        finally:
            if orig_ref_name is not None:
                os.environ["GITHUB_REF_NAME"] = orig_ref_name
            else:
                os.environ.pop("GITHUB_REF_NAME", None)
            if orig_head_ref is not None:
                os.environ["GITHUB_HEAD_REF"] = orig_head_ref
            else:
                os.environ.pop("GITHUB_HEAD_REF", None)

    def test_b16_dual_evidence_dual_scope_12_negative_tests(self) -> None:
        """STD-034 / STD-035 (Std-018): 12 negative test cases for independent dual-evidence and
        dual-scope verification (PR9 historical release evidence vs Std-018 current engineering snapshot).
        Ensures:
          1. PR9 historical evidence correctness cannot mask Std-018 current errors.
          2. Std-018 current snapshot correctness cannot mask PR9 historical errors.
          3. Missing current snapshot evidence blocks execution.
          4. Tampering Markdown and recomputing content_sha256 still fails semantic verification.
        """
        pr9_file = ROOT / "docs" / "release-evidence" / "v3.0.0-reissue.json"
        std018_file = ROOT / "docs" / "release-evidence" / "std018-current-snapshot.json"
        self.assertTrue(pr9_file.exists(), f"PR9 evidence file missing: {pr9_file}")
        self.assertTrue(std018_file.exists(), f"Std-018 evidence file missing: {std018_file}")

        pr9_data = json.loads(pr9_file.read_text(encoding="utf-8"))
        std018_data = json.loads(std018_file.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)

            def run_baseline_verify(pr9_p: Path, std_p: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
                cmd = [
                    sys.executable, str(ROOT / "tools" / "generate_engineering_baseline.py"),
                    "--project-root", str(ROOT),
                    "--release-evidence", str(pr9_p),
                    "--snapshot-evidence", str(std_p),
                    "--verify-only",
                ]
                if extra:
                    cmd.extend(extra)
                return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

            def run_handoff_verify(pr9_p: Path, std_p: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
                cmd = [
                    sys.executable, str(ROOT / "tools" / "generate_handoff.py"),
                    "--project-root", str(ROOT),
                    "--release-evidence", str(pr9_p),
                    "--snapshot-evidence", str(std_p),
                    "--verify-only",
                ]
                if extra:
                    cmd.extend(extra)
                return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

            # --- Negative 1: 修改 PR9 candidate_commit -> FAIL ---
            # Std-018 current snapshot is valid, but PR9 historical error MUST NOT be masked
            p1 = tmp / "pr9_neg1.json"
            p1.write_text(json.dumps(dict(pr9_data, candidate_commit="0000000000000000000000000000000000000000")), encoding="utf-8")
            res1 = run_baseline_verify(p1, std018_file)
            self.assertNotEqual(res1.returncode, 0)
            self.assertIn("candidate_commit", res1.stdout)

            # --- Negative 2: 修改 PR9 historical Run ID -> FAIL ---
            p2 = tmp / "pr9_neg2.json"
            p2.write_text(json.dumps(dict(pr9_data, push_run_id="99999999991")), encoding="utf-8")
            res2 = run_baseline_verify(p2, std018_file)
            self.assertNotEqual(res2.returncode, 0)
            self.assertTrue("push_run_id" in res2.stdout or "ci_run_id" in res2.stdout)

            # --- Negative 3: 修改 PR9 test_count -> FAIL ---
            p3 = tmp / "pr9_neg3.json"
            p3.write_text(json.dumps(dict(pr9_data, test_count=999)), encoding="utf-8")
            res3 = run_baseline_verify(p3, std018_file)
            self.assertNotEqual(res3.returncode, 0)
            self.assertTrue("test count" in res3.stdout or "test_count" in res3.stdout)

            # --- Negative 4: 修改 Std018 snapshot_commit -> FAIL ---
            # PR9 historical evidence is valid, but Std-018 error MUST NOT be masked
            s4 = tmp / "std_neg4.json"
            s4.write_text(json.dumps(dict(std018_data, snapshot_commit="1111111111111111111111111111111111111111")), encoding="utf-8")
            res4_b = run_baseline_verify(pr9_file, s4)
            self.assertNotEqual(res4_b.returncode, 0)
            self.assertIn("snapshot_commit", res4_b.stdout)
            res4_h = run_handoff_verify(pr9_file, s4)
            self.assertNotEqual(res4_h.returncode, 0)
            self.assertIn("snapshot_commit", res4_h.stdout)

            # --- Negative 5: 修改 Std018 latest CI Commit -> FAIL ---
            s5 = tmp / "std_neg5.json"
            s5.write_text(json.dumps(dict(std018_data, last_verified_ci_commit="2222222222222222222222222222222222222222")), encoding="utf-8")
            res5 = run_baseline_verify(pr9_file, s5)
            self.assertNotEqual(res5.returncode, 0)
            self.assertTrue("last_verified_ci_commit" in res5.stdout or "ci_commit" in res5.stdout)

            # --- Negative 6: 修改 Std018 Push Run -> FAIL ---
            s6 = tmp / "std_neg6.json"
            s6.write_text(json.dumps(dict(std018_data, push_run_id="99999999993")), encoding="utf-8")
            res6 = run_baseline_verify(pr9_file, s6)
            self.assertNotEqual(res6.returncode, 0)
            self.assertTrue("push_run_id" in res6.stdout or "ci_run_id" in res6.stdout)

            # --- Negative 7: 修改 Std018 PR Run -> FAIL ---
            s7 = tmp / "std_neg7.json"
            s7.write_text(json.dumps(dict(std018_data, pr_run_id="99999999994")), encoding="utf-8")
            res7 = run_baseline_verify(pr9_file, s7)
            self.assertNotEqual(res7.returncode, 0)
            self.assertIn("pr_run_id", res7.stdout)

            # --- Negative 8: 修改 Std018 TEST_COUNT -> FAIL ---
            s8 = tmp / "std_neg8.json"
            s8.write_text(json.dumps(dict(std018_data, test_count=999)), encoding="utf-8")
            res8 = run_baseline_verify(pr9_file, s8)
            self.assertNotEqual(res8.returncode, 0)
            self.assertTrue("test count" in res8.stdout or "test_count" in res8.stdout)

            # --- Negative 9: 修改 Std018 PR 状态 -> FAIL ---
            s9 = tmp / "std_neg9.json"
            s9.write_text(json.dumps(dict(std018_data, pr_status="MERGED")), encoding="utf-8")
            res9 = run_baseline_verify(pr9_file, s9)
            self.assertNotEqual(res9.returncode, 0)
            self.assertTrue("pr_status" in res9.stdout or "PR status" in res9.stdout)

            # --- Negative 10: 修改 Std018 main_head -> FAIL ---
            s10 = tmp / "std_neg10.json"
            s10.write_text(json.dumps(dict(std018_data, main_head="4444444444444444444444444444444444444444")), encoding="utf-8")
            res10 = run_baseline_verify(pr9_file, s10)
            self.assertNotEqual(res10.returncode, 0)
            self.assertIn("main_head", res10.stdout)

            # --- Negative 11: 删除 Std018 current evidence -> BLOCK ---
            missing_snapshot_ev = tmp / "missing-std018-snapshot.json"
            res11_b = run_baseline_verify(pr9_file, missing_snapshot_ev)
            self.assertNotEqual(res11_b.returncode, 0)
            self.assertTrue("RELEASE_EVIDENCE_NOT_FOUND" in (res11_b.stdout + res11_b.stderr) or "snapshot evidence error" in res11_b.stdout)
            res11_h = run_handoff_verify(pr9_file, missing_snapshot_ev)
            self.assertNotEqual(res11_h.returncode, 0)
            self.assertTrue("RELEASE_EVIDENCE_NOT_FOUND" in (res11_h.stdout + res11_h.stderr) or "snapshot evidence error" in res11_h.stdout)

            # --- Negative 12: 篡改 Markdown 并重新计算 SHA256 -> FAIL ---
            from tools.validate_approval_contract import compute_canonical_document_sha256
            base_md = (ROOT / "docs" / "当前权威基线.md").read_text(encoding="utf-8")
            tampered_base_md = base_md.replace(str(std018_data["push_run_id"]), "99999999995")
            new_sha_base = compute_canonical_document_sha256(tampered_base_md)
            tampered_base_md = re.sub(r'content_sha256:\s*"[^"]+"', f'content_sha256: "{new_sha_base}"', tampered_base_md)
            tampered_base_path = tmp / "tampered_baseline.md"
            tampered_base_path.write_text(tampered_base_md, encoding="utf-8")

            res12 = run_baseline_verify(pr9_file, std018_file, extra=["--output", str(tampered_base_path)])
            self.assertNotEqual(res12.returncode, 0, "Tampered baseline MUST fail verify-only even with matching content_sha256")
            self.assertIn("mismatches", res12.stdout)

    def test_b17_duplicate_scope_and_field_uniqueness_negative_tests(self) -> None:
        """STD-034 / STD-035 (Std-018): 12 negative test cases for scope and field uniqueness enforcement
        in generate_engineering_baseline.py and generate_handoff.py.
        Ensures dual-generator rejection of duplicate scope headings, duplicate fields
        (including same-line duplicates), missing fields, appended conflicting values,
        cross-scope evidence substitution, tampering after hash recomputation, missing
        evidence files, and release-flow status tampering.
        """
        pr9_file = ROOT / "docs" / "release-evidence" / "v3.0.0-reissue.json"
        std018_file = ROOT / "docs" / "release-evidence" / "std018-current-snapshot.json"
        self.assertTrue(pr9_file.exists(), f"PR9 evidence file missing: {pr9_file}")
        self.assertTrue(std018_file.exists(), f"Std-018 evidence file missing: {std018_file}")

        baseline_raw = (ROOT / "docs" / "当前权威基线.md").read_text(encoding="utf-8")
        handoff_raw = (ROOT / "docs" / "CROSS-SESSION-HANDOFF.md").read_text(encoding="utf-8")

        from tools.validate_approval_contract import compute_canonical_document_sha256

        def write_with_sha(content: str, out_p: Path) -> Path:
            csha = compute_canonical_document_sha256(content)
            updated = re.sub(r'content_sha256:\s*"[^"]*"', f'content_sha256: "{csha}"', content)
            out_p.write_text(updated, encoding="utf-8")
            return out_p

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)

            def run_baseline_verify(extra: list) -> subprocess.CompletedProcess:
                cmd = [
                    sys.executable, str(ROOT / "tools" / "generate_engineering_baseline.py"),
                    "--project-root", str(ROOT),
                    "--release-evidence", str(pr9_file),
                    "--snapshot-evidence", str(std018_file),
                    "--verify-only",
                ] + extra
                return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

            def run_handoff_verify(extra: list) -> subprocess.CompletedProcess:
                cmd = [
                    sys.executable, str(ROOT / "tools" / "generate_handoff.py"),
                    "--project-root", str(ROOT),
                    "--release-evidence", str(pr9_file),
                    "--snapshot-evidence", str(std018_file),
                    "--verify-only",
                ] + extra
                return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

            # 1. PR9 scope heading duplicated in baseline -> FAIL (DUPLICATE_SCOPE_SECTION)
            m1 = baseline_raw + "\n\n### 9.9 重复作用域副本 (PR9_HISTORICAL_RELEASE_EVIDENCE)\n- 冗余内容\n"
            p1 = write_with_sha(m1, tmp / "b_neg1.md")
            res1 = run_baseline_verify(["--output", str(p1)])
            self.assertNotEqual(res1.returncode, 0)
            self.assertIn("DUPLICATE_SCOPE_SECTION", res1.stdout)

            # 2. Std018 scope heading duplicated in baseline -> FAIL (DUPLICATE_SCOPE_SECTION)
            m2 = baseline_raw + "\n\n### 9.10 重复作用域副本 (STD018_CURRENT_SNAPSHOT)\n- 冗余内容\n"
            p2 = write_with_sha(m2, tmp / "b_neg2.md")
            res2 = run_baseline_verify(["--output", str(p2)])
            self.assertNotEqual(res2.returncode, 0)
            self.assertIn("DUPLICATE_SCOPE_SECTION", res2.stdout)

            # 3. PR9 field duplicated with conflicting value in baseline -> FAIL (DUPLICATE_FIELD)
            m3 = baseline_raw.replace(
                "- **代码候选 Commit (`candidate_commit`)**：`336114861b2c720106a6076956eef08c9cd6ded7`",
                "- **代码候选 Commit (`candidate_commit`)**：`336114861b2c720106a6076956eef08c9cd6ded7`\n- **代码候选 Commit (`candidate_commit`)**：`0000000000000000000000000000000000000000`"
            )
            p3 = write_with_sha(m3, tmp / "b_neg3.md")
            res3 = run_baseline_verify(["--output", str(p3)])
            self.assertNotEqual(res3.returncode, 0)
            self.assertIn("DUPLICATE_FIELD", res3.stdout)

            # 4. Std018 field duplicated with conflicting value in baseline -> FAIL (DUPLICATE_FIELD)
            m4 = baseline_raw.replace(
                "- **Push Run ID**：`42983601133`",
                "- **Push Run ID**：`42983601133`\n- **Push Run ID**：`99999999999`"
            )
            p4 = write_with_sha(m4, tmp / "b_neg4.md")
            res4 = run_baseline_verify(["--output", str(p4)])
            self.assertNotEqual(res4.returncode, 0)
            self.assertIn("DUPLICATE_FIELD", res4.stdout)

            # 5. Valid field followed by appended erroneous field -> FAIL (DUPLICATE_FIELD)
            m5 = baseline_raw.replace(
                "- **PR Run ID**：`42983609802`",
                "- **PR Run ID**：`42983609802`\n- **PR Run ID**：`42983609802`"
            )
            p5 = write_with_sha(m5, tmp / "b_neg5.md")
            res5 = run_baseline_verify(["--output", str(p5)])
            self.assertNotEqual(res5.returncode, 0)
            self.assertIn("DUPLICATE_FIELD", res5.stdout)

            # 6. Delete PR9 required field in baseline -> FAIL (MISSING_FIELD)
            m6 = baseline_raw.replace("- **代码候选 Commit (`candidate_commit`)**：`336114861b2c720106a6076956eef08c9cd6ded7`\n", "")
            p6 = write_with_sha(m6, tmp / "b_neg6.md")
            res6 = run_baseline_verify(["--output", str(p6)])
            self.assertNotEqual(res6.returncode, 0)
            self.assertIn("MISSING_FIELD", res6.stdout)

            # 7. Delete Std018 required field in baseline -> FAIL (MISSING_FIELD)
            m7 = baseline_raw.replace("- **当前工程候选 Commit (`candidate_commit`)**：`21939da5e13eb39dedd0557561e88e1342be694c`\n", "")
            p7 = write_with_sha(m7, tmp / "b_neg7.md")
            res7 = run_baseline_verify(["--output", str(p7)])
            self.assertNotEqual(res7.returncode, 0)
            self.assertIn("MISSING_FIELD", res7.stdout)

            # 8. Cross-scope isolation: PR9 valid, Std018 invalid in Handoff -> FAIL
            m8 = handoff_raw.replace("- **PR Run ID**：`42983609802`", "- **PR Run ID**：`88888888888`")
            p8 = write_with_sha(m8, tmp / "h_neg8.md")
            res8 = run_handoff_verify(["--output", str(p8)])
            self.assertNotEqual(res8.returncode, 0)
            self.assertIn("pr_run_id", res8.stdout)

            # 9. Cross-scope isolation: Std018 valid, PR9 invalid in Handoff -> FAIL
            m9 = handoff_raw.replace("- **Push Run ID**：`42843755347`", "- **Push Run ID**：`77777777777`")
            p9 = write_with_sha(m9, tmp / "h_neg9.md")
            res9 = run_handoff_verify(["--output", str(p9)])
            self.assertNotEqual(res9.returncode, 0)
            self.assertIn("push_run_id", res9.stdout)

            # 10. Baseline tampered then recomputed SHA256 -> FAIL
            m10 = baseline_raw.replace("21939da5e13eb39dedd0557561e88e1342be694c", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
            p10 = write_with_sha(m10, tmp / "b_neg10.md")
            res10 = run_baseline_verify(["--output", str(p10)])
            self.assertNotEqual(res10.returncode, 0)
            self.assertIn("mismatches", res10.stdout)

            # 11. Handoff tampered then recomputed SHA256 -> FAIL
            m11 = handoff_raw.replace("21939da5e13eb39dedd0557561e88e1342be694c", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
            p11 = write_with_sha(m11, tmp / "h_neg11.md")
            res11 = run_handoff_verify(["--output", str(p11)])
            self.assertNotEqual(res11.returncode, 0)
            self.assertIn("mismatches", res11.stdout)

            # Handoff parity: duplicate PR9 and Std-018 scope headings must both block.
            h12 = handoff_raw + "\n\n### 4.9 Duplicate PR9 scope (PR9_HISTORICAL_RELEASE_EVIDENCE)\n- duplicate\n"
            p12 = write_with_sha(h12, tmp / "h_neg12.md")
            res12 = run_handoff_verify(["--output", str(p12)])
            self.assertNotEqual(res12.returncode, 0)
            self.assertIn("DUPLICATE_SCOPE_SECTION", res12.stdout)

            h13 = handoff_raw + "\n\n### 4.10 Duplicate Std018 scope (STD018_CURRENT_SNAPSHOT)\n- duplicate\n"
            p13 = write_with_sha(h13, tmp / "h_neg13.md")
            res13 = run_handoff_verify(["--output", str(p13)])
            self.assertNotEqual(res13.returncode, 0)
            self.assertIn("DUPLICATE_SCOPE_SECTION", res13.stdout)

            h14 = handoff_raw.replace(
                "- **Push Run ID**：`42843755347`",
                "- **Push Run ID**：`42843755347`\n- **Push Run ID**：`99999999998`",
                1,
            )
            p14 = write_with_sha(h14, tmp / "h_neg14.md")
            res14 = run_handoff_verify(["--output", str(p14)])
            self.assertNotEqual(res14.returncode, 0)
            self.assertIn("DUPLICATE_FIELD", res14.stdout)

            h15 = handoff_raw.replace(
                "- **Push Run ID**：`42983601133`",
                "- **Push Run ID**：`42983601133`\n- **Push Run ID**：`99999999999`",
                1,
            )
            p15 = write_with_sha(h15, tmp / "h_neg15.md")
            res15 = run_handoff_verify(["--output", str(p15)])
            self.assertNotEqual(res15.returncode, 0)
            self.assertIn("DUPLICATE_FIELD", res15.stdout)

            b16 = baseline_raw.replace(
                "- **Push Run ID**：`42983601133`",
                "- **Push Run ID**：`42983601133`；**Push Run ID**：`99999999999`",
                1,
            )
            p16 = write_with_sha(b16, tmp / "b_neg16.md")
            res16 = run_baseline_verify(["--output", str(p16)])
            self.assertNotEqual(res16.returncode, 0)
            self.assertIn("DUPLICATE_FIELD", res16.stdout)

            h17 = handoff_raw.replace(
                "- **Push Run ID**：`42983601133`",
                "- **Push Run ID**：`42983601133`；**Push Run ID**：`99999999999`",
                1,
            )
            p17 = write_with_sha(h17, tmp / "h_neg17.md")
            res17 = run_handoff_verify(["--output", str(p17)])
            self.assertNotEqual(res17.returncode, 0)
            self.assertIn("DUPLICATE_FIELD", res17.stdout)

            h18 = handoff_raw.replace(
                "- **发布流程状态 (`release_flow_status`)**：`IN_PROGRESS`",
                "- **发布流程状态 (`release_flow_status`)**：`RELEASED`",
                1,
            )
            p18 = write_with_sha(h18, tmp / "h_neg18.md")
            res18 = run_handoff_verify(["--output", str(p18)])
            self.assertNotEqual(res18.returncode, 0)
            self.assertIn("release_flow_status", res18.stdout)

            b19 = baseline_raw.replace(
                "- **发布流程状态 (`release_flow_status`)**：`IN_PROGRESS`",
                "- **发布流程状态 (`release_flow_status`)**：`RELEASED`",
                1,
            )
            p19 = write_with_sha(b19, tmp / "b_neg19.md")
            res19 = run_baseline_verify(["--output", str(p19)])
            self.assertNotEqual(res19.returncode, 0)
            self.assertIn("release_flow_status", res19.stdout)

            h20 = handoff_raw.replace(
                "- **PR Run ID**：`42983609802`\n",
                "",
                1,
            )
            p20 = write_with_sha(h20, tmp / "h_neg20.md")
            res20 = run_handoff_verify(["--output", str(p20)])
            self.assertNotEqual(res20.returncode, 0)
            self.assertIn("MISSING_FIELD", res20.stdout)
            # 12. Missing Std018 evidence file -> BLOCK
            missing_ev = tmp / "missing-std018.json"
            res12_b = subprocess.run([
                sys.executable, str(ROOT / "tools" / "generate_engineering_baseline.py"),
                "--project-root", str(ROOT),
                "--release-evidence", str(pr9_file),
                "--snapshot-evidence", str(missing_ev),
                "--verify-only",
            ], capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(res12_b.returncode, 0)
            self.assertTrue("RELEASE_EVIDENCE_NOT_FOUND" in (res12_b.stdout + res12_b.stderr) or "snapshot evidence error" in res12_b.stdout)

            res12_h = subprocess.run([
                sys.executable, str(ROOT / "tools" / "generate_handoff.py"),
                "--project-root", str(ROOT),
                "--release-evidence", str(pr9_file),
                "--snapshot-evidence", str(missing_ev),
                "--verify-only",
            ], capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(res12_h.returncode, 0)
            self.assertTrue("RELEASE_EVIDENCE_NOT_FOUND" in (res12_h.stdout + res12_h.stderr) or "snapshot evidence error" in res12_h.stdout)

    def test_b18_v300_released_evidence_and_three_chains_authenticity_governance(self) -> None:
        """STD-034 / STD-035 (Std-019): 22 test cases for v3.0.0 RELEASED evidence, three independent verification
        chains (Main CI, PR CI, PR Merge Authenticity), remote Tag verification, and dynamic Git state governance.
        """
        canonical_repo = "xiefeifeihu/AI-Engineering-Standards"
        repo_owner = "xiefeifeihu"
        peeled_commit = "8b223019c254e0edeb94576b94af46c1e48b0316"
        tag_obj_sha = "8256bb384e62894219db0992a2cb57e16d4fa8cd"
        pr_head_sha = "a6d3284e14c609d8284f2812c206e913a00a0c07"
        pr_head_ref = "fix/std-016-merged-pr-run-evidence"
        main_run_id = "42996232217"
        pr_run_id = "42995008952"
        pr_number = 10
        release_tag = "v3.0.0"
        workflow_path = ".github/workflows/standards-ci.yml"

        base_released_evidence = {
            "repository": canonical_repo,
            "version": "3.0.0",
            "pr_number": pr_number,
            "pr_status": "MERGED",
            "main_head": peeled_commit,
            "candidate_commit": peeled_commit,
            "snapshot_commit": peeled_commit,
            "last_verified_ci_commit": peeled_commit,
            "main_ci_run_id": main_run_id,
            "push_run_id": main_run_id,
            "push_head_branch": "main",
            "pr_run_id": pr_run_id,
            "ci_status": "PASS",
            "test_count": 222,
            "test_failed": 0,
            "test_skipped": 0,
            "windows_status": "PASS",
            "ubuntu_status": "PASS",
            "old_tag_deleted": True,
            "old_tag_object": "325008af90a1e6dcc88ff714c9ec4e7ecee86ec6",
            "old_tag_peeled_commit": "1d5cbbd6710bef749c8f79e9c1fd21dd14223b1b",
            "old_tag_bundle_sha256": "45bc3e455fc06b96a669ba9d7c44195f5dfb4e42e55397d795200942e434ebfc",
            "release_flow_status": "RELEASED",
            "release_tag": release_tag,
            "tag_object_sha": tag_obj_sha,
            "peeled_commit": peeled_commit,
            "tag_publish_status": "PASS",
            "pr_merged": True,
            "pr_merged_by": repo_owner,
            "task_id": "Std-019-V3-0-0-POST-RELEASE-CLOSEOUT",
        }

        base_main_run_data = {
            "id": int(main_run_id),
            "name": "Standards Schema Validation & Governance CI (STD-034)",
            "head_sha": peeled_commit,
            "headSha": peeled_commit,
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "path": workflow_path,
            "head_branch": "main",
            "headBranch": "main",
            "repository": {"full_name": canonical_repo, "name": "AI-Engineering-Standards"},
            "jobs": [
                {"name": "Validate Schemas, Docs, Baseline, Handoff, Sync & Approval Contracts (ubuntu-latest)", "status": "completed", "conclusion": "success"},
                {"name": "Validate Schemas, Docs, Baseline, Handoff, Sync & Approval Contracts (windows-latest)", "status": "completed", "conclusion": "success"},
                {"name": "Publish Standards Tag after main CI", "status": "completed", "conclusion": "success"},
            ],
        }

        base_pr_run_data = {
            "id": int(pr_run_id),
            "name": "Standards Schema Validation & Governance CI (STD-034)",
            "head_sha": pr_head_sha,
            "headSha": pr_head_sha,
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "path": workflow_path,
            "head_branch": pr_head_ref,
            "headBranch": pr_head_ref,
            "repository": {"full_name": canonical_repo, "name": "AI-Engineering-Standards"},
            "pull_requests": [
                {"number": pr_number, "base": {"ref": "main"}, "head": {"ref": pr_head_ref, "sha": pr_head_sha}}
            ],
            "jobs": [
                {"name": "Validate (ubuntu-latest)", "status": "completed", "conclusion": "success"},
                {"name": "Validate (windows-latest)", "status": "completed", "conclusion": "success"},
            ],
        }

        base_pr_api_data = {
            "number": pr_number,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-11-11T09:33:50Z",
            "merge_commit_sha": peeled_commit,
            "merged_by": {"login": repo_owner},
            "base": {"ref": "main", "sha": "3cd42b69049b148bceea1324d4f8212393cb96df"},
            "head": {"ref": pr_head_ref, "sha": pr_head_sha},
        }

        valid_ls_remote = f"{tag_obj_sha}\trefs/tags/{release_tag}\n{peeled_commit}\trefs/tags/{release_tag}^{{}}\n"

        # 1. 正向用例：RELEASED 完整三链 + Annotated Tag 全部通过 -> PASS
        st1, errs1, det1 = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: base_main_run_data,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): base_pr_api_data},
        )
        self.assertEqual(st1, "PASS")
        self.assertEqual(errs1, [])
        self.assertTrue(det1["tag_publish_verified"])
        self.assertEqual(det1["chains"]["chain_a_main_ci"], "PASS")
        self.assertEqual(det1["chains"]["chain_b_pr_ci"], "PASS")
        self.assertEqual(det1["chains"]["chain_c_pr_merge"], "PASS")

        # 2. 负向用例：PR Run ID 错误
        ev2 = dict(base_released_evidence, pr_run_id="99999999999")
        st2, errs2, _ = verify_github_ci_runs(
            ev2,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: base_main_run_data,
                "99999999999": dict(base_pr_run_data, id=11111111111),
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): base_pr_api_data},
        )
        self.assertEqual(st2, "FAIL")
        self.assertTrue(any("id mismatch" in e.lower() for e in errs2))

        # 3. 负向用例：PR Run HEAD 与 PR HEAD 不一致
        sim3_pr = dict(base_pr_run_data, head_sha="0000000000000000000000000000000000000000", headSha="0000000000000000000000000000000000000000")
        st3, errs3, det3 = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: base_main_run_data,
                pr_run_id: sim3_pr,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): base_pr_api_data},
        )
        self.assertEqual(st3, "FAIL")
        self.assertTrue(any("head_sha mismatch" in e.lower() for e in errs3))
        self.assertEqual(det3["chains"]["chain_b_pr_ci"], "FAIL")
        self.assertEqual(det3["chains"]["chain_c_pr_merge"], "PASS")

        # 4. 负向用例：PR base.ref 不为 main
        sim4_pr_api = dict(base_pr_api_data, base={"ref": "feat/untrusted-branch"})
        st4, errs4, _ = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: base_main_run_data,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): sim4_pr_api},
        )
        self.assertEqual(st4, "FAIL")
        self.assertTrue(any("base.ref" in e.lower() or "base ref" in e.lower() for e in errs4))

        # 5. 负向用例：PR merged_by 不是仓库 Owner
        sim5_pr_api = dict(base_pr_api_data, merged_by={"login": "unauthorized-contributor"})
        st5, errs5, det5 = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: base_main_run_data,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): sim5_pr_api},
        )
        self.assertEqual(st5, "FAIL")
        self.assertTrue(any("not repository owner" in e.lower() or "merged by" in e.lower() for e in errs5))
        self.assertEqual(det5["chains"]["chain_c_pr_merge"], "FAIL")
        self.assertEqual(det5["chains"]["chain_b_pr_ci"], "PASS")

        # 6. 负向用例：PR merge_commit_sha 缺失
        sim6_pr_api = dict(base_pr_api_data, merge_commit_sha=None)
        st6, errs6, _ = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: base_main_run_data,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): sim6_pr_api},
        )
        self.assertEqual(st6, "FAIL")
        self.assertTrue(any("merge_commit_sha is missing" in e.lower() for e in errs6))

        # 7. 负向用例：PR merge_commit_sha 与 peeled_commit 不一致
        sim7_pr_api = dict(base_pr_api_data, merge_commit_sha="1111111111111111111111111111111111111111")
        st7, errs7, _ = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: base_main_run_data,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): sim7_pr_api},
        )
        self.assertEqual(st7, "FAIL")
        self.assertTrue(any("merge commit" in e.lower() for e in errs7))

        # 8. 负向用例：Main CI head_sha 与 peeled_commit 不一致
        sim8_main = dict(base_main_run_data, head_sha="2222222222222222222222222222222222222222", headSha="2222222222222222222222222222222222222222")
        st8, errs8, _ = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: sim8_main,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): base_pr_api_data},
        )
        self.assertEqual(st8, "FAIL")
        self.assertTrue(any("head_sha mismatch" in e.lower() for e in errs8))

        # 9. 负向用例：Main CI Windows Job 失败
        sim9_main = dict(base_main_run_data, jobs=[
            {"name": "Validate Schemas (ubuntu-latest)", "status": "completed", "conclusion": "success"},
            {"name": "Validate Schemas (windows-latest)", "status": "completed", "conclusion": "failure"},
            {"name": "Publish Standards Tag after main CI", "status": "completed", "conclusion": "success"},
        ])
        st9, errs9, _ = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: sim9_main,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): base_pr_api_data},
        )
        self.assertEqual(st9, "FAIL")
        self.assertTrue(any("windows job conclusion" in e.lower() for e in errs9))

        # 10. 负向用例：Main CI Ubuntu Job 失败
        sim10_main = dict(base_main_run_data, jobs=[
            {"name": "Validate Schemas (ubuntu-latest)", "status": "completed", "conclusion": "failure"},
            {"name": "Validate Schemas (windows-latest)", "status": "completed", "conclusion": "success"},
            {"name": "Publish Standards Tag after main CI", "status": "completed", "conclusion": "success"},
        ])
        st10, errs10, _ = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: sim10_main,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): base_pr_api_data},
        )
        self.assertEqual(st10, "FAIL")
        self.assertTrue(any("ubuntu job conclusion" in e.lower() for e in errs10))

        # 11. 负向用例：Main CI Tag Publish Job 失败
        sim11_main = dict(base_main_run_data, jobs=[
            {"name": "Validate Schemas (ubuntu-latest)", "status": "completed", "conclusion": "success"},
            {"name": "Validate Schemas (windows-latest)", "status": "completed", "conclusion": "success"},
            {"name": "Publish Standards Tag after main CI", "status": "completed", "conclusion": "failure"},
        ])
        st11, errs11, _ = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: sim11_main,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): base_pr_api_data},
        )
        self.assertEqual(st11, "FAIL")
        self.assertTrue(any("tag publish job" in e.lower() for e in errs11))

        # 12. 负向用例：远端 Tag 缺失
        st12, errs12 = verify_git_tag(ROOT, release_tag, tag_obj_sha, peeled_commit, simulate_ls_remote="")
        self.assertEqual(st12, "FAIL")
        self.assertTrue(any("not found" in e.lower() for e in errs12))

        # 13. 负向用例：远端 Tag Object SHA 不匹配
        bad_obj_ls = f"3333333333333333333333333333333333333333\trefs/tags/{release_tag}\n{peeled_commit}\trefs/tags/{release_tag}^{{}}\n"
        st13, errs13 = verify_git_tag(ROOT, release_tag, tag_obj_sha, peeled_commit, simulate_ls_remote=bad_obj_ls)
        self.assertEqual(st13, "FAIL")
        self.assertTrue(any("object sha mismatch" in e.lower() for e in errs13))

        # 14. 负向用例：远端 Peeled Commit 不匹配
        bad_peeled_ls = f"{tag_obj_sha}\trefs/tags/{release_tag}\n4444444444444444444444444444444444444444\trefs/tags/{release_tag}^{{}}\n"
        st14, errs14 = verify_git_tag(ROOT, release_tag, tag_obj_sha, peeled_commit, simulate_ls_remote=bad_peeled_ls)
        self.assertEqual(st14, "FAIL")
        self.assertTrue(any("peeled commit mismatch" in e.lower() for e in errs14))

        # 15. 负向用例：Lightweight Tag 被拒绝
        lightweight_ls = f"{peeled_commit}\trefs/tags/{release_tag}\n"
        st15, errs15 = verify_git_tag(ROOT, release_tag, tag_obj_sha, peeled_commit, simulate_ls_remote=lightweight_ls)
        self.assertEqual(st15, "FAIL")
        self.assertTrue(any("lightweight" in e.lower() or "not an annotated tag" in e.lower() for e in errs15))

        # 16. 负向用例：API 不可达返回 NOT_VERIFIABLE
        st16, errs16, _ = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: base_main_run_data,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_error_map={str(pr_number): "HTTP 503: GitHub API Service Unavailable"},
        )
        self.assertEqual(st16, "NOT_VERIFIABLE")
        self.assertTrue(any("service unavailable" in e.lower() or "not accessible" in e.lower() for e in errs16))

        # 17. 负向用例：PR API 缺失 number 必须 FAIL
        sim17_pr_api = dict(base_pr_api_data)
        sim17_pr_api.pop("number", None)
        st17, errs17, _ = verify_github_ci_runs(
            base_released_evidence,
            project_root=ROOT,
            simulate_data_map={
                main_run_id: base_main_run_data,
                pr_run_id: base_pr_run_data,
                "ls_remote": valid_ls_remote,
            },
            simulate_pr_data_map={str(pr_number): sim17_pr_api},
        )
        self.assertEqual(st17, "FAIL")
        self.assertTrue(any("PR_NUMBER_MISSING" in e for e in errs17))

        # 18. 正常生成流程必须使用显式 snapshot/final evidence 路径
        with patch("tools.generate_engineering_baseline.load_release_evidence", wraps=load_release_evidence) as baseline_loader:
            build_engineering_baseline(
                project_root=ROOT,
                release_evidence_path="docs/release-evidence/v3.0.0-reissue.json",
                snapshot_evidence_path="docs/release-evidence/std018-current-snapshot.json",
                final_evidence_path="docs/release-evidence/std019-final-release.json",
            )
            baseline_paths = [str(call.args[1]) for call in baseline_loader.call_args_list if len(call.args) > 1]
            self.assertIn("docs/release-evidence/std018-current-snapshot.json", baseline_paths)
            self.assertIn("docs/release-evidence/std019-final-release.json", baseline_paths)
        with patch("tools.generate_handoff.load_release_evidence", wraps=load_release_evidence) as handoff_loader:
            build_handoff_payload(
                project_root=ROOT,
                task_id="Std-019-V3-0-0-POST-RELEASE-CLOSEOUT",
                release_evidence_path="docs/release-evidence/v3.0.0-reissue.json",
                snapshot_evidence_path="docs/release-evidence/std018-current-snapshot.json",
                final_evidence_path="docs/release-evidence/std019-final-release.json",
            )
            handoff_paths = [str(call.args[1]) for call in handoff_loader.call_args_list if len(call.args) > 1]
            self.assertIn("docs/release-evidence/std018-current-snapshot.json", handoff_paths)
            self.assertIn("docs/release-evidence/std019-final-release.json", handoff_paths)

        # 19. 显式 version 查询不被 final evidence 覆盖
        resolved_211 = resolve_release_evidence_path(ROOT, version="2.11.0")
        self.assertIn("v2.11.0", resolved_211.name)
        self.assertNotIn("std019", resolved_211.name)

        # 20. 发布证据三作用域重复/缺失字段负向测试
        baseline_text = (ROOT / "docs" / "当前权威基线.md").read_text(encoding="utf-8")
        from tools.generate_engineering_baseline import extract_scope_content
        _, miss_errs = extract_scope_content(baseline_text, "NON_EXISTENT_SCOPE_TEST")
        self.assertTrue(any("SCOPE_SECTION_MISSING" in e for e in miss_errs))

        # 21. Handoff 动态 Git HEAD 篡改在 verify-only 被捕获
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            from tools.validate_approval_contract import compute_canonical_document_sha256
            h_text = (ROOT / "docs" / "CROSS-SESSION-HANDOFF.md").read_text(encoding="utf-8")
            h_local = re.search(r'本地 HEAD \(\x60local_head\x60\)\*\*：\x60([0-9a-f]{40})\x60', h_text)
            self.assertIsNotNone(h_local, "Canonical handoff local_head field missing")
            h_local_line = "- **本地 HEAD (" + chr(96) + "local_head" + chr(96) + ")**：" + chr(96) + h_local.group(1) + chr(96)
            h_tampered_line = "- **本地 HEAD (" + chr(96) + "local_head" + chr(96) + ")**：" + chr(96) + "5555555555555555555555555555555555555555" + chr(96)
            tampered_h = h_text.replace(h_local_line, h_tampered_line, 1)
            t_sha = compute_canonical_document_sha256(tampered_h)
            tampered_h = re.sub(r'content_sha256:\s*"[^"]*"', f'content_sha256: "{t_sha}"', tampered_h)
            p_h = tmp / "CROSS-SESSION-HANDOFF.md"
            p_h.write_text(tampered_h, encoding="utf-8")
            res19 = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "generate_handoff.py"), "--project-root", str(ROOT), "--output", str(p_h), "--verify-only"],
                capture_output=True, text=True, encoding="utf-8"
            )
            self.assertNotEqual(res19.returncode, 0)
            self.assertTrue("mismatches" in res19.stdout or "FAIL" in res19.stdout)

        # 22. Baseline 动态 Git 状态不一致在 verify-only 被捕获
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            b_text = (ROOT / "docs" / "当前权威基线.md").read_text(encoding="utf-8")
            b_local = re.search(r'本地 HEAD \(\x60local_head\x60\)\*\*：\x60([0-9a-f]{40})\x60', b_text)
            self.assertIsNotNone(b_local, "Canonical baseline local_head field missing")
            b_local_line = "- **本地 HEAD (" + chr(96) + "local_head" + chr(96) + ")**：" + chr(96) + b_local.group(1) + chr(96)
            b_tampered_line = "- **本地 HEAD (" + chr(96) + "local_head" + chr(96) + ")**：" + chr(96) + "6666666666666666666666666666666666666666" + chr(96)
            tampered_b = b_text.replace(b_local_line, b_tampered_line, 1)
            b_sha = compute_canonical_document_sha256(tampered_b)
            tampered_b = re.sub(r'content_sha256:\s*"[^"]*"', f'content_sha256: "{b_sha}"', tampered_b)
            p_b = tmp / "当前权威基线.md"
            p_b.write_text(tampered_b, encoding="utf-8")
            res20 = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "generate_engineering_baseline.py"), "--project-root", str(ROOT), "--output", str(p_b), "--verify-only"],
                capture_output=True, text=True, encoding="utf-8"
            )
            self.assertNotEqual(res20.returncode, 0)
            self.assertTrue("mismatches" in res20.stdout or "FAIL" in res20.stdout)

    # =========================================================================
    # C. Standards Sync Tool Tests
    # =========================================================================
    def test_c1_discover_latest_tag_and_semver_sorting(self) -> None:
        # Test SemVer sorting (v2.10.0 > v2.9.1 > v2.5.1, not lexical)
        tags = ["v2.5.1", "v2.10.0", "v2.9.1", "v2.11.0"]
        sorted_tags = sorted(tags, key=lambda t: parse_semver(t) or (0, 0, 0), reverse=True)
        self.assertEqual(sorted_tags, ["v2.11.0", "v2.10.0", "v2.9.1", "v2.5.1"])

        # Discover from local repository acting as remote
        res = discover_latest_official_tag(
            standards_root=ROOT,
            remote_url=str(ROOT),
            ci_status_override="PASS",
        )
        self.assertIn(res["status"], ("PASS", "NOT_VERIFIABLE"))
        self.assertIn(res["remote_latest_status"], ("PASS", "NOT_VERIFIABLE"))
        self.assertIn(res["tag"], ("v2.11.0", "v3.0.0"))
        if res["tag"] == "v3.0.0":
            self.assertEqual(res["version"], "3.0.0")
            self.assertEqual(res["peeled_commit"], "8b223019c254e0edeb94576b94af46c1e48b0316")
            self.assertEqual(res["tag_object_sha"], "8256bb384e62894219db0992a2cb57e16d4fa8cd")
        else:
            self.assertEqual(res["version"], "2.11.0")
            self.assertEqual(res["tag_object_sha"], BASELINE_TAG_OBJ)
            self.assertEqual(res["peeled_commit"], BASELINE_COMMIT)

    def test_c2_annotated_tag_object_and_peeled_commit_verification(self) -> None:
        res = verify_project_lock(
            project_root=ROOT,
            standards_root=ROOT,
            remote_url=str(ROOT),
        )
        self.assertIn(res["status"], ("PASS", "NOT_VERIFIABLE"), f"Unexpected lock result: {res}")
        if res["status"] == "NOT_VERIFIABLE":
            self.assertTrue(res.get("offline_verified_lock"), f"Offline lock was not verified locally: {res}")
            self.assertEqual(res.get("remote_latest_status"), "NOT_VERIFIABLE")

    def test_c2b_offline_latest_release_must_not_report_pass(self) -> None:
        result = verify_project_lock(
            project_root=ROOT,
            standards_root=ROOT,
            remote_url=str(ROOT),
            simulate_offline=True,
        )
        self.assertEqual(result.get("status"), "NOT_VERIFIABLE")
        self.assertEqual(result.get("remote_latest_status"), "NOT_VERIFIABLE")
        self.assertTrue(result.get("offline_verified_lock"))

    def test_c3_version_file_consistency_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            shutil.copy2(ROOT / "standards.lock.json", dst / "standards.lock.json")
            lk = json.loads((dst / "standards.lock.json").read_text(encoding="utf-8"))
            lk["version"] = "2.99.0"  # Mismatches tag v2.11.0
            (dst / "standards.lock.json").write_text(json.dumps(lk), encoding="utf-8")
            res = verify_project_lock(project_root=dst, standards_root=ROOT, remote_url=str(ROOT))
            self.assertEqual(res["status"], "BLOCK")
            self.assertTrue(any("LOCK_TAG_VERSION_MISMATCH" in e or "VERSION_FILE_MISMATCH" in e for e in res["errors"]))

    def test_c4_ci_failure_blocks_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            res = promote_upgrade(
                project_root=dst,
                target_tag="v3.0.0",
                target_version="3.0.0",
                target_tag_object_sha="a" * 40,
                target_peeled_commit=BASELINE_COMMIT,
                ci_status="FAIL",
                standards_root=ROOT,
            )
            self.assertEqual(res["status"], "UPGRADE_BLOCKED")
            self.assertIn("CI_NOT_PASSED", res["reason"])

    def test_c5_network_timeout_returns_not_verifiable(self) -> None:
        res = discover_latest_official_tag(
            standards_root=ROOT,
            simulate_offline=True,
        )
        self.assertEqual(res["status"], "NOT_VERIFIABLE")
        self.assertEqual(res["remote_latest_status"], "NOT_VERIFIABLE")

    def test_c6_tag_object_drift_blocks_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            shutil.copy2(ROOT / "standards.lock.json", dst / "standards.lock.json")
            lk = json.loads((dst / "standards.lock.json").read_text(encoding="utf-8"))
            lk["tag_object_sha"] = "f" * 40  # Drifted tag object SHA
            (dst / "standards.lock.json").write_text(json.dumps(lk), encoding="utf-8")
            res = verify_project_lock(project_root=dst, standards_root=ROOT, remote_url=str(ROOT))
            self.assertEqual(res["status"], "BLOCK")
            self.assertTrue(any("TAG_OBJECT_DRIFT" in e for e in res["errors"]), f"Got: {res}")

    def test_c7_untagged_commit_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            shutil.copy2(ROOT / "standards.lock.json", dst / "standards.lock.json")
            lk = json.loads((dst / "standards.lock.json").read_text(encoding="utf-8"))
            lk["tag"] = "v9.9.9"
            lk["version"] = "9.9.9"
            (dst / "standards.lock.json").write_text(json.dumps(lk), encoding="utf-8")
            res = verify_project_lock(project_root=dst, standards_root=ROOT, remote_url=str(ROOT))
            self.assertEqual(res["status"], "BLOCK")
            self.assertTrue(any("UNTAGGED_OR_MISSING_TAG" in e for e in res["errors"]), f"Got: {res}")

    def test_c8_downgrade_blocked(self) -> None:
        cmp_res = compare_versions_and_artifacts(
            from_ref="v2.11.0",
            to_ref="v2.10.0",
            standards_root=ROOT,
        )
        self.assertEqual(cmp_res["status"], "BLOCK")
        self.assertIn("DOWNGRADE_FORBIDDEN", cmp_res["reason"])

    def test_c9_unpublished_commit_not_on_main_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "std_repo"
            repo.mkdir(parents=True)
            subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@standards.local"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Standards Test"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/xiefeifeihu/AI-Engineering-Standards.git"], capture_output=True, check=True)
            (repo / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "VERSION"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "main commit"], capture_output=True, check=True)

            # Create an unmerged side branch and tag it
            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "unmerged-branch"], capture_output=True, check=True)
            (repo / "VERSION").write_text("2.0.0\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "VERSION"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "side commit"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(repo), "tag", "-a", "v2.0.0", "-m", "side tag"], capture_output=True, check=True)

            disc = discover_latest_official_tag(
                standards_root=repo,
                remote_url=str(repo),
                ci_status_override="PASS",
            )
            self.assertEqual(disc["status"], "BLOCK")
            self.assertIn("NOT_ON_MAIN_BRANCH", disc["reason"])

    def test_c10_promotion_fails_closed_without_official_tag_and_verified_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            prep = prepare_upgrade_candidate(
                project_root=dst,
                target_tag="v3.0.0",
                target_version="3.0.0",
                target_tag_object_sha="b" * 40,
                target_peeled_commit=head,
                standards_root=ROOT,
            )
            self.assertIn(prep["status"], ("CANDIDATE_GENERATED", "BLOCK", "NOT_VERIFIABLE"))
            if prep["status"] == "CANDIDATE_GENERATED":
                validation = validate_upgrade_candidate(
                    project_root=dst,
                    standards_root=ROOT,
                    target_tag="v3.0.0",
                )
                self.assertEqual(validation["status"], "NOT_VERIFIABLE")
                self.assertTrue(any("CONSUMER_VALIDATION_EVIDENCE_MISSING" in item for item in validation["errors"]))

            prom = promote_upgrade(
                project_root=dst,
                target_tag="v3.0.0",
                target_version="3.0.0",
                target_tag_object_sha="b" * 40,
                target_peeled_commit=head,
                approval_record={"approval_status": "OWNER_APPROVED"},
                ci_status="PASS",
                standards_root=ROOT,
            )
            self.assertEqual(prom["status"], "UPGRADE_BLOCKED")
            self.assertIn("UNTRUSTED_CI_OVERRIDE", prom.get("reason", ""))

    # =========================================================================
    # D. Approval Authenticity Tests
    # =========================================================================
    def test_d1_coding_agent_self_ai_approved_rejected(self) -> None:
        forged = {
            "schema_version": "1.0.0",
            "task_id": "TASK-FORGE-001",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "candidate_commit": BASELINE_COMMIT,
            "content_sha256": "sha256:" + "1" * 64,
            "approval_scope": "AI_APPROVABLE",
            "reviewer_type": "CODING_AGENT",
            "review_result": "AI_APPROVED",
            "approval_status": "AI_APPROVED",
            "approved_at": "2026-11-05T10:00:00Z",
            "approval_reference": "self-approved",
        }
        ok, errs = validate_approval_record(record=forged)
        self.assertFalse(ok)
        self.assertTrue(any("SELF_APPROVAL_FORBIDDEN" in e or "APPROVAL_SCHEMA_VIOLATION" in e for e in errs))

    def test_d2_coding_agent_self_owner_approved_rejected(self) -> None:
        forged_owner = {
            "schema_version": "1.0.0",
            "task_id": "TASK-FORGE-002",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "candidate_commit": BASELINE_COMMIT,
            "content_sha256": "sha256:" + "2" * 64,
            "decision_scope": "OWNER_MANDATORY",
            "approval_scope": "OWNER_MANDATORY",
            "reviewer_type": "OWNER",
            "review_result": "OWNER_APPROVED",
            "approval_status": "OWNER_APPROVED",
            "approved_at": "2026-11-05T10:00:00Z",
            "approval_reference": "forged-owner-approval",
            "chatgpt_review": {
                "reviewer": "ChatGPT",
                "reviewed_at": "2026-11-05T09:50:00Z",
                "review_result": "OWNER_APPROVAL_REQUIRED",
                "review_reference": "chatgpt://review/1",
                "candidate_commit": BASELINE_COMMIT,
                "content_sha256": "sha256:" + "2" * 64,
                "summary": "Review completed",
            },
            "owner_approval": {
                "approver": "claude-code",
                "approved_at": "2026-11-05T10:00:00Z",
                "approval_channel": "CHATGPT_CHAT_APPROVAL",
                "approval_reference": "forged-owner-approval",
                "approved_decision_ids": ["D1"],
                "candidate_commit": BASELINE_COMMIT,
                "content_sha256": "sha256:" + "2" * 64,
                "decision": "OWNER_APPROVED",
            },
        }
        ok, errs = validate_approval_record(record=forged_owner)
        self.assertFalse(ok)
        self.assertTrue(any("SELF_OWNER_APPROVAL_FORBIDDEN" in e for e in errs), f"Got: {errs}")

    def test_d3_chatgpt_review_bound_to_commit_and_sha256(self) -> None:
        doc_text = "---\ndocument_id: DOC-1\n---\n# Body content\n"
        body_hash = compute_markdown_body_sha256(doc_text)
        rec = {
            "schema_version": "1.0.0",
            "task_id": "TASK-AI-001",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "candidate_commit": BASELINE_COMMIT,
            "content_sha256": body_hash,
            "decision_scope": "AI_APPROVABLE",
            "approval_scope": "AI_APPROVABLE",
            "reviewer_type": "CHATGPT_INDEPENDENT_REVIEW",
            "review_result": "AI_APPROVED",
            "approval_status": "AI_APPROVED",
            "approved_at": "2026-11-05T10:00:00Z",
            "approval_reference": "chatgpt://review/session-123",
            "chatgpt_review": {
                "reviewer": "ChatGPT",
                "reviewed_at": "2026-11-05T10:00:00Z",
                "review_result": "AI_APPROVED",
                "review_reference": "chatgpt://review/session-123",
                "candidate_commit": BASELINE_COMMIT,
                "content_sha256": body_hash,
                "summary": "Independent review passed",
            },
            "owner_approval": None,
        }
        ok, errs = validate_approval_record(
            record=rec,
            target_content=doc_text,
            expected_commit=BASELINE_COMMIT,
            repo_root=ROOT,
        )
        self.assertFalse(ok)
        self.assertTrue(any("UNVERIFIABLE_APPROVAL_PROVENANCE" in e for e in errs), f"Got: {errs}")

    def test_d4_owner_chat_approval_bound_to_decisions_and_sha256(self) -> None:
        doc_text = "---\ndocument_id: DOC-2\n---\n# Architecture Change\n"
        body_hash = compute_markdown_body_sha256(doc_text)
        rec = {
            "schema_version": "1.0.0",
            "task_id": "TASK-OWNER-001",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "candidate_commit": BASELINE_COMMIT,
            "content_sha256": body_hash,
            "decision_scope": "OWNER_MANDATORY",
            "approval_scope": "OWNER_MANDATORY",
            "reviewer_type": "OWNER",
            "review_result": "OWNER_APPROVED",
            "approval_status": "OWNER_APPROVED",
            "approved_at": "2026-11-05T10:30:00Z",
            "approval_reference": "chatgpt://owner/decision-D1-D5",
            "chatgpt_review": {
                "reviewer": "ChatGPT",
                "reviewed_at": "2026-11-05T10:20:00Z",
                "review_result": "OWNER_APPROVAL_REQUIRED",
                "review_reference": "chatgpt://review/99",
                "candidate_commit": BASELINE_COMMIT,
                "content_sha256": body_hash,
                "summary": "Independent review requires Owner decision",
            },
            "owner_approval": {
                "approver": "xiefeifeihu",
                "approved_at": "2026-11-05T10:30:00Z",
                "approval_channel": "CHATGPT_CHAT_APPROVAL",
                "approval_reference": "chatgpt://owner/decision-D1-D5",
                "approved_decision_ids": ["D1", "D2", "D3", "D4", "D5"],
                "candidate_commit": BASELINE_COMMIT,
                "content_sha256": body_hash,
                "decision": "OWNER_APPROVED",
            },
        }
        ok, errs = validate_approval_record(
            record=rec,
            target_content=doc_text,
            expected_commit=BASELINE_COMMIT,
            repo_root=ROOT,
        )
        self.assertFalse(ok)
        self.assertTrue(any("UNVERIFIABLE_APPROVAL_PROVENANCE" in e for e in errs), f"Got: {errs}")

    def test_d6_frontmatter_metadata_change_invalidates_canonical_digest(self) -> None:
        original = "---\ndocument_id: DOC-HASH-001\nstatus: IN_REVIEW\n---\n# Body\n"
        changed = "---\ndocument_id: DOC-HASH-001\nstatus: ACTIVE\n---\n# Body\n"
        self.assertNotEqual(
            compute_markdown_body_sha256(original),
            compute_markdown_body_sha256(changed),
            "Decision-relevant Frontmatter changes must invalidate the canonical digest",
        )

    def test_d5_content_or_commit_change_invalidates_prior_approval(self) -> None:
        doc_text = "---\ndocument_id: DOC-3\n---\n# Original Content\n"
        body_hash = compute_markdown_body_sha256(doc_text)
        rec = {
            "schema_version": "1.0.0",
            "task_id": "TASK-STALE-001",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "candidate_commit": BASELINE_COMMIT,
            "content_sha256": body_hash,
            "decision_scope": "AI_APPROVABLE",
            "approval_scope": "AI_APPROVABLE",
            "reviewer_type": "CHATGPT_INDEPENDENT_REVIEW",
            "review_result": "AI_APPROVED",
            "approval_status": "AI_APPROVED",
            "approved_at": "2026-11-05T10:00:00Z",
            "approval_reference": "chatgpt://review/stale-test",
            "chatgpt_review": {
                "reviewer": "ChatGPT",
                "reviewed_at": "2026-11-05T10:00:00Z",
                "review_result": "AI_APPROVED",
                "review_reference": "chatgpt://review/stale-test",
                "candidate_commit": BASELINE_COMMIT,
                "content_sha256": body_hash,
                "summary": "Independent review passed",
            },
            "owner_approval": None,
        }
        # Modify document content after approval
        modified_doc = "---\ndocument_id: DOC-3\n---\n# Tampered Content After Approval\n"
        ok_mod, errs_mod = validate_approval_record(record=rec, target_content=modified_doc)
        self.assertFalse(ok_mod)
        self.assertTrue(any("APPROVAL_INVALIDATED_BY_CONTENT_CHANGE" in e for e in errs_mod))

        # Modify commit SHA after approval
        ok_commit, errs_commit = validate_approval_record(
            record=rec,
            target_content=doc_text,
            expected_commit="ba25353ec0f2ba28f187a356ebaeda0cb13e2edd",
        )
        self.assertFalse(ok_commit)
        self.assertTrue(any("APPROVAL_INVALIDATED_BY_COMMIT_CHANGE" in e for e in errs_commit))

    # =========================================================================
    # E. Cross-Platform Tests
    # =========================================================================
    def test_e1_no_hardcoded_local_paths_in_tools(self) -> None:
        tools_dir = ROOT / "tools"
        forbidden_patterns = ["D:/Projects", "D:\\Projects", "C:/Users", "C:\\Users"]
        for py_file in sorted(tools_dir.rglob("*.py")):
            content = py_file.read_text(encoding="utf-8")
            for pat in forbidden_patterns:
                self.assertNotIn(
                    pat.lower(),
                    content.lower(),
                    f"Hardcoded machine-specific path '{pat}' found in {py_file.relative_to(ROOT)}",
                )



    # =========================================================================
    # F. Explicit Tests A through R (Prompt Section 11 Requirements)
    # =========================================================================
    def test_f_a_cannot_promote_without_ci_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            app = {"schema_version": "1.0.0", "task_id": "T", "repository": "xiefeifeihu/AI-Engineering-Standards", "candidate_commit": head, "content_sha256": "sha256:" + "0"*64, "approval_scope": "AI_APPROVABLE", "reviewer_type": "CHATGPT", "review_result": "AI_APPROVED", "approval_status": "AI_APPROVED", "approved_at": "2026-11-05T00:00:00Z", "approval_reference": "ref"}
            res = promote_upgrade(project_root=dst, target_tag="v3.0.0", target_version="3.0.0", target_tag_object_sha="a"*40, target_peeled_commit=head, approval_record=app, ci_status="NOT_VERIFIABLE", standards_root=ROOT)
            self.assertEqual(res["status"], "UPGRADE_BLOCKED")
            self.assertIn("CI_NOT_PASSED", res.get("reason", ""))

    def test_f_b_faking_ci_status_pass_cannot_promote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            # Mismatched candidate_commit in approval
            bad_app = {"schema_version": "1.0.0", "task_id": "T", "repository": "xiefeifeihu/AI-Engineering-Standards", "candidate_commit": "1"*40, "content_sha256": "sha256:" + "0"*64, "approval_scope": "AI_APPROVABLE", "reviewer_type": "CHATGPT", "review_result": "AI_APPROVED", "approval_status": "AI_APPROVED", "approved_at": "2026-11-05T00:00:00Z", "approval_reference": "ref"}
            res = promote_upgrade(project_root=dst, target_tag="v3.0.0", target_version="3.0.0", target_tag_object_sha="a"*40, target_peeled_commit=head, approval_record=bad_app, ci_status="PASS", standards_root=ROOT)
            self.assertEqual(res["status"], "UPGRADE_BLOCKED")
            self.assertIn("UNTRUSTED_CI_OVERRIDE", res.get("reason", ""))

    def test_f_c_arbitrary_github_fork_cannot_be_official_standards_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_f = dst / "standards.lock.json"
            lk = json.loads(lock_f.read_text(encoding="utf-8"))
            lk["repository"] = "arbitrary-fork/AI-Engineering-Standards"
            lock_f.write_text(json.dumps(lk), encoding="utf-8")
            res = verify_project_lock(project_root=dst, standards_root=ROOT)
            self.assertEqual(res["status"], "BLOCK")
            self.assertTrue(any("UNOFFICIAL_STANDARDS_REPO_FORBIDDEN" in e for e in res["errors"]))

    def test_f_d_chatgpt_fake_string_cannot_pass_approval_authenticity_check(self) -> None:
        rec = {
            "schema_version": "1.0.0",
            "task_id": "T",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "candidate_commit": BASELINE_COMMIT,
            "content_sha256": "sha256:" + "0"*64,
            "approval_scope": "AI_APPROVABLE",
            "reviewer_type": "CHATGPT",
            "review_result": "AI_APPROVED",
            "approval_status": "AI_APPROVED",
            "approved_at": "2026-11-05T00:00:00Z",
            "approval_reference": "chatgpt://fake-unverified-uri",
        }
        ok, errs = validate_approval_record(rec, verify_provenance=True)
        self.assertFalse(ok)
        self.assertTrue(any("UNVERIFIABLE_APPROVAL_PROVENANCE" in e for e in errs))

    def test_f_e_owner_fake_name_cannot_pass_approval_authenticity_check(self) -> None:
        rec = {
            "schema_version": "1.0.0",
            "task_id": "T",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "candidate_commit": BASELINE_COMMIT,
            "content_sha256": "sha256:" + "0"*64,
            "approval_scope": "OWNER_MANDATORY",
            "reviewer_type": "OWNER",
            "review_result": "OWNER_APPROVED",
            "approval_status": "OWNER_APPROVED",
            "approved_at": "2026-11-05T00:00:00Z",
            "approval_reference": "chatgpt://owner/fake-name",
            "owner_approval": {
                "approver": "xiefeifeihu",
                "approved_at": "2026-11-05T00:00:00Z",
                "approval_channel": "CHATGPT_CHAT_APPROVAL",
                "approval_reference": "chatgpt://fake",
                "candidate_commit": BASELINE_COMMIT,
                "content_sha256": "sha256:" + "0"*64,
                "decision": "OWNER_APPROVED",
            }
        }
        ok, errs = validate_approval_record(rec, verify_provenance=True)
        self.assertFalse(ok)
        self.assertTrue(any("UNVERIFIABLE_APPROVAL_PROVENANCE" in e for e in errs))

    def test_f_f_modifying_frontmatter_invalidates_prior_approval(self) -> None:
        doc_v1 = "---\ndocument_id: DOC-T\nproject_id: p\n---\n# Content\n"
        from tools.validate_approval_contract import compute_canonical_document_sha256
        sha_v1 = compute_canonical_document_sha256(doc_v1)
        doc_v2 = "---\ndocument_id: DOC-T\nproject_id: p-modified\n---\n# Content\n"
        sha_v2 = compute_canonical_document_sha256(doc_v2)
        self.assertNotEqual(sha_v1, sha_v2)
        rec = {
            "schema_version": "1.0.0",
            "task_id": "T",
            "repository": "xiefeifeihu/AI-Engineering-Standards",
            "candidate_commit": BASELINE_COMMIT,
            "content_sha256": sha_v1,
            "approval_scope": "AI_APPROVABLE",
            "reviewer_type": "CHATGPT",
            "review_result": "AI_APPROVED",
            "approval_status": "AI_APPROVED",
            "approved_at": "2026-11-05T00:00:00Z",
            "approval_reference": "ref",
        }
        ok, errs = validate_approval_record(rec, target_content=doc_v2)
        self.assertFalse(ok)
        self.assertTrue(any("APPROVAL_INVALIDATED_BY_CONTENT_CHANGE" in e for e in errs))

    def test_f_g_target_tag_and_commit_mismatch_must_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            app = {"schema_version": "1.0.0", "task_id": "T", "repository": "xiefeifeihu/AI-Engineering-Standards", "candidate_commit": "0"*40, "content_sha256": "sha256:" + "0"*64, "approval_scope": "AI_APPROVABLE", "reviewer_type": "CHATGPT", "review_result": "AI_APPROVED", "approval_status": "AI_APPROVED", "approved_at": "2026-11-05T00:00:00Z", "approval_reference": "ref"}
            res = promote_upgrade(project_root=dst, target_tag="v3.0.0", target_version="3.0.0", target_tag_object_sha="a"*40, target_peeled_commit=head, approval_record=app, ci_status="PASS", standards_root=ROOT)
            self.assertEqual(res["status"], "UPGRADE_BLOCKED")
            self.assertIn("UNTRUSTED_CI_OVERRIDE", res.get("reason", ""))

    def test_f_h_target_tag_not_in_official_main_ancestry_must_block(self) -> None:
        res = discover_latest_official_tag(repository="fake-user/repo")
        self.assertEqual(res["status"], "BLOCK")
        self.assertIn("UNOFFICIAL_REPOSITORY_FORBIDDEN", res.get("reason", ""))

    def test_f_i_ci_missing_or_failure_cannot_pass(self) -> None:
        st, _, _ = check_remote_main_ci("xiefeifeihu/AI-Engineering-Standards", BASELINE_COMMIT, ci_status_override="FAIL")
        self.assertEqual(st, "FAIL")
        st2, _, _ = check_remote_main_ci("xiefeifeihu/AI-Engineering-Standards", BASELINE_COMMIT, ci_status_override="NOT_VERIFIABLE")
        self.assertEqual(st2, "NOT_VERIFIABLE")

    def test_f_j_prepare_upgrade_failure_must_return_nonzero_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            from tools.standards_sync.cli import main as cli_main
            # Non-existent project root causes failure
            rc = cli_main(["--standards-root", str(ROOT), "prepare-upgrade", "--project-root", str(dst / "non_existent"), "--target-tag", "v3.0.0", "--target-version", "3.0.0", "--target-tag-object-sha", "a"*40, "--target-peeled-commit", "b"*40])
            self.assertNotEqual(rc, 0)

    def test_f_k_discover_network_unavailable_must_return_not_verifiable(self) -> None:
        res = discover_latest_official_tag(simulate_offline=True)
        self.assertEqual(res["status"], "NOT_VERIFIABLE")

    def test_f_l_missing_manifest_or_lock_must_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            res = verify_project_lock(project_root=dst, standards_root=ROOT)
            self.assertEqual(res["status"], "BLOCK")

    def test_f_m_missing_handoff_test_log_cannot_pass(self) -> None:
        from tools.generate_handoff import build_handoff_payload
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            fake_pass = {"verification_status": "PASS", "command": "cmd", "exit_code": 0, "passed_count": 1, "failed_count": 0, "evidence_ref": "non_existent.log"}
            ok, errs, _, _ = build_handoff_payload(project_root=dst, task_id="T", test_results_override=fake_pass, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("HANDOFF_TEST_PASS_MISSING_EVIDENCE_FILE" in e for e in errs))

    def test_f_n_missing_baseline_source_evidence_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            fake_fact = {"repository": "r", "source_path": "p", "source_commit": BASELINE_COMMIT, "evidence_ref": "non_existent_file.txt", "observed_at": "2026-11-05T00:00:00Z", "verification_status": "PASS"}
            ok, errs, _, _ = build_engineering_baseline(project_root=dst, standards_root=ROOT, test_fact_override=fake_fact)
            self.assertFalse(ok)
            self.assertTrue(any("BASELINE_MISSING_EVIDENCE_FILE" in e for e in errs))

    def test_f_o_current_doc_active_but_approval_in_review_must_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            p = dst / "docs" / "PRODUCT-BASELINE.md"
            from tools.validate_approval_contract import compute_canonical_document_sha256
            txt = p.read_text(encoding="utf-8").replace('status: "IN_REVIEW"', 'status: "ACTIVE"')
            c_sha = compute_canonical_document_sha256(txt)
            txt = re.sub(r'content_sha256:\s*"[^"]+"', f'content_sha256: "{c_sha}"', txt)
            p.write_text(txt, encoding="utf-8")
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT)
            self.assertFalse(ok)
            self.assertTrue(any("ACTIVE_DOC_WITH_IN_REVIEW_APPROVAL" in e or "FRONTMATTER_SCHEMA_VIOLATION" in e for e in errs))

    def test_f_p_temporary_handoff_must_correctly_mark_temporary(self) -> None:
        from tools.generate_handoff import build_handoff_payload
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            ok, errs, payload, md = build_handoff_payload(project_root=dst, task_id="TASK-TEMP-001", handoff_type="TEMPORARY", standards_root=ROOT)
            self.assertTrue(ok)
            self.assertEqual(payload["handoff_type"], "TEMPORARY")
            self.assertIn("HANDOFF_TYPE=TEMPORARY", md)

    def test_f_q_historical_task_snapshot_must_not_be_overwritten(self) -> None:
        from tools.generate_handoff import write_handoff_files
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            ok1, _, written1 = write_handoff_files(project_root=dst, task_id="TASK-SNAP-001", standards_root=ROOT)
            self.assertTrue(ok1)
            # Second call without overwrite must fail
            ok2, errs2, _ = write_handoff_files(project_root=dst, task_id="TASK-SNAP-001", standards_root=ROOT)
            self.assertFalse(ok2)
            self.assertTrue(any("HISTORICAL_HANDOFF_OVERWRITE_FORBIDDEN" in e for e in errs2))

            # Verify semantic negative checks on handoff
            handoff_fixture = """
TASK_ID=Std-013-V3-0-0-REISSUE-VERIFY-ONLY-INTEGRITY
COMMIT_HASH=4538b8ba29cb9413782c4197e73bddab64849d82

## 1. 当前 Git 状态与分支身份 (`git_state`)
- **本地 HEAD (`local_head`)**：`4538b8ba29cb9413782c4197e73bddab64849d82`

## 3. 实际测试结果汇总 (`test_results`)
- **通过 / 失败用例数**：`216 / 0`

## 4. 远端 CI 关联 (`ci_run`)
- **Run ID (`run_id`)**：`42783497089`
- **Push Run ID**：`42783497089`
- **PR Run ID**：`42783504258`
- **关联 Commit (`commit`)**：`4538b8ba29cb9413782c4197e73bddab64849d82`
- **核验状态 (`verification_status`)**：`PASS`

### 4.1 六项 CI / 快照核心概念区分 (`STD-034` / `STD-035`)
- **3. 最近一次已验证 CI Commit**：`4538b8ba29cb9413782c4197e73bddab64849d82`（Run 42783497089 Push / Run 42783504258 PR #9 双平台全绿，216 tests PASS）
- **4. 当前候选 Commit**：`60a03bc1ca03e03ad1e88f3036ec06bcbe748837`

### 4.2 v3.0.0 一次性重发发布与 Tag 状态追踪
- **PR 状态 (`pr_status`)**：`DRAFT`
- **旧 Tag 删除状态 (`old_tag_deleted`)**：`true`
- **发布流程状态 (`release_flow_status`)**：`IN_PROGRESS`
"""
            # Negative 1: Old CI Run ID fails
            self.assertTrue(bool(verify_handoff_semantic_facts(handoff_fixture, {"ci_run_id": "42772211734"})))
            # Negative 2: Wrong CI Commit fails
            self.assertTrue(bool(verify_handoff_semantic_facts(handoff_fixture, {"ci_commit": "1111111111111111111111111111111111111111"})))
            # Negative 3: PASS changed to NOT_VERIFIABLE fails
            self.assertTrue(bool(verify_handoff_semantic_facts(handoff_fixture, {"ci_status": "NOT_VERIFIABLE"})))
            # Negative 4: 216 tests changed to 215 tests fails
            self.assertTrue(bool(verify_handoff_semantic_facts(handoff_fixture, {"test_count": 215})))
            # Negative 5: Old candidate commit fails
            self.assertTrue(bool(verify_handoff_semantic_facts(handoff_fixture, {"candidate_commit": "c52f97a52c9080bc76e05684f996fd89653e1fa8"})))
            # Negative 6: Old tag status changed to not deleted fails
            self.assertTrue(bool(verify_handoff_semantic_facts(handoff_fixture, {"old_tag_deleted": False})))

    def test_f_r_doc_source_path_not_existing_in_source_commit_must_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            head = _copy_minimal_valid_project(dst)
            from tools.validate_approval_contract import compute_canonical_document_sha256
            # Create a doc whose path and history_reference do not exist at source_commit
            bad_doc = dst / "docs" / "NON-EXISTENT-NEW-DOC.md"
            sample_txt = (dst / "docs" / "PRODUCT-BASELINE.md").read_text(encoding="utf-8")
            bad_txt = sample_txt.replace("DOC-STANDARDS-PRODUCT-BASELINE", "DOC-STANDARDS-NON-EXISTENT")
            bad_txt = bad_txt.replace('history_reference: "CHANGELOG.md"', 'history_reference: "docs/does_not_exist.md"')
            c_sha = compute_canonical_document_sha256(bad_txt)
            bad_txt = re.sub(r'content_sha256:\s*"[^"]+"', f'content_sha256: "{c_sha}"', bad_txt)
            bad_doc.write_text(bad_txt, encoding="utf-8")
            ok, errs = run_collection_validation(project_root=dst, standards_root=ROOT, verify_source_paths=True)
            self.assertFalse(ok)
            self.assertTrue(any("SOURCE_PATH_MISSING_AT_COMMIT" in e for e in errs), f"Got: {errs}")

    # =========================================================================
    # G. Transactional Safety & Fault Injection Tests (P0 Remediation)
    # =========================================================================
    def test_g1_transactional_two_file_update_recovers_when_second_replace_fails(self) -> None:
        """P0 Fault Injection: When the second os.replace fails, the first file is restored,
        temporary/backup files are cleaned up, and both files remain completely consistent.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"
            self.assertTrue(lock_path.exists())
            self.assertTrue(manifest_path.exists())

            orig_lock = lock_path.read_text(encoding="utf-8")
            orig_manifest = manifest_path.read_text(encoding="utf-8")

            # Target new lock and manifest updates
            new_lock_obj = json.loads(orig_lock)
            new_lock_obj["version"] = "3.0.0"
            new_lock_obj["tag"] = "v3.0.0"
            new_manifest_std = {"version": "3.0.0", "tag": "v3.0.0"}

            # Fault injection: Succeed on call 1 (lock), fail on call 2 (manifest)
            call_count = 0
            def fault_replace(src: Path, target: Path) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("Injected disk I/O failure on second os.replace")
                os.replace(src, target)

            ok, err = execute_transactional_two_file_update(
                project_root=dst,
                new_lock=new_lock_obj,
                new_manifest_standards=new_manifest_std,
                replace_fn=fault_replace,
            )

            self.assertFalse(ok)
            self.assertIn("TRANSACTION_FAILED", str(err))
            self.assertIn("State successfully rolled back", str(err))

            # Verify files are identical to their pre-transaction states
            self.assertEqual(lock_path.read_text(encoding="utf-8"), orig_lock)
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), orig_manifest)

            # Verify no temporary or backup files left behind
            self.assertFalse((dst / "standards.lock.json.tmp").exists())
            self.assertFalse((dst / "standards.lock.json.bak").exists())
            self.assertFalse((dst / "engineering-manifest.yaml.tmp").exists())
            self.assertFalse((dst / "engineering-manifest.yaml.bak").exists())

    def test_g2_transactional_rollback_recovers_when_second_replace_fails(self) -> None:
        """P0 Fault Injection: When rollback_lock encounters failure on the second replace,
        it aborts cleanly, rolls back changes, and preserves original lock and manifest.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"

            # Populate a valid previous lock entry so rollback is possible
            lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
            lock_data["previous_locks"] = [
                {
                    "repository": "xiefeifeihu/AI-Engineering-Standards",
                    "version": "2.10.0",
                    "tag": "v2.10.0",
                    "tag_object_sha": "3" * 40,
                    "peeled_commit": "4" * 40,
                    "locked_at": "2026-04-12T00:00:00Z",
                    "lock_reason": "Prior official release v2.10.0",
                    "approval_evidence_ref": "CHANGELOG.md",
                    "ci_verification_status": "PASS",
                }
            ]
            lock_path.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")

            pre_lock = lock_path.read_text(encoding="utf-8")
            pre_manifest = manifest_path.read_text(encoding="utf-8")

            call_count = 0
            def fault_replace(src: Path, target: Path) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise PermissionError("Injected permission denied on manifest replacement")
                os.replace(src, target)

            res = rollback_lock(project_root=dst, replace_fn=fault_replace)
            self.assertEqual(res["status"], "FAIL")
            self.assertIn("TRANSACTION_FAILED", res.get("reason", ""))

            # Both files must remain in exact pre-rollback state
            self.assertEqual(lock_path.read_text(encoding="utf-8"), pre_lock)
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), pre_manifest)
            self.assertFalse((dst / "standards.lock.json.tmp").exists())
            self.assertFalse((dst / "standards.lock.json.bak").exists())

    def test_g3_transactional_two_file_update_post_replace_inconsistency_fails(self) -> None:
        """P0 Transactional Safety: If post-replace verification detects inconsistency
        between lock and manifest, the transaction aborts and rolls back to pre-transaction state.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"
            orig_lock = lock_path.read_text(encoding="utf-8")
            orig_manifest = manifest_path.read_text(encoding="utf-8")

            new_lock_obj = json.loads(orig_lock)
            new_lock_obj["version"] = "3.0.0"
            new_lock_obj["tag"] = "v3.0.0"
            # Intentionally mismatched manifest standards version
            new_manifest_std = {"version": "2.99.0", "tag": "v2.99.0"}

            ok, err = execute_transactional_two_file_update(
                project_root=dst,
                new_lock=new_lock_obj,
                new_manifest_standards=new_manifest_std,
            )
            self.assertFalse(ok)
            self.assertIn("POST_REPLACE_INCONSISTENCY", str(err))

            # Restored to pre-transaction state
            self.assertEqual(lock_path.read_text(encoding="utf-8"), orig_lock)
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), orig_manifest)

    def test_g4_transactional_two_file_update_fails_when_manifest_missing(self) -> None:
        """P0-A Transaction Safety: When engineering-manifest.yaml is missing,
        execute_transactional_two_file_update fails fast with MISSING_MANIFEST and
        never modifies standards.lock.json or leaves temporary files.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"
            manifest_path.unlink()  # Remove manifest completely

            orig_lock = lock_path.read_text(encoding="utf-8")
            new_lock_obj = json.loads(orig_lock)
            new_lock_obj["version"] = "3.0.0"

            ok, err = execute_transactional_two_file_update(
                project_root=dst,
                new_lock=new_lock_obj,
                new_manifest_standards={"version": "3.0.0"},
            )
            self.assertFalse(ok)
            self.assertIn("MISSING_MANIFEST", str(err))

            # Lock file must remain untouched
            self.assertEqual(lock_path.read_text(encoding="utf-8"), orig_lock)
            self.assertFalse((dst / "standards.lock.json.tmp").exists())
            self.assertFalse((dst / "standards.lock.json.bak").exists())
            self.assertFalse((dst / ".standards_sync_tx.json").exists())

    def test_g5_transactional_two_file_update_fails_when_manifest_standards_invalid(self) -> None:
        """P0-A Transaction Safety: When engineering-manifest.yaml lacks a valid standards
        mapping, execute_transactional_two_file_update blocks with INVALID_MANIFEST_STANDARDS
        without modifying lock or creating orphaned files.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"

            # Corrupt standards block in manifest
            manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            del manifest_data["standards"]
            manifest_path.write_text(yaml.safe_dump(manifest_data), encoding="utf-8")

            orig_lock = lock_path.read_text(encoding="utf-8")
            orig_manifest = manifest_path.read_text(encoding="utf-8")
            new_lock_obj = json.loads(orig_lock)
            new_lock_obj["version"] = "3.0.0"

            ok, err = execute_transactional_two_file_update(
                project_root=dst,
                new_lock=new_lock_obj,
                new_manifest_standards={"version": "3.0.0"},
            )
            self.assertFalse(ok)
            self.assertIn("INVALID_MANIFEST_STANDARDS", str(err))

            # Files must remain unchanged
            self.assertEqual(lock_path.read_text(encoding="utf-8"), orig_lock)
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), orig_manifest)
            self.assertFalse((dst / "standards.lock.json.tmp").exists())
            self.assertFalse((dst / "standards.lock.json.bak").exists())

    def test_g6_transactional_recovery_failure_preserves_backup_files(self) -> None:
        """P0-B Fault Injection: When recovery fails during rollback (e.g. disk failure during restore),
        the .bak files are strictly preserved and NOT deleted, guaranteeing human recovery data is retained.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"
            lock_bak = dst / "standards.lock.json.bak"

            orig_lock = lock_path.read_text(encoding="utf-8")
            new_lock_obj = json.loads(orig_lock)
            new_lock_obj["version"] = "3.0.0"

            # Injected fault: fails on replace AND shutil.copy2 fails during recovery
            import os
            def fault_replace(src: Path, target: Path) -> None:
                if "manifest" in str(target):
                    raise OSError("Injected disk failure on manifest replace")
                os.replace(src, target)

            import shutil
            orig_copy2 = shutil.copy2
            def fault_copy2(src, target, *args, **kwargs):
                if str(src).endswith(".bak"):
                    raise PermissionError("Injected permission error preventing backup restoration")
                return orig_copy2(src, target, *args, **kwargs)

            from unittest.mock import patch
            with patch("tools.standards_sync.core.shutil.copy2", side_effect=fault_copy2):
                ok, err = execute_transactional_two_file_update(
                    project_root=dst,
                    new_lock=new_lock_obj,
                    new_manifest_standards={"version": "3.0.0", "tag": "v3.0.0"},
                    replace_fn=fault_replace,
                )

            self.assertFalse(ok)
            self.assertIn("RECOVERY_FAILED", str(err))

            # Backup file MUST BE PRESERVED on disk!
            self.assertTrue(lock_bak.exists(), "Backup file must NOT be deleted when recovery failed!")
            self.assertEqual(lock_bak.read_text(encoding="utf-8"), orig_lock)

    def test_g7_interrupted_transaction_detection_and_recovery(self) -> None:
        """P0-B Fault Injection: When an external process kill or crash interrupts an update mid-flight,
        detect_interrupted_transaction flags the pending state, and recover_interrupted_transaction
        restores the original snapshot and removes residual backups and journals.
        """
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"
            lock_bak = dst / "standards.lock.json.bak"
            manifest_bak = dst / "engineering-manifest.yaml.bak"
            journal_path = dst / ".standards_sync_tx.json"

            orig_lock_bytes = lock_path.read_bytes()
            orig_manifest_bytes = manifest_path.read_bytes()
            orig_lock = orig_lock_bytes.decode("utf-8")
            orig_manifest = orig_manifest_bytes.decode("utf-8")

            # Simulate interrupted state: backups written, lock replaced, manifest not replaced
            lock_bak.write_bytes(orig_lock_bytes)
            manifest_bak.write_bytes(orig_manifest_bytes)
            lock_path.write_text("{\"version\": \"partially-written\"}\n", encoding="utf-8")

            lock_sha = hashlib.sha256(orig_lock_bytes).hexdigest()
            manifest_sha = hashlib.sha256(orig_manifest_bytes).hexdigest()
            journal_data = {
                "tx_id": "tx-123",
                "phase": "LOCK_REPLACED",
                "operation_type": "UPDATE",
                "status": "IN_PROGRESS",
                "has_orig_lock": True,
                "has_orig_manifest": True,
                "orig_lock_sha256": lock_sha,
                "orig_manifest_sha256": manifest_sha,
                "backup_lock_sha256": lock_sha,
                "backup_manifest_sha256": manifest_sha,
                "targets": {
                    "lock_path": "standards.lock.json",
                    "manifest_path": "engineering-manifest.yaml",
                    "lock_tmp": "standards.lock.json.tmp",
                    "manifest_tmp": "engineering-manifest.yaml.tmp",
                    "lock_bak": "standards.lock.json.bak",
                    "manifest_bak": "engineering-manifest.yaml.bak",
                },
            }
            journal_path.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")

            # 1. Detect interrupted state
            status = detect_interrupted_transaction(dst)
            self.assertTrue(status.get("interrupted"))
            self.assertIn("standards.lock.json.bak", status.get("backup_files", []))
            self.assertIn("engineering-manifest.yaml.bak", status.get("backup_files", []))

            # 2. Recover from interrupted state
            ok, err = recover_interrupted_transaction(dst)
            self.assertTrue(ok, err)
            self.assertEqual(lock_path.read_bytes(), orig_lock_bytes)
            self.assertEqual(manifest_path.read_bytes(), orig_manifest_bytes)

            # 3. Verify clean state after recovery
            status_after = detect_interrupted_transaction(dst)
            self.assertFalse(status_after.get("interrupted"))
            self.assertFalse(lock_bak.exists())
            self.assertFalse(manifest_bak.exists())
            self.assertFalse(journal_path.exists())

    def test_g8_interrupted_transaction_detected_in_verify_lock_and_blocks(self) -> None:
        """P0-B Governance Gate: verify_project_lock detects interrupted transaction backups
        and blocks with INTERRUPTED_TRANSACTION_PENDING.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_bak = dst / "standards.lock.json.bak"
            lock_bak.write_text("{}", encoding="utf-8")

            res = verify_project_lock(project_root=dst, standards_root=ROOT)
            self.assertEqual(res.get("status"), "BLOCK")
            self.assertTrue(any("INTERRUPTED_TRANSACTION_PENDING" in e for e in res.get("errors", [])), res)

    def test_g9_original_lock_backup_missing_fails(self) -> None:
        """P0 Fault Injection G9: When original lock backup is missing, recovery blocks and preserves journal."""
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"
            manifest_bak = dst / "engineering-manifest.yaml.bak"
            journal_path = dst / ".standards_sync_tx.json"

            orig_man_bytes = manifest_path.read_bytes()
            manifest_bak.write_bytes(orig_man_bytes)

            journal_data = {
                "tx_id": "tx-g9",
                "phase": "LOCK_REPLACED",
                "operation_type": "UPDATE",
                "status": "IN_PROGRESS",
                "has_orig_lock": True,
                "has_orig_manifest": True,
                "orig_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
                "orig_manifest_sha256": hashlib.sha256(orig_man_bytes).hexdigest(),
                "backup_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
                "backup_manifest_sha256": hashlib.sha256(orig_man_bytes).hexdigest(),
                "targets": {"lock_path": "standards.lock.json"},
            }
            journal_path.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")

            ok, err = recover_interrupted_transaction(dst)
            self.assertFalse(ok)
            self.assertIn("MISSING_REQUIRED_BACKUP", str(err))
            self.assertTrue(journal_path.exists())

            # verify_project_lock must also block
            res = verify_project_lock(dst, standards_root=ROOT, allow_offline=True)
            self.assertEqual(res.get("status"), "BLOCK")

    def test_g10_original_manifest_backup_missing_fails(self) -> None:
        """P0 Fault Injection G10: When original manifest backup is missing, recovery blocks and preserves journal."""
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            lock_bak = dst / "standards.lock.json.bak"
            manifest_path = dst / "engineering-manifest.yaml"
            journal_path = dst / ".standards_sync_tx.json"

            orig_lock_bytes = lock_path.read_bytes()
            lock_bak.write_bytes(orig_lock_bytes)

            journal_data = {
                "tx_id": "tx-g10",
                "phase": "LOCK_REPLACED",
                "operation_type": "UPDATE",
                "status": "IN_PROGRESS",
                "has_orig_lock": True,
                "has_orig_manifest": True,
                "orig_lock_sha256": hashlib.sha256(orig_lock_bytes).hexdigest(),
                "orig_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "backup_lock_sha256": hashlib.sha256(orig_lock_bytes).hexdigest(),
                "backup_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "targets": {"manifest_path": "engineering-manifest.yaml"},
            }
            journal_path.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")

            ok, err = recover_interrupted_transaction(dst)
            self.assertFalse(ok)
            self.assertIn("MISSING_REQUIRED_BACKUP", str(err))
            self.assertTrue(journal_path.exists())
            self.assertTrue(lock_bak.exists())

            res = verify_project_lock(dst, standards_root=ROOT, allow_offline=True)
            self.assertEqual(res.get("status"), "BLOCK")

    def test_g11_backup_sha256_tampered_fails(self) -> None:
        """P0 Fault Injection G11: When backup file SHA256 has been tampered, recovery blocks and preserves evidence."""
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"
            lock_bak = dst / "standards.lock.json.bak"
            manifest_bak = dst / "engineering-manifest.yaml.bak"
            journal_path = dst / ".standards_sync_tx.json"

            orig_lock_bytes = lock_path.read_bytes()
            orig_man_bytes = manifest_path.read_bytes()
            lock_bak.write_bytes(orig_lock_bytes)
            # Tamper manifest backup
            manifest_bak.write_bytes(b"tampered content\n")

            journal_data = {
                "tx_id": "tx-g11",
                "phase": "LOCK_REPLACED",
                "operation_type": "UPDATE",
                "status": "IN_PROGRESS",
                "has_orig_lock": True,
                "has_orig_manifest": True,
                "orig_lock_sha256": hashlib.sha256(orig_lock_bytes).hexdigest(),
                "orig_manifest_sha256": hashlib.sha256(orig_man_bytes).hexdigest(),
                "backup_lock_sha256": hashlib.sha256(orig_lock_bytes).hexdigest(),
                "backup_manifest_sha256": hashlib.sha256(orig_man_bytes).hexdigest(),
                "targets": {},
            }
            journal_path.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")

            ok, err = recover_interrupted_transaction(dst)
            self.assertFalse(ok)
            self.assertIn("BACKUP_SHA256_MISMATCH", str(err))
            # Evidence must be preserved
            self.assertTrue(journal_path.exists())
            self.assertTrue(manifest_bak.exists())
            self.assertEqual(manifest_bak.read_bytes(), b"tampered content\n")

            res = verify_project_lock(dst, standards_root=ROOT, allow_offline=True)
            self.assertEqual(res.get("status"), "BLOCK")

    def test_g12_initialization_mode_crash_recovers_cleanly(self) -> None:
        """P0 Fault Injection G12: When initialization crashes, recovery removes newly created files only,
        never deleting unrelated historical files, and restores clean state.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            # Historical unrelated file
            history_file = dst / "README.md"
            history_file.write_text("# Historical Project\n", encoding="utf-8")

            # In initialization, lock and manifest did NOT exist beforehand
            lock_path = dst / "standards.lock.json"
            lock_tmp = dst / "standards.lock.json.tmp"
            manifest_path = dst / "engineering-manifest.yaml"
            journal_path = dst / ".standards_sync_tx.json"

            lock_path.write_text("{\"created\": \"in-initialization\"}\n", encoding="utf-8")
            lock_tmp.write_text("{\"tmp\": true}\n", encoding="utf-8")

            journal_data = {
                "tx_id": "tx-g12",
                "phase": "LOCK_REPLACED",
                "operation_type": "INITIALIZATION",
                "status": "IN_PROGRESS",
                "has_orig_lock": False,
                "has_orig_manifest": False,
                "created_new_lock": True,
                "created_new_manifest": True,
                "orig_lock_sha256": None,
                "orig_manifest_sha256": None,
                "backup_lock_sha256": None,
                "backup_manifest_sha256": None,
                "targets": {
                    "lock_path": "standards.lock.json",
                    "manifest_path": "engineering-manifest.yaml",
                },
            }
            journal_path.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")

            ok, err = recover_interrupted_transaction(dst)
            self.assertTrue(ok, err)

            # Verified: newly created lock was deleted
            self.assertFalse(lock_path.exists())
            self.assertFalse(lock_tmp.exists())
            self.assertFalse(manifest_path.exists())
            self.assertFalse(journal_path.exists())

            # Verified: historical unrelated file strictly preserved
            self.assertTrue(history_file.exists())
            self.assertEqual(history_file.read_text(encoding="utf-8"), "# Historical Project\n")

    def test_g13_recovery_process_secondary_failure_preserves_evidence(self) -> None:
        """P0 Fault Injection G13: When a secondary failure occurs during restoration,
        backups and journal are preserved, and status is recorded as RECOVERY_FAILED.
        """
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"
            lock_bak = dst / "standards.lock.json.bak"
            manifest_bak = dst / "engineering-manifest.yaml.bak"
            journal_path = dst / ".standards_sync_tx.json"

            orig_lock_bytes = lock_path.read_bytes()
            orig_man_bytes = manifest_path.read_bytes()
            lock_bak.write_bytes(orig_lock_bytes)
            manifest_bak.write_bytes(orig_man_bytes)

            journal_data = {
                "tx_id": "tx-g13",
                "phase": "LOCK_REPLACED",
                "operation_type": "UPDATE",
                "status": "IN_PROGRESS",
                "has_orig_lock": True,
                "has_orig_manifest": True,
                "orig_lock_sha256": hashlib.sha256(orig_lock_bytes).hexdigest(),
                "orig_manifest_sha256": hashlib.sha256(orig_man_bytes).hexdigest(),
                "backup_lock_sha256": hashlib.sha256(orig_lock_bytes).hexdigest(),
                "backup_manifest_sha256": hashlib.sha256(orig_man_bytes).hexdigest(),
                "targets": {},
            }
            journal_path.write_text(json.dumps(journal_data, indent=2), encoding="utf-8")

            def broken_restore(src: Path, target: Path) -> None:
                raise PermissionError("Injected secondary disk restore failure")

            ok, err = recover_interrupted_transaction(dst, restore_fn=broken_restore)
            self.assertFalse(ok)
            self.assertIn("RECOVERY_FAILED", str(err))

            # Both backups and journal must remain preserved
            self.assertTrue(lock_bak.exists())
            self.assertTrue(manifest_bak.exists())
            self.assertTrue(journal_path.exists())
            j_after = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(j_after.get("status"), "RECOVERY_FAILED")

    def test_g14_recovery_idempotency_subsequent_call_succeeds(self) -> None:
        """P0 Fault Injection G14: Executing recovery again after successful completion is idempotent and succeeds cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"
            orig_lock = lock_path.read_text(encoding="utf-8")
            orig_manifest = manifest_path.read_text(encoding="utf-8")

            # Clean state without pending transaction
            ok1, err1 = recover_interrupted_transaction(dst)
            self.assertTrue(ok1, err1)
            self.assertIsNone(err1)

            # Second call
            ok2, err2 = recover_interrupted_transaction(dst)
            self.assertTrue(ok2, err2)
            self.assertIsNone(err2)

            # File contents intact
            self.assertEqual(lock_path.read_text(encoding="utf-8"), orig_lock)
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), orig_manifest)

    def test_g15_corrupt_journal_blocks_recovery_and_preserves_backups(self) -> None:
        """P0 Fault Injection G15: Corrupt or malformed journal blocks recovery with CORRUPT_TRANSACTION_JOURNAL
        and preserves backup files.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_bak = dst / "standards.lock.json.bak"
            manifest_bak = dst / "engineering-manifest.yaml.bak"
            journal_path = dst / ".standards_sync_tx.json"

            lock_bak.write_text("{\"backup\": true}\n", encoding="utf-8")
            manifest_bak.write_text("backup: true\n", encoding="utf-8")
            journal_path.write_text("{invalid-json-content", encoding="utf-8")

            ok, err = recover_interrupted_transaction(dst)
            self.assertFalse(ok)
            self.assertIn("CORRUPT_TRANSACTION_JOURNAL", str(err))

            # Backup files must be preserved
            self.assertTrue(lock_bak.exists())
            self.assertTrue(manifest_bak.exists())
            self.assertTrue(journal_path.exists())

            # verify_project_lock must also block
            res = verify_project_lock(dst, standards_root=ROOT, allow_offline=True)
            self.assertEqual(res.get("status"), "BLOCK")


    # =========================================================================
    # H. Release Discovery & Semantic Tests (P2 Remediation)
    # =========================================================================
    def test_h1_official_release_defined_by_annotated_git_tags_not_github_releases(self) -> None:
        """P2 Regression: Official releases are discovered from Git Annotated Tags,
        never from GitHub /releases/latest REST API objects.
        """
        res = discover_latest_official_tag(
            standards_root=ROOT,
            remote_url=str(ROOT),
            ci_status_override="PASS",
        )
        self.assertIn(res["status"], ("PASS", "NOT_VERIFIABLE"))
        self.assertIn(res["tag"], ("v2.11.0", "v3.0.0"))
        if res["tag"] == "v3.0.0":
            self.assertEqual(res["version"], "3.0.0")
            self.assertEqual(res["peeled_commit"], "8b223019c254e0edeb94576b94af46c1e48b0316")
            self.assertEqual(res["tag_object_sha"], "8256bb384e62894219db0992a2cb57e16d4fa8cd")
        else:
            self.assertEqual(res["version"], "2.11.0")
            self.assertEqual(res["tag_object_sha"], BASELINE_TAG_OBJ)
            self.assertEqual(res["peeled_commit"], BASELINE_COMMIT)
        # Tag object SHA must differ from peeled commit SHA (proving annotated tag, not lightweight)
        self.assertNotEqual(res["tag_object_sha"], res["peeled_commit"])

    def test_h2_discover_never_mutates_local_project_files(self) -> None:
        """P2 Regression: Discover operation is strictly read-only and does not modify
        standards.lock.json or engineering-manifest.yaml in consumer projects.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            _copy_minimal_valid_project(dst)
            lock_path = dst / "standards.lock.json"
            manifest_path = dst / "engineering-manifest.yaml"
            pre_lock = lock_path.read_text(encoding="utf-8")
            pre_manifest = manifest_path.read_text(encoding="utf-8")

            _ = discover_latest_official_tag(
                standards_root=ROOT,
                remote_url=str(ROOT),
                ci_status_override="PASS",
            )

            self.assertEqual(lock_path.read_text(encoding="utf-8"), pre_lock)
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), pre_manifest)


    # =========================================================================
    # Owner GitHub Review Provenance Tests (P1-C Remediation)
    # =========================================================================
    def test_owner_github_review_provenance_success_path(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-09T10:00:00Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "owner_approval": {
                "approved_decision_ids": ["D-001"],
                "approved_at": "2026-11-09T10:00:00Z",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
            },
            "approval_event": {
                "event_type": "GITHUB_PR_REVIEW_EVENT",
                "provenance_type": "GITHUB_PR_REVIEW",
                "event_id": "123456",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8/reviews/123456",
                },
            },
        }
        review_data = {
            "id": 123456,
            "user": {"login": "xiefeifeihu"},
            "state": "APPROVED",
            "commit_id": commit,
            "body": f"MAPPING_DIGEST={digest}\nAPPROVED_DECISION_IDS=D-001\nAPPROVAL_SCOPE=GATE_MAPPING",
            "submitted_at": "2026-11-09T10:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(review_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "VERIFIED", errors)
        self.assertEqual(errors, [])

    def test_owner_review_agent_self_approval_fails(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-09T10:00:00Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "owner_approval": {
                "approved_decision_ids": ["D-001"],
                "approved_at": "2026-11-09T10:00:00Z",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
            },
            "approval_event": {
                "event_type": "GITHUB_PR_REVIEW_EVENT",
                "provenance_type": "GITHUB_PR_REVIEW",
                "event_id": "123456",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8/reviews/123456",
                },
            },
        }
        review_data = {
            "id": 123456,
            "user": {"login": "CODING_AGENT"},
            "state": "APPROVED",
            "commit_id": commit,
            "body": f"MAPPING_DIGEST={digest}\nAPPROVED_DECISION_IDS=D-001\nAPPROVAL_SCOPE=GATE_MAPPING",
            "submitted_at": "2026-11-09T10:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(review_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("AGENT_SELF_APPROVAL_FORBIDDEN" in e for e in errors), errors)

    def test_owner_review_mapping_digest_change_fails(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-09T10:00:00Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "owner_approval": {
                "approved_decision_ids": ["D-001"],
                "approved_at": "2026-11-09T10:00:00Z",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
            },
            "approval_event": {
                "event_type": "GITHUB_PR_REVIEW_EVENT",
                "provenance_type": "GITHUB_PR_REVIEW",
                "event_id": "123456",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8/reviews/123456",
                },
            },
        }
        review_data = {
            "id": 123456,
            "user": {"login": "xiefeifeihu"},
            "state": "APPROVED",
            "commit_id": commit,
            "body": f"MAPPING_DIGEST={'f' * 64}\nAPPROVED_DECISION_IDS=D-001\nAPPROVAL_SCOPE=GATE_MAPPING",
            "submitted_at": "2026-11-09T10:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(review_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("APPROVAL_REVIEW_CONTENT_BINDING_MISSING" in e for e in errors), errors)

    def test_owner_review_commit_mismatch_fails(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-09T10:00:00Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "owner_approval": {
                "approved_decision_ids": ["D-001"],
                "approved_at": "2026-11-09T10:00:00Z",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
            },
            "approval_event": {
                "event_type": "GITHUB_PR_REVIEW_EVENT",
                "provenance_type": "GITHUB_PR_REVIEW",
                "event_id": "123456",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8/reviews/123456",
                },
            },
        }
        review_data = {
            "id": 123456,
            "user": {"login": "xiefeifeihu"},
            "state": "APPROVED",
            "commit_id": "b" * 40,
            "body": f"MAPPING_DIGEST={digest}\nAPPROVED_DECISION_IDS=D-001\nAPPROVAL_SCOPE=GATE_MAPPING",
            "submitted_at": "2026-11-09T10:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(review_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("APPROVAL_REVIEW_COMMIT_MISMATCH" in e for e in errors), errors)

    def test_owner_review_revoked_dismissed_fails(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-09T10:00:00Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "owner_approval": {
                "approved_decision_ids": ["D-001"],
                "approved_at": "2026-11-09T10:00:00Z",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
            },
            "approval_event": {
                "event_type": "GITHUB_PR_REVIEW_EVENT",
                "provenance_type": "GITHUB_PR_REVIEW",
                "event_id": "123456",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8/reviews/123456",
                },
            },
        }
        review_data = {
            "id": 123456,
            "user": {"login": "xiefeifeihu"},
            "state": "DISMISSED",
            "commit_id": commit,
            "body": f"MAPPING_DIGEST={digest}\nAPPROVED_DECISION_IDS=D-001\nAPPROVAL_SCOPE=GATE_MAPPING",
            "submitted_at": "2026-11-09T10:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(review_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("APPROVAL_REVIEW_NOT_APPROVED" in e for e in errors), errors)

    def test_owner_review_scope_mismatch_fails(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-09T10:00:00Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "owner_approval": {
                "approved_decision_ids": ["D-001"],
                "approved_at": "2026-11-09T10:00:00Z",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
            },
            "approval_event": {
                "event_type": "GITHUB_PR_REVIEW_EVENT",
                "provenance_type": "GITHUB_PR_REVIEW",
                "event_id": "123456",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "ENGINEERING_BASELINE",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8/reviews/123456",
                },
            },
        }
        review_data = {
            "id": 123456,
            "user": {"login": "xiefeifeihu"},
            "state": "APPROVED",
            "commit_id": commit,
            "body": f"MAPPING_DIGEST={digest}\nAPPROVED_DECISION_IDS=D-001\nAPPROVAL_SCOPE=GATE_MAPPING",
            "submitted_at": "2026-11-09T10:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(review_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("EVENT_SCOPE_MISMATCH" in e for e in errors), errors)

    def test_owner_review_time_mismatch_fails(self) -> None:
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-09T10:00:00Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "owner_approval": {
                "approved_decision_ids": ["D-001"],
                "approved_at": "2026-11-09T10:00:00Z",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
            },
            "approval_event": {
                "event_type": "GITHUB_PR_REVIEW_EVENT",
                "provenance_type": "GITHUB_PR_REVIEW",
                "event_id": "123456",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8/reviews/123456",
                },
            },
        }
        review_data = {
            "id": 123456,
            "user": {"login": "xiefeifeihu"},
            "state": "APPROVED",
            "commit_id": commit,
            "body": f"MAPPING_DIGEST={digest}\nAPPROVED_DECISION_IDS=D-001\nAPPROVAL_SCOPE=GATE_MAPPING",
            "submitted_at": "2026-11-09T12:00:00Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(review_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("APPROVAL_TIME_MISMATCH" in e for e in errors), errors)

    # =========================================================================
    # G16-G21: Concurrency and Cleanup Robustness (P1-D Remediation)
    # =========================================================================
    def test_owner_merge_event_approved_verifies(self) -> None:
        """Section II: Owner PR Merge Event positive verification path."""
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-10T02:09:26Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "owner_approval": {
                "approved_decision_ids": ["D-001"],
                "approved_at": "2026-11-10T02:09:26Z",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
            },
            "approval_event": {
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "event_id": "8",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8",
                },
            },
        }
        pr_data = {
            "number": 8,
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": commit},
            "merged_at": "2026-11-10T02:09:26Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(pr_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "VERIFIED", errors)
        self.assertEqual(errors, [])

    def test_owner_merge_event_unmerged_pr_fails(self) -> None:
        """Section II: Unmerged PR must fail with APPROVAL_PR_NOT_MERGED; status stays OWNER_APPROVAL_REQUIRED."""
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-10T02:09:26Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "owner_approval": {
                "approved_decision_ids": ["D-001"],
                "approved_at": "2026-11-10T02:09:26Z",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
            },
            "approval_event": {
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "event_id": "8",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8",
                },
            },
        }
        pr_data = {
            "number": 8,
            "merged": False,
            "merged_by": None,
            "base": {"ref": "main"},
            "head": {"sha": commit},
            "merged_at": None,
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(pr_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("APPROVAL_PR_NOT_MERGED" in e for e in errors), errors)

    def test_owner_merge_event_merged_by_non_owner_fails(self) -> None:
        """Section II: PR merged by unauthorized third-party user must fail."""
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-10T02:09:26Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "approval_event": {
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "event_id": "8",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8",
                },
            },
        }
        pr_data = {
            "number": 8,
            "merged": True,
            "merged_by": {"login": "attacker-user"},
            "base": {"ref": "main"},
            "head": {"sha": commit},
            "merged_at": "2026-11-10T02:09:26Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(pr_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("APPROVAL_ACTOR_MISMATCH" in e for e in errors), errors)

    def test_owner_merge_event_base_branch_not_main_fails(self) -> None:
        """Section II: PR merged into non-main branch must fail."""
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-10T02:09:26Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "approval_event": {
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "event_id": "8",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8",
                },
            },
        }
        pr_data = {
            "number": 8,
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "feat/other"},
            "head": {"sha": commit},
            "merged_at": "2026-11-10T02:09:26Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(pr_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("APPROVAL_PR_BASE_BRANCH_MISMATCH" in e for e in errors), errors)

    def test_owner_merge_event_head_commit_mismatch_fails(self) -> None:
        """Section II: PR head commit must match candidate commit."""
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-10T02:09:26Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "approval_event": {
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "event_id": "8",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "xiefeifeihu",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8",
                },
            },
        }
        pr_data = {
            "number": 8,
            "merged": True,
            "merged_by": {"login": "xiefeifeihu"},
            "base": {"ref": "main"},
            "head": {"sha": "b" * 40},
            "merged_at": "2026-11-10T02:09:26Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(pr_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("APPROVAL_PR_HEAD_COMMIT_MISMATCH" in e for e in errors), errors)

    def test_owner_merge_event_agent_actor_fails(self) -> None:
        """Section II: Agent or bot actor cannot perform Owner merge approval."""
        from unittest.mock import patch
        commit = "a" * 40
        digest = "1a5152a6773f0ceccc961fe528c0187d95c642bff2978eec586260d9e8453f25"
        repo = "xiefeifeihu/AI-Engineering-Standards"
        record = {
            "schema_version": "1.0.0",
            "repository": repo,
            "candidate_commit": commit,
            "content_sha256": f"sha256:{digest}",
            "approved_at": "2026-11-10T02:09:26Z",
            "approval_scope": "GATE_MAPPING",
            "approval_status": "OWNER_APPROVED",
            "approval_event": {
                "event_type": "GITHUB_PR_MERGE_EVENT",
                "provenance_type": "GITHUB_PR_MERGE",
                "event_id": "8",
                "candidate_commit": commit,
                "content_sha256": f"sha256:{digest}",
                "approval_scope": "GATE_MAPPING",
                "actor_identity": {
                    "identity_type": "GITHUB_USER",
                    "identity_id": "claude-code",
                    "service_provenance_ref": f"https://api.github.com/repos/{repo}/pulls/8",
                },
            },
        }
        pr_data = {
            "number": 8,
            "merged": True,
            "merged_by": {"login": "claude-code"},
            "base": {"ref": "main"},
            "head": {"sha": commit},
            "merged_at": "2026-11-10T02:09:26Z",
        }
        with patch.dict(os.environ, {"GITHUB_TOKEN": "mock-token"}):
            with patch("urllib.request.urlopen", return_value=FakeResponse(pr_data)):
                status, errors = verify_approval_event_provenance(record)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("AGENT_SELF_APPROVAL_FORBIDDEN" in e for e in errors), errors)

    def test_g16_concurrent_upgrade_processes_blocked_by_mutex(self) -> None:
        from tools.standards_sync.core import _os_lock_file
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            (dst / "standards.lock.json").write_text("{}", encoding="utf-8")
            (dst / "engineering-manifest.yaml").write_text("standards: {}", encoding="utf-8")
            lock_file = dst / ".standards_sync.lock"
            fd_holder = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
            os.write(fd_holder, json.dumps({"pid": 999999, "tx_id": "other-process"}).encode("utf-8"))
            _os_lock_file(fd_holder)
            try:
                ok, err = execute_transactional_two_file_update(
                    project_root=dst,
                    new_lock={"version": "3.0.0"},
                    new_manifest_standards={"version": "3.0.0"},
                )
                self.assertFalse(ok)
                self.assertIn("TRANSACTION_CONCURRENCY_BLOCKED", str(err))
            finally:
                os.close(fd_holder)

    def test_g17_upgrade_and_recover_concurrent_blocked(self) -> None:
        from tools.standards_sync.core import _os_lock_file
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            lock_file = dst / ".standards_sync.lock"
            fd_holder = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
            os.write(fd_holder, json.dumps({"pid": 999999, "tx_id": "other-process"}).encode("utf-8"))
            _os_lock_file(fd_holder)
            try:
                ok, err = recover_interrupted_transaction(dst)
                self.assertFalse(ok)
                self.assertIn("TRANSACTION_CONCURRENCY_BLOCKED", str(err))
            finally:
                os.close(fd_holder)

    def test_g18_backup_deletion_failure_preserves_committed_cleanup_pending(self) -> None:
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            (dst / "standards.lock.json").write_text(json.dumps({"version": "2.11.0", "tag": "v2.11.0", "peeled_commit": "abc"}), encoding="utf-8")
            (dst / "engineering-manifest.yaml").write_text("standards:\n  version: '2.11.0'\n  tag: 'v2.11.0'\n  peeled_commit: 'abc'\n", encoding="utf-8")

            new_lock = {"version": "3.0.0", "tag": "v3.0.0", "peeled_commit": "xyz"}
            new_manifest = {"version": "3.0.0", "tag": "v3.0.0", "peeled_commit": "xyz"}

            orig_unlink = Path.unlink
            def failing_unlink(path_self, *args, **kwargs):
                if path_self.name.endswith(".bak"):
                    raise PermissionError(f"Mocked unlink failure on {path_self.name}")
                return orig_unlink(path_self, *args, **kwargs)

            with patch.object(Path, "unlink", side_effect=failing_unlink, autospec=True):
                ok, err = execute_transactional_two_file_update(dst, new_lock, new_manifest)

            self.assertFalse(ok)
            self.assertIn("TRANSACTION_CLEANUP_PENDING", str(err))
            journal_path = dst / ".standards_sync_tx.json"
            self.assertTrue(journal_path.exists())
            jdata = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(jdata.get("status"), "CLEANUP_PENDING")
            self.assertEqual(jdata.get("phase"), "COMMITTED")
            curr_lock = json.loads((dst / "standards.lock.json").read_text(encoding="utf-8"))
            self.assertEqual(curr_lock.get("version"), "3.0.0")

    def test_g19_journal_deletion_failure_preserves_committed_cleanup_pending(self) -> None:
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            (dst / "standards.lock.json").write_text(json.dumps({"version": "2.11.0", "tag": "v2.11.0", "peeled_commit": "abc"}), encoding="utf-8")
            (dst / "engineering-manifest.yaml").write_text("standards:\n  version: '2.11.0'\n  tag: 'v2.11.0'\n  peeled_commit: 'abc'\n", encoding="utf-8")

            new_lock = {"version": "3.0.0", "tag": "v3.0.0", "peeled_commit": "xyz"}
            new_manifest = {"version": "3.0.0", "tag": "v3.0.0", "peeled_commit": "xyz"}

            orig_unlink = Path.unlink
            def failing_unlink(path_self, *args, **kwargs):
                if path_self.name == ".standards_sync_tx.json":
                    raise PermissionError("Mocked unlink failure on journal")
                return orig_unlink(path_self, *args, **kwargs)

            with patch.object(Path, "unlink", side_effect=failing_unlink, autospec=True):
                ok, err = execute_transactional_two_file_update(dst, new_lock, new_manifest)

            self.assertFalse(ok)
            self.assertIn("TRANSACTION_CLEANUP_PENDING", str(err))
            journal_path = dst / ".standards_sync_tx.json"
            self.assertTrue(journal_path.exists())
            jdata = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(jdata.get("status"), "CLEANUP_PENDING")
            self.assertEqual(jdata.get("phase"), "COMMITTED")

    def test_g20_crash_after_committed_phase_recovers_via_cleanup_not_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            (dst / "standards.lock.json").write_text(json.dumps({"version": "3.0.0"}), encoding="utf-8")
            (dst / "engineering-manifest.yaml").write_text("standards:\n  version: '3.0.0'\n", encoding="utf-8")
            (dst / "standards.lock.json.bak").write_text(json.dumps({"version": "2.11.0"}), encoding="utf-8")
            (dst / "engineering-manifest.yaml.bak").write_text("standards:\n  version: '2.11.0'\n", encoding="utf-8")

            journal_data = {
                "tx_id": "tx-123",
                "phase": "COMMITTED",
                "operation_type": "UPDATE",
                "status": "CLEANUP_PENDING",
                "has_orig_lock": True,
                "has_orig_manifest": True,
                "targets": {
                    "lock_path": "standards.lock.json",
                    "manifest_path": "engineering-manifest.yaml",
                    "lock_bak": "standards.lock.json.bak",
                    "manifest_bak": "engineering-manifest.yaml.bak",
                },
            }
            (dst / ".standards_sync_tx.json").write_text(json.dumps(journal_data), encoding="utf-8")

            ok, err = recover_interrupted_transaction(dst)
            self.assertTrue(ok, err)
            self.assertFalse((dst / ".standards_sync_tx.json").exists())
            self.assertFalse((dst / "standards.lock.json.bak").exists())
            self.assertFalse((dst / "engineering-manifest.yaml.bak").exists())
            curr_lock = json.loads((dst / "standards.lock.json").read_text(encoding="utf-8"))
            self.assertEqual(curr_lock.get("version"), "3.0.0")

    def test_g21_cleanup_retry_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            ok, err = recover_interrupted_transaction(dst)
            self.assertTrue(ok)
            self.assertIsNone(err)

            ok2, err2 = recover_interrupted_transaction(dst)
            self.assertTrue(ok2)
            self.assertIsNone(err2)

    def test_g22_real_multiprocess_lock_concurrency_blocked(self) -> None:
        """P1-A: Real multi-process concurrency test. When parent process holds lock,
        child process attempting to acquire lock is blocked by mutual exclusion.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            ok, err, fd = acquire_transaction_lock(dst, "parent-tx", timeout=1.0)
            self.assertTrue(ok)
            try:
                child_code = f"""
import sys
from pathlib import Path
sys.path.insert(0, r"{ROOT}")
from tools.standards_sync.core import acquire_transaction_lock
ok, err, fd = acquire_transaction_lock(Path(r"{dst}"), "child-tx", timeout=0.2)
if not ok and "TRANSACTION_CONCURRENCY_BLOCKED" in str(err):
    print("CHILD_BLOCKED_OK")
else:
    print(f"CHILD_UNEXPECTED: ok={{ok}}, err={{err}}")
"""
                res = subprocess.run([sys.executable, "-c", child_code], capture_output=True, text=True)
                self.assertIn("CHILD_BLOCKED_OK", res.stdout.strip())
            finally:
                release_transaction_lock(dst, fd)

    def test_g23_stale_lock_recovered_after_holder_process_killed(self) -> None:
        """P1-A: Stale lock recovery when holder process is forcefully terminated (killed)
        mid-transaction. recover_interrupted_transaction safely detects dead process PID,
        checks transaction identity against journal, and restores backups.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            lock_path = dst / "standards.lock.json"
            man_path = dst / "engineering-manifest.yaml"
            lock_path.write_text(json.dumps({"version": "2.11.0", "tag": "v2.11.0", "peeled_commit": "abc"}), encoding="utf-8")
            man_path.write_text("standards:\n  version: '2.11.0'\n  tag: 'v2.11.0'\n  peeled_commit: 'abc'\n", encoding="utf-8")

            child_code = f"""
import sys, time, json, hashlib
from pathlib import Path
sys.path.insert(0, r"{ROOT}")
from tools.standards_sync.core import acquire_transaction_lock
dst = Path(r"{dst}")
ok, err, fd = acquire_transaction_lock(dst, "crashed-tx-001", timeout=1.0)
if not ok:
    print("LOCK_FAILED")
    sys.exit(1)

lock_bytes = (dst / "standards.lock.json").read_bytes()
man_bytes = (dst / "engineering-manifest.yaml").read_bytes()
(dst / "standards.lock.json.bak").write_bytes(lock_bytes)
(dst / "engineering-manifest.yaml.bak").write_bytes(man_bytes)

(dst / "standards.lock.json").write_text(json.dumps({{"version": "corrupted"}}), encoding="utf-8")

journal = {{
    "tx_id": "crashed-tx-001",
    "phase": "PREPARED",
    "operation_type": "UPDATE",
    "status": "IN_PROGRESS",
    "has_orig_lock": True,
    "has_orig_manifest": True,
    "orig_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
    "orig_manifest_sha256": hashlib.sha256(man_bytes).hexdigest(),
    "backup_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
    "backup_manifest_sha256": hashlib.sha256(man_bytes).hexdigest(),
    "targets": {{
        "lock_path": "standards.lock.json",
        "manifest_path": "engineering-manifest.yaml",
        "lock_bak": "standards.lock.json.bak",
        "manifest_bak": "engineering-manifest.yaml.bak",
    }}
}}
(dst / ".standards_sync_tx.json").write_text(json.dumps(journal), encoding="utf-8")
print("CHILD_READY", flush=True)
while True:
    time.sleep(1)
"""
            proc = subprocess.Popen([sys.executable, "-c", child_code], stdout=subprocess.PIPE, text=True)
            ready_line = proc.stdout.readline()
            self.assertEqual(ready_line.strip(), "CHILD_READY")

            proc.kill()
            proc.stdout.close()
            proc.wait()

            self.assertTrue((dst / ".standards_sync.lock").exists())

            rec_ok, rec_err = recover_interrupted_transaction(dst)
            self.assertTrue(rec_ok, f"Recovery failed: {rec_err}")

            res_lock = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(res_lock.get("version"), "2.11.0")
            self.assertFalse((dst / ".standards_sync_tx.json").exists())
            self.assertTrue((dst / ".standards_sync.lock").exists())
            # Persistent lock file exists and can immediately be acquired by a new transaction
            acq_ok, acq_err, fd = acquire_transaction_lock(dst, "test-tx-recovered")
            self.assertTrue(acq_ok, f"Failed to acquire lock: {acq_err}")
            self.assertIsNotNone(fd)
            release_transaction_lock(dst, fd)

    def test_g24_journal_path_traversal_targets_blocked(self) -> None:
        """P1-B: Fault injection for journal path traversal. Targets with '../' traversal
        are detected and blocked with CORRUPT_TRANSACTION_JOURNAL.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            outside_file = dst.parent / "escape.txt"
            outside_file.write_text("outside data", encoding="utf-8")
            try:
                journal = {
                    "tx_id": "malicious-tx-001",
                    "phase": "PREPARED",
                    "operation_type": "UPDATE",
                    "status": "IN_PROGRESS",
                    "has_orig_lock": True,
                    "has_orig_manifest": True,
                    "targets": {
                        "lock_path": "../escape.txt",
                        "manifest_path": "engineering-manifest.yaml",
                        "lock_bak": "../escape.txt",
                        "manifest_bak": "engineering-manifest.yaml.bak",
                    }
                }
                (dst / ".standards_sync_tx.json").write_text(json.dumps(journal), encoding="utf-8")
                det = detect_interrupted_transaction(dst)
                self.assertTrue(det.get("journal_corrupt"))
                rec_ok, rec_err = recover_interrupted_transaction(dst)
                self.assertFalse(rec_ok)
                self.assertIn("CORRUPT_TRANSACTION_JOURNAL", str(rec_err))
                self.assertIn("TARGET_TRAVERSAL", str(rec_err))
                self.assertEqual(outside_file.read_text(encoding="utf-8"), "outside data")
            finally:
                if outside_file.exists():
                    outside_file.unlink()

    def test_g25_journal_absolute_and_drive_path_targets_blocked(self) -> None:
        """P1-B: Fault injection for absolute, drive letter, and UNC paths in journal targets."""
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            bad_targets = [
                "/etc/passwd",
                "C:\\Windows\\system32\\cmd.exe",
                "\\\\server\\share\\file.txt",
            ]
            for bad in bad_targets:
                journal = {
                    "tx_id": "bad-target-tx",
                    "phase": "PREPARED",
                    "operation_type": "UPDATE",
                    "status": "IN_PROGRESS",
                    "has_orig_lock": True,
                    "has_orig_manifest": True,
                    "targets": {
                        "lock_path": bad,
                        "manifest_path": "engineering-manifest.yaml",
                        "lock_bak": "standards.lock.json.bak",
                        "manifest_bak": "engineering-manifest.yaml.bak",
                    }
                }
                (dst / ".standards_sync_tx.json").write_text(json.dumps(journal), encoding="utf-8")
                det = detect_interrupted_transaction(dst)
                self.assertTrue(det.get("journal_corrupt"))
                rec_ok, rec_err = recover_interrupted_transaction(dst)
                self.assertFalse(rec_ok)
                self.assertIn("CORRUPT_TRANSACTION_JOURNAL", str(rec_err))


    def test_g26_journal_internal_normal_files_blocked(self) -> None:
        """Section III-B: Journal path whitelist strictly allows only fixed target files
        (standards.lock.json, engineering-manifest.yaml, and their .bak backups).
        Internal normal files (e.g. README.md, docs/RELEASE-OPERATIONS.md, config files)
        or unknown target keys are blocked with CORRUPT_TRANSACTION_JOURNAL and left untouched.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            readme_file = dst / "README.md"
            readme_file.write_text("# Important Project README\nDo not overwrite!", encoding="utf-8")
            docs_dir = dst / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            doc_file = docs_dir / "RELEASE-OPERATIONS.md"
            doc_file.write_text("# Sensitive Release Ops", encoding="utf-8")

            bad_cases = [
                {"lock_path": "README.md"},
                {"manifest_path": "docs/RELEASE-OPERATIONS.md"},
                {"unknown_key": "standards.lock.json"},
                {"lock_path": "standards.lock.json", "manifest_path": "config.yaml"},
                {"lock_path": "standards.lock.json", "manifest_path": "engineering-manifest.yaml", "temp_lock": "arbitrary_temp.json"},
            ]
            for case in bad_cases:
                targets = {
                    "lock_path": "standards.lock.json",
                    "manifest_path": "engineering-manifest.yaml",
                    "lock_bak": "standards.lock.json.bak",
                    "manifest_bak": "engineering-manifest.yaml.bak",
                }
                targets.update(case)
                journal = {
                    "tx_id": "malicious-internal-tx",
                    "phase": "PREPARED",
                    "operation_type": "UPDATE",
                    "status": "IN_PROGRESS",
                    "has_orig_lock": True,
                    "has_orig_manifest": True,
                    "targets": targets,
                }
                (dst / ".standards_sync_tx.json").write_text(json.dumps(journal), encoding="utf-8")
                det = detect_interrupted_transaction(dst)
                self.assertTrue(det.get("journal_corrupt"), f"Expected journal_corrupt for {case}")
                rec_ok, rec_err = recover_interrupted_transaction(dst)
                self.assertFalse(rec_ok)
                self.assertIn("CORRUPT_TRANSACTION_JOURNAL", str(rec_err))
                self.assertEqual(readme_file.read_text(encoding="utf-8"), "# Important Project README\nDo not overwrite!")
                self.assertEqual(doc_file.read_text(encoding="utf-8"), "# Sensitive Release Ops")

    def test_g27_transaction_lock_multiprocess_concurrency_and_recovery(self) -> None:
        """Section III-A: Real multi-process concurrency, lock handoff, and crash recovery.
        Verifies:
        1. Lock release and immediate acquisition by another process without race window.
        2. Two processes consecutively executing transactions with persistent lock file.
        3. Stale metadata after abnormal termination is recovered and another process can execute.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            lock_path = dst / "standards.lock.json"
            lock_path.write_text(json.dumps({"version": "2.11.0", "digest": "init"}), encoding="utf-8")
            manifest_path = dst / "engineering-manifest.yaml"
            manifest_path.write_text("standards: {}\n", encoding="utf-8")

            # Part 1: Process 1 acquires lock, signals, waits for trigger, then releases.
            # Process 2 waits for trigger and immediately acquires lock.
            child_proc1 = f"""
import sys, time
from pathlib import Path
sys.path.insert(0, r"{ROOT}")
from tools.standards_sync.core import acquire_transaction_lock, release_transaction_lock

dst = Path(r"{dst}")
ok, err, fd = acquire_transaction_lock(dst, "tx-proc-1")
if not ok:
    print(f"PROC1_ERROR: {{err}}", flush=True)
    sys.exit(1)
print("PROC1_HOLDING", flush=True)
cmd = sys.stdin.readline().strip()
release_transaction_lock(dst, fd)
print("PROC1_RELEASED", flush=True)
"""
            child_proc2 = f"""
import sys, time
from pathlib import Path
sys.path.insert(0, r"{ROOT}")
from tools.standards_sync.core import acquire_transaction_lock, release_transaction_lock

dst = Path(r"{dst}")
cmd = sys.stdin.readline().strip()
ok, err, fd = acquire_transaction_lock(dst, "tx-proc-2")
if ok:
    print("PROC2_ACQUIRED", flush=True)
    release_transaction_lock(dst, fd)
    print("PROC2_RELEASED", flush=True)
else:
    print(f"PROC2_FAILED: {{err}}", flush=True)
    sys.exit(2)
"""
            p1 = subprocess.Popen([sys.executable, "-c", child_proc1], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            line1 = p1.stdout.readline().strip()
            self.assertEqual(line1, "PROC1_HOLDING")

            p2 = subprocess.Popen([sys.executable, "-c", child_proc2], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            # Release p1 and trigger p2 simultaneously
            p1.stdin.write("RELEASE\n")
            p1.stdin.flush()
            p2.stdin.write("ACQUIRE\n")
            p2.stdin.flush()

            out2 = p2.stdout.readline().strip()
            self.assertEqual(out2, "PROC2_ACQUIRED")
            rel1 = p1.stdout.readline().strip()
            self.assertEqual(rel1, "PROC1_RELEASED")
            rel2 = p2.stdout.readline().strip()
            self.assertEqual(rel2, "PROC2_RELEASED")
            p1.wait(timeout=5)
            p2.wait(timeout=5)
            p1.stdin.close()
            p1.stdout.close()
            p2.stdin.close()
            p2.stdout.close()
            self.assertEqual(p1.returncode, 0)
            self.assertEqual(p2.returncode, 0)
            self.assertTrue((dst / ".standards_sync.lock").exists())

            # Part 2: Two processes executing consecutive transactions
            step_code = f"""
import sys, json
from pathlib import Path
sys.path.insert(0, r"{ROOT}")
from tools.standards_sync.core import acquire_transaction_lock, release_transaction_lock

dst = Path(r"{dst}")
tx_name = sys.argv[1]
val = sys.argv[2]
ok, err, fd = acquire_transaction_lock(dst, tx_name)
if not ok:
    print(f"FAILED: {{err}}", flush=True)
    sys.exit(3)
lp = dst / "standards.lock.json"
data = json.loads(lp.read_text(encoding="utf-8"))
data["version"] = val
lp.write_text(json.dumps(data), encoding="utf-8")
release_transaction_lock(dst, fd)
print("SUCCESS", flush=True)
"""
            res_c1 = subprocess.run([sys.executable, "-c", step_code, "tx-c1", "2.12.0"], capture_output=True, text=True)
            self.assertEqual(res_c1.returncode, 0)
            self.assertIn("SUCCESS", res_c1.stdout)
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8")).get("version"), "2.12.0")

            res_c2 = subprocess.run([sys.executable, "-c", step_code, "tx-c2", "3.0.0"], capture_output=True, text=True)
            self.assertEqual(res_c2.returncode, 0)
            self.assertIn("SUCCESS", res_c2.stdout)
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8")).get("version"), "3.0.0")

            # Part 3: Abnormal termination & recovery, then re-execution
            crash_code = f"""
import sys, json, time, hashlib
from pathlib import Path
sys.path.insert(0, r"{ROOT}")
from tools.standards_sync.core import acquire_transaction_lock

dst = Path(r"{dst}")
ok, err, fd = acquire_transaction_lock(dst, "tx-crashed")
if not ok:
    sys.exit(4)
lock_bytes = (dst / "standards.lock.json").read_bytes()
(dst / "standards.lock.json.bak").write_bytes(lock_bytes)
(dst / "standards.lock.json").write_text(json.dumps({{"version": "damaged"}}), encoding="utf-8")
journal = {{
    "tx_id": "tx-crashed",
    "phase": "PREPARED",
    "operation_type": "UPDATE",
    "status": "IN_PROGRESS",
    "has_orig_lock": True,
    "has_orig_manifest": False,
    "orig_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
    "backup_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
    "targets": {{
        "lock_path": "standards.lock.json",
        "lock_bak": "standards.lock.json.bak",
    }}
}}
(dst / ".standards_sync_tx.json").write_text(json.dumps(journal), encoding="utf-8")
print("CRASH_READY", flush=True)
while True:
    time.sleep(0.5)
"""
            p_crash = subprocess.Popen([sys.executable, "-c", crash_code], stdout=subprocess.PIPE, text=True)
            ready = p_crash.stdout.readline().strip()
            self.assertEqual(ready, "CRASH_READY")
            p_crash.kill()
            p_crash.stdout.close()
            p_crash.wait()

            # Recovery
            rec_ok, rec_err = recover_interrupted_transaction(dst)
            self.assertTrue(rec_ok, f"Recovery failed: {rec_err}")
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8")).get("version"), "3.0.0")

            # Post-recovery transaction execution
            res_c3 = subprocess.run([sys.executable, "-c", step_code, "tx-c3", "3.0.1"], capture_output=True, text=True)
            self.assertEqual(res_c3.returncode, 0)
            self.assertIn("SUCCESS", res_c3.stdout)
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8")).get("version"), "3.0.1")

    def test_g28_journal_internal_symlink_to_readme_blocked(self) -> None:
        """Negative test: Journal target pointing via project-internal symlink to README.md is rejected.
        Journal path validation rejects all symbolic links to prevent tampering with regular project files.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp)
            readme_file = dst / "README.md"
            readme_file.write_text("# Sensitive Project README\nDo not overwrite!", encoding="utf-8")
            lock_symlink = dst / "standards.lock.json"

            created_symlink = False
            try:
                lock_symlink.symlink_to(readme_file)
                created_symlink = True
            except OSError:
                # Platform lacks symlink creation privilege (e.g. unprivileged Windows)
                pass

            journal = {
                "tx_id": "malicious-symlink-tx",
                "phase": "PREPARED",
                "operation_type": "UPDATE",
                "status": "IN_PROGRESS",
                "has_orig_lock": True,
                "has_orig_manifest": True,
                "targets": {
                    "lock_path": "standards.lock.json",
                    "manifest_path": "engineering-manifest.yaml",
                    "lock_bak": "standards.lock.json.bak",
                    "manifest_bak": "engineering-manifest.yaml.bak",
                },
            }
            (dst / ".standards_sync_tx.json").write_text(json.dumps(journal), encoding="utf-8")

            if created_symlink:
                ok, path, err = _validate_journal_target(dst, "standards.lock.json", target_key="lock_path", tx_id="malicious-symlink-tx")
                self.assertFalse(ok)
                self.assertIn("TARGET_SYMLINK_PROHIBITED", str(err))

                det = detect_interrupted_transaction(dst)
                self.assertTrue(det.get("journal_corrupt"))
                rec_ok, rec_err = recover_interrupted_transaction(dst)
                self.assertFalse(rec_ok)
                self.assertIn("CORRUPT_TRANSACTION_JOURNAL", str(rec_err))
                self.assertIn("TARGET_SYMLINK_PROHIBITED", str(rec_err))
                self.assertEqual(readme_file.read_text(encoding="utf-8"), "# Sensitive Project README\nDo not overwrite!")
            else:
                orig_is_symlink = Path.is_symlink

                def fake_is_symlink(self_path: Path) -> bool:
                    if self_path.name == "standards.lock.json":
                        return True
                    return orig_is_symlink(self_path)

                with patch.object(Path, "is_symlink", fake_is_symlink):
                    ok, path, err = _validate_journal_target(dst, "standards.lock.json", target_key="lock_path", tx_id="malicious-symlink-tx")
                    self.assertFalse(ok)
                    self.assertIn("TARGET_SYMLINK_PROHIBITED", str(err))

                    det = detect_interrupted_transaction(dst)
                    self.assertTrue(det.get("journal_corrupt"))
                    rec_ok, rec_err = recover_interrupted_transaction(dst)
                    self.assertFalse(rec_ok)
                    self.assertIn("CORRUPT_TRANSACTION_JOURNAL", str(rec_err))
                    self.assertIn("TARGET_SYMLINK_PROHIBITED", str(rec_err))
                    self.assertEqual(readme_file.read_text(encoding="utf-8"), "# Sensitive Project README\nDo not overwrite!")

            # Also test bak target symlink pointing to README.md
            bak_symlink = dst / "standards.lock.json.bak"
            created_bak_symlink = False
            try:
                bak_symlink.symlink_to(readme_file)
                created_bak_symlink = True
            except OSError:
                pass

            if created_bak_symlink:
                ok, path, err = _validate_journal_target(dst, "standards.lock.json.bak", target_key="lock_bak", tx_id="malicious-symlink-tx")
                self.assertFalse(ok)
                self.assertIn("TARGET_SYMLINK_PROHIBITED", str(err))
            else:
                with patch.object(Path, "is_symlink", return_value=True):
                    ok, path, err = _validate_journal_target(dst, "standards.lock.json.bak", target_key="lock_bak", tx_id="malicious-symlink-tx")
                    self.assertFalse(ok)
                    self.assertIn("TARGET_SYMLINK_PROHIBITED", str(err))


if __name__ == "__main__":
    unittest.main()
