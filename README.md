# AI Engineering Standards (V1.8.0)

Canonical engineering standards shared across local AI / Vibe Coding projects.

本项目是开发机跨工程共享的架构标准规范库（Source of Truth），定义网络通信、推理资源共享、智能体接入、上下文管理与工程协作标准。

```text
STANDARDS_VERSION=1.8.0
STATUS=RELEASED
BASELINE=AI-ENGINEERING-PLATFORM-V1-001
LAST_UPDATED=2026-10-07
```

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
| [`STD-014`](./standards/11-testing/STD-014-testing-standard.md) | **Testing Standard** | 跨项目分层测试与非破坏性原则 |
| [`STD-015`](./standards/12-acceptance/STD-015-playwright-acceptance.md) | **Playwright Acceptance Standard**| 自动化 UI 验收、多主题与视频截图证据 |
| [`STD-016`](./standards/12-acceptance/STD-016-acceptance-evidence-zip.md) | **Acceptance Evidence ZIP** | 独立工程阶段交付物压缩包标准 |
| [`STD-017`](./standards/13-git-release/STD-017-git-release-versioning.md) | **Git Release & Versioning** | 独立 Git 仓库提交、干净工作区与 SemVer |
| [`STD-018`](./standards/14-ui-diagnostics/STD-018-ui-diagnostics-enum-presentation.md) | **UI Diagnostics & Presentation** | 内部大写英文枚举向纯简体中文界面的映射规范 |
| [`STD-019`](./standards/15-artifact-hygiene/STD-019-Artifact-Workspace-Hygiene.md) | **Artifact & Workspace Hygiene** | 六分类交付物管理、.artifacts 目录与清理规范 |
| [`STD-020`](./standards/16-handoff/STD-020-Cross-Session-Handoff.md) | **Cross-Session Handoff Standard** | 会话持久化交接标准与跨工程隔离规范 |
| [`STD-021`](./standards/08-model-governance/STD-021-coding-agent-gateway-contract.md) | **Coding Agent Gateway Contract** | 虚拟模型、双协议接入、透明故障转移与编程会话粘性 |
| [`STD-022`](./standards/08-model-governance/STD-022-model-runtime-memory-and-decay-governance.md) | **Model Runtime Memory & Decay Governance** | 全量历史与近期衰减路由记忆解耦、模型指纹与 Epoch 治理 |
| [`STD-023`](./standards/08-model-governance/STD-023-coding-agent-outcome-contract.md) | **Coding Agent Outcome Contract** | 编程智能体任务级工程结果契约、持久化编码任务记忆与 Bake-Off 公平治理 |
| [`STD-024`](./standards/08-model-governance/STD-024-model-ops-autopilot-governance-contract.md) | **Model Ops Autopilot Governance** | 模型自发现、能力分级验证、生命周期状态机与影子治理契约 |
| [`STD-025`](./standards/08-model-governance/STD-025-owner-action-execution-contract.md) | **Owner Action Execution Contract** | 控制平面决策、Resource Owner 校验执行、独占租约、幂等恢复、零敏感凭据、事实结果与 Hub 独立验证 |
| [`STD-026`](./standards/08-model-governance/STD-026-model-scout-and-challenger-contract.md) | **Model Scout and Challenger Contract** | 候选模型侦察源注册、可用性分级、公正挑战战役、冻结公平性规范、微基准测试、记忆衰减与晋升建议 |

---

## 2. 机器可读 JSON Schemas (`schemas/`)

规范库提供 15 个标准 JSON Schema，均支持通过 `python tools/validate-schemas.py` 自动化检验：
- `schemas/engineering-manifest.schema.json`
- `schemas/resource.schema.json`
- `schemas/endpoint.schema.json`
- `schemas/canonical-action.schema.json`
- `schemas/model-registry.schema.json`
- `schemas/model-routing-request.schema.json`
- `schemas/model-routing-response.schema.json`
- `schemas/model-feedback.schema.json`
- `schemas/audit-event.schema.json`
- `schemas/coding-gateway.schema.json`
- `schemas/coding-agent-outcome.schema.json`
- `schemas/model-ops-autopilot.schema.json`
- `schemas/owner-action-execution.schema.json`
- `schemas/model-scout-challenger.schema.json`

---

## 3. 跨工程长会话交接指南 (`handoff/`)

- [`AI-KB 模型治理接入交接指南`](./handoff/AI-KB-Model-Governance-Integration-Handoff.md)
- [`Sidecar 模型治理接入交接指南`](./handoff/Sidecar-Model-Governance-Integration-Handoff.md)
- [`Sidecar 首次真实编码 Bake-Off 平台接入交接指南`](./handoff/SIDECAR-CODING-BAKEOFF-INTEGRATION-HANDOFF.md)
- [`VTIP 模型治理架构交接指南`](./handoff/VTIP-Model-Governance-Architecture-Handoff.md)

---

## 4. 废弃内容归档 (`deprecated/`)

- [`Cloud CPA 隧道旧管理脚本废弃说明`](./deprecated/CLOUD-CPA-TUNNEL-DEPRECATED.md)（替代脚本：`scripts/cpa/cloud-cpa-tunnel.cmd`）
