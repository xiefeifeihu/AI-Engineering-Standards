# STD-022: Model Runtime Memory & Decay Governance (模型长期运行记忆、时间衰减与周期治理规范)

```text
STANDARD_ID=STD-022
VERSION=1.4.0
CATEGORY=08-model-governance
STATUS=NORMATIVE
```

## 1. 目标与问题定义

随着 `STD-010 (v1.3.0)` 多阶段反馈契约在各消费端（AI-KB、VTIP-AI-Sidecar、Coding Agent 等）落地，AI-Hub 已能完整记录调用执行（`execution`）、业务质量评估（`business_evaluation`）与人工复核（`human_review`）的真实事件事实。

然而，若模型路由直接使用“全生命周期历史累计值（All-Time Cumulative Statistics）”作为主导依据，会导致严重的治理失真：
- 某模型在数月前积累了上万次成功调用，但近期出现上游版本退化、配额限流或质量下滑，其历史总成功率依然接近 100%，从而阻碍路由及时切换；
- 某上游逻辑模型名称未变，但底层供应方版本、量化配置或模型映射发生实质变更，旧周期的运行统计不应继续无条件代表新模型身份。

本规范定义 **原始历史事实（Raw Historical Facts / All-Time Memory）** 与 **近期有效路由记忆（Recent Effective Routing Memory）** 的双视图分离架构、基于 `observed_at` 的指数时间衰减模型、模型身份指纹（`model_fingerprint`）与记忆周期（`memory_epoch`）、以及幂等历史 L2 记忆重建机制。

---

## 2. 核心记忆分层与双视图架构

AI-Hub 必须永久保留 L3 原始调用与反馈事件事实，**严禁覆写或删除原始历史记录**。在此基础上，L1（技术执行健康）与 L2（业务质量记忆）均须维护两套并行视图：

### 2.1 全量历史记忆（All-Time Memory）
- **用途**：合规审计、历史趋势分析、全生命周期统计展示。
- **必须保留字段**：
  - `attempt_count` / `sample_count`（真实整数样本计数，严禁被衰减权重覆盖）
  - `success_count` / `failure_count`
  - `prompt_tokens` / `completion_tokens` / `total_tokens`
  - `historical_success_rate` / `historical_latency_p50_ms` / `historical_latency_p95_ms`
  - `historical_quality_score` / `historical_quality_metrics`
- **路由约束**：全量历史统计值**不得**直接作为当前模型路由排名的主导依据。

### 2.2 近期有效记忆（Recent Effective Memory）
- **用途**：实时模型动态评分与候选路由排序（`STD-009`）。
- **时间基准**：严格以事件发生时间 `observed_at` 为准，而非数据库入库时间 `created_at`。
- **必须包含指标**：
  - `effective_sample_weight`（经过指数衰减后的浮点有效样本权重）
  - `effective_success_rate` / `effective_failure_rate`
  - `effective_latency_ms`（衰减加权有效延迟）
  - `effective_quality_score` / `recent_business_quality`（衰减加权有效业务质量）
  - `recent_failure_pressure`（近期故障压力指标）
  - `effective_confidence_level`（基于有效样本权重的当前治理置信度）

---

## 3. 基于 `observed_at` 的指数时间衰减模型

### 3.1 衰减公式
对于任意发生在 $t_{\text{observed}}$ 的事件，在当前评估时刻 $t_{\text{now}}$ 的时间年龄为：

$$\text{age\_days} = \max\left(0.0, \frac{t_{\text{now}} - t_{\text{observed}}}{86400}\right)$$

其指数时间衰减权重定义为：

$$w(\text{age\_days}) = 0.5^{\left(\frac{\text{age\_days}}{\text{half\_life\_days}}\right)}$$

### 3.2 可配置半衰期默认值
技术执行状态变化迅速，而业务评测质量具有较长周期稳定性，因此两类记忆采用独立的可配置半衰期（严禁在业务代码中硬编码散落常量）：
- **技术健康半衰期（`technical_half_life_days`）**：默认 `7.0` 天（可通过环境变量或配置项覆写）。
- **业务质量半衰期（`business_quality_half_life_days`）**：默认 `30.0` 天（可通过环境变量或配置项覆写）。

### 3.3 乱序事件安全性（Out-of-Order Event Safety）
- 异步业务质量评估（`business_evaluation`）或人工复核（`human_review`）可能在调用结束后数小时或次日才到达 AI-Hub。
- 衰减计算**必须**依赖事件携带的 `observed_at` 时间戳，且聚合结果必须对事件到达顺序不敏感（Order-Independent）：即便较早发生的事件 B 晚于较晚发生的事件 C 到达，最终计算出的近期有效记忆必须完全一致。

---

