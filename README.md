# AI工程标准库（AI Engineering Standards）

跨工程共享的架构、研发、测试、文档、发布、证据与运行契约权威源。首个消费端试点为 `AI-Engineering-Hub`；其他工程是否接入由各工程后续决策。

本项目是跨工程架构、研发、测试、文档、发布、证据和运行契约的**唯一规范权威源（Single Source of Truth）**。`VERSION` 表示当前工作分支声明的基线版本；正式发布版本以官方 `main` 上的 Annotated Tag、Tag Object SHA、Peeled Commit 和 main CI 为准。当前官方正式发布版本为 `v3.0.0`（Tag Object SHA: `8256bb384e62894219db0992a2cb57e16d4fa8cd`，Peeled Commit: `8b223019c254e0edeb94576b94af46c1e48b0316`，main CI Run `42996232217` 双平台 222 项测试全绿）。

**版本锁定区分说明**：
- **Standards 自身的正式 Lock**：位于本仓库根目录 [`standards.lock.json`](./standards.lock.json)，已正式同步锁定至最新已发布的 `v3.0.0`。
- **消费端各自的 Lock**：各下游消费工程（如首个试点 `AI-Engineering-Hub`）各自持有独立的 `standards.lock.json`。Standards 的正式发布不代表消费端已自动升级；消费端升级必须遵循 `STD-034` 的 11 步受控升级状态机，经独立 CI 验证和消费端 Owner 批准后方可变更。

- **文档总入口**：[`docs/DOCUMENT-INDEX.md`](./docs/DOCUMENT-INDEX.md)
- **目录导航**：[`docs/目录导航.md`](./docs/目录导航.md)
- **消费端接入与工具使用协议**：[`docs/Standards消费端接入与工具使用协议.md`](./docs/Standards消费端接入与工具使用协议.md)
- **当前权威基线**：[`docs/当前权威基线.md`](./docs/当前权威基线.md)
- **跨会话交接入口**：[`docs/CROSS-SESSION-HANDOFF.md`](./docs/CROSS-SESSION-HANDOFF.md)
- **版本锁定文件**：[`standards.lock.json`](./standards.lock.json)

---

## 1. 标准规范导航（Formal Standards）

