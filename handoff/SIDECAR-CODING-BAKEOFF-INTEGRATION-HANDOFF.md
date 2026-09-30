# Sidecar 首次真实编码 Bake-Off 平台接入交接指南 (SIDECAR-CODING-BAKEOFF-INTEGRATION-HANDOFF)

```text
TASK_ID=AI-Hub-013-R1-CODING-OUTCOME-CONTRACT
VERSION=v0.9.0
STANDARDS_VERSION=1.5.0
HUB_VERSION=0.9.0
STATUS=COMPLETED
TARGET_PROJECT=VTIP-AI-SIDECAR (D:\Projects\vtip-ai-sidecar)
TARGET_NEXT_TASK=SIDECAR-DEV-022 (First Real Coding Model Bake-Off)
LAST_UPDATED=2026-09-30

CODING_CANDIDATE_PLAN_ENDPOINT=POST /api/coding/candidate-plan
CODING_GATEWAY_ANTHROPIC_ENDPOINT=POST /v1/messages
CODING_GATEWAY_OPENAI_ENDPOINT=POST /v1/chat/completions
MODEL_FEEDBACK_ENDPOINT=POST /api/model/feedback
CODING_OUTCOME_ENDPOINT=POST /api/coding/outcome
CODING_OUTCOMES_QUERY_ENDPOINT=GET /api/coding/outcomes
CODING_MEMORY_ENDPOINT=GET /api/coding/memory

REQUIRED_IDS=
task_id
agent_run_id
coding_attempt_id
decision_id

OUTCOME_STAGE_FLOW=
1. Freeze candidate plan
2. Run Candidate A independently -> submit ATTEMPT_COMPLETED
3. Run Candidate B independently -> submit ATTEMPT_COMPLETED
4. Select winning candidate -> submit INTEGRATION_DECISION

NON_GOALS=
No full patch upload
No fake upstream identities
No automatic routing score bias during first bake-off

COMPLETED_ITEMS=
- STD-023 Coding Agent Outcome Contract & schemas/coding-agent-outcome.schema.json (Standards v1.5.0)
- Frozen Coding Candidate Plan API (POST /api/coding/candidate-plan, GET /api/coding/candidate-plan/{decision_id})
- Layer 2 Coding Agent Outcome API (POST /api/coding/outcome, GET /api/coding/outcomes)
- Persistent Coding Task Memory API (GET /api/coding/memory) with STD-022 exponential time decay
- First Bake-Off Routing Safety Guard (CODING_OUTCOME_RANKING_MODE=SHADOW_ONLY)
- Hub UI Coding Gateway Layer 2 Coding Outcome & Coding Memory observability panel

PENDING_ITEMS=
- Execute SIDECAR-DEV-022 real coding task bake-off in D:\Projects\vtip-ai-sidecar using frozen candidate plans and two-stage outcome reporting

COMMIT_HASH=HEAD
TEST_RESULTS=PASS (Standards validate-schemas + Hub R1 Coding Outcome Contract & Playwright UI suite)
```

---

## 1. 架构分层铁律：Layer 1 模型调用 vs Layer 2 编码任务结果

在 `SIDECAR-DEV-022` 首次真实编码模型 Bake-Off 中，必须严格区分以下两层上报语义：

1. **Layer 1 — 单次模型调用反馈 (`POST /api/model/feedback`)**：
   - 记录每次 HTTP 推理请求的技术执行事实（`latency_ms`、`prompt_tokens`、`completion_tokens`、`status_code`、`error_type`）。
   - 由 Coding Gateway（`/v1/messages`、`/v1/chat/completions`）自动采集或由调用方按次上报。
2. **Layer 2 — 独立编码尝试工程结果 (`POST /api/coding/outcome`)**：
   - 记录某个候选模型在一次独立编码尝试（`coding_attempt_id`）中的客观工程交付结果：补丁生成/解析/应用、语法/类型检查、定向单测、核心回归、Playwright 浏览器验收、最终分支合入采纳决策。
   - **单尝试单样本定律**：一个 `coding_attempt_id` 严格对应 `coding_model_memory` 中的 **1 个编码记忆样本**。

