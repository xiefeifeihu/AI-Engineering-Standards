# STD-023: Coding Agent Outcome Contract & Persistent Coding Task Memory (编程智能体结果契约与持久化编码任务记忆规范)

```text
STANDARD_ID=STD-023
VERSION=1.5.0
STATUS=ACTIVE
SCOPE=Coding Agent 任务级真实工程结果契约、持久化编码任务记忆与首次真实模型 Bake-Off 平台治理
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-30
RELATED_STANDARDS=STD-009, STD-010, STD-018, STD-021, STD-022
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 架构背景与双层解耦原则 (Layer Separation)

在真实软件工程任务中，单次模型 HTTP 调用成功（如 `status_code=200`、`latency_ms=656`）仅代表**模型调用执行遥测（Model Execution Telemetry）**，并不代表生成了合法补丁、通过了语法/测试校验或完成了工程交付。

为回答“哪个模型在真实编码工程任务中表现更优”，平台 **MUST** 将模型调用反馈与编程智能体任务结果严格划分为两个独立语义层：

| 层级 | 名称 | 规范接口 | 核心职责与语义粒度 |
| :--- | :--- | :--- | :--- |
| **Layer 1** | **Model Invocation Feedback（模型调用反馈层）** | `POST /api/model/feedback` (`STD-010`) | 记录单次 LLM HTTP 请求的技术执行事实（延迟、Token、HTTP 状态码、通道/Provider 级错误、熔断健康度）及通用单次调用业务评测。 |
| **Layer 2** | **Coding Agent Outcome（编程智能体任务结果层）** | `POST /api/coding/outcome` (`STD-023`) | 记录一次独立编码尝试（`coding_attempt_id`）的客观工程结果（补丁生成与应用、语法/类型检查、定向单测、核心回归、Playwright 浏览器验收、任务结项与分支采纳决策）。一次独立编码尝试可包含多次 LLM 调用、工具调用与测试执行。 |

- **MUST NOT** 将整个 Coding Agent 工程任务结果塞入 `/api/model/feedback` 的 `error_message`、`review_reason_code` 或通用 `business_score` 字段中。
- **MUST NOT** 将一次包含多轮工具调用的编码尝试降维等同于单次 HTTP 请求。

---

## 2. 规范接口矩阵 (Canonical Coding Outcome APIs)

AI-Engineering-Hub **MUST** 提供以下规范端点：

1. **冻结编码候选方案（Frozen Coding Candidate Plan）**：
   - `POST /api/coding/candidate-plan`
   - `GET /api/coding/candidate-plan/{decision_id}`
   - 用途：在真实模型 Bake-Off 或多候选编码执行前，生成并持久化不可变的候选模型计划快照（包含 `decision_id`、`task_id`、`task_profile`、`repo_id`、`repo_stack`、`candidates`、`ranking_mode`），防止执行期间并发反馈漂移候选顺序。
2. **提交编码任务结果（Idempotent Coding Outcome Submission）**：
   - `POST /api/coding/outcome`
   - 用途：按阶段幂等提交独立编码尝试的工程验证结果与采纳决策。
3. **查询编码任务结果（Read-Only Outcomes Query）**：
   - `GET /api/coding/outcomes`
   - 支持按 `consumer`、`repo_id`、`task_id`、`task_profile`、`logical_model_id`、`channel`、`task_outcome`、`outcome_stage`、`limit` 过滤。
4. **查询持久化编码任务记忆（Read-Only Coding Aggregate Memory）**：
   - `GET /api/coding/memory`
   - 支持按 `consumer`、`task_profile`、`repo_stack`、`logical_model_id`、`channel` 过滤，返回全量历史与近期时间衰减后的编码记忆指标。

---

## 3. 结果生命周期与单尝试单样本定律 (Outcome Lifecycle & Sample Counting)

### 3.1 规范阶段枚举 (`outcome_stage`)
- `ATTEMPT_COMPLETED`（默认阶段）：当某候选模型完成一次独立编码尝试（完成补丁生成/应用、单测、回归与验收判定）时上报。
- `INTEGRATION_DECISION`（可选后续阶段）：当多候选 Bake-Off 对比完成、确定最终哪个候选方案被合入主干（`integration_selected = true | false`）及最终 Git 提交/推送状态时追加上报。

### 3.2 单尝试单样本铁律 (One Coding Attempt = One Sample)
- **MUST** 保证一个 `coding_attempt_id` 在 `coding_model_memory` 中严格计为 **1 个编码记忆样本（`sample_count += 1` 仅在首次 `ATTEMPT_COMPLETED` 时发生）**。
- 当同一 `coding_attempt_id` 后续提交 `INTEGRATION_DECISION` 时，Hub **MUST** 合并更新该尝试的采纳状态（`integration_selected`）与最终交付元数据（`commit_created`、`result_commit`、`git_clean`、`remote_push_performed`、`acceptance_pass`、`task_complete`），并重算采纳率（`integration_selection_rate`），**MUST NOT** 将 `sample_count` 重复累加为 2。

---

## 4. 编码尝试身份与真实溯源契约 (Identity & Authentic Provenance)

1. **核心身份字段**：
   - 必填标识：`consumer`、`repo_id`、`task_id`、`agent_run_id`、`coding_attempt_id`。
   - 编码上下文：`coding_client`、`base_commit`、`result_commit`、`task_profile`、`repo_stack`、`decision_id`、`candidate_plan_id`、`candidate_rank`、`observed_at`。
   - 模型与通道身份：`virtual_model`、`logical_model_id`、`selected_model_id`、`upstream_model_id`、`upstream_provider`、`channel`、`resource_id`。
2. **禁止伪造身份（No Fake Identities）**：
   - 当 `upstream_model_id`、`upstream_provider`、`base_commit`、`result_commit` 等字段未经真实权威验证时，客户端与 Hub **MUST** 省略该字段或传入 `null`（数据库存为 `NULL`）。
   - **MUST NOT** 写入 `"unknown"`、`"UNKNOWN"`、`"未验证"`、`"未知"`、`"N/A"`、`"not_verified"` 等伪造占位字符串。
3. **首次 Bake-Off 归因铁律（One Primary Model Per Independent Coding Attempt）**：
   - R1 阶段执行 `attribution_mode = SINGLE_PRIMARY_MODEL`。
   - 每个 `coding_attempt_id` **MUST** 归因于唯一主模型（`logical_model_id`）。
   - 若模型 A 生成代码后验证失败，随后由模型 B 进行修复并完成任务，调用方 **MUST** 上报两条独立的编码尝试：
     - `Attempt A`（`logical_model_id = Model A`）：`task_outcome = PARTIAL` 或 `FAILED`。
     - `Attempt B`（`logical_model_id = Model B`，设置 `parent_attempt_id = Attempt A`）：记录修复尝试结果 `COMPLETED`。
   - **MUST NOT** 将模型 B 修复后的成功虚假归功于模型 A。

---

## 5. 补丁元数据与零源码存储红线 (Patch Metadata & Zero Source Content)

1. **仅允许结构化补丁元数据**：
   - `patch_created` (`boolean | null`)
   - `patch_parse_success` (`boolean | null`)
   - `patch_apply_success` (`boolean | null`)
   - `patch_hash` (`string | null`，推荐 SHA-256 摘要)
   - `files_changed_count` (`integer | null`)
   - `lines_added` (`integer | null`)
   - `lines_deleted` (`integer | null`)
2. **零源码与零敏感内容护栏（Zero Source Content Guardrail）**：
   - Hub **MUST NOT** 接收或持久化完整补丁（`patch` / `diff` / `raw_patch`）、源码文件内容（`source_code` / `source_files` / `file_contents`）、Prompt/Response 原文或任何凭证密钥。
   - `schemas/coding-agent-outcome.schema.json` 与服务端校验 **MUST** 拒绝任何包含上述禁止字段或未知扩展字段（`additionalProperties: false`）的请求（返回 HTTP 422）。

---

## 6. 工程验证、任务结果与部分成功语义 (Validation, Outcomes & Partial Success)

### 6.1 客观工程验证字段
所有未执行的检查项 **MUST** 保持 `null`（严禁伪造 `0` 或 `true/false`）：
- 静态检查：`syntax_check_run` / `syntax_check_pass`、`lint_run` / `lint_pass`、`typecheck_run` / `typecheck_pass`
- 定向单测：`targeted_tests_run` / `targeted_tests_passed` / `targeted_tests_failed`
- 核心回归：`core_regression_run` / `core_regression_passed` / `core_regression_failed`
- 构建与浏览器验收：`build_run` / `build_pass`、`browser_acceptance_run` / `browser_acceptance_pass`、`acceptance_gates_total` / `acceptance_gates_passed`

### 6.2 任务结果枚举 (`task_outcome`) 与失败阶段 (`failure_stage`)
- `task_outcome` 规范枚举：
  - `COMPLETED`：所有要求执行的工程验证与验收门禁全部通过。
  - `PARTIAL`：取得实质工程进展（如成功生成并应用补丁，但部分定向测试或验收未通过）。
  - `FAILED`：未产出有效补丁、补丁无法解析/应用，或关键工程验证失败且无可用成果。
  - `BLOCKED`：因外部环境、依赖缺失或前置条件阻塞而中止。
- `failure_stage` 规范枚举：
  - `MODEL_INVOCATION_FAILED`
  - `NO_PATCH_PRODUCED`
  - `PATCH_PARSE_FAILED`
  - `PATCH_APPLY_FAILED`
  - `SYNTAX_CHECK_FAILED`
  - `LINT_FAILED`
  - `TYPECHECK_FAILED`
  - `TARGETED_TEST_FAILED`
  - `REGRESSION_FAILED`
  - `BUILD_FAILED`
  - `ACCEPTANCE_FAILED`
  - `SECURITY_REJECTED`

### 6.3 采纳决策独立性铁律 (`task_outcome=COMPLETED` + `integration_selected=false`)
- 在多候选模型 Bake-Off 中，两个或多个候选模型均可能独立完成任务并通过全部测试（`task_outcome = COMPLETED`），但最终仅有一个候选方案被选入主分支（`integration_selected = true`），其余合格候选记录为 `integration_selected = false`。
- **`task_outcome = COMPLETED` 且 `integration_selected = false` 是完全合法的正向工程结果**：
  - **MUST** 计入该模型的完成率（`completion_rate` 正向贡献）；
  - **MUST NOT** 被视为编码失败、技术故障或模型健康度降级；
  - Hub **MUST** 将“独立完成能力（`completion_rate`）”与“最终采纳偏好（`integration_selection_rate`）”分开统计与学习。

---

## 7. 持久化编码任务记忆与严格层间隔离 (Coding Task Memory & Isolation)

### 7.1 记忆分桶维度
`coding_model_memory` **MUST** 按以下 5 元组维度进行隔离聚合（并支持全局汇总视图）：
`(consumer, task_profile, repo_stack, logical_model_id, channel)`

其中 `task_profile` 规范枚举包括：
`bugfix`、`feature_implementation`、`refactor`、`test_writing`、`ui_playwright`、`governance_contract`、`repo_exploration`、`general_coding`。

### 7.2 聚合指标与时间衰减复用 (`STD-022`)
每个编码记忆桶 **MUST** 同时维护全量历史指标与基于 `observed_at` 的指数衰减有效指标（复用 `STD-022` 衰减引擎与模型指纹追踪）：
- 样本与置信度：`sample_count`、`decayed_sample_weight`、`confidence_level`（`0=NONE`、`1-9=LOW`、`10-49=MEDIUM`、`50+=HIGH`）、`effective_confidence_level`
- 核心工程率值（冷启动 0 样本时 **MUST** 为 `null`）：
  - `completion_rate` / `recent_completion_rate`
  - `partial_rate`
  - `failed_rate`
  - `blocked_rate`
  - `patch_apply_rate`
  - `targeted_test_pass_rate` / `recent_targeted_test_pass_rate`
  - `core_regression_pass_rate` / `recent_core_regression_pass_rate`
  - `browser_acceptance_pass_rate` / `recent_browser_acceptance_pass_rate`
  - `integration_selection_rate` / `recent_integration_selection_rate`
  - `median_wall_time_ms` / `p95_wall_time_ms`
  - `avg_repair_rounds`
- 模型身份指纹：`model_fingerprint`、`fingerprint_status`（`VERIFIED` / `PARTIAL` / `UNKNOWN`）、`memory_epoch`、`last_observed_at`。

### 7.3 严格跨层与跨租户隔离保证
1. **L1 技术健康度绝对隔离**：提交 `task_outcome = FAILED / PARTIAL / BLOCKED` 的编码结果 **MUST NOT** 修改 `model_governance_states` 中的技术失败计数（`failure_count`、`consecutive_failures`）、技术成功率或熔断器状态（`circuit_state`）。
2. **跨业务域记忆绝对隔离**：更新 `coding_model_memory` **MUST NOT** 污染 `model_consumer_task_memory` 中 `ai-kb` 的知识提炼质量记忆或 `vtip-ai-sidecar` 的文本报告合成质量记忆。

---

## 8. 首次 Bake-Off 公平性与路由安全模式 (First Bake-Off Fairness)

1. **路由影响模式（`CODING_OUTCOME_RANKING_MODE`）**：
   - `SHADOW_ONLY`（**R1 默认强制模式**）：记录编码任务结果并计算持久化编码记忆，在控制台展示完整的对比指标，但 **MUST NOT** 自动改变 `/api/model/select` 或 `/api/coding/candidate-plan` 的候选打分排序。
   - `SOFT_PREFERENCE`：仅当样本置信度达到阈值后施加有界软偏好加分。
   - `GOVERNED_ROUTING`：允许基于高置信度编码记忆驱动自动排序。
2. **Qwen 编码软偏好保持不变**：
   - 在 `SHADOW_ONLY` 模式下，保留既有的 `task=code` Qwen 家族 `-40.0` 软偏好（非编码任务保持 `0.0`）。
3. **UI 简体中文规范展示（`STD-018`）**：
   - 在 Hub 控制台「编程网关 (`#view-gateway`)」视图中，**MUST** 将 Layer 1「模型调用执行记录」与 Layer 2「编码任务结果 / 编码模型长期记忆」清晰分区展示，所有内部枚举映射为规范简体中文（如 `已完成`、`部分完成`、`未通过`、`已阻塞`、`已采纳`、`未采纳（有效候选）`、`待定`、`影子观测（不影响排序）`）。
