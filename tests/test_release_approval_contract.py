"""Structural contract tests only; fixtures are never human approval evidence."""
import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def validator(name):
    schema = json.loads((ROOT / 'schemas' / name).read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class ApprovalContractTests(unittest.TestCase):
    def setUp(self):
        self.envelope_validator = validator('release-approval.schema.json')
        self.policy_validator = validator('release-approval-policy.schema.json')
        self.envelope = {
            'approval_source': 'LOCAL_AUTHORIZED_KEY',
            'key_fingerprint': 'sha256:' + 'a' * 64,
            'algorithm': 'RSA-PSS-SHA256',
            # Deliberately invalid cryptographic bytes: schema acceptance is not approval.
            'signature': 'A' * 512,
            'payload': {
                'schema_version': '1.0.0', 'domain': 'STD-032:production-release:v1',
                'repository': 'example/service', 'branch': 'main',
                'source_sha': 'a' * 40, 'version': '1.0.0',
                'image': 'ghcr.io/example/service@sha256:' + 'b' * 64,
                'workflow': '.github/workflows/cd-production.yml',
                'run_id': 10, 'run_attempt': 1, 'ci_run_id': 9,
                'release_task_id': 'example/service:10:1',
                'candidate_sha256': 'sha256:' + 'c' * 64,
                'change_summary_sha256': 'sha256:' + 'd' * 64,
                'approver': 'isolated-test-signer',
                'issued_at': '2026-10-25T12:00:00Z',
                'expires_at': '2026-10-25T13:00:00Z', 'decision': 'APPROVED',
            },
        }
        self.policy = {
            'schema_version': '1.0.0', 'repository': 'example/service',
            'branch': 'main', 'approval_mode': 'GITHUB_ENVIRONMENT_REVIEW',
            'workflow': '.github/workflows/cd-production.yml',
            'environment': 'production', 'max_age_seconds': 3600,
        }
        self.local = {
            'capability_evidence_ref': 'admin-reviewed-capability-evidence',
            'keys': [{
                'fingerprint': 'sha256:' + 'a' * 64,
                'algorithm': 'RSA-PSS-SHA256', 'approver': 'isolated-test-signer',
                'public_key_spki_base64': 'A' * 512, 'status': 'ACTIVE',
                'not_before': '2026-10-25T12:00:00Z',
                'not_after': '2027-10-25T12:00:00Z',
                'boundary_evidence_ref': 'independent-boundary-review',
                'registration_review_ref': 'independent-registration-review',
            }],
        }

    def test_both_explicit_policy_shapes(self):
        self.policy_validator.validate(self.policy)
        self.policy['approval_mode'] = 'LOCAL_AUTHORIZED_KEY'
        self.policy['local_authorized_key'] = self.local
        self.policy_validator.validate(self.policy)

    def test_policy_rejects_implicit_fallback_and_unregistered_local(self):
        for mode in [None, 'AUTO', 'LOCAL_AUTHORIZED_KEY']:
            policy = copy.deepcopy(self.policy)
            policy['approval_mode'] = mode
            self.assertTrue(list(self.policy_validator.iter_errors(policy)))
        self.policy['local_authorized_key'] = self.local
        self.assertTrue(list(self.policy_validator.iter_errors(self.policy)))

    def test_missing_boundary_or_registration_is_invalid(self):
        self.policy.update(approval_mode='LOCAL_AUTHORIZED_KEY', local_authorized_key=self.local)
        for field in self.local['keys'][0]:
            policy = copy.deepcopy(self.policy)
            del policy['local_authorized_key']['keys'][0][field]
            with self.subTest(field=field):
                self.assertTrue(list(self.policy_validator.iter_errors(policy)))

    def test_every_payload_binding_required(self):
        self.envelope_validator.validate(self.envelope)
        for field in self.envelope['payload']:
            envelope = copy.deepcopy(self.envelope)
            del envelope['payload'][field]
            with self.subTest(field=field):
                self.assertTrue(list(self.envelope_validator.iter_errors(envelope)))

    def test_payload_rejects_ambiguous_or_unbound_values(self):
        for field, value in [('source_sha', 'a' * 7), ('image', 'ghcr.io/example/service:latest'),
                             ('run_id', 1.2), ('run_attempt', 0), ('branch', 'feature'),
                             ('issued_at', '2026-99-99T12:00:00Z'),
                             ('expires_at', 'tomorrow'), ('decision', True),
                             ('repository', '../elsewhere'), ('version', 'latest'),
                             ('approver', '\u4eba\u5de5'), ('human_present', True)]:
            envelope = copy.deepcopy(self.envelope)
            envelope['payload'][field] = value
            with self.subTest(field=field):
                self.assertTrue(list(self.envelope_validator.iter_errors(envelope)))

    def test_algorithm_and_source_are_fixed(self):
        for field, value in [('algorithm', 'none'), ('approval_source', 'AUTO'),
                             ('signature', 'sha256:' + 'a' * 64), ('approved', True)]:
            envelope = copy.deepcopy(self.envelope)
            envelope[field] = value
            self.assertTrue(list(self.envelope_validator.iter_errors(envelope)))



    def test_personal_local_owner_consent_valid(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'PERSONAL_LOCAL'
        policy['approval_mode'] = 'OWNER_LOCAL_CONSENT'
        policy['owner_consent'] = {
            'operator_identity': 'local-owner',
            'confirmation_channel': 'terminal_prompt',
            'require_explicit_consent': True,
        }
        self.policy_validator.validate(policy)

    def test_personal_local_no_hardware_key_required(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'PERSONAL_LOCAL'
        policy['approval_mode'] = 'OWNER_LOCAL_CONSENT'
        self.assertNotIn('local_authorized_key', policy)
        self.policy_validator.validate(policy)

    def test_high_assurance_cannot_use_owner_consent(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'HIGH_ASSURANCE'
        policy['approval_mode'] = 'OWNER_LOCAL_CONSENT'
        errors = list(self.policy_validator.iter_errors(policy))
        self.assertTrue(errors, "HIGH_ASSURANCE must reject OWNER_LOCAL_CONSENT")

    def test_high_assurance_requires_production_env(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'HIGH_ASSURANCE'
        policy['approval_mode'] = 'GITHUB_ENVIRONMENT_REVIEW'
        policy['environment'] = 'local-dev'
        errors = list(self.policy_validator.iter_errors(policy))
        self.assertTrue(errors, "HIGH_ASSURANCE must require production environment")

    def test_maintainer_release_valid(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'MAINTAINER_RELEASE'
        policy['approval_mode'] = 'MAINTAINER_APPROVAL'
        self.policy_validator.validate(policy)

    def test_maintainer_approval_requires_maintainer_release_profile(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'HIGH_ASSURANCE'
        policy['approval_mode'] = 'MAINTAINER_APPROVAL'
        errors = list(self.policy_validator.iter_errors(policy))
        self.assertTrue(errors, "HIGH_ASSURANCE must reject MAINTAINER_APPROVAL")

    def test_unknown_release_profile_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'UNTRUSTED_COMMUNITY'
        errors = list(self.policy_validator.iter_errors(policy))
        self.assertTrue(errors, "Unknown release_profile must be rejected")

    def test_release_engineering_7_stages_personal_local(self):
        rel_eng_validator = validator('release-engineering.schema.json')
        sample = {
            "standard_id": "STD-032",
            "service": "AI-Hub",
            "version": "v0.21.8",
            "tag": "v0.21.8",
            "release_profile": "PERSONAL_LOCAL",
            "pipeline_status": "PASS",
            "stages": [
                "SOURCE_AND_POLICY",
                "TEST_AND_SECURITY",
                "BUILD_AND_PUBLISH",
                "OWNER_AUTHORIZATION",
                "BACKUP_AND_DEPLOY",
                "RUNTIME_AND_SMOKE",
                "RELEASE_TAG_AND_VERIFY"
            ],
            "commit_identity": {
                "LOCAL_HEAD": "a" * 40,
                "REMOTE_HEAD": "a" * 40,
                "TAG_COMMIT": "a" * 40,
                "BUILD_COMMIT": "a" * 40,
                "LIVE_COMMIT": "a" * 40,
                "all_consistent": True
            },
            "gates": {
                "SOURCE": {"git_clean": True, "secret_scan": True, "passed": True},
                "DEV_TEST": {"unit_test": True, "contract_test": True, "integration_test": True, "e2e": True, "passed": True},
                "BUILD": {"build_metadata_generated": True, "passed": True},
                "PACKAGE": {"artifact_sha256": "a" * 64, "passed": True},
                "DEPLOY": {"runtime_probe": True, "technology_agnostic": True, "docker_bound": False, "passed": True},
                "SMOKE": {"minimal_business_verification": True, "passed": True}
            },
            "artifacts": {
                "layout_valid": True,
                "docs_clean": True,
                "package_path": ".artifacts/packages/Acceptance-TEST.zip",
                "package_sha256": "a" * 64
            },
            "runtime_acceptance": True,
            "rollback_contract": {
                "technology_agnostic": True,
                "docker_bound": False,
                "target_tag": "v0.21.7",
                "verified": True
            },
            "timestamp": "2026-10-27T08:00:00Z"
        }
        rel_eng_validator.validate(sample)

    def test_personal_local_auto_after_green_valid(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'PERSONAL_LOCAL'
        policy['approval_mode'] = 'AUTO_AFTER_GREEN'
        policy['auto_after_green'] = {
            'enabled': True,
            'target_environment': 'local_wsl',
            'required_gates': [
                'PR_MERGED',
                'REMOTE_CI_PASS',
                'AUTOMATED_TESTS_PASS',
                'PLAYWRIGHT_PASS',
                'SECRETS_SCAN_PASS',
                'SOURCE_BUILD_COMMIT_UNAMBIGUOUS',
                'BACKUP_AND_RESTORE_VERIFIED',
                'ROLLBACK_READY',
                'CONTROLLED_WSL_EXECUTOR',
                'HEALTH_AND_SMOKE_RUNNABLE'
            ],
            'max_auto_rollback_attempts': 2
        }
        self.policy_validator.validate(policy)

    def test_high_assurance_rejects_auto_after_green(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'HIGH_ASSURANCE'
        policy['approval_mode'] = 'AUTO_AFTER_GREEN'
        policy['auto_after_green'] = {
            'enabled': True,
            'target_environment': 'local_wsl',
            'required_gates': [
                'PR_MERGED', 'REMOTE_CI_PASS', 'AUTOMATED_TESTS_PASS',
                'PLAYWRIGHT_PASS', 'SECRETS_SCAN_PASS',
                'SOURCE_BUILD_COMMIT_UNAMBIGUOUS', 'BACKUP_AND_RESTORE_VERIFIED'
            ]
        }
        errors = list(self.policy_validator.iter_errors(policy))
        self.assertTrue(errors, 'HIGH_ASSURANCE must reject AUTO_AFTER_GREEN')

    def test_maintainer_release_rejects_auto_after_green(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'MAINTAINER_RELEASE'
        policy['approval_mode'] = 'AUTO_AFTER_GREEN'
        policy['auto_after_green'] = {
            'enabled': True,
            'target_environment': 'local_wsl',
            'required_gates': [
                'PR_MERGED', 'REMOTE_CI_PASS', 'AUTOMATED_TESTS_PASS',
                'PLAYWRIGHT_PASS', 'SECRETS_SCAN_PASS',
                'SOURCE_BUILD_COMMIT_UNAMBIGUOUS', 'BACKUP_AND_RESTORE_VERIFIED'
            ]
        }
        errors = list(self.policy_validator.iter_errors(policy))
        self.assertTrue(errors, 'MAINTAINER_RELEASE must reject AUTO_AFTER_GREEN')

    def test_auto_after_green_missing_required_gates_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy['release_profile'] = 'PERSONAL_LOCAL'
        policy['approval_mode'] = 'AUTO_AFTER_GREEN'
        policy['auto_after_green'] = {
            'enabled': True,
            'target_environment': 'local_wsl',
            'required_gates': ['PR_MERGED']
        }
        errors = list(self.policy_validator.iter_errors(policy))
        self.assertTrue(errors, 'AUTO_AFTER_GREEN with fewer than 7 required gates must be rejected')

    def test_release_engineering_7_stages_auto_after_green(self):
        rel_eng_validator = validator('release-engineering.schema.json')
        sample = {
            'standard_id': 'STD-032',
            'service': 'AI-Hub',
            'version': 'v0.21.9',
            'tag': 'v0.21.9',
            'release_profile': 'PERSONAL_LOCAL',
            'pipeline_status': 'PASS',
            'stages': [
                'SOURCE_AND_POLICY',
                'TEST_AND_SECURITY',
                'BUILD_AND_PUBLISH',
                'AUTO_AFTER_GREEN_GATE',
                'BACKUP_AND_DEPLOY',
                'RUNTIME_AND_SMOKE',
                'RELEASE_TAG_AND_VERIFY'
            ],
            'commit_identity': {
                'LOCAL_HEAD': 'b' * 40,
                'REMOTE_HEAD': 'b' * 40,
                'TAG_COMMIT': 'b' * 40,
                'BUILD_COMMIT': 'b' * 40,
                'LIVE_COMMIT': 'b' * 40,
                'all_consistent': True
            },
            'gates': {
                'SOURCE': {'git_clean': True, 'secret_scan': True, 'passed': True},
                'DEV_TEST': {'unit_test': True, 'contract_test': True, 'integration_test': True, 'e2e': True, 'passed': True},
                'BUILD': {'build_metadata_generated': True, 'passed': True},
                'PACKAGE': {'artifact_sha256': 'b' * 64, 'passed': True},
                'DEPLOY': {'runtime_probe': True, 'technology_agnostic': True, 'docker_bound': False, 'passed': True},
                'SMOKE': {'minimal_business_verification': True, 'passed': True}
            },
            'artifacts': {
                'layout_valid': True,
                'docs_clean': True,
                'package_path': '.artifacts/packages/Acceptance-AI-HUB.zip',
                'package_sha256': 'b' * 64
            },
            'runtime_acceptance': True,
            'rollback_contract': {
                'technology_agnostic': True,
                'docker_bound': False,
                'target_tag': 'v0.21.7',
                'verified': True
            },
            'timestamp': '2026-10-27T08:30:00Z'
        }
        rel_eng_validator.validate(sample)


if __name__ == '__main__':
    unittest.main()