---

## 2. 运行时端点配置 (Host & Docker Consumer)

- **宿主机 CLI / 评测器 (`HUB_HOST_ENDPOINT`)**：`http://127.0.0.1:80`
- **Docker 容器内 (`HUB_DOCKER_ENDPOINT`)**：`http://host.docker.internal:18000`

| 能力 | 方法与路径 | 说明 |
| :--- | :--- | :--- |
| **冻结编码候选方案** | `POST /api/coding/candidate-plan` | 生成并持久化冻结的候选方案快照，返回 `decision_id` 与候选列表 |
| **查询冻结候选方案** | `GET /api/coding/candidate-plan/{decision_id}` | 按 `decision_id` 读取已冻结的候选方案，确保 Candidate A/B 执行期间排序零漂移 |
| **Anthropic 编程网关** | `POST /v1/messages` | Claude Code 等客户端接入（支持 `hub-code-auto` / `hub-code-deep` 等虚拟模型） |
| **OpenAI 编程网关** | `POST /v1/chat/completions` | OpenCode / Codex / 通用 Agent 接入 |
| **Layer 1 模型反馈** | `POST /api/model/feedback` | 单次 LLM 调用执行遥测反馈 (`STD-010`) |
| **Layer 2 编码结果提交** | `POST /api/coding/outcome` | 幂等提交 `ATTEMPT_COMPLETED` 与 `INTEGRATION_DECISION` (`STD-023`) |
| **Layer 2 编码结果查询** | `GET /api/coding/outcomes` | 查询编码尝试记录 |
| **Layer 2 编码任务记忆** | `GET /api/coding/memory` | 查询按 `(consumer, task_profile, repo_stack, logical_model_id, channel)` 聚合的编码记忆 |

---

## 3. SIDECAR-DEV-022 首次真实 Bake-Off 标准四步流 (`OUTCOME_STAGE_FLOW`)

### Step 1: 冻结候选计划 (`Freeze candidate plan`)
在开始任何代码修改前，调用 `POST /api/coding/candidate-plan` 冻结本次任务的候选模型：

```json
{
  "consumer": "vtip-ai-sidecar",
  "repo_id": "vtip-ai-sidecar",
  "repo_stack": "python_fastapi",
  "task_id": "SIDECAR-DEV-022",
  "task_profile": "feature_implementation",
  "quality": "high",
  "latency": "normal",
  "max_candidates": 2
}
```
保存返回的 `decision_id`（即 `candidate_plan_id`）及 `candidates` 列表（例如 Rank 1 `qwen3-coder-next`、Rank 2 `gpt-5.4`）。

### Step 2: 独立运行 Candidate A 并上报 `ATTEMPT_COMPLETED`
在干净的 Git 基线（`base_commit`）工作区或独立分支上，仅使用 Candidate A 完成编码、单测、回归与浏览器验收（**严禁混用其他模型修补 Candidate A 的代码**），然后调用 `POST /api/coding/outcome`：

