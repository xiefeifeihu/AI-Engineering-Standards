#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate All AI Engineering Standards Schemas and Sample Payloads."""
import json
import sys
import unittest
import jsonschema
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"

def validate_schema_structure(schema_path: Path):
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "$schema" in data, "Missing $schema"
        assert "type" in data, "Missing type"
        jsonschema.validators.validator_for(data).check_schema(data)
        return True, "Valid JSON Schema"
    except Exception as e:
        return False, str(e)

def test_samples():
    print("Testing realistic samples against standard schemas...")


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

    # 1b. Test Generic Task Contract v2.1.1 Request Samples
    sample_request_v211 = {
        "consumer_id": "sidecar",
        "task_family": "document_transformation",
        "task_type": "report_polishing",
        "capability_profile": "faithful_summarization",
        "output_contract": "markdown_structured_bullets",
        "quality": "high",
        "latency": "normal",
    }
    jsonschema.validate(instance=sample_request_v211, schema=req_schema)

    # Mixed request sample (legacy + canonical)
    sample_request_mixed = {
        "consumer": "vtip-ai-sidecar",
        "consumer_id": "sidecar",
        "task": "report_polishing",
        "task_type": "report_polishing",
        "task_family": "document_transformation",
        "capability_profile": "faithful_summarization",
        "output_contract": "markdown_structured_bullets",
        "quality": "high",
        "latency": "normal",
    }
    jsonschema.validate(instance=sample_request_mixed, schema=req_schema)

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

    with open(SCHEMAS_DIR / "coding-agent-outcome.schema.json", "r", encoding="utf-8") as f:
        outcome_schema = json.load(f)

    # 5. Test Coding Agent Outcome Schema (STD-023 v1.5.0)
    sample_outcome_attempt = {
        "outcome_stage": "ATTEMPT_COMPLETED",
        "observed_at": "2026-09-30T08:00:00Z",
        "consumer": "vtip-ai-sidecar",
        "coding_client": "claude-code",
        "repo_id": "vtip-ai-sidecar",
        "repo_stack": "python_fastapi",
        "task_id": "SIDECAR-DEV-022",
        "task_profile": "feature_implementation",
        "agent_run_id": "run-bakeoff-001",
        "coding_attempt_id": "attempt-cand-a-001",
        "decision_id": "code-plan-1790000001",
        "candidate_rank": 1,
        "virtual_model": "hub-code-auto",
        "logical_model_id": "qwen3-coder-next",
        "selected_model_id": "local-cpa::qwen3-coder-next",
        "upstream_model_id": None,
        "upstream_provider": None,
        "channel": "local-cpa",
        "resource_id": "local-cpa",
        "base_commit": "abc1234",
        "patch_created": True,
        "patch_parse_success": True,
        "patch_apply_success": True,
        "patch_hash": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "files_changed_count": 2,
        "lines_added": 45,
        "lines_deleted": 8,
        "syntax_check_run": True,
        "syntax_check_pass": True,
        "targeted_tests_run": 5,
        "targeted_tests_passed": 5,
        "targeted_tests_failed": 0,
        "core_regression_run": 30,
        "core_regression_passed": 30,
        "core_regression_failed": 0,
        "browser_acceptance_run": True,
        "browser_acceptance_pass": True,
        "acceptance_gates_total": 4,
        "acceptance_gates_passed": 4,
        "task_outcome": "COMPLETED",
        "integration_selected": False,
        "wall_time_ms": 32400.0,
        "model_call_count": 3,
        "tool_call_count": 6,
        "repair_rounds": 0
    }
    jsonschema.validate(instance=sample_outcome_attempt, schema=outcome_schema)

    sample_outcome_integration = {
        "outcome_stage": "INTEGRATION_DECISION",
        "consumer": "vtip-ai-sidecar",
        "repo_id": "vtip-ai-sidecar",
        "task_id": "SIDECAR-DEV-022",
        "agent_run_id": "run-bakeoff-001",
        "coding_attempt_id": "attempt-cand-a-001",
        "integration_selected": True,
        "commit_created": True,
        "result_commit": "def5678",
        "git_clean": True,
        "acceptance_pass": True,
        "task_complete": True
    }
    jsonschema.validate(instance=sample_outcome_integration, schema=outcome_schema)

    # Negative tests for STD-023: raw patch/source/fake identity MUST fail
    bad_outcome_samples = [
        ("raw_patch", dict(sample_outcome_attempt, patch="diff --git a/app.py b/app.py")),
        ("raw_diff", dict(sample_outcome_attempt, diff="@@ -1,3 +1,3 @@")),
        ("source_code", dict(sample_outcome_attempt, source_code="def secret(): pass")),
        ("fake_upstream_unknown", dict(sample_outcome_attempt, upstream_model_id="unknown")),
        ("fake_upstream_unverified_zh", dict(sample_outcome_attempt, upstream_provider="未验证")),
        ("fake_commit_na", dict(sample_outcome_attempt, result_commit="N/A")),
    ]
    for label, bad_instance in bad_outcome_samples:
        try:
            jsonschema.validate(instance=bad_instance, schema=outcome_schema)
            raise AssertionError(f"Failed negative test for STD-023: '{label}' was accepted!")
        except jsonschema.ValidationError:
            pass

    # 6. Test Model Ops Autopilot Schema (STD-024 v1.6.1)
    with open(SCHEMAS_DIR / "model-ops-autopilot.schema.json", "r", encoding="utf-8") as f:
        autopilot_schema = json.load(f)

    # 6.1 Sample Discovery Observation
    sample_autopilot_discovery = {
        "record_type": "DISCOVERY_OBSERVATION",
        "logical_model_id": "qwen3-coder-plus",
        "selected_model_id": "local-cpa::qwen3-coder-plus",
        "upstream_model_id": None,
        "resource_id": "local-cpa",
        "channel": "local-cpa",
        "owner": "AI-KB",
        "upstream_provider": None,
        "provenance_status": "LOCAL_RUNTIME",
        "provenance_source": "ENDPOINT_REGISTRY",
        "first_seen_at": "2026-10-06T10:00:00Z",
        "last_seen_at": "2026-10-06T12:00:00Z",
        "discovery_generation": 1,
        "availability": "AVAILABLE",
        "model_fingerprint": None,
        "capability_state": "VERIFIED",
        "lifecycle_state": "PROBE_VERIFIED"
    }
    jsonschema.validate(instance=sample_autopilot_discovery, schema=autopilot_schema)

    # 6.1.1 Additive capability_state PROBE_VERIFIED
    sample_autopilot_discovery_pv = dict(sample_autopilot_discovery, capability_state="PROBE_VERIFIED")
    jsonschema.validate(instance=sample_autopilot_discovery_pv, schema=autopilot_schema)

    # 6.2 Sample Capability Probe
    sample_autopilot_probe = {
        "record_type": "CAPABILITY_PROBE",
        "probe_id": "probe-l1-001",
        "logical_model_id": "qwen3-coder-plus",
        "channel": "local-cpa",
        "probe_level": "L1_INFERENCE",
        "capability_dimension": "coding",
        "execution_purpose": "CAPABILITY_PROBE",
        "probe_status": "PASS",
        "latency_ms": 320.0,
        "tokens_used": 15,
        "observed_at": "2026-10-06T12:00:01Z",
        "error_type": None
    }
    jsonschema.validate(instance=sample_autopilot_probe, schema=autopilot_schema)

    # 6.3 Sample Lifecycle Transition
    sample_autopilot_transition = {
        "record_type": "LIFECYCLE_TRANSITION",
        "transition_id": "trans-001",
        "logical_model_id": "qwen3-coder-plus",
        "channel": "local-cpa",
        "from_state": "DISCOVERED",
        "to_state": "PROBE_VERIFIED",
        "reason_code": "PROBE_L1_INFERENCE_PASS",
        "evidence_type": "PROBE_RUN",
        "evidence_ref": "probe-l1-001",
        "observed_at": "2026-10-06T12:00:02Z",
        "algorithm_version": "v0.11.0"
    }
    jsonschema.validate(instance=sample_autopilot_transition, schema=autopilot_schema)

    # 6.4 Sample Promotion Recommendation
    sample_autopilot_recommendation = {
        "record_type": "PROMOTION_RECOMMENDATION",
        "recommendation_id": "rec-001",
        "logical_model_id": "qwen3-coder-plus",
        "channel": "local-cpa",
        "consumer": "claude-code",
        "task_family": "coding",
        "capability": "agent_loop",
        "enforcement_mode": "SHADOW_ONLY",
        "current_state": "CHALLENGER",
        "recommended_state": "SHADOW",
        "promotion_recommended": True,
        "demotion_recommended": False,
        "confidence": 0.95,
        "sample_count": 25,
        "recent_success_rate": 0.98,
        "technical_failure_rate": 0.02,
        "latency_p50": 850.0,
        "latency_p95": 1420.0,
        "component_reasons": [
            {
                "metric_name": "agent_loop_pass",
                "threshold": True,
                "observed_value": True,
                "pass": True,
                "reason_cn": "Claude Code 2轮工具闭环验证通过"
            }
        ]
    }
    jsonschema.validate(instance=sample_autopilot_recommendation, schema=autopilot_schema)

    # 6.5 Sample Owner Action Request (Contract Only)
    sample_autopilot_action = {
        "record_type": "OWNER_ACTION_REQUEST",
        "request_id": "act-req-001",
        "action_type": "OLLAMA_PULL_MODEL",
        "owner": "AI-KB",
        "target_resource": "ollama",
        "requested_by": "AI-Engineering-Hub",
        "requested_at": "2026-10-06T12:00:03Z",
        "execution_implemented": False,
        "parameters": {"model_name": "qwen2.5:14b-instruct"},
        "status": "REQUESTED",
        "reason": "Challenger candidate identified for coding experiments"
    }
    jsonschema.validate(instance=sample_autopilot_action, schema=autopilot_schema)

    # 6.5.1 Safe Logical Reference Test
    sample_safe_action = dict(sample_autopilot_action, parameters={"model_name": "qwen2.5:14b-instruct", "credential_ref": "LOCAL_CPA_KEY"})
    jsonschema.validate(instance=sample_safe_action, schema=autopilot_schema)

    # 6.6 Negative tests: forbidden secrets/content (root, parameters, nested depth >= 2, arrays)
    bad_autopilot_samples = [
        ("has_api_key_root", dict(sample_autopilot_probe, api_key="fake-secret")),
        ("has_token_root", dict(sample_autopilot_probe, token="fake-token")),
        ("has_password_root", dict(sample_autopilot_probe, password="fake-password")),
        ("has_secret_root", dict(sample_autopilot_probe, secret="fake-secret")),
        ("has_prompt_body_root", dict(sample_autopilot_probe, prompt_body="fake prompt")),
        ("has_response_body_root", dict(sample_autopilot_probe, response_body="fake response")),
        ("has_source_code_root", dict(sample_autopilot_probe, source_code="fake code")),
        ("has_patch_root", dict(sample_autopilot_probe, patch="fake patch")),
        ("fake_upstream_provider", dict(sample_autopilot_discovery, upstream_provider="unknown")),
        ("fake_provider_zh", dict(sample_autopilot_discovery, upstream_provider="未验证")),
        ("params_api_key", dict(sample_autopilot_action, parameters={"api_key": "fake-secret"})),
        ("params_token", dict(sample_autopilot_action, parameters={"token": "fake-token"})),
        ("params_password", dict(sample_autopilot_action, parameters={"password": "fake-pass"})),
        ("params_secret", dict(sample_autopilot_action, parameters={"secret": "fake-secret"})),
        ("params_prompt_body", dict(sample_autopilot_action, parameters={"prompt_body": "fake-prompt"})),
        ("params_response_body", dict(sample_autopilot_action, parameters={"response_body": "fake-resp"})),
        ("params_source_code", dict(sample_autopilot_action, parameters={"source_code": "fake-code"})),
        ("params_patch", dict(sample_autopilot_action, parameters={"patch": "fake-patch"})),
        ("params_nested_depth_2", dict(sample_autopilot_action, parameters={"model_name": "qwen2.5:14b-instruct", "nested": {"api_key": "fake-key"}})),
        ("params_array_object", dict(sample_autopilot_action, parameters={"model_name": "qwen2.5:14b-instruct", "items": [{"api_key": "fake-key"}]})),
    ]
    for label, bad_item in bad_autopilot_samples:
        try:
            jsonschema.validate(instance=bad_item, schema=autopilot_schema)
            raise AssertionError(f"Failed negative test for STD-024: '{label}' was accepted!")
        except jsonschema.ValidationError:
            pass

    # 7. STD-025 Owner Action Execution Schema Testing
    with open(SCHEMAS_DIR / "owner-action-execution.schema.json", "r", encoding="utf-8") as f:
        exec_schema = json.load(f)
    with open(SCHEMAS_DIR / "model-scout-challenger.schema.json", "r", encoding="utf-8") as f:
        scout_schema = json.load(f)

    sample_owner_action_record = {
        "record_type": "OWNER_ACTION_RECORD",
        "request_id": "act-req-20261007-001",
        "action_type": "CPA_RESTART",
        "safety_class": "REVERSIBLE_OPERATIONAL",
        "target_resource": "local-cpa",
        "owner": "AI-KB",
        "requested_by": "AI-Engineering-Hub",
        "requested_at": "2026-10-07T09:30:00Z",
        "approval_state": "APPROVED",
        "approved_by": "platform-admin",
        "approved_at": "2026-10-07T09:30:05Z",
        "idempotency_key": "idem-act-20261007-001",
        "execution_mode": "APPROVAL_REQUIRED",
        "lease_id": "lease-aikb-cpa-001",
        "executor_id": "aikb-owner-executor",
        "attempt": 1,
        "status": "COMPLETED",
        "reason_code": "LOCAL_CPA_UNHEALTHY_RESTART",
        "reason_cn": "本地 CPA 连续探针失败触发重启自愈",
        "parameters": {"resource_id": "local-cpa", "reason": "health-probe-timeout"},
        "credential_ref": "LOCAL_CPA_KEY",
        "evidence_ref": "evid-1779234567",
        "created_at": "2026-10-07T09:30:00Z",
        "updated_at": "2026-10-07T09:30:30Z"
    }
    jsonschema.validate(instance=sample_owner_action_record, schema=exec_schema)

    sample_transition = {
        "record_type": "OWNER_ACTION_TRANSITION",
        "transition_id": "trans-act-20261007-001",
        "request_id": "act-req-20261007-001",
        "from_status": "APPROVED",
        "to_status": "LEASED",
        "actor": "hub-lease-dispatcher",
        "reason_code": "LEASE_GRANTED",
        "evidence_ref": "lease-aikb-cpa-001",
        "attempt": 1,
        "transitioned_at": "2026-10-07T09:30:10Z"
    }
    jsonschema.validate(instance=sample_transition, schema=exec_schema)

    sample_lease = {
        "record_type": "OWNER_ACTION_LEASE",
        "lease_id": "lease-aikb-cpa-001",
        "request_id": "act-req-20261007-001",
        "executor_id": "aikb-owner-executor",
        "target_resource": "local-cpa",
        "leased_at": "2026-10-07T09:30:10Z",
        "lease_expires_at": "2026-10-07T09:32:10Z",
        "lease_duration_seconds": 120,
        "attempt": 1
    }
    jsonschema.validate(instance=sample_lease, schema=exec_schema)

    sample_result = {
        "record_type": "OWNER_ACTION_RESULT",
        "request_id": "act-req-20261007-001",
        "lease_id": "lease-aikb-cpa-001",
        "executor_id": "aikb-owner-executor",
        "attempt": 1,
        "execution_started_at": "2026-10-07T09:30:12Z",
        "execution_finished_at": "2026-10-07T09:30:22Z",
        "exit_status": "SUCCESS",
        "exit_code": 0,
        "owner_result": {
            "command_executed": "ops/cpa/local_cpa.py restart",
            "duration_seconds": 9.8,
            "status_summary": "Local CPA container restarted and reached healthy state"
        },
        "reason_code": "LOCAL_CPA_RESTART_SUCCESS",
        "resource_state_before": {"status": "UNHEALTHY", "port": 18117},
        "resource_state_after": {"status": "RUNNING", "port": 18117, "healthy": True},
        "evidence_ref": "exec-fact-1779234567"
    }
    jsonschema.validate(instance=sample_result, schema=exec_schema)

    sample_verification = {
        "record_type": "OWNER_ACTION_VERIFICATION",
        "verification_id": "verif-act-20261007-001",
        "request_id": "act-req-20261007-001",
        "action_type": "CPA_RESTART",
        "target_resource": "local-cpa",
        "verification_status": "PASS",
        "verified_at": "2026-10-07T09:30:25Z",
        "checks": [
            {"name": "endpoint_http_reachability", "pass": True, "observed_value": 200, "detail": "HTTP 200 OK from 127.0.0.1:18117"},
            {"name": "catalog_rediscovery", "pass": True, "observed_value": 92, "detail": "Discovered 92 models from Local CPA"},
            {"name": "l1_inference_probe", "pass": True, "observed_value": "pass", "detail": "Minimal generation probe passed"},
            {"name": "agent_compatibility_invariant", "pass": True, "observed_value": "preserved", "detail": "No degradation detected"}
        ],
        "evidence_ref": "verif-fact-1779234567"
    }
    jsonschema.validate(instance=sample_verification, schema=exec_schema)

    bad_exec_samples = [
        ("action_has_api_key", dict(sample_owner_action_record, api_key="leak")),
        ("action_has_secret", dict(sample_owner_action_record, secret="leak")),
        ("action_params_token", dict(sample_owner_action_record, parameters={"token": "leak"})),
        ("result_has_password", dict(sample_result, password="leak")),
        ("result_owner_result_secret", dict(sample_result, owner_result={"secret": "leak"})),
        ("invalid_action_type", dict(sample_owner_action_record, action_type="UNKNOWN_DOCKER_RUN")),
        ("invalid_status", dict(sample_owner_action_record, status="INVALID_STATUS")),
    ]
    for label, bad_item in bad_exec_samples:
        try:
            jsonschema.validate(instance=bad_item, schema=exec_schema)
            raise AssertionError(f"Failed negative test for STD-025: '{label}' was accepted!")
        except jsonschema.ValidationError:
            pass

    # 9. Test STD-026 Model Scout and Challenger Contract Samples
    sample_scout_source = {
        "record_type": "SCOUT_SOURCE",
        "source_id": "src-local-cpa",
        "source_type": "ACTIVE_RUNTIME_CATALOG",
        "owner": "AI-KB",
        "provider": None,
        "trust_level": "AUTHORITATIVE_RUNTIME",
        "endpoint_ref": "http://127.0.0.1:18117/v1/models",
        "credential_ref": "LOCAL_CPA_KEY",
        "enabled": True,
        "discovery_interval_seconds": 60,
        "last_success_at": "2026-10-07T10:00:00Z",
        "last_error": None,
        "catalog_generation": 12
    }
    jsonschema.validate(instance=sample_scout_source, schema=scout_schema)

    sample_scout_candidate = {
        "record_type": "SCOUT_CANDIDATE",
        "candidate_id": "cand-qwen-coder-30b",
        "logical_model_id": "qwen2.5-coder-32b-instruct",
        "channel": "local-cpa",
        "resource_id": "local-cpa",
        "provider": None,
        "provenance_status": "LOCAL_RUNTIME",
        "source_id": "src-local-cpa",
        "availability_class": "AVAILABLE_NOW",
        "first_seen_at": "2026-10-07T08:00:00Z",
        "last_seen_at": "2026-10-07T10:00:00Z",
        "model_fingerprint": "fp-qwen-32b-v1",
        "declared_capabilities": ["coding", "agent_loop"],
        "verified_capabilities": ["coding", "agent_tool_use", "agent_loop"],
        "context_metadata": {"context_window": 32768},
        "cost_metadata": None,
        "install_action_required": None,
        "lifecycle_state": "CHALLENGER",
        "agent_compatibility": "AGENT_COMPATIBLE",
        "technical_health": "HEALTHY",
        "confidence": 0.85,
        "memory_epoch": 1
    }
    jsonschema.validate(instance=sample_scout_candidate, schema=scout_schema)

    sample_scout_campaign = {
        "record_type": "SCOUT_CAMPAIGN",
        "campaign_id": "camp-20261007-claude-coding",
        "consumer": "claude-code",
        "task_family": "coding_agent",
        "capability_profile": "agent_coding_high_quality",
        "champion": {
            "logical_model_id": "claude-3-7-sonnet",
            "channel": "cloud-cpa",
            "champion_source": "PRODUCTION_ROUTE_WINNER",
            "champion_reason": "Incumbent production route leader for claude-code",
            "champion_snapshot_at": "2026-10-07T10:00:00Z"
        },
        "challengers": [
            {"logical_model_id": "qwen2.5-coder-32b-instruct", "channel": "local-cpa", "eligibility_status": "ELIGIBLE"},
            {"logical_model_id": "deepseek-coder-v2", "channel": "cloud-cpa", "eligibility_status": "ELIGIBLE"}
        ],
        "candidate_source_snapshot": ["src-local-cpa", "src-cloud-cpa"],
        "candidate_eligibility_rules": {"agent_compatible_required": True, "availability": "AVAILABLE_NOW"},
        "challenge_suite": {
            "suite_id": "agent-coding-microbench-v1",
            "suite_type": "AGENT_MICROBENCH",
            "suite_version": "v1.0.0",
            "case_count": 3
        },
        "fairness_specification": {
            "task": "coding_agent_microbench",
            "prompt_version": "v1.0.0",
            "tool_definition_version": "v1.0.0",
            "acceptance_criteria": "pass_syntax_and_targeted_tests",
            "timeout_seconds": 30.0,
            "retry_allowance": 1,
            "execution_environment": "isolated_sandbox",
            "base_fixture_hash": "a1b2c3d4e5f6",
            "max_token_budget": 4096,
            "evaluator_version": "v1.0.0",
            "temperature": 0.0,
            "capability_probe_level": "L3_AGENT_LOOP",
            "fairness_spec_hash": "f9e8d7c6b5a4"
        },
        "budget_specification": {
            "max_candidates_per_cycle": 5,
            "max_challenges_per_cycle": 10,
            "max_concurrent_challenges": 2,
            "max_token_budget_per_cycle": 50000,
            "max_token_budget_per_day": 200000,
            "per_provider_cooldown_seconds": 30,
            "timeout_budget_seconds": 120,
            "owner_action_request_budget": 2
        },
        "created_at": "2026-10-07T10:00:00Z",
        "status": "COMPLETED"
    }
    jsonschema.validate(instance=sample_scout_campaign, schema=scout_schema)

    sample_trial = {
        "record_type": "CHALLENGE_TRIAL",
        "trial_id": "trial-20261007-001",
        "campaign_id": "camp-20261007-claude-coding",
        "suite_id": "agent-coding-microbench-v1",
        "case_id": "case-01-file-patch",
        "logical_model_id": "qwen2.5-coder-32b-instruct",
        "channel": "local-cpa",
        "execution_purpose": "SCOUT_CHALLENGE",
        "workspace_path_hash": "ws-hash-12345",
        "pass": True,
        "latency_ms": 1250.0,
        "tool_result_enums": ["TOOL_CALL_VALID", "PATCH_APPLIED", "TEST_PASS"],
        "attempts": 1,
        "failure_stage": None,
        "executed_at": "2026-10-07T10:05:00Z"
    }
    jsonschema.validate(instance=sample_trial, schema=scout_schema)

    sample_result_memory = {
        "record_type": "CHALLENGE_RESULT_MEMORY",
        "memory_id": "mem-qwen-coder-32b",
        "consumer": "claude-code",
        "task_family": "coding_agent",
        "capability_profile": "agent_coding_high_quality",
        "logical_model_id": "qwen2.5-coder-32b-instruct",
        "channel": "local-cpa",
        "suite_version": "v1.0.0",
        "sample_count": 15,
        "completion_rate": 0.933,
        "technical_pass_rate": 1.0,
        "tool_loop_pass_rate": 0.933,
        "targeted_test_pass_rate": 0.933,
        "latency_p50_ms": 1100.0,
        "latency_p95_ms": 2300.0,
        "retry_rate": 0.067,
        "failure_stage_distribution": {"none": 14, "syntax": 1},
        "recent_evidence_weight": 12.4,
        "confidence": 0.88,
        "last_challenged_at": "2026-10-07T10:05:00Z",
        "memory_epoch": 1,
        "view_type": "EFFECTIVE"
    }
    jsonschema.validate(instance=sample_result_memory, schema=scout_schema)

    sample_comparison = {
        "record_type": "CHALLENGER_COMPARISON",
        "comparison_id": "comp-20261007-001",
        "campaign_id": "camp-20261007-claude-coding",
        "champion_model": "claude-3-7-sonnet",
        "challenger_model": "qwen2.5-coder-32b-instruct",
        "channel": "local-cpa",
        "conclusion": "TRADEOFF",
        "multi_dimensional_metrics": {
            "completion_rate_diff": -0.05,
            "latency_p95_diff_ms": -450.0
        },
        "pareto_tradeoffs": ["Challenger faster P95 latency (-450ms) but slightly lower completion rate (-5%)"],
        "raw_challenge_capability": {"completion_rate": 0.933, "agent_loop_pass": True},
        "platform_production_policy": {"policy": "QWEN_LAST_RESORT", "live_routing_penalty": -40},
        "compared_at": "2026-10-07T10:10:00Z"
    }
    jsonschema.validate(instance=sample_comparison, schema=scout_schema)

    sample_recommendation = {
        "record_type": "SCOUT_PROMOTION_RECOMMENDATION",
        "recommendation_id": "rec-scout-20261007-001",
        "campaign_id": "camp-20261007-claude-coding",
        "logical_model_id": "qwen2.5-coder-32b-instruct",
        "channel": "local-cpa",
        "consumer": "claude-code",
        "task_family": "coding_agent",
        "recommendation_type": "MORE_EVIDENCE_REQUIRED",
        "production_promoted": False,
        "confidence": 0.88,
        "sample_count": 15,
        "component_reasons": [
            {
                "metric_name": "agent_loop_pass",
                "threshold": True,
                "observed_value": True,
                "pass": True,
                "reason_cn": "智能体编程闭环微基准全部通过"
            },
            {
                "metric_name": "sample_count",
                "threshold": 20,
                "observed_value": 15,
                "pass": False,
                "reason_cn": "样本量15次，尚低于高置信晋升门槛20次"
            }
        ],
        "owner_action_required": None,
        "resource_preflight": {
            "model_size_bytes": None,
            "free_disk_bytes": None,
            "gpu_category": None,
            "ram_category": None,
            "resource_fit": "UNKNOWN"
        },
        "created_at": "2026-10-07T10:10:00Z"
    }
    jsonschema.validate(instance=sample_recommendation, schema=scout_schema)

    bad_scout_samples = [
        ("scout_source_has_api_key", dict(sample_scout_source, api_key="leak")),
        ("scout_candidate_has_secret", dict(sample_scout_candidate, secret="leak")),
        ("scout_trial_has_prompt_body", dict(sample_trial, prompt_body="leak")),
        ("scout_trial_has_response_body", dict(sample_trial, response_body="leak")),
        ("scout_trial_has_source_code", dict(sample_trial, source_code="leak")),
        ("scout_trial_has_patch", dict(sample_trial, patch="leak")),
        ("scout_campaign_invalid_status", dict(sample_scout_campaign, status="INVALID_STATUS")),
        ("scout_candidate_invalid_avail", dict(sample_scout_candidate, availability_class="UNKNOWN_CLASS")),
    ]
    for label, bad_item in bad_scout_samples:
        try:
            jsonschema.validate(instance=bad_item, schema=scout_schema)
            raise AssertionError(f"Failed negative test for STD-026: '{label}' was accepted!")
        except jsonschema.ValidationError:
            pass

    
    # 15. Test Safe Autonomous Promotion Sample (STD-027 v1.9.0)
    with open(SCHEMAS_DIR / "safe-autonomous-promotion.schema.json", "r", encoding="utf-8") as f:
        autonomy_schema = json.load(f)

    sample_scope = {
        "record_type": "AUTONOMY_SCOPE_DEFINITION",
        "scope_id": "scope-claude-code-coding_agent-agent_coding_high_quality-hub-code-auto",
        "consumer": "claude-code",
        "task_family": "coding_agent",
        "capability_profile": "agent_coding_high_quality",
        "virtual_profile": "hub-code-auto",
        "mode": "SAFE_AUTONOMOUS",
        "rollout_state": "CANARY_ACTIVE",
        "champion_model_id": "qwen2.5:7b-instruct",
        "champion_channel": "local-cpa",
        "canary_model_id": "deepseek-coder:6.7b",
        "canary_channel": "local-cpa",
        "canary_weight": 0.05,
        "routing_revision": 2,
        "stage": 1,
        "observation_count": 5,
        "cooldown_until": 0.0,
        "is_frozen": False,
        "pinned_champion_model_id": None,
        "updated_at": "2026-10-08T10:00:00Z"
    }
    jsonschema.validate(instance=sample_scope, schema=autonomy_schema)

    sample_snapshot = {
        "record_type": "CHAMPION_ROUTING_SNAPSHOT",
        "snapshot_id": "snap-20261008-001",
        "scope_id": "scope-claude-code-coding_agent-agent_coding_high_quality-hub-code-auto",
        "routing_revision": 1,
        "champion_model_id": "qwen2.5:7b-instruct",
        "champion_channel": "local-cpa",
        "candidate_plan": [{"rank": 1, "model": "qwen2.5:7b-instruct", "channel": "local-cpa"}],
        "policy_version": "v1.9.0",
        "captured_at": "2026-10-08T10:00:00Z"
    }
    jsonschema.validate(instance=sample_snapshot, schema=autonomy_schema)

    sample_event = {
        "record_type": "AUTONOMOUS_PROMOTION_EVENT",
        "promotion_event_id": "promo-20261008-001",
        "scope": "scope-claude-code-coding_agent-agent_coding_high_quality-hub-code-auto",
        "candidate": "deepseek-coder:6.7b",
        "champion": "qwen2.5:7b-instruct",
        "from_rollout_state": "ELIGIBLE",
        "to_rollout_state": "CANARY_ACTIVE",
        "from_weight": 0.0,
        "to_weight": 0.05,
        "routing_revision_before": 1,
        "routing_revision_after": 2,
        "reason_code": "CANARY_ACTIVATED_5",
        "reason_cn": "候选模型通过全部 19 项硬门禁，首次进入 5% 受控金丝雀分流",
        "evidence_refs": ["scout-campaign-20261008-001"],
        "policy_version": "v1.9.0",
        "algorithm_version": "v1.0.0",
        "executed_at": "2026-10-08T10:00:00Z",
        "rollback_snapshot_ref": "snap-20261008-001"
    }
    jsonschema.validate(instance=sample_event, schema=autonomy_schema)

    sample_rollback = {
        "record_type": "AUTONOMOUS_ROLLBACK_EVENT",
        "rollback_event_id": "roll-20261008-001",
        "scope_id": "scope-claude-code-coding_agent-agent_coding_high_quality-hub-code-auto",
        "candidate": "deepseek-coder:6.7b",
        "champion": "qwen2.5:7b-instruct",
        "trigger_gate": "AGENT_COMPATIBILITY_INVALIDATED",
        "trigger_reason": "Tool loop failure exceeded threshold",
        "trigger_cn": "Agent 工具循环协议异常，触发自主安全回滚",
        "canary_vs_champion_diff": {"error_rate_diff": 0.08},
        "restored_routing_revision": 1,
        "cooldown_until": "2026-10-08T11:00:00Z",
        "executed_at": "2026-10-08T10:05:00Z"
    }
    jsonschema.validate(instance=sample_rollback, schema=autonomy_schema)

