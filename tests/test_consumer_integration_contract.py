from __future__ import annotations

import json
import tempfile
import unittest
import yaml
from pathlib import Path

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

    def test_consumer_ci_gate_rejects_artifact_run_id_mismatch(self) -> None:
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
            "artifact_info": {
                "artifact_name": "test-results",
                "artifact_id": 999,
                "run_id": 54321,
                "head_sha": commit,
                "artifact_sha256": "abcdef" * 10 + "abcd",
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
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_ARTIFACT_RUN_ID_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_artifact_commit_mismatch(self) -> None:
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
            "artifact_info": {
                "artifact_name": "test-results",
                "artifact_id": 999,
                "run_id": 12345,
                "head_sha": diff_commit,
                "artifact_sha256": "abcdef" * 10 + "abcd",
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
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_ARTIFACT_COMMIT_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_artifact_sha256_mismatch(self) -> None:
        from unittest.mock import patch
        import hashlib
        commit = "a" * 40
        repository = "example/consumer"
        actual_bytes = b"real-artifact-data"
        actual_sha = hashlib.sha256(actual_bytes).hexdigest()
        different_sha = "f" * 64
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
            "artifact_info": {
                "artifact_name": "test-results",
                "artifact_id": 999,
                "run_id": 12345,
                "head_sha": commit,
                "artifact_sha256": f"sha256:{different_sha}",
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
        artifacts_payload = {
            "artifacts": [{"id": 999, "name": "test-results", "workflow_run": {"id": 12345}}]
        }
        with patch("urllib.request.urlopen", side_effect=[
            FakeResponse(run_payload),
            FakeResponse(jobs_payload),
            FakeResponse(artifacts_payload),
            FakeResponse(actual_bytes),
        ]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_ARTIFACT_SHA256_MISMATCH" in e for e in errors), errors)

    def test_consumer_ci_gate_rejects_artifact_not_found(self) -> None:
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
            "artifact_info": {
                "artifact_name": "missing-artifact",
                "artifact_id": 999,
                "run_id": 12345,
                "head_sha": commit,
                "artifact_sha256": "f" * 64,
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
        artifacts_payload = {
            "artifacts": [{"id": 888, "name": "other-artifact", "workflow_run": {"id": 12345}}]
        }
        with patch("urllib.request.urlopen", side_effect=[
            FakeResponse(run_payload),
            FakeResponse(jobs_payload),
            FakeResponse(artifacts_payload),
        ]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_ARTIFACT_NOT_FOUND" in e for e in errors), errors)

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



    def test_consumer_ci_gate_real_artifact_success_path(self) -> None:
        import io
        import zipfile
        import hashlib
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"

        report_content = json.dumps({
            "repository": repository,
            "commit": commit,
            "run_id": 12345,
            "job_name": "Unit Tests",
            "summary": {
                "tests_collected": 10,
                "tests_passed": 8,
                "tests_failed": 0,
                "tests_skipped": 2,
                "test_errors": 0,
            },
            "exit_code": 0,
        }).encode("utf-8")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("test-report.json", report_content)
        zip_bytes = buf.getvalue()
        zip_sha = hashlib.sha256(zip_bytes).hexdigest()

        gate = {
            "status": "PASS",
            "command": "python -m pytest --json-report",
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
                "tests_passed": 8,
                "tests_failed": 0,
                "tests_skipped": 2,
            },
            "test_execution": {
                "tests_collected": 10,
                "tests_passed": 8,
                "tests_failed": 0,
                "tests_skipped": 2,
                "exit_code": 0,
                "evidence_log_ref": f"https://github.com/{repository}/actions/runs/12345",
            },
            "artifact_info": {
                "artifact_name": "test-report",
                "artifact_id": 202,
                "run_id": 12345,
                "head_sha": commit,
                "artifact_sha256": f"sha256:{zip_sha}",
                "report_file": "test-report.json",
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
        artifacts_payload = {
            "artifacts": [{"id": 202, "name": "test-report", "workflow_run": {"id": 12345}, "expired": False}]
        }
        with patch("urllib.request.urlopen", side_effect=[
            FakeResponse(run_payload),
            FakeResponse(jobs_payload),
            FakeResponse(artifacts_payload),
            FakeResponse(zip_bytes),
        ]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "VERIFIED", errors)
        self.assertEqual(errors, [])

    def test_consumer_ci_gate_rejects_artifact_path_traversal(self) -> None:
        import io
        import zipfile
        import hashlib
        from unittest.mock import patch
        commit = "a" * 40
        repository = "example/consumer"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("../../evil.json", b"{}")
        zip_bytes = buf.getvalue()
        zip_sha = hashlib.sha256(zip_bytes).hexdigest()

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
            "artifact_info": {
                "artifact_name": "test-report",
                "artifact_id": 202,
                "run_id": 12345,
                "head_sha": commit,
                "artifact_sha256": zip_sha,
            },
        }
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
        artifacts_payload = {"artifacts": [{"id": 202, "name": "test-report", "workflow_run": {"id": 12345}}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(artifacts_payload), FakeResponse(zip_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_ARTIFACT_PATH_TRAVERSAL_DETECTED" in e for e in errors), errors)

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

    def test_artifact_report_missing_job_identity_fails(self) -> None:
        from unittest.mock import patch
        import io, zipfile, hashlib
        commit = "a" * 40
        repository = "example/consumer"
        rep_bytes = json.dumps({
            "repository": repository,
            "commit": commit,
            "run_id": 12345,
            "summary": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "test_errors": 0},
        }).encode("utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("report.json", rep_bytes)
        z_bytes = buf.getvalue()
        z_sha = hashlib.sha256(z_bytes).hexdigest()

        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 5, "tests_passed": 5},
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0},
            "artifact_info": {
                "artifact_name": "test-report", "artifact_id": 100, "run_id": 12345,
                "head_sha": commit, "artifact_sha256": f"sha256:{z_sha}", "report_file": "report.json",
            },
        }
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
        artifacts_payload = {"artifacts": [{"id": 100, "name": "test-report", "workflow_run": {"id": 12345}, "expired": False}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(artifacts_payload), FakeResponse(z_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_JOB_IDENTITY_MISSING" in e for e in errors), errors)

    def test_artifact_report_job_id_mismatch_fails(self) -> None:
        from unittest.mock import patch
        import io, zipfile, hashlib
        commit = "a" * 40
        repository = "example/consumer"
        rep_bytes = json.dumps({
            "repository": repository,
            "commit": commit,
            "run_id": 12345,
            "job_id": 99999,
            "job_name": "Unit Tests",
            "summary": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "test_errors": 0},
        }).encode("utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("report.json", rep_bytes)
        z_bytes = buf.getvalue()
        z_sha = hashlib.sha256(z_bytes).hexdigest()

        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 5, "tests_passed": 5},
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0},
            "artifact_info": {
                "artifact_name": "test-report", "artifact_id": 100, "run_id": 12345,
                "head_sha": commit, "artifact_sha256": f"sha256:{z_sha}", "report_file": "report.json",
            },
        }
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
        artifacts_payload = {"artifacts": [{"id": 100, "name": "test-report", "workflow_run": {"id": 12345}, "expired": False}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(artifacts_payload), FakeResponse(z_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_RAW_REPORT_JOB_ID_MISMATCH" in e for e in errors), errors)

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

    def test_artifact_missing_report_file_fails(self) -> None:
        from unittest.mock import patch
        import io, zipfile, hashlib
        commit = "a" * 40
        repository = "example/consumer"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("unrelated.txt", b"hello")
        z_bytes = buf.getvalue()
        z_sha = hashlib.sha256(z_bytes).hexdigest()
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 5, "tests_passed": 5},
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0},
            "artifact_info": {
                "artifact_name": "test-report", "artifact_id": 100, "run_id": 12345,
                "head_sha": commit, "artifact_sha256": f"sha256:{z_sha}",
            },
        }
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
        artifacts_payload = {"artifacts": [{"id": 100, "name": "test-report", "workflow_run": {"id": 12345}, "expired": False}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(artifacts_payload), FakeResponse(z_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_ARTIFACT_REPORT_FILE_UNSPECIFIED" in e for e in errors), errors)

    def test_artifact_zip_size_exceeded_fails(self) -> None:
        from unittest.mock import patch
        from tools.standards_sync.core import MAX_ARTIFACT_ZIP_BYTES
        commit = "a" * 40
        repository = "example/consumer"
        oversized_bytes = b"X" * (MAX_ARTIFACT_ZIP_BYTES + 10)
        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 5, "tests_passed": 5},
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0},
            "artifact_info": {
                "artifact_name": "test-report", "artifact_id": 100, "run_id": 12345,
                "head_sha": commit, "artifact_sha256": "a" * 64, "report_file": "report.json",
            },
        }
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
        artifacts_payload = {"artifacts": [{"id": 100, "name": "test-report", "workflow_run": {"id": 12345}, "expired": False}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(artifacts_payload), FakeResponse(oversized_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_ARTIFACT_SIZE_EXCEEDED" in e for e in errors), errors)

    def test_artifact_report_size_exceeded_fails(self) -> None:
        from unittest.mock import patch
        import io, zipfile, hashlib
        from tools.standards_sync.core import MAX_REPORT_JSON_BYTES
        commit = "a" * 40
        repository = "example/consumer"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("report.json", b" " * (MAX_REPORT_JSON_BYTES + 100))
        z_bytes = buf.getvalue()
        z_sha = hashlib.sha256(z_bytes).hexdigest()

        gate = {
            "status": "PASS", "command": "pytest", "workflow_path": ".github/workflows/ci.yml",
            "run_id": 12345, "job_name": "Unit Tests", "head_sha": commit,
            "evidence_ref": f"https://github.com/{repository}/actions/runs/12345",
            "raw_report": {"tests_collected": 5, "tests_passed": 5},
            "test_execution": {"tests_collected": 5, "tests_passed": 5, "tests_failed": 0, "tests_skipped": 0, "exit_code": 0},
            "artifact_info": {
                "artifact_name": "test-report", "artifact_id": 100, "run_id": 12345,
                "head_sha": commit, "artifact_sha256": f"sha256:{z_sha}", "report_file": "report.json",
            },
        }
        run_payload = {"repository": {"full_name": repository}, "head_sha": commit, "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs_payload = {"jobs": [{"id": 101, "name": "Unit Tests", "status": "completed", "conclusion": "success"}]}
        artifacts_payload = {"artifacts": [{"id": 100, "name": "test-report", "workflow_run": {"id": 12345}, "expired": False}]}
        with patch("urllib.request.urlopen", side_effect=[FakeResponse(run_payload), FakeResponse(jobs_payload), FakeResponse(artifacts_payload), FakeResponse(z_bytes)]):
            status, errors = verify_consumer_ci_gate(repository, gate, commit)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any("CONSUMER_CI_ARTIFACT_REPORT_SIZE_EXCEEDED" in e for e in errors), errors)

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


if __name__ == "__main__":
    unittest.main()
