# AI Engineering Standards - Changelog

All notable changes to the AI Engineering Standards baseline are documented in this file.

## [2.1.1] - 2026-10-10

### Added
- **STD-009 v2.1.1**: 通用任务契约（Generic Task Contract）落地，正式引入 consumer_id, 	ask_family, 	ask_type, capability_profile, output_contract 字段。
- **STD-009 v2.1.1**: 同义字段冲突硬检验契约（HTTP 422 SYNONYMOUS_FIELD_CONFLICT）与未注册消费端鉴权拒绝（HTTP 403）。
- **STD-010 v1.3.1**: 多阶段反馈契约支持通用任务字段，明确 BULLET_LIMIT_EXCEEDED 软告警隔离与 HTTP200_EMPTY_STRUCTURE 真实归因。
- **STD-030 v2.1.1**: 明确 Sidecar 标准语义 (consumer_id=sidecar, 	ask_family=document_transformation, 	ask_type=report_polishing, capability_profile=faithful_summarization, output_contract=markdown_structured_bullets)，锁定 capability_profile 为命名字符串。

### Changed
- schemas/model-routing-request.schema.json: 支持 nyOf 兼容旧 	ask 与规范 	ask_type，新增通用契约可选字段。
- schemas/model-feedback.schema.json: 新增通用契约可选字段，继续保持 dditionalProperties: false。
- schemas/model-routing-response.schema.json: 增补候选执行方案增量元数据定义。
- schemas/unified-ai-capability-platform.schema.json: 升级 contract_version 至 2.1.1，补齐消费端契约字段。

---

## [2.1.0] - 2026-10-09

### Added
- **STD-030: Unified AI Capability Platform Contract**: 四库分离架构、模型部署智能、推理引擎能力目录、只读硬件画像、多模态调度与多消费端隔离治理。
- schemas/unified-ai-capability-platform.schema.json: 统一平台契约元数据 Schema。

---

## [2.0.0] - 2026-10-08

### Added
- **STD-028 Model Supply Autopilot and Champion Management Contract**: Canonical standard for external model supply discovery, free/trial pricing classification, zero-secret availability probing, CPA transactional onboarding, quota health backoff, cost-aware multi-objective routing with Free Capacity Lane, and 5-stage autonomous Champion management.
- **model-supply-autopilot.schema.json**: JSON Schema validating Model Supply Sources, Discovered Items, Probe Results, Quota Events, CPA Onboarding Events, and Champion Rollout Events.
- **STD-025 Extension**: Added `CPA_REGISTER_MODEL_ROUTE`, `CPA_DISABLE_MODEL_ROUTE`, and `CPA_REFRESH_MODEL_CATALOG` canonical action types, alongside `POLICY_PREAUTHORIZED` execution mode for approved low-risk non-destructive route registrations.

---

## [1.9.0] - 2026-10-08

### Added
- **STD-027: Safe Autonomous Promotion and Canary Routing Contract** (`standards/08-model-governance/STD-027-safe-autonomous-promotion-contract.md`)
  - Canonical contract for Model Ops Autopilot R4 bounded production routing autonomy:
    - Scoped `SAFE_AUTONOMOUS` mode while retaining global `SHADOW_ONLY` default.
    - Orthogonal rollout state machine (`NOT_ELIGIBLE`, `ELIGIBLE`, `CANARY_PENDING`, `CANARY_ACTIVE`, `CANARY_HOLD`, `ROLLBACK_PENDING`, `ROLLED_BACK`, `PROMOTION_READY`, `FULL_PROMOTION_BLOCKED`).
    - 19 mandatory hard evidence gates (sample_count >= 10, confidence >= 0.90, agent compatible, health, circuit breaker, etc.).
    - Strict bounded canary stages (0% -> 5% -> 10% maximum).
    - Deterministic non-sensitive hash bucketing and frozen plan preservation.
    - Dual-condition observation windows (dwell time + eligible samples).
    - Autonomous rollback with relative Champion degradation budgets.
    - Anti-flapping hysteresis cooldown (>= 60 minutes).
    - Champion preservation snapshot and versioned Compare-and-Swap (CAS) routing policy update.
    - Operator override precedence and restart-persistent global Autonomy Kill Switch.
    - Explainable governance audit and zero metrics double-counting invariants.