| 规范代号 | 规范名称 | 核心职责 |
| :--- | :--- | :--- |
| [`STD-001`](./standards/00-governance/STD-001-engineering-manifest.md) | **工程清单规范（Engineering Manifest Standard）** | 项目单一清单持有与 Hub 汇聚契约 |
| [`STD-002`](./standards/00-governance/STD-002-resource-ownership.md) | **资源归属规范（Resource Ownership Standard）** | 资源单一 Owner 原则，禁止跨库复制实现 |
| [`STD-003`](./standards/03-endpoint-registry/STD-003-endpoint-registry.md) | **端点注册规范（Endpoint Registry Standard）** | 宿主端点、容器端点、远端端点与控制台隔离 |
| [`STD-004`](./standards/04-canonical-actions/STD-004-canonical-actions.md) | **标准动作规范（Canonical Action Standard）** | 白名单动作集 (`start`, `stop`, `restart`, `status`, `test`) |
| [`STD-005`](./standards/05-health-status/STD-005-health-status-lifecycle.md) | **健康状态与生命周期规范（Health Status & Lifecycle）** | 四类生命周期 (`ALWAYS_ON`, `ON_DEMAND` 等) 与递进健康感知 |
| [`STD-006`](./standards/06-port-governance/STD-006-port-governance.md) | **端口治理规范（Port Governance Standard）** | Windows 动态端口排查与 18000-19999 机器级分配约定 |
| [`STD-007`](./standards/07-credential-security/STD-007-credential-zero-secret.md) | **凭据引用与零密钥规范（Credential Reference & Zero Secret）** | 绝对零密钥入库与三态凭据引用契约 |
| [`STD-008`](./standards/08-model-governance/STD-008-model-registry.md) | **模型注册规范（Model Registry Standard）** | 206+ 模型统一元数据与类型分类 |
| [`STD-009`](./standards/08-model-governance/STD-009-model-routing-contract.md) | **模型路由契约（Model Routing Contract）** | Candidate Plan 决策契约、冷启动空值语义与多样性 |
| [`STD-010`](./standards/08-model-governance/STD-010-model-feedback-contract.md) | **模型反馈契约（Model Feedback Contract）** | 业务执行结果反馈与通用指标契约 |
| [`STD-011`](./standards/08-model-governance/STD-011-application-consumer-contract.md) | **应用消费契约（Application Consumer Contract）** | 候选方案消费、Hub 非单点故障与双重兜底 |
| [`STD-012`](./standards/10-runtime-boundary/STD-012-windows-wsl-docker-boundary.md) | **运行时边界规范（Runtime Boundary Standard）** | Windows / WSL / Docker 运行时互联边界 |
| [`STD-013`](./standards/09-observability/STD-013-observability-logging.md) | **日志与可观测性规范（Logging & Observability）** | 统一审计中心事件格式与 UTC 时间存储 |
| [`STD-014`](./standards/11-testing/STD-014-testing-standard.md) | **测试规范（Testing Standard）** | 跨项目分层测试、AI自主测试设计闭环与持续用例基线治理 |
| [`STD-015`](./standards/12-acceptance/STD-015-playwright-acceptance.md) | **Playwright 浏览器验收规范（Playwright Acceptance Standard）**| 自动化 UI 验收、业务闭环强断言、多主题与视频截图证据 |
| [`STD-016`](./standards/12-acceptance/STD-016-acceptance-evidence-zip.md) | **验收证据 ZIP 规范（Acceptance Evidence ZIP）** | 独立工程阶段交付物压缩包标准 |
| [`STD-017`](./standards/13-git-release/STD-017-git-release-versioning.md) | **Git 发布与版本治理规范（Git Release & Versioning）** | 独立 Git 仓库提交、干净工作区与 SemVer |
| [`STD-018`](./standards/14-ui-diagnostics/STD-018-ui-diagnostics-enum-presentation.md) | **UI 诊断与展示规范（UI Diagnostics & Presentation）** | 内部大写英文枚举向纯简体中文界面的映射规范 |
| [`STD-019`](./standards/15-artifact-hygiene/STD-019-Artifact-Workspace-Hygiene.md) | **制品与工作区卫生规范（Artifact & Workspace Hygiene）** | 六分类交付物管理、.artifacts 目录与清理规范 |
| [`STD-020`](./standards/16-handoff/STD-020-Cross-Session-Handoff.md) | **跨会话交接规范（Cross-Session Handoff Standard）** | 跨会话自动采集交接标准、双层持久化与启动实时重验契约 |
| [`STD-021`](./standards/08-model-governance/STD-021-coding-agent-gateway-contract.md) | **编程智能体网关契约（Coding Agent Gateway Contract）** | 虚拟模型、双协议接入、透明故障转移与编程会话粘性 |
| [`STD-022`](./standards/08-model-governance/STD-022-model-runtime-memory-and-decay-governance.md) | **模型运行记忆与衰减治理规范（Model Runtime Memory & Decay Governance）** | 全量历史与近期衰减路由记忆解耦、模型指纹与 Epoch 治理 |
| [`STD-023`](./standards/08-model-governance/STD-023-coding-agent-outcome-contract.md) | **编程智能体结果契约（Coding Agent Outcome Contract）** | 编程智能体任务级工程结果契约、持久化编码任务记忆与 Bake-Off 公平治理 |
| [`STD-024`](./standards/08-model-governance/STD-024-model-ops-autopilot-governance-contract.md) | **模型运维自动驾驶治理契约（Model Ops Autopilot Governance）** | 模型自发现、能力分级验证、生命周期状态机与影子治理契约 |
| [`STD-025`](./standards/08-model-governance/STD-025-owner-action-execution-contract.md) | **所有者动作执行契约（Owner Action Execution Contract）** | 控制平面决策、Resource Owner 校验执行、独占租约、幂等恢复、零敏感凭据、事实结果与 Hub 独立验证 |
| [`STD-026`](./standards/08-model-governance/STD-026-model-scout-and-challenger-contract.md) | **模型侦察与挑战者契约（Model Scout and Challenger Contract）** | 候选模型侦察源注册、可用性分级、公正挑战战役、冻结公平性规范、微基准测试、记忆衰减与晋升建议 |
| [`STD-031`](./standards/12-acceptance/STD-031-runtime-acceptance-contract.md) | **运行时验收契约（Runtime Acceptance Contract）** | 跨项目运行时验收契约、技术中立探针与统一验收报文 |
| [`STD-032`](./standards/13-git-release/STD-032-release-engineering-contract.md) | **AI 平台发布工程契约（AI Platform Release Engineering Contract）** | 12阶段发布生命周期、五态Commit一致性、强制门禁、Artifact与Git Tag及回滚规范 |
| [`STD-033`](./standards/12-acceptance/STD-033-platform-verification-governance.md) | **平台验证治理规范（Platform Verification Governance）** | 跨项目平台验证中心、五维运行时验收矩阵、统一工程生命周期契约 (14阶段)、证据Schema与验证大盘治理 |
| [`STD-034`](./standards/00-governance/STD-034-coding-agent-execution-governance.md) | **编程智能体执行治理规范（Coding Agent Execution Governance）** | 跨工程编程智能体规则契约、`standards.lock.json` 四元组锁定、11步受控升级状态机与双层审批防伪造契约 |
| [`STD-035`](./standards/17-documentation/STD-035-documentation-lifecycle.md) | **工程文档生命周期与权威基线规范（Documentation Lifecycle & Baseline）** | 12类正式工程文档契约、`ENGINEERING_BASELINE` 自动综合视图、生命周期与审批状态解耦及 17 项集合校验 |

