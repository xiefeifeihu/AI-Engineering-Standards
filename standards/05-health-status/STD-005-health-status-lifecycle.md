# STD-005: Health Status & Lifecycle Model Standard (健康感知与生命周期模型规范)

```text
STANDARD_ID=STD-005
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=AI-Hub 门户、资源监控、模型网关与所有接入受管实体
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
SCHEMA_REF=schemas/resource.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 四类正式资源生命周期策略 (Lifecycle Policy)

所有接入 AI-Hub 的受管服务与资源 **MUST** 声明明确的 `lifecycle_policy`：

1. **`ALWAYS_ON` (常驻服务)**：
   - 核心生产依赖，设计上需常态化保持运行。
   - `desired_state`: `RUNNING`。
   - 典型代表：`local-cpa`、`ollama`、`ai-kb-control`、`elasticsearch`、`mysql`。
   - 故障判定：当实际状态为 `OFFLINE` 或 `ERROR` 时，UI **MUST** 显式告警提示：“常驻资源未达到期望状态”。
2. **`ON_DEMAND` (按需服务)**：
   - 弹性或可选资源，仅在特定任务或人工需要时动态拉起。
   - `desired_state`: `STOPPED`。
   - 典型代表：`cpa-cloud` (云端海外隧道)。
   - 状态语义：平时处于 `STOPPED` 时为正常待命态，**MUST NOT** 视为系统故障，禁止引发全局红色告警。
3. **`MANUAL` (手动管理)**：
   - 依赖人工在特定工作流下拉起或调试的临时组件。
4. **`EXTERNAL` (外部管理)**：
   - 运行于外部服务器、云端或第三方机器的服务，本机仅作为客户端接入，不负责其生命周期。

---

## 2. 递进式三层健康检查感知模型

```text
[ 1. 资源存在 (PRESENT) ] -> 容器/文件/进程实体已检测到
            │
            ▼
[ 2. 服务可达 (AVAILABLE) ] -> TCP 端口连通或 HTTP 基础可达
            │
            ▼
[ 3. 业务就绪 (READY) ]     -> 专用 /health 或 /v1/models 返回业务成功信号
```

## 3. 低成本非阻塞探测红线 (Low-Cost Probing)

- 探测网络超时 **MUST NOT** 超过 2.0 秒；
- 探测过程 **MUST NOT** 发起真实 LLM 文本生成、向量 Embedding 或大数据检索；
- 探针数据 **MUST** 由 Hub 维护 TTL 缓存（15~30 秒），避免频繁探针引起端口拥塞。
