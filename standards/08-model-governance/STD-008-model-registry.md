# STD-008: Model Registry Standard (模型注册表规范)

```text
STANDARD_ID=STD-008
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=AI-Hub 聚合的所有底层推理模型元数据
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
SCHEMA_REF=schemas/model-registry.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 模型实体定义

AI-Hub 汇聚来自 Local CPA、Cloud CPA 与 Ollama 的所有底层模型，形成统一视图。每个模型实体 **MUST** 具备：
- `id`: 全局唯一标识符（例如 `local-cpa::qwen2.5-72b-instruct`）
- `name`: 模型原生命名
- `logical_model_id`: 逻辑模型名（去除了渠道前缀的通用模型代号，例如 `qwen2.5-72b-instruct`）
- `provider`: 底层模型提供商（例如 `Alibaba`, `NVIDIA`, `Google`, `DeepSeek`）
- `channel`: 接入渠道（`local-cpa`, `cloud-cpa`, `ollama`）
- `resource_id`: 所属物理资源
- `capability_tags`: 能力标签列表
- `type_code`: 模型主要类型（`chat`, `reasoning`, `embedding`, `multimodal`）
- `status`: 当前物理可用状态（`HEALTHY`, `DEGRADED`, `QUARANTINED`, `RECOVERING`）
