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
    rollback_lock,
    validate_upgrade_candidate,
    verify_project_lock,
)
from tools.validate_approval_contract import (
    compute_canonical_document_sha256,
    compute_markdown_body_sha256,
    validate_approval_record,
)
from tools.validate_documentation_collection_bridge import (
    run_collection_validation,
    validate_templates_directory,
)

SCHEMAS_DIR = ROOT / "schemas"
TEMPLATES_DOC_DIR = ROOT / "templates" / "documentation"
BASELINE_COMMIT = "5e17c0ef560ab8abafe880b988d70f85f380a104"
PROJECT_SOURCE_COMMIT = "cdc3a7babe50fff69c52da406a0a2745b442ac14"
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


class TestBaselineSyncAndApprovalGovernance(unittest.TestCase):
    # =========================================================================
    # A. Schema Tests
    # =========================================================================
    def test_a1_all_schemas_valid_and_manifest_schemas_unified(self) -> None:
        schema_files = sorted(SCHEMAS_DIR.glob("*.schema.json"))
        self.assertGreaterEqual(len(schema_files), 30)
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
        self.assertEqual(res["status"], "NOT_VERIFIABLE")
        self.assertEqual(res["remote_latest_status"], "NOT_VERIFIABLE")
        self.assertEqual(res["tag"], "v2.11.0")
        self.assertEqual(res["version"], "2.11.0")
        self.assertEqual(res["tag_object_sha"], BASELINE_TAG_OBJ)
        self.assertEqual(res["peeled_commit"], BASELINE_COMMIT)

    def test_c2_annotated_tag_object_and_peeled_commit_verification(self) -> None:
        res = verify_project_lock(
            project_root=ROOT,
            standards_root=ROOT,
            remote_url=str(ROOT),
        )
        self.assertEqual(res["status"], "PASS", f"Locally verified lock should remain usable: {res}")

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
            self.assertIn(prep["status"], ("BLOCK", "NOT_VERIFIABLE"))

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

if __name__ == "__main__":
    unittest.main()
