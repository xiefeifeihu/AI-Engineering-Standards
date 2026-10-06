# STD-024: Model Ops Autopilot Governance Contract (模型运维自治与影子治理契约规范)

```text
STANDARD_ID=STD-024
VERSION=1.6.0
STATUS=ACTIVE
SCOPE=Model Ops Autopilot 基础架构：模型自发现、能力分级验证、生命周期状态机与影子治理契约
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-06
RELATED_STANDARDS=STD-008, STD-009, STD-010, STD-018, STD-019, STD-020, STD-021, STD-022, STD-023
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 架构目标与双边界所有权原则 (Architectural Goal & Hard Ownership Boundaries)

AI-Engineering-Hub 的演进目标是从单纯的“模型路由网关（Model Router）”迈向“模型运行时控制平面与模型运维自治引擎（Model Runtime Control Plane + Model Ops Autopilot）”，包含四大核心能力：
1. **SELF-DISCOVERY（模型自发现）**：自动感知开发机与局域网内可用的 AI 模型与算力资源。
2. **SELF-RECOVERY（故障自愈）**：基于真实技术证据，自动对发生熔断或临时受限的模型执行周期探测与安全纳管恢复。
3. **SELF-LEARNING（能力自学习）**：从真实运行时结果与多维测试事实中沉淀模型能力指标。
4. **SELF-OPTIMIZATION（自治优化）**：基于累积的可信证据，动态实施挑战者比选、影子流量评估、晋升与降级推荐。

### 1.1 R1 阶段定位 (Foundation Only)
R1 阶段 **MUST** 仅实现 Autopilot 的基础架构（Foundation Only）。
- **MUST NOT** 赋予 Hub 无限制变更宿主与 Owner 基础设施的权限。
- **MUST NOT** 跨界接管外部工程的所有权。

### 1.2 严格所有权边界 (Ownership Boundaries)
- **AI-Engineering-Hub 拥有（Hub Owns）**：
  - 模型自发现观测数据（Discovery Catalog）
  - 模型多维能力档案注册（Model Capability Registry）
  - 低成本分级能力验证探针及调度（Capability Verification & Probe Scheduler）
  - 确定性生命周期状态机（Lifecycle State Machine）
  - 运行期观察事实与状态迁移证明（Observations & Transitions Provenance）
  - 挑战者与影子候选池准入管理（Challenger & Shadow Eligibility）
  - 晋升/降级可解释建议（Explainable Promotion / Demotion Recommendations）
  - 模型与消费方运行时记忆（Model Runtime Memory）
  - 未来 Owner 动作请求封装（Owner Action Requests Envelope）
- **AI-KB 保持资源唯一所有权（AI-KB Remains Resource Owner）**：
  - Local CPA 本地中继生命周期与容器配置
  - Cloud CPA 云端中继生命周期与 SSH 隧道
  - Ollama 服务生命周期与系统资源
  - Docker 容器、卷与网络编排
  - 模型文件物理下载（`ollama pull`）与删除
  - CPA 版本升级与回滚
  - 宿主服务守护与机器级凭据
- **R1 阶段绝对禁令（Hub Invariants in R1）**：
  - Hub **MUST NOT** 执行 `ollama pull` 下载模型。
  - Hub **MUST NOT** 删除或卸载已存在的模型。
  - Hub **MUST NOT** 修改 AI-KB 目录下的配置文件、Docker Compose 或运行时清单。
  - Hub **MUST NOT** 变更生产环境凭据或密钥。
  - Hub **MUST NOT** 通过 SSH 登录远端 VPS 执行基础设施变更。
  - Sidecar、VTIP Platform 及 AI-KB 工程源码与配置 **MUST** 保持 0 修改。

---

## 2. 确定性生命周期状态机 (Deterministic Lifecycle State Machine)

平台内的模型实例 **MUST** 遵循确定性生命周期状态机。状态迁移必须基于可信证据，禁止跳跃与模糊判断。

### 2.1 规范生命周期状态 (Canonical States)
| 状态枚举 | 状态含义与操作语义 | 准入/退出前置条件 |
| :--- | :--- | :--- |
| `DISCOVERED` | 已在资源中发现，但能力与可用性尚未验证 | 探针仅在 L0 目录发现阶段；不可用于路由选择 |
| `PROBE_VERIFIED` | 最低语义/推理探针（L1）通过，技术可用性就绪 | 成功完成轻量级语义问答，证明接口非虚假上报 |
| `CHALLENGER` | 具备特定任务能力，获准进入受控挑战试验候选池 | 符合任务基线要求，可作为备选参与 Bake-Off 或测试 |
| `SHADOW` | 获准接收非生产流量或镜像影子流量进行深度评估 | 具备多轮或结构化能力证明，处于试运行观察期 |
| `PRODUCTION_ELIGIBLE` | 经过充分多样本验证，获准进入正常生产主路由 | 样本量、成功率、延迟与质量指标全部达标 |
| `TEMP_UNAVAILABLE` | 遭遇临时性故障（网络抖动、配额耗尽、限流排队） | 触发熔断保护，进入退避等待状态，由自愈调度器探测 |
| `QUARANTINED` | 遭遇连续技术性崩溃或严重协议错误，被安全隔离 | 连续失败超阈值；需延长退避等待深度验证 |
| `REJECTED` | 在当前任务或消费上下文中被判定为确定性不适用 | 如代码模型完全不支持工具调用且协议解析崩溃 |

### 2.2 防伪与语义辨析定则 (Non-Equivalence Invariants)
- **定则 1：HTTP 200 != PROBE_VERIFIED**。仅凭 HTTP 200 状态码只能证明网络通道可达（L0），绝不能等同于模型具备正确的语义推理或指令跟随能力。
- **定则 2：AGENT_COMPATIBLE != PRODUCTION_ELIGIBLE**。通过单次 Claude Code 工具协议探测仅能证明具备协议结构兼容性，绝不能直接赋予全量生产主路由资格。
- **定则 3：单次编码任务成功 != 通用编码能力**。在特定仓库完成一次单测修复，绝不能过度推断该模型在其他工程栈中通用可用。
- **定则 4：QUOTA_EXHAUSTED 为暂时可用性状态**。遇到供应商配额耗尽（429 / Insufficient Quota）时，**MUST** 标记为 `TEMP_UNAVAILABLE` 并记录退避，**MUST NOT** 判定为 `REJECTED` 或永久模型缺陷。

### 2.3 状态迁移审计要素 (Auditable State Transitions)
每次模型状态发生迁移时，Hub **MUST** 持久化一条不可篡改的审计记录：
```json
{
  "record_type": "LIFECYCLE_TRANSITION",
  "transition_id": "trans-20261006-001",
  "logical_model_id": "qwen3-coder-plus",
  "channel": "local-cpa",
  "from_state": "DISCOVERED",
  "to_state": "PROBE_VERIFIED",
  "reason_code": "PROBE_L1_INFERENCE_PASS",
  "evidence_type": "PROBE_RUN",
  "evidence_ref": "probe-l1-1791234567",
  "observed_at": "2026-10-06T12:00:00Z",
  "algorithm_version": "v0.11.0"
}
```

---

## 3. 异步模型自发现规范 (Asynchronous Model Self-Discovery)

### 3.1 发现源与权威端点 (Discovery Sources)
Hub **MUST** 通过机器级权威端点配置或 Endpoint Registry 异步发现以下三类资源：
1. **Local CPA**（宿主端口 18117，端点 `/v1/models`）
2. **Cloud CPA**（宿主端口 18317，端点 `/v1/models`）
3. **Ollama**（宿主端口 11434，端点 `/api/tags`）
- **MUST NOT** 硬编码端点地址；若存在 Endpoint Registry 或 Owner 清单，以注册表为唯一事实源。

### 3.2 发现事实要素与非敏感元数据
自发现收集的元数据 **MUST** 包含：
- `logical_model_id`（逻辑模型标识）
- `selected_model_id`（通道限定完整标识）
- `upstream_model_id`（真实上游模型名，不可推断时为 null）
- `resource_id` / `channel`（资源标识与通道标识）
- `owner`（资源归属，如 AI-KB）
- `upstream_provider`（真实供应商，不可推断时为 null，**严禁猜测**）
- `provenance_status`（如 `LOCAL_RUNTIME`、`CLOUD_TUNNEL`）
- `first_seen_at` / `last_seen_at`（首次与最近发现时间）
- `discovery_generation`（发现轮次世代号）
- `availability`（可用状态：`AVAILABLE`, `DISAPPEARED`, `AUTH_REQUIRED`, `STOPPED`, `ERROR`）
- `model_fingerprint`（模型权重指纹或哈希）
- `lifecycle_state`（生命周期状态）

### 3.3 零阻塞路由准则 (Critical Path Isolation)
- 模型发现与网络扫描 **MUST** 纯后台异步执行。
- `POST /api/model/select`、Coding Agent Gateway、Sidecar 路由与 AI-KB 模型匹配 **MUST NOT** 在关键路径上同步扫描 CPA 目录、Ollama 目录或执行远程探测。
- 路由逻辑 **MUST** 仅消费内存快照或预计算缓存。
- 路由决策延迟指标 **MUST** 保持 P95 <= 50ms。

---

## 4. 模型多维能力档案与分级低成本验证 (Capability Profile & Layered Probes)

### 4.1 能力档案维度 (Capability Dimensions)
模型能力档案包含以下正交维度：
- `text_generation`（文本生成与基础指令跟随）
- `reasoning`（深度思考与逻辑推演）
- `coding`（编程语法生成与代码重构）
- `agent_tool_use`（单轮工具声明与参数调用）
- `agent_loop`（多轮确定性文件操作工具闭环收敛）
- `structured_output`（严格 JSON Schema 输出）
- `embedding`（向量表征）
- `vision`（多模态视觉理解）
- `long_context`（长上下文检索与综合）

每个维度状态分为：`UNKNOWN`（未知）、`DECLARED`（静态声明）、`PROBE_VERIFIED`（真实探针验证）、`UNSUPPORTED`（确定不支持）。

### 4.2 分级低成本验证阶梯 (Verification Hierarchy)
- **L0 DISCOVERY（目录存在）**：接口返回模型条目，证明资源被暴露。
- **L1 INFERENCE（轻量推理）**：消耗不超过 30 Token 的极简语义探针，验证连通性与基础生成。
- **L2 STRUCTURED / TOOL（结构化与工具契约）**：验证工具描述注入与合法工具调用块返回。
- **L3 AGENT LOOP（智能体闭环）**：专为 Claude Code / Coding Agent 设计的 2 轮本地沙箱虚拟文件读写测试。

### 4.3 探针流量与业务流量严格隔离 (Probe Isolation)
Autopilot 产生的所有探测调用均为**治理观察数据（Governance Observations）**：
- **MUST** 携带 `execution_purpose = RECOVERY_PROBE | CAPABILITY_PROBE | SHADOW_EVALUATION`。
- **MUST NOT** 虚增 Layer 1 用户真实调用成功计数（Zero Layer 1 Double-Counting）。
- **MUST NOT** 虚增 Layer 2 Coding Outcome 的样本计数（Zero Coding Outcome Sample Inflation）。
- **MUST NOT** 干扰历史衰减商业质量记忆。

---

## 5. 影子治理与可解释推荐机制 (Shadow Governance & Explainable Recommendations)

### 5.1 R1 影子唯一模式 (Shadow-Only Enforcement Mode)
在 R1 阶段，Autopilot 的治理执行模式 **MUST** 强制为：
```text
AUTOPILOT_ENFORCEMENT_MODE=SHADOW_ONLY
```
- Autopilot **MAY** 发现、验证、分类、记录状态迁移并计算推荐意见。
- Autopilot **MUST NOT** 自动将新发现的模型直接插入生产正式生效的路由池中。
- 现有生产路由策略保持绝对权威。

### 5.2 挑战者进阶流 (Challenger Progression Flow)
新模型遵循保守演进链路：
$$	ext{DISCOVERED} \longrightarrow 	ext{PROBE\_VERIFIED} \longrightarrow 	ext{CHALLENGER} \longrightarrow 	ext{SHADOW}$$
- 仅当累积样本充足、指标全面达标时，Autopilot 才会输出 `PROMOTION_RECOMMENDED=true`。
- 严禁单次或少数几次样本直接触发生产晋升推荐。

### 5.3 可解释治理推荐 (Explainable Recommendations)
推荐结果 **MUST** 包含结构化的组成分解原因（`component_reasons`），禁止输出单一黑盒分数值：
```json
{
  "recommendation_id": "rec-20261006-001",
  "logical_model_id": "qwen3-coder-plus",
  "channel": "local-cpa",
  "consumer": "claude-code",
  "task_family": "coding",
  "capability": "agent_loop",
  "enforcement_mode": "SHADOW_ONLY",
  "current_state": "CHALLENGER",
  "recommended_state": "SHADOW",
  "promotion_recommended": true,
  "demotion_recommended": false,
  "confidence": 0.95,
  "sample_count": 25,
  "component_reasons": [
    {
      "metric_name": "agent_loop_pass",
      "threshold": true,
      "observed_value": true,
      "pass": true,
      "reason_cn": "Claude Code 2轮工具闭环验证通过"
    },
    {
      "metric_name": "recent_success_rate",
      "threshold": 0.95,
      "observed_value": 0.98,
      "pass": true,
      "reason_cn": "近期请求成功率 98% (高于阈值 95%)"
    },
    {
      "metric_name": "latency_p95",
      "threshold": 2500.0,
      "observed_value": 1420.0,
      "pass": true,
      "reason_cn": "P95 延迟 1420ms (低于上限 2500ms)"
    }
  ]
}
```

---

## 6. 未来 Owner 动作契约信封 (Future Owner Action Envelope)

为后续 AI-Hub-014-R2 自动化运维做好架构铺垫，本标准冻结未来 Hub 与 AI-KB 间 Owner 动作请求的标准信封契约。
- **R1 阶段冻结声明**：
  ```text
  OWNER_ACTION_CONTRACT_DEFINED=true
  OWNER_ACTION_EXECUTION_IMPLEMENTED=false
  ```
- 动作类型包括：`OLLAMA_PULL_MODEL`、`OLLAMA_REMOVE_MODEL`、`CPA_CANARY_UPGRADE`、`CPA_RESTART`、`CPA_ROLLBACK`。
- 在 R1 中，Hub 仅可模拟生成请求对象并进行合法性校验，**严禁向任何系统发出执行指令**。

---

## 7. 安全防护与测试隔离不变式 (Security & Test Isolation Invariants)

### 7.1 绝对零敏感数据持久化 (Zero-Secrets & Zero-Content Guardrails)
Model Ops 所有持久化表与传输数据中：
- **MUST NOT** 存储任何 API Key、Token、密码或凭据原文。
- **MUST NOT** 存储任何用户的 Prompt 文本、模型生成的 Response 文本或源文件补丁代码。
- **MUST NOT** 存储任何私有文件内容或知识库文档原文。

### 7.2 测试/生产数据隔离不变式 (Test/Production State Isolation)
根据 STD-021 / STD-023 / AI-Hub-013-R1.5.1 铁律：
- 任何单元测试、集成测试或验收测试运行期间，**MUST** 注入独立的临时测试数据库。
- 运行测试前后的生产环境数据库检查必须满足：
  ```text
  LIVE_SYNTHETIC_ROWS_BEFORE_TESTS=0
  LIVE_SYNTHETIC_ROWS_AFTER_TESTS=0
  TEST_MODEL_OPS_ROWS_IN_PRODUCTION=0
  ```
