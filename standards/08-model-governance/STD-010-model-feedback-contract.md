# STD-010: Model Feedback Contract (模型调用与多阶段反馈契约)

```text
STANDARD_ID=STD-010
VERSION=1.3.0
STATUS=ACTIVE
SCOPE=所有向 AI-Hub 上报实际调用结果与多阶段评测反馈的业务消费者 (AI-KB, Sidecar, Coding Agents 等)
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-29
SCHEMA_REF=schemas/model-feedback.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 核心架构原则与所有权边界 (Core Architecture Rule)

1. **业务判定所有权归消费端 (Consumers Own Domain Judgment)**：
   - **AI-KB** 独立拥有知识切片提炼质量、证据引用真实性、核心论点覆盖度、知识边界合规与人工审核判定的全部所有权。
   - **VTIP-AI-SIDECAR** 独立拥有周报/日报结构有效性、事实护栏 (Fact Guard)、形态护栏 (Shape Guard)、中文质量过滤与业务验收评分的全部所有权。
   - **Coding Agents** 独立拥有代码语法合规、Patch 应用、测试执行、Linter 校验与任务闭环完成度的所有权。
2. **AI-Hub 平台所有权 (Hub Ownership)**：
   - 结构化反馈摄取与归一化 (Structured Feedback Ingestion & Normalization)
   - 幂等持久化与调用链路追踪 (L3 Invocations Trace)
   - L1 全局与任务技术健康记忆 (Global Technical Health Memory & Circuit Breaker)
   - L2 消费端与业务任务隔离记忆 (Consumer + Task Business Memory)
   - 模型治理与路由决策打分影响 (Model Governance & Routing Influence)
3. **零内容与绝对数据边界 (Zero Content & Privacy Guardrail)**：
   - AI-Hub **MUST NOT** 存储任何原始业务文本，包括但不限于：原始文档全文、RAG 文档切片 (Chunks)、Prompt 提示词正文、模型生成的回答/报告正文、私有业务数据。
   - AI-Hub 仅持久化标识符 (IDs)、哈希值 (Hashes)、枚举 (Enums)、时间戳 (Timestamps)、计数值 (Counts) 与数值度量 (Numeric Metrics)。

---

## 2. 接口端点与载荷规范 (API Endpoint & Payload)

业务系统在完成模型调用、业务评估或人工复核后，**SHOULD** 异步将结构化反馈上报至 `POST /api/model/feedback`。

```json
{
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
  "evaluation_method": "combined",
  "prompt_version": "v1.2.0",
  "rubric_version": "kq-003",
  "evaluation_confidence": 0.95,
  "review_decision": "approved",
  "review_reason_code": "",
  "candidate_rank": 1,
  "retry_count": 0,
  "fallback_count": 0,
  "success": true,
  "latency_ms": 765.4,
  "prompt_tokens": 1250,
  "completion_tokens": 420,
  "total_tokens": 1670,
  "status_code": 200,
  "error_type": "",
  "error_message": "",
  "quality_metrics": {
    "knowledge_quality": 0.96,
    "citation_validity": 1.0,
    "answer_completeness": 0.92
  }
}
```

---

## 3. 多阶段反馈生命周期语义 (Feedback Stage Semantics)

`feedback_stage` 枚举定义如下：
- `execution`: 实际提供商/模型调用尝试。可包含紧随执行完成由消费端直接产生的自动化质量评分 (`quality_metrics`)。
  - **允许更新**：L1 全局与任务技术健康记忆、L2 消费端业务记忆、L3 调用追踪。
- `business_evaluation`: 后续异步执行的业务自动化评估（如基于 Benchmark、Golden Set、Critic 模型等）。
  - **更新规则**：**MUST NOT** 再次递增 L1 技术调用次数、成功/失败计数或 Token 消耗总量。仅允许更新 L2 业务记忆与 L3 评测追踪。
- `human_review`: 后续人工复核、专家审核、批准或驳回。
  - **更新规则**：**MUST NOT** 修改任何 L1 技术健康状态。仅允许更新 L2 人工复核记忆与 L3 复核追踪。
- **向后兼容性**：若消费端请求未携带 `feedback_stage`，系统默认按 `execution` 阶段处理。

---

## 4. 业务审核结论与原因代码 (Review Decision & Reason Code)

1. **规范审核结论 (`review_decision`) 枚举**：
   - `approved`: 审核通过，内容完全符合业务预期。
   - `approved_with_note`: 审核通过，但附带改进备注或非阻断性建议。
   - `rejected`: 业务审核驳回，内容未达到准出要求。
   - `revise`: 需要修订，待进一步调整重试。
   - `discard`: 废弃当前产物，不再进入后续流程。
   - `execution_failed`: 执行期致命失败导致无法进入业务审核。
   - `not_reviewed`: 尚未经过审核。
2. **结构化原因代码 (`review_reason_code`)**：
   消费端的具体拦截或驳回原因 **MUST** 采用结构化代码，严禁回传业务正文文本。示例：
   - `fact_guard_failed`: 事实护栏拦截（幻觉/篡改事实）
   - `structure_invalid`: 结构解析失败或不符合 Schema
   - `shape_guard_failed`: 篇幅、段落形态超标
   - `quality_guard_failed`: 质量降级或低于基线
   - `golden_review_discard`: 金标校准测试丢弃
   - `boundary_violation`: 业务边界违规

---

## 5. 评估方法枚举 (Evaluation Method)

`evaluation_method` 枚举定义：
- `deterministic`: 纯确定性代码逻辑校验（正则表达式、语法解析、规则断言）。
- `llm_judge`: 大模型作为裁判 (LLM-as-a-Judge) 评估。
- `human`: 人工专家审核打分。
- `combined`: 复合评估（结合确定性规则、金标语义比对与裁判模型，例如 AI-KB 三层评估器）。
- `unknown`: 评估方式未指定。

---

## 6. 度量命名空间规范 (Metric Namespace)

1. 为防止各消费端业务指标发生语义混淆，推荐上报 `metric_namespace`。
   - AI-KB 示例：`ai-kb.knowledge_distillation.v1`
   - Sidecar 示例：`vtip-ai-sidecar.report_synthesis.v1`
   - 编程智能体示例：`coding-agent.code.v1`
2. **跨命名空间数值不可比性**：
   相同数值在不同命名空间下 **MUST NOT** 被推断为等价业务含义（例如 AI-KB 的 `knowledge_quality = 0.92` 与 Sidecar 的 `business_score = 0.92` 各自独立，不可直接横向等价对比）。
3. `quality_metrics` 保持为 `map<string, number>` 字典结构，以支持各领域特化的数值度量。

---

## 7. 置信度语义分离 (Confidence Semantics Separation)

为消除单次评测置信度与统计样本置信度的概念混淆，特此严格分离：
- `evaluation_confidence`: 消费端对本次单次评测结果的自评估置信度 (0.0 ~ 1.0)。
- `sample_confidence_level`: 由 AI-Hub 依据累积样本量分布自主计算的统计置信等级 (`NONE`, `LOW`, `MEDIUM`, `HIGH`)。
- **所有权边界**：消费端 **MUST NOT** 发送统计样本置信度；`sample_count` 为 Hub 服务端自增管理字段，严禁作为入参上报。
- 历史兼容性：Sidecar 现存的 `quality_metrics.confidence` 为业务润色完整度评分，维持其作为 domain metric 存在，不重新解释为统计置信度。

---

## 8. 样本置信度阶梯基线 (Sample Confidence Thresholds)

与 `STD-009` 模型路由决策契约保持单一大源对齐：
- `sample_count = 0`: `NONE` (暂无数据 / 冷启动)
- `sample_count 1 ~ 9`: `LOW` (低置信度)
- `sample_count 10 ~ 49`: `MEDIUM` (中置信度)
- `sample_count >= 50`: `HIGH` (高置信度)

---

## 9. 来源单元与规格哈希语义 (Source Unit & Spec Hash)

- `source_unit_id`: 消费端持有的不透明输入单元标识符（如金标槽位 `U1`，或业务文档分块编号）。
- `source_unit_hash`: **仅针对归一化后的来源单元身份/内容本身计算的哈希**（如 SHA-256）。**MUST NOT** 混入 Prompt 模板、系统指令或模型执行参数。
- `execution_spec_hash`: **独立记录执行规格的哈希**（包含 Prompt 版本、温度、Top-P、JSON Schema 约束等）。
- Hub 仅存储哈希值，严禁存储正文。

---

## 10. 模型身份语义 (Model Identity Semantics)

- `logical_model_id`: 规范逻辑模型标识符（如 `qwen3-coder-next`, `gemini-3.5-flash-lite`）。
- `selected_model_id`: Hub 路由决策规划中被选中的具体候选标识符。
- `upstream_model_id`: 经适配层验证的实际上游提供商返回的模型标识符。
- `resource_id`: 服务该候选的底层基础设施资源标识符。
- `model`: 保留作为向后兼容字段。

---

## 11. 多阶段反馈幂等契约 (Multi-Stage Idempotency Contract)

1. 若消费端显式提供 `idempotency_key`，Hub 以其作为唯一去重依据。
2. 若未提供，v1.3 推荐服务端组合幂等键：
   `consumer::(run_id or decision_id)::(source_unit_id or "none")::channel::logical_model_id::attempt::feedback_stage`
3. **多阶段共存原则**：同一调用尝试的 `execution` 事件与后续到达的 `human_review` 或 `business_evaluation` 事件具有不同的阶段后缀，**MUST** 能够共存持久化，不得误判去重。
4. **同阶段重放幂等**：完全相同的重放请求返回 `idempotent_duplicate: true`，且 **MUST NOT** 发生二次计数或重复累加。

---

## 12. 观察时间戳 (Observed At)

- `observed_at`: ISO-8601 UTC 时间戳，记录事件在消费端实际发生的时间。
- 服务端记录 `created_at`（入库时间），但业务分析与延迟衰减计算应当以 `observed_at` 为准，确保乱序到达与异步离线评测的数据正确性。

---

## 13. 业务驳回与技术健康严格隔离 (Business Rejection Safety)

- 业务审核驳回（如事实护栏拦截、质量不达标）**MUST NOT** 污染技术错误分类。
- 业务拒绝时技术 `success` 可保持为 `true`，通过 `review_decision: "rejected"` 与 `review_reason_code` 表明业务结论。
- 业务驳回 **MUST NOT** 增加技术失败计数 (`failure_count`)、连续失败计数 (`consecutive_failures`) 或触发熔断器 (`QUARANTINED`)。

---

## 14. 编程智能体网关扩展 (Coding Gateway Extension)

沿用 `STD-021` 定义的编程专用指标字段：
- `ttft_ms`: 首字流式输出耗时 (毫秒)
- `tool_call_success`: 智能体工具调用是否成功执行
- `retry_count`: 单次轮次内的重试次数
- `fallback_count`: 触发 Candidate 故障转移的次数
- `patch_applied`: 代码 Patch 是否成功落盘应用
- `tests_passed`: 单元测试是否通过
- `lint_passed`: 静态代码检查是否通过
- `task_completed`: 编程任务是否最终闭环完成
