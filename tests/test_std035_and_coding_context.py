# -*- coding: utf-8 -*-
"""Unit tests for STD-035 Documentation Lifecycle & Coding Gateway Auto Context Contracts."""
import json
import unittest
import jsonschema
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
TEMPLATES_DIR = ROOT / "templates" / "documentation"

class TestStd035AndCodingContext(unittest.TestCase):
    def setUp(self):
        with open(SCHEMAS_DIR / "documentation-metadata.schema.json", "r", encoding="utf-8") as f:
            self.doc_schema = json.load(f)
        with open(SCHEMAS_DIR / "coding-gateway.schema.json", "r", encoding="utf-8") as f:
            self.gw_schema = json.load(f)

    def test_doc_metadata_schema_validity(self):
        jsonschema.validators.validator_for(self.doc_schema).check_schema(self.doc_schema)

    def test_valid_doc_metadata_sample(self):
        sample = {
            "document_id": "DOC-HUB-PRODUCT-BASELINE-001",
            "document_version": "1.0.0",
            "project_id": "ai-engineering-hub",
            "document_type": "PRODUCT_BASELINE",
            "status": "ACTIVE",
            "applies_to_release": "v0.21.10",
            "last_updated": "2026-10-27",
            "supersedes": None,
            "change_summary": "Unified full product baseline for AI Engineering Hub",
            "history_reference": None,
            "primary_entrypoint": True
        }
        jsonschema.validate(instance=sample, schema=self.doc_schema)

    def test_doc_metadata_negative_invalid_type(self):
        bad_sample = {
            "document_id": "DOC-BAD-001",
            "document_version": "1.0.0",
            "project_id": "ai-engineering-hub",
            "document_type": "UNKNOWN_TYPE",
            "status": "ACTIVE",
            "applies_to_release": "v0.21.10",
            "last_updated": "2026-10-27",
            "change_summary": "Bad type test",
            "primary_entrypoint": True
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_sample, schema=self.doc_schema)

    def test_doc_metadata_negative_missing_primary_entrypoint(self):
        bad_sample = {
            "document_id": "DOC-BAD-002",
            "document_version": "1.0.0",
            "project_id": "ai-engineering-hub",
            "document_type": "PRODUCT_BASELINE",
            "status": "ACTIVE",
            "applies_to_release": "v0.21.10",
            "last_updated": "2026-10-27",
            "change_summary": "Missing primary_entrypoint"
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_sample, schema=self.doc_schema)

    def test_coding_gateway_auto_context_explicit(self):
        payload = {
            "virtual_model": "hub-code-auto",
            "protocol": "anthropic_messages",
            "routing_profile": "auto",
            "consumer_id": "claude-code",
            "target_project": "vtip-ai-sidecar",
            "task_family": "coding_agent",
            "task_type": "code_refactor",
            "task_id": "TASK-SIDECAR-001",
            "run_id": "run-001",
            "turn_id": "1",
            "attempt_id": 1,
            "decision_id": "dec-123",
            "route_id": "route-cpa-1",
            "trace_id": "trace-999",
            "context_origin": "EXPLICIT"
        }
        jsonschema.validate(instance=payload, schema=self.gw_schema)

    def test_coding_gateway_auto_context_session(self):
        payload = {
            "virtual_model": "hub-code-fast",
            "protocol": "openai_chat_completions",
            "routing_profile": "fast",
            "consumer_id": "workbuddy",
            "target_project": "ai-engineering-hub",
            "task_family": "coding_agent",
            "task_type": "unit_test_fix",
            "task_id": "task-sess-abc-001",
            "run_id": "run-sess-001",
            "session_id": "sess-workbuddy-abc",
            "turn_id": 2,
            "attempt_id": 1,
            "context_origin": "CLIENT_SESSION"
        }
        jsonschema.validate(instance=payload, schema=self.gw_schema)

    def test_coding_gateway_auto_context_negative_invalid_origin(self):
        bad_payload = {
            "virtual_model": "hub-code-auto",
            "protocol": "anthropic_messages",
            "routing_profile": "auto",
            "consumer_id": "claude-code",
            "context_origin": "INVALID_ORIGIN"
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad_payload, schema=self.gw_schema)

if __name__ == "__main__":
    unittest.main()
