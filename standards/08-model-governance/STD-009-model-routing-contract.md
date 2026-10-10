# STD-009: Model Routing Contract (模型路由决策契约)

```text
STANDARD_ID=STD-009
VERSION=2.1.1
STATUS=ACTIVE
SCOPE=AI-Hub 候选方案推荐引擎与所有业务消费系统
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
SCHEMA_REF=schemas/model-routing-response.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 契约请求与响应架构

业务系统向 `POST /api/model/select` 发送声明式意图，Hub 计算返回 **Candidate Plan (候选执行方案)**。

```json
{
  "decision_id": "route-1774316000-a1b2c3",
  "policy_version": "v1.0.0",
  "task": "knowledge_distillation",
  "requirements": {
    "quality": "high",
    "latency": "normal",
    "multimodal_required": false
  },
  "candidates": [ ... ],
  "diversity": {
    "model_diversity": 3,
    "provider_diversity": 2,
    "channel_diversity": 2
  },
  "fallback_policy": {
    "strategy": "priority_candidate_chain_then_consumer_legacy",
    "max_candidates": 3,
    "description": "业务系统按候选优先级逐个尝试；若全部失败允许回退至自身Legacy策略"
  }
}
```

---

## 2. 候选方案多样性 (Candidate Diversity)

1. **候选数量上限**：候选方案最多返回 **5 个**。
2. **逻辑模型去重**：同一 `logical_model_id` 在候选列表中默认**最多出现 1 次**，优先保证模型能力的多样性。
3. **通道容灾显式标记**：
   若因特定容灾需要，同一模型在不同 Channel 同时入选（例如 Local CPA 与 Ollama），**MUST** 显式设置 `path_redundancy: true`，并在 reason 中说明：“通道容灾（同模型异构通道备份），非模型能力多样性”。

---

## 3. 任务能力硬过滤规则 (Hard Filtering)

1. **纯文本任务防多模态污染**：
   对 `knowledge_distillation`, `chat`, `code`, `reasoning` 等文本任务，默认 `multimodal_required: false`。明显包含 Vision / Multimodal / Image 特征的模型 **MUST NOT** 因名称评分进入前列高位候选。
2. **多模态准入**：
   仅当请求显式指定 `target_type: "multimodal"` 或 `multimodal_required: true` 时，才允许推荐多模态模型。

---

## 4. 冷启动与无样本统计语义修正

1. **无样本空值红线**：
   当模型调用次数为 0 或无延迟采样时，`success_rate` **MUST** 为 `null`，`latency_p50` 与 `latency_p95` **MUST** 为 `null`。
   **UI 严格禁止显示 100% 或 0ms**，**MUST** 明确显示“暂无数据”。
2. **数据置信度分级 (`metric_confidence`)**：
   - `0` 样本：`NONE`（中文：暂无数据，并标记 `cold_start: true`）
   - `1 - 9` 样本：`LOW`（中文：低）
   - `10 - 49` 样本：`MEDIUM`（中文：中）
   - `50+` 样本：`HIGH`（中文：高）

---

## 5. 通用任务契约规范 (Generic Task Contract - v2.1.1)

### 5.1 契约字段定义与映射体系
为消除各业务消费端特定任务与模型治理之间的私有耦合，规范定义以下标准维度：
- **`consumer_id`**: 规范消费端标识符（依据 STD-030 登记，如 `sidecar`, `aikb`, `claude-code`, `generic-openai`）。
- **`task_family`**: 通用任务家族（如 `document_transformation`, `rag_knowledge`, `coding_agent`）。
- **`task_type`**: 具体任务类型（如 `report_polishing`, `knowledge_distillation`, `chat`, `code`）。
- **`capability_profile`**: 命名能力画像 ID（保持**字符串类型**，如 `faithful_summarization`, `analytical_reasoning`）。
- **`output_contract`**: 业务输出契约（如 `markdown_structured_bullets`, `json_structured_schema`）。

### 5.2 Sidecar 标准语义基准
- `consumer_id`: `sidecar` (历史兼容别名 `vtip-ai-sidecar`)
- `task_family`: `document_transformation`
- `task_type`: `report_polishing`
- `capability_profile`: `faithful_summarization`
- `output_contract`: `markdown_structured_bullets`

### 5.3 双轨兼容与同义字段冲突契约
1. **向后兼容**: 客户端可使用旧字段（`consumer`, `task`）或规范新字段（`consumer_id`, `task_type`），亦允许混合携带。
2. **冲突硬拒绝 (422)**:
   - 若请求同时携带 `consumer` 与 `consumer_id`，经别名归一化后若指向不同属主，服务端 **MUST** 返回结构化 HTTP 422 (`SYNONYMOUS_FIELD_CONFLICT`)，严禁静默覆盖。
   - 若请求同时携带 `task` 与 `task_type` 且取值不同，服务端 **MUST** 返回结构化 HTTP 422 (`SYNONYMOUS_FIELD_CONFLICT`)，严禁静默降级为其他任务（如严禁将 `report_polishing` 静默降级为 `knowledge_distillation`）。
3. **未登记消费端鉴权拒绝**:
   - 若显式提供未在 Consumer Registry 登记的 `consumer_id` / `consumer`，服务端 **MUST** 返回 HTTP 403 (`CONSUMER_NOT_REGISTERED`) 权限拒绝。

### 5.4 路由响应增量元数据
路由响应在保持既有 `decision_id`, `candidates`, `candidate_plan`, `fallback_policy` 等字段完全不变的基础上，**MUST** 增量附带：
```json
{
  "canonical_consumer_id": "sidecar",
  "task_family": "document_transformation",
  "task_type": "report_polishing",
  "capability_profile": "faithful_summarization",
  "output_contract": "markdown_structured_bullets",
  "contract_version": "v2.1.1"
}
```
所有内部字段必须有权威来源，严禁虚构伪画像。
