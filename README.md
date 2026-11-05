# AI Engineering Standards

Canonical engineering standards shared across AI / Vibe Coding projects (`AI-Engineering-Hub`, `AI-KB`, `vtip-platform-catalog`, `vtip-ai-sidecar`).

本项目是跨工程架构、研发、测试、文档、发布、证据和运行契约的**唯一规范权威源 (Single Source of Truth)**。当前仓库版本、正式发布 Tag 锁定与实时工程事实请以 [`VERSION`](./VERSION)、[`standards.lock.json`](./standards.lock.json) 及 [`docs/当前权威基线.md`](./docs/当前权威基线.md) 为准（遵循 `D3=APPROVED` / `STD-034`，不在说明文档中手工硬编码浮动版本）。

- **文档总入口**：[`docs/DOCUMENT-INDEX.md`](./docs/DOCUMENT-INDEX.md)
- **当前权威基线**：[`docs/当前权威基线.md`](./docs/当前权威基线.md)
- **跨会话交接入口**：[`docs/CROSS-SESSION-HANDOFF.md`](./docs/CROSS-SESSION-HANDOFF.md)
- **版本锁定文件**：[`standards.lock.json`](./standards.lock.json)

---

## 1. 规范矩阵导航 (Formal Standards)

| 规范代号 | 规范名称 | 核心职责 |
| :--- | :--- | :--- |
| [`STD-001`](./standards/00-governance/STD-001-engineering-manifest.md) | **Engineering Manifest Standard** | 项目单一清单持有与 Hub 汇聚契约 |
| [`STD-002`](./standards/00-governance/STD-002-resource-ownership.md) | **Resource Ownership Standard** | 资源单一 Owner 原则，禁止跨库复制实现 |
| [`STD-003`](./standards/03-endpoint-registry/STD-003-endpoint-registry.md) | **Endpoint Registry Standard** | 宿主端点、容器端点、远端端点与控制台隔离 |
| [`STD-004`](./standards/04-canonical-actions/STD-004-canonical-actions.md) | **Canonical Action Standard** | 白名单动作集 (`start`, `stop`, `restart`, `status`, `test`) |
| [`STD-005`](./standards/05-health-status/STD-005-health-status-lifecycle.md) | **Health Status & Lifecycle** | 四类生命周期 (`ALWAYS_ON`, `ON_DEMAND` 等) 与递进健康感知 |
| [`STD-006`](./standards/06-port-governance/STD-006-port-governance.md) | **Port Governance Standard** | Windows 动态端口排查与 18000-19999 机器级分配约定 |
| [`STD-007`](./standards/07-credential-security/STD-007-credential-zero-secret.md) | **Credential Reference & Zero Secret** | 绝对零密钥入库与三态凭据引用契约 |
| [`STD-008`](./standards/08-model-governance/STD-008-model-registry.md) | **Model Registry Standard** | 206+ 模型统一元数据与类型分类 |
| [`STD-009`](./standards/08-model-governance/STD-009-model-routing-contract.md) | **Model Routing Contract** | Candidate Plan 决策契约、冷启动空值语义与多样性 |
| [`STD-010`](./standards/08-model-governance/STD-010-model-feedback-contract.md) | **Model Feedback Contract** | 业务执行结果反馈与通用指标契约 |
| [`STD-011`](./standards/08-model-governance/STD-011-application-consumer-contract.md) | **Application Consumer Contract** | 候选方案消费、Hub 非单点故障与双重兜底 |
| [`STD-012`](./standards/10-runtime-boundary/STD-012-windows-wsl-docker-boundary.md) | **Runtime Boundary Standard** | Windows / WSL / Docker 运行时互联边界 |
| [`STD-013`](./standards/09-observability/STD-013-observability-logging.md) | **Logging & Observability** | 统一审计中心事件格式与 UTC 时间存储 |
| [`STD-014`](./standards/11-testing/STD-014-testing-standard.md) | **Testing Standard** | 跨项目分层测试、AI自主测试设计闭环与持续用例基线治理 |
| [`STD-015`](./standards/12-acceptance/STD-015-playwright-acceptance.md) | **Playwright Acceptance Standard**| 自动化 UI 验收、业务闭环强断言、多主题与视频截图证据 |
| [`STD-016`](./standards/12-acceptance/STD-016-acceptance-evidence-zip.md) | **Acceptance Evidence ZIP** | 独立工程阶段交付物压缩包标准 |
| [`STD-017`](./standards/13-git-release/STD-017-git-release-versioning.md) | **Git Release & Versioning** | 独立 Git 仓库提交、干净工作区与 SemVer |
| [`STD-018`](./standards/14-ui-diagnostics/STD-018-ui-diagnostics-enum-presentation.md) | **UI Diagnostics & Presentation** | 内部大写英文枚举向纯简体中文界面的映射规范 |
| [`STD-019`](./standards/15-artifact-hygiene/STD-019-Artifact-Workspace-Hygiene.md) | **Artifact & Workspace Hygiene** | 六分类交付物管理、.artifacts 目录与清理规范 |
| [`STD-020`](./standards/16-handoff/STD-020-Cross-Session-Handoff.md) | **Cross-Session Handoff Standard** | 跨会话自动采集交接标准、双层持久化与启动实时重验契约 |
| [`STD-021`](./standards/08-model-governance/STD-021-coding-agent-gateway-contract.md) | **Coding Agent Gateway Contract** | 虚拟模型、双协议接入、透明故障转移与编程会话粘性 |
| [`STD-022`](./standards/08-model-governance/STD-022-model-runtime-memory-and-decay-governance.md) | **Model Runtime Memory & Decay Governance** | 全量历史与近期衰减路由记忆解耦、模型指纹与 Epoch 治理 |
| [`STD-023`](./standards/08-model-governance/STD-023-coding-agent-outcome-contract.md) | **Coding Agent Outcome Contract** | 编程智能体任务级工程结果契约、持久化编码任务记忆与 Bake-Off 公平治理 |
| [`STD-024`](./standards/08-model-governance/STD-024-model-ops-autopilot-governance-contract.md) | **Model Ops Autopilot Governance** | 模型自发现、能力分级验证、生命周期状态机与影子治理契约 |
| [`STD-025`](./standards/08-model-governance/STD-025-owner-action-execution-contract.md) | **Owner Action Execution Contract** | 控制平面决策、Resource Owner 校验执行、独占租约、幂等恢复、零敏感凭据、事实结果与 Hub 独立验证 |
| [`STD-026`](./standards/08-model-governance/STD-026-model-scout-and-challenger-contract.md) | **Model Scout and Challenger Contract** | 候选模型侦察源注册、可用性分级、公正挑战战役、冻结公平性规范、微基准测试、记忆衰减与晋升建议 |
| [`STD-031`](./standards/12-acceptance/STD-031-runtime-acceptance-contract.md) | **Runtime Acceptance Contract** | 跨项目运行时验收契约、技术中立探针与统一验收报文 |
| [`STD-032`](./standards/13-git-release/STD-032-release-engineering-contract.md) | **AI Platform Release Engineering Contract** | 12阶段发布生命周期、五态Commit一致性、强制门禁、Artifact与Git Tag及回滚规范 |
| [`STD-033`](./standards/12-acceptance/STD-033-platform-verification-governance.md) | **Platform Verification Governance** | 跨项目平台验证中心、五维运行时验收矩阵、统一工程生命周期契约 (14阶段)、证据Schema与验证大盘治理 |
| [`STD-034`](./standards/00-governance/STD-034-coding-agent-execution-governance.md) | **Coding Agent Execution Governance** | 跨工程编程智能体规则契约、`standards.lock.json` 四元组锁定、11步受控升级状态机与双层审批防伪造契约 |
| [`STD-035`](./standards/17-documentation/STD-035-documentation-lifecycle.md) | **Documentation Lifecycle & Baseline** | 12类正式工程文档契约、`ENGINEERING_BASELINE` 自动综合视图、生命周期与审批状态解耦及 17 项集合校验 |

