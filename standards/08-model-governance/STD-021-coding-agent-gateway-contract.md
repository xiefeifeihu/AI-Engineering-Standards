# STD-021: Coding Agent Gateway Contract (编程智能体网关契约)

```text
STANDARD_ID=STD-021
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=AI-Hub 编程智能体网关 (Execution Plane Gateway) 及下游所有编程代理 (Claude Code, Antigravity, OpenCode, Cline, Continue, Aider 等)
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-28
SCHEMA_REF=schemas/coding-gateway.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 架构定位：从控制平面延伸至执行平面 (Control Plane to Execution Plane)

此前 AI-Hub 通过 `STD-008` (模型注册)、`STD-009` (候选方案路由推荐) 和 `STD-010` (调用反馈) 构成了控制平面。
但专业编程智能体（Claude Code, OpenCode, Cline 等）通常仅支持配置单一 LLM 端点。
本规范确立 **AI-Hub Coding Gateway (编程智能体网关)** 作为统一执行平面接入点：
1. **单一接入端点**：编程智能体仅需配置 Hub Gateway URL 与虚拟模型名称。
2. **多协议兼容**：原生兼容 Anthropic Messages API 与 OpenAI Chat Completions API。
3. **零密钥与信息屏蔽**：智能体**严禁**持有任何上游提供商密钥，亦无需感知物理模型名称或多通道拓扑。
4. **自主容灾与熔断**：首字流式输出前由网关自动透明重试与故障转移，屏蔽瞬态网络抖动与配额耗尽。

---

## 2. 虚拟模型与路由画像 (Virtual Models & Routing Profiles)

网关对外暴露 4 组规范虚拟模型别名：

| 虚拟模型名称 | 内部画像 | 决策逻辑与通道偏好 | 典型适用场景 |
| :--- | :--- | :--- | :--- |
| `hub-code-auto` | `auto` | 智能自适应路由：`Local CPA` -> `Cloud CPA` -> `Ollama`。依据编程能力分、P50/P95延迟、历史成功率、配额状态与熔断状态综合权衡。 | Claude Code / Cline 日常编程、特性开发与综合重构 |
| `hub-code-fast` | `fast` | 极速低延迟优先：优先选用 P50 延迟低、高并发且健康的编程模型。 | 行内补全、快速 Lint 修复、小函数生成 |
| `hub-code-deep` | `deep` | 深度推理与架构设计：倾向于具备长思维链 (CoT) 与超强架构推导能力的高智力模型 (如 Claude 3.7 Sonnet Thinking / DeepSeek-R1 / Qwen Coder)。 | 跨仓库架构重构、疑难 Bug 根因诊断、安全审计 |
| `hub-code-local` | `local` | 本地离线优先：强制限制仅使用宿主本地 Ollama 或离线 Local CPA 通道，绝不上云。 | 隔离网络环境、无公网依赖或高敏私有代码调试 |

网关 **MUST** 在 `GET /v1/models` 端点中公开声明上述虚拟模型。

---

## 3. 协议支持规范 (Dual Protocol Support)

### 3.1 Anthropic-Compatible Messages API
- **端点路径**：`POST /v1/messages`
- **目标客户端**：Claude Code、支持 Anthropic SDK 的智能体。
- **流式格式**：严格遵循 Anthropic SSE 事件流水线：
  - `message_start` -> `content_block_start` -> `content_block_delta` -> `content_block_stop` -> `message_delta` -> `message_stop`。
- **工具调用 (Tool Use)**：完整映射 `tools` 声明、`tool_use` 内容块解析以及 `tool_result` 轮次拼装。

### 3.2 OpenAI-Compatible Chat Completions API
- **端点路径**：`POST /v1/chat/completions`
- **目标客户端**：OpenCode, Cline, Continue, Aider 及通用 OpenAI 兼容代理。
- **流式格式**：标准 SSE `data: {"choices": [{"delta": {...}}]}

` 并以 `data: [DONE]

