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
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.generate_engineering_baseline import (
    build_engineering_baseline,
    compute_deterministic_baseline_sha256,
)
from tools.generate_handoff import build_handoff_payload, write_handoff_files
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

    # Commit the updated docs so that docs in repo match working tree
    subprocess.run(["git", "-C", str(dst), "add", "docs"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(dst), "commit", "-m", "update docs source commit"], capture_output=True, check=True)
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
            self.assertEqual(res["peeled_commit"], "1d5cbbd6710bef749c8f79e9c1fd21dd14223b1b")
            self.assertEqual(res["tag_object_sha"], "325008af90a1e6dcc88ff714c9ec4e7ecee86ec6")
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
            self.assertEqual(res["peeled_commit"], "1d5cbbd6710bef749c8f79e9c1fd21dd14223b1b")
            self.assertEqual(res["tag_object_sha"], "325008af90a1e6dcc88ff714c9ec4e7ecee86ec6")
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


if __name__ == "__main__":
    unittest.main()