# 13. Test Model Supply Autopilot Schema
    with open(SCHEMAS_DIR / "model-supply-autopilot.schema.json", "r", encoding="utf-8") as f:
        supply_schema = json.load(f)

    sample_source = {
        "record_type": "MODEL_SUPPLY_SOURCE",
        "source_id": "src-openrouter-official",
        "source_type": "OPENROUTER_CATALOG",
        "provider_name": "OpenRouter",
        "catalog_endpoint": "https://openrouter.ai/api/v1/models",
        "probe_endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "credential_ref": "env://OPENROUTER_API_KEY",
        "credential_state": "AVAILABLE",
        "trust_level": "TRUSTED",
        "enabled": True,
        "discovery_interval_seconds": 3600,
        "rate_limit_policy": "DEFAULT_BACKOFF",
        "terms_status": "ACCEPTED",
        "last_success_at": "2026-10-08T10:00:00Z",
        "last_error": None,
        "backoff_until": None,
        "catalog_generation": 1
    }
    jsonschema.validate(instance=sample_source, schema=supply_schema)

    sample_supply_item = {
        "record_type": "MODEL_SUPPLY_ITEM",
        "supply_id": "sup-openrouter-liquid-lfm-free",
        "source_id": "src-openrouter-official",
        "provider_name": "OpenRouter",
        "logical_model_id": "liquid/lfm-2.5-2.6b:free",
        "raw_model_id": "liquid/lfm-2.5-2.6b:free",
        "channel": "openrouter-free",
        "pricing_class": "FREE_NOW",
        "stability_class": "EPHEMERAL_FREE",
        "availability_state": "PROBE_READY",
        "quota_state": "HEALTHY",
        "cost_class": "COST_FREE",
        "input_price_per_m": 0.0,
        "output_price_per_m": 0.0,
        "currency": "USD",
        "pricing_verified_at": "2026-10-08T10:00:00Z",
        "cpa_onboarded": False,
        "cpa_route_id": None,
        "discovered_at": "2026-10-08T10:00:00Z",
        "updated_at": "2026-10-08T10:00:00Z"
    }
    jsonschema.validate(instance=sample_supply_item, schema=supply_schema)

    sample_onboarding_event = {
        "record_type": "CPA_ONBOARDING_EVENT",
        "onboarding_id": "onb-20261008-001",
        "supply_id": "sup-codingplan-qwen3.6-plus-auto",
        "provider_name": "CodingPlan",
        "model_name": "qwen3.6-plus",
        "target_resource": "local-cpa",
        "onboarding_path": "PREAUTHORIZED_AUTOMATIC",
        "owner_action_request_id": "act-req-20261008-onb-001",
        "catalog_preserved": True,
        "post_probe_verified": True,
        "fallback_count": 0,
        "completed_at": "2026-10-08T10:05:00Z"
    }
    jsonschema.validate(instance=sample_onboarding_event, schema=supply_schema)

    # 18. Test STD-031 Runtime Acceptance Contract Sample
    with open(SCHEMAS_DIR / "runtime-acceptance.schema.json", "r", encoding="utf-8") as f:
        runtime_acc_schema = json.load(f)

    sample_runtime_acc = {
        "runtime_acceptance": True,
        "service": "AI-Hub",
        "version": "v0.20.0",
        "commit": "a45b0fa",
        "build_commit": "a45b0fa",
        "stage": "PRODUCTION_READY",
        "checks_total": 8,
        "checks_pass": 8,
        "checks_fail": 0,
        "failed_components": [],
        "runtime_identity": {
            "source_commit": "a45b0fa",
            "build_commit": "a45b0fa",
            "live_commit": "a45b0fa",
            "platform": "Windows-11",
            "python_version": "3.10.11",
            "technology_stack": "TECHNOLOGY_AGNOSTIC",
            "docker_bound": False,
        },
        "checks": [
            {
                "name": "hub_python_runtime",
                "stage": "BUILD",
                "component": "Hub",
                "passed": True,
                "detail": "Python version: 3.10.11"
            }
        ],
        "timestamp": "2026-10-12T06:00:00Z"
    }
    jsonschema.validate(instance=sample_runtime_acc, schema=runtime_acc_schema)

    # 19. Test STD-032 Release Engineering Contract Sample
    with open(SCHEMAS_DIR / "release-engineering.schema.json", "r", encoding="utf-8") as f:
        rel_eng_schema = json.load(f)

    sample_rel_eng = {
        "standard_id": "STD-032",
        "service": "AI-Hub",
        "version": "v0.20.1",
        "tag": "v0.20.1",
        "pipeline_status": "PASS",
        "stages": [
            "PLAN",
            "CODE",
            "DEV_TEST",
            "SECURITY_SCAN",
            "BUILD",
            "PACKAGE",
            "PUBLISH",
            "DEPLOY",
            "RUNTIME_VERIFY",
            "SMOKE_TEST",
            "PRODUCTION_RELEASE",
            "TAG",
        ],
        "commit_identity": {
            "LOCAL_HEAD": "a1b2c3d",
            "REMOTE_HEAD": "a1b2c3d",
            "TAG_COMMIT": "a1b2c3d",
            "BUILD_COMMIT": "a1b2c3d",
            "LIVE_COMMIT": "a1b2c3d",
            "all_consistent": True,
        },
        "gates": {
            "SOURCE": {"git_clean": True, "secret_scan": True, "passed": True},
            "DEV_TEST": {
                "unit_test": True,
                "contract_test": True,
                "integration_test": True,
                "e2e": True,
                "passed": True,
            },
            "BUILD": {"build_metadata_generated": True, "passed": True},
            "PACKAGE": {
                "artifact_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "passed": True,
            },
            "DEPLOY": {
                "runtime_probe": True,
                "technology_agnostic": True,
                "docker_bound": False,
                "passed": True,
            },
            "SMOKE": {"minimal_business_verification": True, "passed": True},
        },
        "artifacts": {
            "layout_valid": True,
            "docs_clean": True,
            "package_path": ".artifacts/packages/Acceptance-AI-Platform-023-RELEASE-ENGINEERING-STANDARDIZATION.zip",
            "package_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        },
        "runtime_acceptance": True,
        "rollback_contract": {
            "technology_agnostic": True,
            "docker_bound": False,
            "target_tag": "v0.20.0",
            "verified": True,
        },
        "timestamp": "2026-10-13T04:00:00Z",
    }
    jsonschema.validate(instance=sample_rel_eng, schema=rel_eng_schema)

# 20. Test STD-033 Platform Verification Governance Evidence Sample
    with open(SCHEMAS_DIR / "platform-verification.schema.json", "r", encoding="utf-8") as f:
        pv_schema = json.load(f)

    sample_platform_verification = {
        "verification_id": "VERIFY-AI-PLATFORM-026-FINAL",
        "timestamp": "2026-10-13T09:00:00Z",
        "overall_status": "READY",
        "status": "PASS",
        "platform": {
            "name": "AI Engineering Platform",
            "task_id": "AI-Platform-026-ENGINEERING-GOVERNANCE-FINALIZATION",
            "role": "PLATFORM_ENGINEERING_GOVERNANCE_FINALIZATION",
            "version": "v2.4.0",
            "standard_version": "v2.4.0",
            "governance_standard": "STD-033 (Tri-Layer: STD-031, STD-032, STD-033)",
            "environment": "Windows-11",
            "python_version": "3.14.3",
            "technology_stack": "TECHNOLOGY_AGNOSTIC",
            "docker_bound": False,
            "package_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        },
        "components": {
            "AI-Hub": {
                "component": "AI-Hub",
                "repo_name": "AI-Engineering-Hub",
                "version": "v0.20.3",
                "status": "READY",
                "last_verified_at": "2026-10-13T09:00:00Z",
                "commit": "f8326fd",
                "tag": "v0.20.3",
                "five_way_consistent": True,
                "runtime": "READY (HTTP 200)",
                "runtime_passed": True,
                "dependency_status": "READY (CPA · Ollama · SQLite WAL)",
                "dependency_passed": True,
                "smoke_status": "PASS (model/select)",
                "smoke_passed": True,
                "endpoint": "http://127.0.0.1:80/health"
            },
            "AI-KB": {
                "component": "AI-KB",
                "repo_name": "AI-KB",
                "version": "v0.9.0",
                "status": "READY",
                "last_verified_at": "2026-10-13T09:00:00Z",
                "commit": "cddd081",
                "tag": "v0.9.0",
                "five_way_consistent": True,
                "runtime": "READY (HTTP 200)",
                "runtime_passed": True,
                "dependency_status": "READY (RAGFlow · Ollama · Control Center)",
                "dependency_passed": True,
                "smoke_status": "PASS (readonly query)",
                "smoke_passed": True,
                "endpoint": "http://127.0.0.1:18090/api/health"
            },
            "Sidecar": {
                "component": "Sidecar",
                "repo_name": "vtip-ai-sidecar",
                "version": "v0.14.2",
                "status": "READY",
                "last_verified_at": "2026-10-13T09:00:00Z",
                "commit": "3393806",
                "tag": "v0.14.2",
                "five_way_consistent": True,
                "runtime": "READY (HTTP 200)",
                "runtime_passed": True,
                "dependency_status": "READY (AI-Hub Gateway · CPA)",
                "dependency_passed": True,
                "smoke_status": "PASS (sample transform)",
                "smoke_passed": True,
                "endpoint": "http://127.0.0.1:8799/health"
            },
            "VTIP": {
                "component": "VTIP",
                "repo_name": "vtip-platform-catalog",
                "version": "v2.6.7",
                "status": "READY",
                "last_verified_at": "2026-10-13T09:00:00Z",
                "commit": "d44c06a",
                "tag": "v2.6.7",
                "five_way_consistent": True,
                "runtime": "READY (HTTP 200)",
                "runtime_passed": True,
                "dependency_status": "READY (Confluence/Jira Read-Only · Work Calendar)",
                "dependency_passed": True,
                "smoke_status": "PASS (catalog query)",
                "smoke_passed": True,
                "endpoint": "http://127.0.0.1:8787/healthz"
            }
        },
        "identity": {
            "status": "READY",
            "passed": True,
            "five_way_consistent": True,
            "LOCAL_HEAD": "f8326fd",
            "REMOTE_HEAD": "f8326fd",
            "TAG": "v0.20.3",
            "TAG_COMMIT": "f8326fd",
            "BUILD": "f8326fd",
            "LIVE": "f8326fd",
            "by_component": {
                "AI-Hub": {"all_consistent": True},
                "AI-KB": {"all_consistent": True},
                "Sidecar": {"all_consistent": True},
                "VTIP": {"all_consistent": True}
            }
        },
        "runtime": {
            "status": "READY",
            "passed": True,
            "service_health": "HTTP 200",
            "process_status": "RUNNING",
            "endpoint": "ALL_LISTENING",
            "startup": "LIFESPAN_READY",
            "by_component": {}
        },
        "dependency": {
            "status": "READY",
            "passed": True,
            "non_spof_enforced": True,
            "CPA": {"status": "READY", "port": 18317},
            "AI-KB": {"status": "READY", "port": 18090},
            "RAGFlow": {"status": "READY", "port": 18080},
            "Ollama": {"status": "READY", "port": 11434},
            "Database": {"status": "READY", "type": "sqlite_wal"}
        },
        "network": {
            "status": "READY",
            "passed": True,
            "expected_network": {"loopback": "127.0.0.1"},
            "actual_network": {"exposed_lan": False},
            "dns_alias": {"localhost": "127.0.0.1"},
            "service_discovery": {"status": "ACTIVE"}
        },
        "business_smoke": {
            "status": "READY",
            "passed": True,
            "Hub": {"passed": True, "action": "model/select"},
            "AI-KB": {"passed": True, "action": "readonly query"},
            "Sidecar": {"passed": True, "action": "sample transform"},
            "VTIP": {"passed": True, "action": "catalog query"}
        }
    }
    jsonschema.validate(instance=sample_platform_verification, schema=pv_schema)

    print(f"Sample validation PASS: Standards {(ROOT / 'VERSION').read_text().strip()}.")
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
    approval_tests = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    if not unittest.TextTestRunner(verbosity=2).run(approval_tests).wasSuccessful():
        failed += 1

    if failed == 0:
        print(f"\nAll {len(schemas)} schemas validated successfully!")
        sys.exit(0)
    else:
        print(f"\nValidation failed for {failed} schemas.")
        sys.exit(1)

if __name__ == "__main__":
    main()