- **Canonical Schema**: `schemas/safe-autonomous-promotion.schema.json` supporting all 9 canonical R4 autonomy record types.

## [1.8.0] - 2026-10-07

### Added
- **STD-026: Model Scout and Challenger Contract (AI-Hub-014-R3-MODEL-SCOUT-AND-CHALLENGER-AUTOMATION)**:
  - Established canonical Model Scout Source Registry supporting 4 classes (`ACTIVE_RUNTIME_CATALOG`, `OWNER_CANDIDATE_CATALOG`, `PROVIDER_DECLARED_CATALOG`, `OPTIONAL_PUBLIC_METADATA_CATALOG`).
  - Defined 3 candidate physical availability classes (`AVAILABLE_NOW`, `OWNER_ACTION_REQUIRED`, `METADATA_ONLY`).
  - Enforced zero-trust model provenance (no provider inference from model names).
  - Defined Scoped Scout Campaign with frozen Champion semantics (`PRODUCTION_ROUTE_WINNER`, `HISTORICAL_LEADER`, `PLATFORM_PINNED_BASELINE`) and hard eligibility gates (`AGENT_COMPATIBLE` required for coding agent challenges).
  - Codified separation of production routing preferences from challenge fairness (`RAW_CHALLENGE_CAPABILITY` vs `PLATFORM_PRODUCTION_POLICY`).
  - Defined Frozen Fairness Specification with `fairness_spec_hash`.
  - Defined Challenge Suite Registry (`TECHNICAL_MICROBENCH`, `AGENT_MICROBENCH`, `CONSUMER_BUSINESS_EVALUATION`) with isolated coding sandboxes and zero prompt/code leakage.
  - Defined Dedicated Challenge Result Memory, exponential time decay (`ALL_TIME` vs `EFFECTIVE` views), memory epochs, and conservative exploration budget governance.
  - Defined multi-dimensional Pareto comparison conclusions and explainable promotion recommendations (`PROMOTION_RECOMMENDED != PRODUCTION_PROMOTED`).
  - Integrated STD-025 Owner Action requests in `APPROVAL_REQUIRED` and Ollama resource preflight; strictly disabled automatic model removal (`OLLAMA_REMOVE_MODEL`).
  - Codified four-layer zero double-counting invariants (`SCOUT_L1_DOUBLE_COUNT=false`, `SCOUT_CODING_OUTCOME_DOUBLE_COUNT=false`, `SCOUT_AIKB_QUALITY_DOUBLE_COUNT=false`, `SCOUT_SIDECAR_BUSINESS_DOUBLE_COUNT=false`).
  - Published machine-readable `schemas/model-scout-challenger.schema.json`.

## [1.7.0] - 2026-10-07

### Added
- **STD-025: Owner Action Execution Contract (AI-Hub-014-R2-OWNER-ACTION-EXECUTOR)**:
  - Formally established the execution plane boundary: Hub = Control Plane (decision, approval, lease, verification, close-loop), AI-KB = Resource Owner (local validation, exclusive lock, canonical lifecycle execution, non-sensitive fact results).
  - Defined canonical end-to-end flow: OBSERVE -> RECOMMEND -> OWNER_ACTION_REQUEST -> APPROVAL -> OWNER_ACK -> EXECUTION_LEASE -> OWNER_EXECUTION -> OWNER_RESULT -> HUB_REDISCOVERY -> HUB_CAPABILITY_PROBE -> VERIFY -> ACTION_COMPLETED | ACTION_FAILED -> LIFECYCLE_REEVALUATION.
  - Defined 14 canonical execution states (`REQUESTED`, `APPROVAL_REQUIRED`, `APPROVED`, `ACKNOWLEDGED`, `LEASED`, `EXECUTING`, `EXECUTION_SUCCEEDED`, `EXECUTION_FAILED`, `VERIFYING`, `VERIFIED`, `COMPLETED`, `REJECTED`, `EXPIRED`, `CANCELLED`).
  - Codified the non-equivalence invariant: `OWNER_EXECUTION_SUCCEEDED != ACTION_COMPLETED` (execution exit code 0 requires independent Hub verification).
  - Codified `ONE_REQUEST_ID_ONE_EFFECT=true`, exclusive execution leases, and resource concurrency guards.
  - Published machine-readable `schemas/owner-action-execution.schema.json`.