## 4. L1 技术记忆衰减与熔断协同

1. **阶段隔离**：L1 技术有效记忆仅消费 `feedback_stage = "execution"` 的技术执行事件。`business_evaluation` 与 `human_review` 阶段的业务低分或驳回**严禁**计入技术失败次数、技术成功率或触发技术熔断器。
2. **近期故障加权**：通过 `technical_half_life_days = 7` 的指数衰减，近期技术失败对 `effective_success_rate` 和 `recent_failure_pressure` 的影响显著高于数周或数月前的历史成功记录。
3. **与实时熔断器（Circuit Breaker）协同**：时间衰减是长期记忆治理机制，不能替代实时熔断器。连续失败计数（`consecutive_failures`）与熔断器状态（`OPEN` / `HALF_OPEN` / `CLOSED`）继续提供毫秒级实时保护。

---

## 5. L2 业务质量记忆隔离与命名空间聚合

### 5.1 严格五维隔离
业务质量记忆（L2）必须按以下五个维度严格隔离，**严禁跨消费端或跨任务构建单一全局业务质量分**：
1. `consumer`（消费方标识，如 `ai-kb`、`vtip-ai-sidecar`、`claude-code`）
2. `task`（标准任务类型，如 `knowledge_distillation`、`report_synthesis`、`code`）
3. `metric_namespace`（指标命名空间，如 `ai-kb.knowledge_distillation.v1`、`vtip-ai-sidecar.report_synthesis.v1`、`coding-agent.code.v1`）
4. `logical_model_id`（逻辑模型标识）
5. `channel`（执行通道，如 `local-cpa`、`cloud-cpa`、`ollama`）

同一模型在 `ai-kb` 中排名第 1、在 `vtip-ai-sidecar` 中排名第 3、在 `coding-agent` 中排名第 5 属于预期正常治理现象。

### 5.2 命名空间内聚合策略
- 不同 `metric_namespace` 拥有各自独立的 `quality_metrics` 字段集合（例如 AI-KB 包含极性归一化至 `[0.0, 1.0]` 的 `knowledge_quality`、`citation_validity`、`answer_completeness`；Sidecar 包含 `fact_guard_pass`、`structure_validity`、`confidence`、`business_score`）。
- **严禁**将不同命名空间的异构指标直接混算。
- 在同一命名空间内部，支持命名空间特定的派生质量分规则（`namespace_specific_weighted`）；若未配置特定加权规则，则采用透明的中性均值聚合策略（`neutral_mean_normalized`），并在诊断接口中显式暴露所使用的 `aggregation_strategy`。

---

## 6. 有效样本权重与治理置信度

1. **保留原始计数**：`sample_count` 始终保持真实的整数样本数，不得被衰减计算改写。
2. **有效样本权重（`effective_sample_weight`）**：定义为当前记忆周期内各样本时间衰减权重之和 $\sum w_i$（浮点数）。例如 100 条远古样本的 `effective_sample_weight` 可能远低于 10 条今日新样本。
3. **当前治理置信度（`effective_confidence_level`）**：路由置信度必须基于 `effective_sample_weight` 而非单纯依赖历史总 `sample_count`，避免陈旧样本赋予模型虚高的治理置信度：
   - `NONE`（暂无数据）：`effective_sample_weight <= 0`
   - `LOW`（低置信度 / 冷启动探索）：`0 < effective_sample_weight < 3.0`
   - `MEDIUM`（中等置信度）：`3.0 <= effective_sample_weight < 10.0`
   - `HIGH`（高置信度）：`effective_sample_weight >= 10.0`
4. **中文 UI 规范术语**：
   - `历史样本数`（对应 `sample_count`）
   - `当前有效样本权重`（对应 `effective_sample_weight`）
   - `当前治理置信度`（对应中文映射：`高置信度` / `中等置信度` / `低置信度（探索期）` / `暂无数据`）

---

## 7. 模型身份指纹（Model Fingerprint）与记忆周期（Memory Epoch）

### 7.1 模型身份指纹（`model_fingerprint`）
为识别同名逻辑模型背后的上游实际模型或运行时配置是否发生实质变化，AI-Hub 必须基于权威已知元数据计算确定性指纹（SHA-256 前缀摘要）：
- **允许纳入指纹的权威字段（仅限实际已知时）**：
  - `logical_model_id`
  - `upstream_provider`
  - `upstream_model_id`
  - `channel`
  - `resource_id`
  - `context_window`
  - `provider_revision` / `model_digest`（上游显式版本摘要或修订号）
  - `quantization`（量化精度）
  - `runtime_profile`