---

## 2. 机器可读 JSON Schemas (`schemas/`)

规范库提供 30 个标准 JSON Schema，均支持通过 `python tools/validate-schemas.py` 自动化检验：
- `schemas/audit-event.schema.json`
- `schemas/canonical-action.schema.json`
- `schemas/coding-agent-outcome.schema.json`
- `schemas/coding-gateway.schema.json`
- `schemas/cross-session-handoff.schema.json`
- `schemas/documentation-approval.schema.json`
- `schemas/documentation-metadata.schema.json`
- `schemas/endpoint.schema.json`
- `schemas/engineering-baseline.schema.json`
- `schemas/engineering-manifest.schema.json`
- `schemas/model-feedback.schema.json`
- `schemas/model-ops-autopilot.schema.json`
- `schemas/model-registry.schema.json`
- `schemas/model-routing-request.schema.json`
- `schemas/model-routing-response.schema.json`
- `schemas/model-scout-challenger.schema.json`
- `schemas/model-supply-autopilot.schema.json`
- `schemas/owner-action-execution.schema.json`
- `schemas/platform-verification.schema.json`
- `schemas/release-approval-policy.schema.json`
- `schemas/release-approval.schema.json`
- `schemas/release-authorization-evidence.schema.json`
- `schemas/release-engineering.schema.json`
- `schemas/resource.schema.json`
- `schemas/runtime-acceptance.schema.json`
- `schemas/safe-autonomous-promotion.schema.json`
- `schemas/standards-lock.schema.json`
- `schemas/test-coverage-verification.schema.json`
- `schemas/two-stage-release-acceptance.schema.json`
- `schemas/unified-ai-capability-platform.schema.json`