---

## 2. 机器可读契约（JSON Schemas）

规范库提供 31 个标准 JSON Schema，均支持通过 `python tools/validate-schemas.py` 自动化检验：
- `schemas/audit-event.schema.json`
- `schemas/canonical-action.schema.json`
- `schemas/coding-agent-outcome.schema.json`
- `schemas/coding-gateway.schema.json`
- `schemas/cross-session-handoff.schema.json`
- `schemas/consumer-validation-evidence.schema.json`
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

## 3. 官方共享工具（Tools）

- `tools/standards_sync/cli.py`：Standards 官方同步与版本治理 CLI（支持 `discover`、`verify-lock`、`compare`、`impact`、`prepare-upgrade`、`validate-upgrade`、`promote`、`rollback`）。
- `tools/validate-documentation-collection.py`：跨平台 17 项正式文档集合与链接锚点校验器（`STD-035`）。
- `tools/generate_engineering_baseline.py`：`docs/当前权威基线.md` 确定性生成与 `--verify-only` 校验工具。
- `tools/generate_handoff.py`：`docs/CROSS-SESSION-HANDOFF.md` 与任务级快照自动采集生成工具（`STD-020`）。
- `tools/validate_approval_contract.py`：ChatGPT 独立审核与 Owner 批准证据校验工具（`D2` / `STD-034 §16`）。
- `tools/standards_sync/core.py`：消费端 CI Run/Job 证据核验，确保升级测试绑定精确消费 Commit。

详细接入、安装、调用权限、Windows/Linux 示例与升级流程见 [`消费端接入与工具使用协议`](./docs/Standards消费端接入与工具使用协议.md)。

---

## 4. 其他工程专题交接资料（非本轮试点）

> 以下为此前各工程的专题交接材料，仅供追溯，不构成本轮消费端试点或升级授权。本轮唯一消费端试点为 AI-Engineering-Hub；AI-KB、VTIP、SideCar 暂不纳入。

- [`当前会话交接入口 (docs/CROSS-SESSION-HANDOFF.md)`](./docs/CROSS-SESSION-HANDOFF.md)
- [`AI-KB 模型治理接入交接指南`](./handoff/AI-KB-Model-Governance-Integration-Handoff.md)
- [`Sidecar 模型治理接入交接指南`](./handoff/Sidecar-Model-Governance-Integration-Handoff.md)
- [`Sidecar 首次真实编码 Bake-Off 平台接入交接指南`](./handoff/SIDECAR-CODING-BAKEOFF-INTEGRATION-HANDOFF.md)
- [`VTIP 模型治理架构交接指南`](./handoff/VTIP-Model-Governance-Architecture-Handoff.md)

---

## 5. 废弃资料归档（Deprecated）

- [`Cloud CPA 隧道旧管理脚本废弃说明`](./deprecated/CLOUD-CPA-TUNNEL-DEPRECATED.md)（替代脚本：`scripts/cpa/cloud-cpa-tunnel.cmd`）