## [1.6.1] - 2026-10-06

### Changed
- Hardened STD-024 Model Ops Autopilot parameter allowlists and recursive zero-secret scanning.
- Normalized dual-layer capability states: Aggregate Capability State vs Per-Dimension Capability Verification State.

## [1.6.0] - 2026-10-06

### Added
- **STD-024: Model Ops Autopilot Governance Contract (AI-Hub-014-R1-MODEL-OPS-AUTOPILOT-FOUNDATION)**:
  - Background asynchronous discovery across Local CPA, Cloud CPA, and Ollama.
  - Tiered capability probes (L0-L3) with critical-path routing isolation (P95 <= 50ms).
  - Deterministic lifecycle state machine (DISCOVERED, PROBE_VERIFIED, CHALLENGER, SHADOW, PRODUCTION_ELIGIBLE, TEMP_UNAVAILABLE, QUARANTINED, REJECTED).
  - Shadow-only governance mode and explainable recommendations.

## [1.5.0] - 2026-09-30

### Added
- **STD-023: Coding Agent Outcome Contract & Persistent Coding Task Memory (AI-Hub-013-R1-CODING-OUTCOME-CONTRACT)**:
  - Strictly separated Layer 1 Model Invocation Feedback (`POST /api/model/feedback`) from Layer 2 Coding Agent Outcome (`POST /api/coding/outcome`).
  - Defined canonical two-stage outcome lifecycle (`ATTEMPT_COMPLETED`, `INTEGRATION_DECISION`) and the core invariant: one `coding_attempt_id` equals exactly one Coding Memory sample.
  - Defined Frozen Coding Candidate Plan contract (`POST /api/coding/candidate-plan`, `GET /api/coding/candidate-plan/{decision_id}`) and First Bake-Off fairness mode (`CODING_OUTCOME_RANKING_MODE=SHADOW_ONLY`).
  - Enforced single-primary-model attribution (`SINGLE_PRIMARY_MODEL`) per independent coding attempt, authentic provenance (prohibiting fake strings such as `unknown`/`未验证`/`N/A`/`not_verified`), and zero raw source/patch/diff storage (`additionalProperties: false` in `schemas/coding-agent-outcome.schema.json`).
  - Codified non-penalizing integration semantics (`task_outcome=COMPLETED` with `integration_selected=false` is valid and never penalizes completion capability or L1 health).
  - Guaranteed strict isolation between Coding Outcome failures (`FAILED`/`PARTIAL`/`BLOCKED`), L1 technical health/circuit breakers, and non-coding L2 domain quality memories (`ai-kb`, `vtip-ai-sidecar`).
  - Published durable handoff `handoff/SIDECAR-CODING-BAKEOFF-INTEGRATION-HANDOFF.md` for `SIDECAR-DEV-022`.

## [1.4.0] - 2026-09-30

