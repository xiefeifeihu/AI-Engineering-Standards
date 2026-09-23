# STD-013: Logging & Observability Standard (审计与可观测性规范)

```text
STANDARD_ID=STD-013
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=AI-Hub 统一审计中心及跨工程运维操作追踪
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
SCHEMA_REF=schemas/audit-event.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 统一审计事件模型

所有系统关键事件（启动、健康状态迁移、资源动作执行、路由决策、模型调用反馈）**MUST** 记录至统一审计存储，记录格式包含：
- `event_id`: 唯一事件标识
- `timestamp`: UTC ISO 8601 标准时间字符串（严格禁止因时区混乱导致排序错位）
- `category`: `SYSTEM_EVENT`, `RESOURCE_ACTION`, `MODEL_PROBE`, `ROUTE_DECISION`
- `action`: 动作类型
- `target`: 目标资源或模型标识
- `status`: `PASS`, `FAIL`, `WARN`
- `duration_ms`: 执行耗时毫秒
- `summary`: 简明中文字要说明
- `technical_detail`: 结构化技术细节字典