```json
{
  "outcome_stage": "ATTEMPT_COMPLETED",
  "consumer": "vtip-ai-sidecar",
  "coding_client": "claude-code",
  "repo_id": "vtip-ai-sidecar",
  "repo_stack": "python_fastapi",
  "task_id": "SIDECAR-DEV-022",
  "task_profile": "feature_implementation",
  "agent_run_id": "run-sidecar-022-bakeoff-01",
  "coding_attempt_id": "attempt-sidecar-022-cand-a",
  "decision_id": "<frozen_decision_id>",
  "candidate_rank": 1,
  "logical_model_id": "qwen3-coder-next",
  "selected_model_id": "local-cpa::qwen3-coder-next",
  "channel": "local-cpa",
  "resource_id": "local-cpa",
  "base_commit": "<git_base_sha>",
  "patch_created": true,
  "patch_parse_success": true,
  "patch_apply_success": true,
  "patch_hash": "sha256:<hex_digest_of_diff>",
  "files_changed_count": 3,
  "lines_added": 84,
  "lines_deleted": 12,
  "syntax_check_run": true,
  "syntax_check_pass": true,
  "targeted_tests_run": 6,
  "targeted_tests_passed": 6,
  "targeted_tests_failed": 0,
  "core_regression_run": 42,
  "core_regression_passed": 42,
  "core_regression_failed": 0,
  "browser_acceptance_run": true,
  "browser_acceptance_pass": true,
  "acceptance_gates_total": 5,
  "acceptance_gates_passed": 5,
  "task_outcome": "COMPLETED",
  "wall_time_ms": 48200,
  "model_call_count": 4,
  "tool_call_count": 7,
  "repair_rounds": 1
}
```

### Step 3: 独立运行 Candidate B 并上报 `ATTEMPT_COMPLETED`
重置回完全相同的 `base_commit`（或独立 worktree），仅使用 Candidate B 独立执行同一任务，并以 `coding_attempt_id: "attempt-sidecar-022-cand-b"`、`candidate_rank: 2` 上报 `ATTEMPT_COMPLETED`。

### Step 4: 选定最终合入方案并上报 `INTEGRATION_DECISION`
对比 Candidate A 与 Candidate B 的客观验证结果后，对两个 `coding_attempt_id` 分别提交 `INTEGRATION_DECISION`：

- 对被选入主分支的获胜候选：
```json
{
  "outcome_stage": "INTEGRATION_DECISION",
  "consumer": "vtip-ai-sidecar",
  "repo_id": "vtip-ai-sidecar",
  "task_id": "SIDECAR-DEV-022",
  "agent_run_id": "run-sidecar-022-bakeoff-01",
  "coding_attempt_id": "attempt-sidecar-022-cand-a",
  "integration_selected": true,
  "commit_created": true,
  "result_commit": "<winning_git_commit_sha>",
  "git_clean": true,
  "acceptance_pass": true,
  "task_complete": true
}
```

- 对同样完成任务但未被最终合入的候选（**注意：`task_outcome=COMPLETED` 且 `integration_selected=false` 是完全合法的正向结果，绝不会扣减其完成率或健康度**）：
```json
{
  "outcome_stage": "INTEGRATION_DECISION",
  "consumer": "vtip-ai-sidecar",
  "repo_id": "vtip-ai-sidecar",
  "task_id": "SIDECAR-DEV-022",
  "agent_run_id": "run-sidecar-022-bakeoff-01",
  "coding_attempt_id": "attempt-sidecar-022-cand-b",
  "integration_selected": false,
  "acceptance_pass": true,
  "task_complete": true
}
```

---

## 4. 严格红线与非目标 (`NON_GOALS`)

1. **禁止上传源码或完整补丁 (`No full patch upload`)**：仅允许上传 `patch_hash`（SHA-256）及行数/文件数统计，严禁在请求中包含 `patch`、`diff`、`source_code`、`prompt` 等字段（服务端将返回 `422 Unprocessable Entity`）。
2. **禁止伪造上游身份 (`No fake upstream identities`)**：未经真实校验的 `upstream_model_id`、`upstream_provider`、`result_commit` 必须省略或传 `null`，严禁传入 `"unknown"`、`"未验证"`、`"N/A"`、`"not_verified"`。
3. **首次 Bake-Off 期间保持影子观测 (`No automatic routing score bias during first bake-off`)**：Hub 当前默认运行于 `CODING_OUTCOME_RANKING_MODE=SHADOW_ONLY`，确保 Candidate A 的上报不会中途污染 Candidate B 的路由分数或冻结方案。