### Added
- **STD-022: Model Runtime Memory & Decay Governance (AI-Hub-012-R2-LONG-TERM-MODEL-MEMORY)**:
  - Defined separation of **Raw Historical Facts (All-Time Memory)** and **Recent Effective Routing Memory**.
  - Specified `observed_at` canonical exponential time decay ($w = 0.5^{\text{age}/\text{half\_life}}$) with configurable defaults (`technical_half_life_days = 7`, `business_quality_half_life_days = 30`) and out-of-order arrival safety.
  - Defined strict 5-tuple L2 business quality isolation (`consumer`, `task`, `metric_namespace`, `logical_model_id`, `channel`) and namespace-internal aggregation (`namespace_specific_weighted` vs `neutral_mean_normalized`).
  - Defined `effective_sample_weight` and effective governance confidence (`历史样本数`, `当前有效样本权重`, `当前治理置信度`).
  - Defined `model_fingerprint`, `fingerprint_status` (`VERIFIED`/`已确认`, `PARTIAL`/`部分可识别`, `UNKNOWN`/`未知`), and `memory_epoch` with false-epoch prevention and cold-start neutral priors.
  - Defined idempotent historical L2 memory rebuild from persisted L3 `model_invocations` without downstream consumer replay or L1 counter mutation.

## [1.3.0] - 2026-09-29

### Added
- **STD-010: Model Feedback Contract v1.3.0 (AI-Hub-012-R1-FEEDBACK-CONTRACT-FREEZE)**:
  - Codified multi-stage feedback lifecycle: `execution`, `business_evaluation`, and `human_review` stages.
  - Formally established domain judgment ownership: consumers own business evaluation, Hub owns technical health memory and multi-tenant persistence.
  - Added canonical `review_decision` enum (`approved`, `approved_with_note`, `rejected`, `revise`, `discard`, `execution_failed`, `not_reviewed`) and structured `review_reason_code`.
  - Added `evaluation_method` enum (`deterministic`, `llm_judge`, `human`, `combined`, `unknown`).
  - Added `metric_namespace` specification to isolate cross-consumer metric comparability.
  - Decoupled `evaluation_confidence` (consumer single-event confidence) from Hub-computed `sample_confidence_level`.
  - Aligned Hub and STD-009 sample confidence thresholds: 0=NONE, 1-9=LOW, 10-49=MEDIUM, 50+=HIGH.
  - Added `source_unit_id`, `source_unit_hash` (content only), and `execution_spec_hash` (params only).
  - Clarified model identities: `logical_model_id`, `selected_model_id`, `upstream_model_id`, `resource_id`.
  - Fixed multi-stage idempotency collisions with stage-aware deduplication identity.
  - Added `observed_at` (ISO-8601 UTC) for asynchronous evaluation and out-of-order tolerance.
  - Enforced zero raw business content guardrail via `additionalProperties: false` in `schemas/model-feedback.schema.json`.
  - Guaranteed business rejections never mutate technical failure counters or trigger circuit breakers.

## [1.2.0] - 2026-09-28

### Added
- **STD-021: Coding Agent Gateway Contract (AI-Hub-010-CODING-GATEWAY)**:
  - Formally established AI-Hub execution plane capabilities for professional coding agents.
  - Defined 4 canonical virtual models: `hub-code-auto`, `hub-code-fast`, `hub-code-deep`, and `hub-code-local`.
  - Standardized dual-protocol support: Anthropic Messages API (`/v1/messages`) for Claude Code, and OpenAI Chat Completions API (`/v1/chat/completions`) for OpenCode, Cline, Continue, Aider, and generic agents.
  - Codified failover semantics: transparent candidate-plan failover strictly before first streamed token; strictly prohibited cross-model output concatenation after stream start.
  - Established soft session stickiness based on `session_id` and diagnostic header metadata (`X-Hub-Decision-Id`, `X-Hub-Selected-Model`, `X-Hub-Channel`, `X-Hub-Attempts`).
  - Standardized coding-specific feedback metrics (`ttft_ms`, `tool_call_success`, `retry_count`, `fallback_count`, and reserved quality fields in `schemas/model-feedback.schema.json`).
  - Added `schemas/coding-gateway.schema.json` with full automated validation in `tools/validate-schemas.py`.

## [1.1.3] - 2026-09-25