` 终结。
- **工具调用**：支持 `tools`、`tool_choice` 及增量 `tool_calls`。

---

## 4. 故障转移与熔断语义 (Failover Semantics)

### 4.1 首字前透明故障转移 (Failover BEFORE First Streamed Token)
1. 客户端发起请求后，网关依据 Candidate Plan 依次尝试候选通道与模型。
2. 触发故障转移的标准错误类型（严格映射 `STD-010` 7 类规范错误）：
   - `NETWORK_ERROR` (连接重置、DNS 失败)
   - `TIMEOUT` (握手或首字等待超时)
   - `RATE_LIMITED` (HTTP 429)
   - `QUOTA_EXHAUSTED` (上游配额耗尽)
   - `MODEL_UNAVAILABLE` (HTTP 503 / 502 模型离线)
   - `PROVIDER_ERROR` (提供商内部 500 异常)
   - `AUTH_FAILED` (符合自动切换条件的凭据/权限异常)
3. 发生上述故障且**尚未向客户端发送任何数据包（首字流前）**时，网关 **MUST** 静默尝试下一个 Candidate。
4. 每次故障均由网关自动向 Model Governance 记录降权/熔断惩罚，并记录 Audit Event。

### 4.2 首字流后严禁混串拼接 (NO Output Concatenation After First Token)
1. 一旦首字（First Token）已经通过 SSE 发送给客户端，网关 **MUST NOT** 切换至另一模型并将输出混拼在一起。
2. 混拼会导致上下文断裂、代码语法破损及思维链错乱。
3. 若首字输出后连接断开或上游异常，网关 **MUST** 按照协议标准发送带错误详情的终止事件或切断连接，由客户端执行完整轮次重试（Turn-level Retry）。

### 4.3 熔断器与冷却旁路 (Circuit Breakers & Cooldown)
1. 连续失败达到阈值的模型立即进入 `QUARANTINED` 状态并开启冷却计时器（默认 60s）。
2. 在冷却期内，Candidate Plan 计算 **MUST** 旁路该模型，**严禁**让已知故障模型每次都导致超时等待。

---

## 5. 会话软粘性 (Session Stickiness)

1. 智能体编写复杂代码时通常涉及多轮对话。网关支持基于 `session_id`（通过 `X-Session-Id` 请求头或首轮对话特征提取）的软粘性。
2. 在会话生命周期内，若当前选择的模型保持 `HEALTHY` 且延迟与错误率受控，后续请求 **SHOULD** 持续沿用该模型，以保障上下文理解连贯性。
3. 发生以下情况之一时强制解绑粘性：
   - 当前模型出现健康恶化、限流或配额耗尽；
   - 响应延迟显著超过阈值；
   - 客户端显式请求不同的虚拟模型（如从 `hub-code-auto` 切换至 `hub-code-deep`）。
4. 网关 **MUST** 在 HTTP 响应头中注入只读诊断指标：
   - `X-Hub-Decision-Id`: 决策追踪 ID
   - `X-Hub-Selected-Model`: 实际执行的底层模型
   - `X-Hub-Channel`: 实际命中的通道
   - `X-Hub-Attempts`: 尝试总次数
   - `X-Hub-Session-Id`: 会话粘性 ID
   - `X-Hub-Failover-Count`: 故障转移次数

---

## 6. 编程场景治理与反馈契约 (Coding Feedback Contract)

网关与消费者遵循通用反馈契约扩展：

1. **基础度量指标 (Base Metrics)**：
   - `request_success` (布尔值)
   - `ttft_ms` (首字延迟毫秒数)
   - `total_latency_ms` (全量耗时毫秒数)
   - `token_input` 与 `token_output` (Token 消耗量)
   - `tool_call_success` (工具调用执行成败)
   - `retry_count` 与 `fallback_count` (重试与切换次数)
2. **高级编程质量指标预留 (Reserved Fields - 仅在实际具备时上报)**：
   - `patch_applied`: 代码补丁是否成功应用
   - `tests_passed`: 工程单元测试是否通过
   - `lint_passed`: 语法/规范静态检查是否通过
   - `task_completed`: 编程目标是否最终完成
   **严禁虚构上述高级指标**，未采集时必须留空或为 `null`。

---

## 7. 凭据边界与零密钥安全 (Credential Boundary)

1. 编程智能体在配置 `ANTHROPIC_BASE_URL` 或 OpenAI `base_url` 时，仅使用本地网关凭据或留空，**严禁**配置云端提供商真实密钥。
2. Hub 依据内部 `credential_reference` 解析上游密钥（存储于机器机密存储区或内存），绝不在请求链路、响应头、前端 DOM、日志或交付归档包中暴露任何提供商明文密钥。