- **安全与真实性禁令**：
  - **严禁**使用模型自我描述（LLM Self-Description）生成指纹。
  - **严禁**对 API Key、Token 等凭证（`STD-007`）或业务文本内容进行哈希。
  - **严禁**伪造未知字段：当上游（如部分 CPA 通道）未暴露显式 `revision/digest` 时，必须如实标记指纹可信度状态。

### 7.2 指纹可信度状态（`fingerprint_status`）
- `VERIFIED`（UI 中文：**已确认**）：具备明确的上游修订号、模型摘要（Digest）、量化配置或完整权威版本元数据。
- `PARTIAL`（UI 中文：**部分可识别**）：具备稳定的逻辑模型 ID、上游供应方、通道与资源映射，但上游未暴露显式模型修订号。
- `UNKNOWN`（UI 中文：**未知**）：尚未完成权威注册或缺少基础身份元数据。

### 7.3 记忆周期（`memory_epoch`）与防误切机制
1. **周期延续**：当模型指纹未发生实质性身份或版本变化时，新产生的运行与评测事件归入当前 `current_epoch`。
2. **实质变更触发新周期**：当权威模型身份（如 `upstream_model_id`、`provider_revision`、`quantization` 等实质字段）发生改变时，AI-Hub 自动开启新的 `memory_epoch`（`current_epoch = previous + 1`）：
   - 旧周期（Previous Epochs）统计数据完整保留于历史表，可供查询与审计，**严禁删除**；
   - 新周期（Current Epoch）的近期有效记忆从零/冷启动中性先验开始累积，**严禁**将旧周期统计数据直接混入新周期有效记忆。
3. **防误切（False Epoch Prevention）**：以下瞬态运行事件**严禁**触发新 `memory_epoch`：
   - 终端 URL 或临时端口切换；
   - Cloud CPA 隧道重启或重连；
   - Docker 容器或宿主服务重启；
   - 响应延迟波动或网络抖动；
   - 上游供应方临时报错、超时或通道暂时不可用。
4. **冷启动与新周期先验（Cold Start / New Epoch Prior）**：新模型或新 Epoch 在无有效样本时，其展示指标必须为 `null`（UI 显示 `暂无数据`），路由层采用中性先验分（Neutral Prior），**严禁**赋予虚假的 `100%` 成功率、`0ms` 延迟或满分质量，也严禁仅因无历史记录而彻底封杀合法候选模型。

---

## 8. 历史 L2 记忆幂等重建规范（Historical L2 Rebuild）

1. **Hub 自主重建原则**：当升级记忆治理架构时，AI-Hub 必须仅通过读取本地已持久化的 `model_invocations`（L3 历史事实表）重建 L2 业务质量记忆，**严禁要求下游消费方（如 AI-KB）重放历史评测任务（如 KQ-003）**。
2. **数据安全红线**：
   - **严禁**产生重复的 `model_invocations`（L3）记录；
   - **严禁**修改或累加 L1 技术计数器（`attempt_count`、`success_count`、`failure_count`、`consecutive_failures`）及 Token 消耗统计；
   - **必须幂等**：通过持久化迁移水位线/版本标记或基于全量 L3 合格记录的确定性重算，确保多次执行重建不会产生重复计数。
3. **确定性命名空间推导**：
   - 对于 `v1.3` 之前未显式记录 `metric_namespace` 的历史记录，仅当 `(consumer, task)` 与 `quality_metrics_json` 结构具有唯一确定性映射时才允许推导命名空间：
     - `consumer = "ai-kb"` 且 `task = "knowledge_distillation"`（含结构化知识提炼指标）$\rightarrow$ `ai-kb.knowledge_distillation.v1`
     - `consumer = "vtip-ai-sidecar"` 且 `task = "report_synthesis"`（含结构化报告合成指标）$\rightarrow$ `vtip-ai-sidecar.report_synthesis.v1`
     - `consumer in ("claude-code", "coding-agent")` 且 `task = "code"` $\rightarrow$ `coding-agent.code.v1`
   - 对于消费方不明、任务缺失或指标结构歧义的记录，必须安全跳过（`SKIP`）并在重建报告中如实记录，**严禁猜测**。

---

## 9. 性能与零内容边界（Performance & Zero-Content Boundary）

1. **路由高性能保障**：`/api/model/select` 必须保持纯内存/预计算级响应（Host 与 Docker P95 < 100ms，`SELECT_SYNCHRONOUS_DISCOVERY = 0`）。时间衰减计算必须基于预聚合状态（如指数移动衰减充分统计量或有界缓存更新），**严禁在每次路由请求时全表扫描数千条 SQLite L3 记录**。
2. **零内容与零密钥边界**：任何记忆表、诊断接口、重建报告或前端视图均**严禁**存储或暴露 API 密钥、Prompt 原文、知识库文档正文或模型生成内容。