### Added
- **Engineering Manifest Docker Consumer Endpoint & SOT Convergence (AI-HUB-V1-008)**:
  - Extended `schemas/engineering-manifest.schema.json` and `governance/engineering-manifest-schema.json` with `endpoints.docker_consumer`.
  - Added support for `schema_version` `"1.1"`, `"1.1.0"`, and `"1.1.3"` while maintaining 100% backward compatibility with `"1.0"` / `"1.0.0"`.
  - Defined explicit semantics: `docker_internal` for in-network container communication vs `docker_consumer` for bridge container access via host gateway relay.
  - Aligned STD-001 (v1.1.3), STD-003 (v1.1.3), and STD-012 (v1.1.3) with single source of truth resolution.

## [1.1.2] - 2026-09-24

### Added
- **Docker / Host Dual-Profile Runtime Topology (AI-ENGINEERING-PLATFORM-V1-005)**:
  - Formally established `HUB_HOST_ENDPOINT` (`http://127.0.0.1:80`, loopback only) and `HUB_DOCKER_ENDPOINT` (`http://host.docker.internal:18000`, dedicated bridge ingress).
  - Extended `schemas/endpoint.schema.json` with `runtime_profiles` (host, docker) and `canonical_paths` (`health`, `model_select`, `model_feedback`).
  - Allocated Port `18000` in `STD-006` Port Governance for Hub Docker Consumer Ingress.
  - Published official durable handoff `handoff/SIDECAR-FULL-ADOPTION-HANDOFF.md`.

### Changed
- **STD-003 v1.1.2**: Decoupled Canonical Paths from Base URL; defined Runtime Profiles to drive dynamic endpoint resolution.
- **STD-011 v1.1.2**: Explicitly prohibited Docker consumers from assuming `127.0.0.1` represents host; required consumers to prioritize `docker_endpoint`.
- **STD-012 v1.1.2**: Codified 3-tier boundary isolation rules, requiring Hub to bind dedicated listeners strictly on Docker bridge gateways while keeping loopback intact and physical LAN completely unexposed.

## [1.1.1] - 2026-09-23