---

## 3. 官方共享工具 (`tools/`)

- `tools/standards_sync/cli.py`：Standards 官方同步与版本治理 CLI（支持 `discover`、`verify-lock`、`compare`、`impact`、`prepare-upgrade`、`validate-upgrade`、`promote`、`rollback`）。
- `tools/validate-documentation-collection.py`：跨平台 17 项正式文档集合与链接锚点校验器（`STD-035`）。
- `tools/generate_engineering_baseline.py`：`docs/当前权威基线.md` 确定性生成与 `--verify-only` 校验工具。
- `tools/generate_handoff.py`：`docs/CROSS-SESSION-HANDOFF.md` 与任务级快照自动采集生成工具（`STD-020`）。
- `tools/validate_approval_contract.py`：ChatGPT 独立审核与 Owner 批准证据校验工具（`D2` / `STD-034 §16`）。

---

## 4. 跨工程长会话交接指南 (`handoff/`)

- [`当前会话交接入口 (docs/CROSS-SESSION-HANDOFF.md)`](./docs/CROSS-SESSION-HANDOFF.md)
- [`AI-KB 模型治理接入交接指南`](./handoff/AI-KB-Model-Governance-Integration-Handoff.md)
- [`Sidecar 模型治理接入交接指南`](./handoff/Sidecar-Model-Governance-Integration-Handoff.md)
- [`Sidecar 首次真实编码 Bake-Off 平台接入交接指南`](./handoff/SIDECAR-CODING-BAKEOFF-INTEGRATION-HANDOFF.md)
- [`VTIP 模型治理架构交接指南`](./handoff/VTIP-Model-Governance-Architecture-Handoff.md)

---

## 5. 废弃内容归档 (`deprecated/`)

- [`Cloud CPA 隧道旧管理脚本废弃说明`](./deprecated/CLOUD-CPA-TUNNEL-DEPRECATED.md)（替代脚本：`scripts/cpa/cloud-cpa-tunnel.cmd`）
