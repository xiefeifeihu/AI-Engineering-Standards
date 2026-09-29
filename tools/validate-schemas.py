#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate All AI Engineering Standards Schemas and Sample Payloads."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"

def validate_schema_structure(schema_path: Path):
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "$schema" in data, "Missing $schema"
        assert "type" in data, "Missing type"
        return True, "Valid JSON Schema"
    except Exception as e:
        return False, str(e)

def test_samples():
    print("Testing realistic samples against standard schemas...")


    try:
        import jsonschema
    except ImportError:
        print("[WARN] jsonschema not installed, skipping deep payload validation.")
        return True

    with open(SCHEMAS_DIR / "model-routing-request.schema.json", "r", encoding="utf-8") as f:
        req_schema = json.load(f)
    with open(SCHEMAS_DIR / "model-routing-response.schema.json", "r", encoding="utf-8") as f:
        resp_schema = json.load(f)
    with open(SCHEMAS_DIR / "model-feedback.schema.json", "r", encoding="utf-8") as f:
        fb_schema = json.load(f)
    with open(SCHEMAS_DIR / "coding-gateway.schema.json", "r", encoding="utf-8") as f:
        gw_schema = json.load(f)

    # 1. Test Routing Request Sample
    sample_request_high = {
        "task": "knowledge_distillation",
        "quality": "high",
        "latency": "normal",
        "multimodal_required": False,
        "preferred_channel": "local-cpa",
        "max_candidates": 3,
        "consumer": "ai-kb"
    }
    jsonschema.validate(instance=sample_request_high, schema=req_schema)

    sample_request_medium = {
        "task": "general_chat",
        "quality": "medium",
        "latency": "normal"
    }
    jsonschema.validate(instance=sample_request_medium, schema=req_schema)

    # Negative test: quality="normal" MUST fail (normal belongs to latency)
    invalid_quality_req = {
        "task": "general_chat",
        "quality": "normal",
        "latency": "normal"
    }
    try:
        jsonschema.validate(instance=invalid_quality_req, schema=req_schema)
        raise AssertionError("Failed negative test: quality='normal' was incorrectly accepted!")
    except jsonschema.ValidationError:
        pass  # Expected

    # 2. Test Candidate Plan Sample (with cold start null semantics & diversity)
    sample_candidate_plan = {
        "decision_id": "route-1774316000-sample",
        "policy_version": "v1.1.1",
        "task": "knowledge_distillation",
        "requirements": {
            "quality": "high",
            "latency": "normal",
            "multimodal_required": False
        },
        "candidates": [
            {
                "rank": 1,
                "logical_model_id": "qwen2.5-72b-instruct",
                "model": "local-cpa::qwen2.5-72b-instruct",
                "model_name": "Qwen 2.5 72B Instruct",
                "provider": "Alibaba",
                "channel": "local-cpa",
                "resource_id": "local-cpa",
                "endpoint_reference": "http://127.0.0.1:18117/v1",
                "capabilities": ["知识提炼", "长文本问答", "深度推理"],
                "score": 0.92,
                "score_breakdown": {
                    "ability": 43.0,
                    "channel": 70.0,
                    "success_rate": 20.0,
                    "latency": 15.0,
                    "quality": 15.0,
                    "failure_penalty": 0.0,
                    "circuit_penalty": 0.0,
                    "quota_penalty": 0.0,
                    "total": 128.0,
                    "normalized": 0.92
                },
                "governance_state": "HEALTHY",
                "metrics": {
                    "sample_count": 0,
                    "metric_confidence": "NONE",
                    "success_rate": None,
                    "latency_p50": None,
                    "latency_p95": None,
                    "cold_start": True
                },
                "path_redundancy": False,
                "reason": "第 1 候选 (local-cpa): 首选高智能知识提炼模型，冷启动待命中"
            }
        ],
        "diversity": {
            "model_diversity": 1,
            "provider_diversity": 1,
            "channel_diversity": 1
        },
        "fallback_policy": {
            "strategy": "priority_candidate_chain_then_consumer_legacy",
            "max_candidates": 1,
            "description": "逐个候选尝试，全失败回退业务 Legacy"
        }
    }
    jsonschema.validate(instance=sample_candidate_plan, schema=resp_schema)
    
    # 2.5 Test Engineering Manifest (Old and New)
    with open(SCHEMAS_DIR / "engineering-manifest.schema.json", "r", encoding="utf-8") as f:
        manifest_schema = json.load(f)

    # Legacy v1.0.0 sample manifest without docker_consumer
    sample_manifest_legacy = {
        "schema_version": "1.0.0",
        "project": {
            "id": "legacy-project",
            "name": "Legacy Project",
            "purpose": "Testing backward compatibility",
            "consumer_contract": {
                "shared_inference": "REQUIRED"
            }
        },
        "services": [
            {
                "id": "legacy-service",
                "name": "Legacy Service",
                "purpose": "Service without docker_consumer",
                "category": "project_app",
                "exposure": "loopback",
                "lifecycle_policy": "ALWAYS_ON",
                "desired_state": "RUNNING",
                "endpoints": {
                    "windows_host": "http://127.0.0.1:8000",
                    "wsl_host": "http://127.0.0.1:8000",
                    "docker_internal": "http://legacy-app:8000"
                },
                "health_contract": {
                    "probe_type": "http",
                    "endpoint": "http://127.0.0.1:8000/health"
                }
            }
        ]
    }
    jsonschema.validate(instance=sample_manifest_legacy, schema=manifest_schema)

    # Modern v1.1.3 sample manifest with docker_consumer
    sample_manifest_v113 = {
        "schema_version": "1.1.3",
        "project": {
            "id": "modern-project",
            "name": "Modern Project",
            "purpose": "Testing v1.1.3 dual-profile endpoints",
            "consumer_contract": {
                "shared_inference": "REQUIRED"
            }
        },
        "services": [
            {
                "id": "cloud-cpa-tunnel",
                "name": "Cloud CPA Tunnel",
                "purpose": "SSH tunnel with host gateway relay",
                "category": "shared_ai_resource",
                "exposure": "optional_tunnel",
                "lifecycle_policy": "ALWAYS_ON",
                "desired_state": "RUNNING",
                "endpoints": {
                    "windows_host": "http://127.0.0.1:18317",
                    "docker_consumer": "http://host.docker.internal:18318"
                },
                "health_contract": {
                    "probe_type": "http",
                    "endpoint": "http://127.0.0.1:18317/v1/models"
                }
            }
        ]
    }
    jsonschema.validate(instance=sample_manifest_v113, schema=manifest_schema)

    # Negative test: invalid schema_version
    invalid_manifest = dict(sample_manifest_v113)
    invalid_manifest["schema_version"] = "99.0.0"
    try:
        jsonschema.validate(instance=invalid_manifest, schema=manifest_schema)
        raise AssertionError("Failed negative test: invalid schema_version was accepted!")
    except jsonschema.ValidationError:
        pass

    # 3. Test Feedback Payload Samples (STD-010 v1.3.0)
    # 3.1 Legacy v1.2 payload (Backward compatibility)
    sample_feedback_legacy = {
        "decision_id": "route-1774316000-sample",
        "consumer": "ai-kb",
        "task": "knowledge_distillation",
        "model": "qwen2.5-72b-instruct",
        "channel": "local-cpa",
        "success": True,
        "latency_ms": 1350.2,
        "prompt_tokens": 1200,
        "completion_tokens": 400,
        "total_tokens": 1600,
        "status_code": 200,
        "error_type": "",
        "quality_metrics": {
            "knowledge_quality": 0.95,
            "citation_validity": 1.0
        }
    }
    jsonschema.validate(instance=sample_feedback_legacy, schema=fb_schema)

    # 3.2 Stage: execution (v1.3 canonical)
    sample_fb_execution = {
        "feedback_stage": "execution",
        "observed_at": "2026-09-29T10:45:00Z",
        "decision_id": "route-1790643768998",
        "run_id": "run-distill-20260929-001",
        "attempt": 1,
        "idempotency_key": "ai-kb::run-distill-20260929-001::U1::local-cpa::qwen3-coder-next::1::execution",
        "consumer": "ai-kb",
        "task": "knowledge_distillation",
        "metric_namespace": "ai-kb.knowledge_distillation.v1",
        "model": "qwen3-coder-next",
        "logical_model_id": "qwen3-coder-next",
        "selected_model_id": "local-cpa::qwen3-coder-next",
        "upstream_model_id": "qwen3-coder-next",
        "resource_id": "local-cpa",
        "channel": "local-cpa",
        "source_unit_id": "U1",
        "source_unit_hash": "a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890",
        "execution_spec_hash": "fedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321",
        "candidate_rank": 1,
        "retry_count": 0,
        "fallback_count": 0,
        "success": True,
        "latency_ms": 765.4,
        "prompt_tokens": 1250,
        "completion_tokens": 420,
        "total_tokens": 1670,
        "status_code": 200,
        "error_type": "",
        "quality_metrics": {
            "knowledge_quality": 0.96,
            "citation_validity": 1.0,
            "answer_completeness": 0.92
        }
    }
    jsonschema.validate(instance=sample_fb_execution, schema=fb_schema)

    # 3.3 Stage: business_evaluation (Asynchronous automated domain evaluation)
    sample_fb_biz_eval = {
        "feedback_stage": "business_evaluation",
        "observed_at": "2026-09-29T10:47:30Z",
        "decision_id": "route-1790643768998",
        "run_id": "run-distill-20260929-001",
        "attempt": 1,
        "idempotency_key": "ai-kb::run-distill-20260929-001::U1::local-cpa::qwen3-coder-next::1::business_evaluation",
        "consumer": "ai-kb",
        "task": "knowledge_distillation",
        "metric_namespace": "ai-kb.knowledge_distillation.v1",
        "model": "qwen3-coder-next",
        "logical_model_id": "qwen3-coder-next",
        "channel": "local-cpa",
        "source_unit_id": "U1",
        "source_unit_hash": "a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890",
        "execution_spec_hash": "fedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321",
        "evaluation_method": "combined",
        "prompt_version": "v1.2.0",
        "rubric_version": "kq-003",
        "evaluation_confidence": 0.95,
        "review_decision": "approved",
        "review_reason_code": "",
        "success": True,
        "quality_metrics": {
            "knowledge_quality": 0.96,
            "citation_validity": 1.0,
            "answer_completeness": 0.92,
            "core_thesis_accuracy": 0.98,
            "boundary_accuracy": 0.94
        }
    }
    jsonschema.validate(instance=sample_fb_biz_eval, schema=fb_schema)

    # 3.4 Stage: human_review (Human expert review outcome)
    sample_fb_human_review = {
        "feedback_stage": "human_review",
        "observed_at": "2026-09-29T11:00:00Z",
        "decision_id": "route-1790643768998",
        "run_id": "run-distill-20260929-001",
        "attempt": 1,
        "idempotency_key": "ai-kb::run-distill-20260929-001::U1::local-cpa::qwen3-coder-next::1::human_review",
        "consumer": "ai-kb",
        "task": "knowledge_distillation",
        "metric_namespace": "ai-kb.knowledge_distillation.v1",
        "model": "qwen3-coder-next",
        "logical_model_id": "qwen3-coder-next",
        "channel": "local-cpa",
        "source_unit_id": "U1",
        "evaluation_method": "human",
        "evaluation_confidence": 1.0,
        "review_decision": "approved_with_note",
        "review_reason_code": "minor_formatting_observation",
        "success": True
    }
    jsonschema.validate(instance=sample_fb_human_review, schema=fb_schema)

    # 3.5 Negative tests: invalid error_type MUST fail
    invalid_fb_error = {
        "model": "qwen2.5:7b-instruct",
        "channel": "ollama",
        "success": False,
        "error_type": "UNKNOWN_CUSTOM_ERROR"
    }
    try:
        jsonschema.validate(instance=invalid_fb_error, schema=fb_schema)
        raise AssertionError("Failed negative test: invalid error_type was incorrectly accepted!")
    except jsonschema.ValidationError:
        pass  # Expected

    # 3.6 Negative tests proving: consumer cannot submit raw content fields (Zero Content Storage Guardrail)
    forbidden_content_samples = [
        ("prompt", {"model": "qwen3-coder-next", "success": True, "prompt": "Translate this secret doc..."}),
        ("response", {"model": "qwen3-coder-next", "success": True, "response": "Here is the confidential response..."}),
        ("source_content", {"model": "qwen3-coder-next", "success": True, "source_content": "Sensitive document text..."}),
        ("chunk_content", {"model": "qwen3-coder-next", "success": True, "chunk_content": "RAG chunk private text..."}),
        ("document_text", {"model": "qwen3-coder-next", "success": True, "document_text": "Full article raw text..."}),
        ("raw_metrics_string", {"model": "qwen3-coder-next", "success": True, "quality_metrics": {"analysis": "Non-numeric string"}})
    ]
    for forbidden_key, bad_payload in forbidden_content_samples:
        try:
            jsonschema.validate(instance=bad_payload, schema=fb_schema)
            raise AssertionError(f"Failed negative test: forbidden content '{forbidden_key}' was accepted by schema!")
        except jsonschema.ValidationError:
            pass  # Expected

        # 4. Test Coding Gateway Schema Sample
    sample_gateway_payload = {
        "virtual_model": "hub-code-auto",
        "protocol": "anthropic_messages",
        "routing_profile": "auto",
        "session_id": "sess-claude-20260928-01",
        "caller_identity": "claude-code",
        "consumer_runtime": "host",
        "streaming": True,
        "execution_diagnostics": {
            "decision_id": "route-code-12345",
            "selected_model": "qwen3-coder-plus",
            "selected_channel": "local-cpa",
            "attempt_count": 1,
            "fallback_count": 0,
            "ttft_ms": 320.5,
            "total_latency_ms": 1250.0,
            "tokens_input": 450,
            "tokens_output": 210,
            "tool_call_success": True,
            "circuit_state": "HEALTHY"
        }
    }
    jsonschema.validate(instance=sample_gateway_payload, schema=gw_schema)

    print("Sample validation PASS: structures conform to Standards V1.3 specifications.")
    return True

def main():
    schemas = list(SCHEMAS_DIR.glob("*.schema.json"))
    if not schemas:
        print("ERROR: No schemas found!")
        sys.exit(1)
    
    failed = 0
    for s in sorted(schemas):
        ok, msg = validate_schema_structure(s)
        if ok:
            print(f"[PASS] {s.name}: {msg}")
        else:
            print(f"[FAIL] {s.name}: {msg}")
            failed += 1
            
    test_samples()

    if failed == 0:
        print(f"\nAll {len(schemas)} schemas validated successfully!")
        sys.exit(0)
    else:
        print(f"\nValidation failed for {failed} schemas.")
        sys.exit(1)

if __name__ == "__main__":
    main()