### Changed
- **Contract Freeze (AI-ENGINEERING-PLATFORM-V1-004)**:
  - Unified Canonical Model Router API (POST /api/model/select) and Model Feedback API (POST /api/model/feedback).
  - Formally deprecated /api/router/* as compatibility aliases (/api/router/candidate-plan, /api/router/feedback, /api/router/match).
  - Fixed request enum typo across documentation and templates (quality strictly [high, medium, low]; latency strictly [low, normal, batch]; eliminated quality=normal).
  - Eliminated dual error taxonomies: unified on the 7 canonical classes in model-feedback.schema.json (QUOTA_EXHAUSTED, RATE_LIMITED, AUTH_FAILED, MODEL_UNAVAILABLE, NETWORK_ERROR, TIMEOUT, PROVIDER_ERROR).
  - Standardized Candidate Plan response schema conformance (rank, logical_model_id, endpoint_reference, governance_state, metrics, reason).
  - Aligned Durable Handoff baselines in handoff/ to Standards v1.1.1 and Hub v0.5.8.
  - Added contract regression assertions to tools/validate-schemas.py.

## [1.1.0] - 2026-09-23

### Added
- **STD-019: Artifact & Workspace Hygiene Standard** – Six-category artifact taxonomy (SOURCE, GENERATED, ACCEPTANCE, DEMO, TEMPORARY, ARCHIVE), `.artifacts/` directory layout, and workspace cleanup policy.
- **STD-020: Cross-Session Handoff Standard** – DURABLE vs TEMPORARY handoff types, mandatory fields, lifecycle constraints, and cross-repo isolation rules.
- **ARTIFACT-GOVERNANCE-V1.1.md** – Architecture overview of artifact governance model, KPI semantic correctness fix rationale, and Playwright mode governance.
- **tools/cleanup_audit.py** – Automated workspace audit tool implementing STD-019 classification.

### Changed
- **STD-014 v1.1**: Extended to four-level testing matrix (L1-SMOKE, L2-CORE, L3-DEEP, L4-DIAGNOSTIC) with explicit per-level constraints on scope, duration, tooling and output location.
- **STD-015 v1.1**: Added three explicit Playwright execution modes (AUTOMATED_TEST, ACCEPTANCE, DEMO) with mandatory headless/headed rules and KPI card verification requirement.
- **`.gitignore`**: Added `.artifacts/`, `playwright-report/`, `test-results/`.

## [1.0.0] - 2026-09-23

### Added
- **Formal Standards Framework (STD-001 to STD-018)**:
  - STD-001: Engineering Manifest Standard
  - STD-002: Resource Ownership Standard
  - STD-003: Endpoint Registry Standard
  - STD-004: Canonical Action Standard
  - STD-005: Health Status & Lifecycle Model Standard
  - STD-006: Port Governance Standard (18000-19999 Convention & Windows Dynamic Port Range)
  - STD-007: Credential Reference & Zero Secret Standard
  - STD-008: Model Registry Standard
  - STD-009: Model Routing Contract
  - STD-010: Model Feedback Contract
  - STD-011: Application Consumer Contract
  - STD-012: Windows / WSL / Docker Runtime Boundary
  - STD-013: Logging & Observability Standard
  - STD-014: Testing Standard
  - STD-015: Playwright Acceptance Standard
  - STD-016: Acceptance Evidence ZIP Standard
  - STD-017: Git Release & Versioning Standard
  - STD-018: UI Diagnostics & Enum Presentation Standard
- **Machine-readable JSON Schemas (`schemas/`)**:
  - `engineering-manifest.schema.json`
  - `resource.schema.json`
  - `endpoint.schema.json`
  - `canonical-action.schema.json`
  - `model-registry.schema.json`
  - `model-routing-request.schema.json`
  - `model-routing-response.schema.json`
  - `model-feedback.schema.json`
  - `audit-event.schema.json`
- **Resource Lifecycle Classification Model**:
  - `ALWAYS_ON` (常驻服务), `ON_DEMAND` (按需服务), `MANUAL` (手动管理), `EXTERNAL` (外部管理)
  - Explicit `desired_state` and `actual_state` contracts.
- **Cross-Session Integration Handoffs (`handoff/`)**:
  - `AI-KB-Model-Governance-Integration-Handoff.md`
  - `Sidecar-Model-Governance-Integration-Handoff.md`
  - `VTIP-Model-Governance-Architecture-Handoff.md`
- **Audit & Architecture Baseline**:
  - `docs/audit/STANDARDS-V1-AUDIT.md`
  - `docs/architecture/STANDARDS-V1-ARCHITECTURE.md`
  - `deprecated/CLOUD-CPA-TUNNEL-DEPRECATED.md`
- **Automated Schema Validator**:
  - `tools/validate-schemas.py`

### Changed
- **Local CPA Ground Truth Alignment**:
  - Aligned Host Endpoint to `http://127.0.0.1:18117` and Docker Internal Endpoint to `http://cpa-local:8317`.
  - Affirmed Owner as `ai-kb-infra` (`D:\AI-KB\Repo\ai-kb-infra`).
  - Standardized canonical lifecycle commands to `scripts/cpa/local-cpa.cmd` (`start`, `stop`, `restart`, `status`, `test`).
- **Cloud CPA Alignment**:
  - Standardized script path to `scripts/cpa/cloud-cpa-tunnel.cmd`.
  - Host Endpoint `http://127.0.0.1:18317` with fallback range `18318-18320`.
  - Classified as `ON_DEMAND` with `desired_state: STOPPED`.
- **Cold Start Semantics**:
  - Established contract: 0 invocations must return `success_rate: null` and `latency_p50/p95: null`. UI must display "暂无数据" and never "100%" or "0ms".
  - Introduced `sample_count` and `metric_confidence` (`NONE`, `LOW`, `MEDIUM`, `HIGH`).

### Deprecated
- `scripts/tunnel/cloud-cpa-tunnel.cmd` permanently marked as DEPRECATED in favor of `scripts/cpa/cloud-cpa-tunnel.cmd`.
- Direct Host port `8317` marked as DEPRECATED in favor of governed Host port `18117`.
