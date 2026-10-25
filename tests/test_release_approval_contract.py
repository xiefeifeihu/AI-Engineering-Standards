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


if __name__ == '__main__':
    unittest.main()
