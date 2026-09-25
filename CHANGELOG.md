# AI Engineering Standards - Changelog

All notable changes to the AI Engineering Standards baseline are documented in this file.

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
