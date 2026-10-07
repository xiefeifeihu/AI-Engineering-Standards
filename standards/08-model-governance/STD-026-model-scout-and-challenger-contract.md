# STD-026: Model Scout and Challenger Contract (模型候选侦察、公正挑战与学习契约规范)

```text
STANDARD_ID=STD-026
VERSION=1.8.0
STATUS=ACTIVE
SCOPE=Model Ops Autopilot 候选模型侦察源注册、候选可用性分级、公正挑战战役、冻结公平性规范、微基准测试套件、挑战记忆与衰减、帕累托比选、置信度与晋升建议契约
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-07
RELATED_STANDARDS=STD-008, STD-009, STD-010, STD-019, STD-020, STD-021, STD-022, STD-023, STD-024, STD-025
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 架构目标与双边界自治原则 (Architectural Goal & Self-Learning Boundary)

在 AI 平台架构演进中，Model Ops 运维自治进入 R3 阶段（模型侦察与挑战者自动化）。系统核心目标**不是**评选出一个静态的“全局最高分模型”，而是：
> **“针对特定的消费方（Consumer）+ 任务族（Task Family）+ 能力档案（Capability Profile），持续发现可信挑战者，实施确定性公平影子挑战，沉淀真实多维证据，并可解释地阐明其相比现任冠军（Incumbent Champion）的优劣与权衡。”**

### 1.1 严格安全边界 (Hard Safety Boundaries)
- Autopilot 执行模式在 R3 **MUST** 强制保持为影子唯一模式：
  ```text
  AUTOPILOT_ENFORCEMENT_MODE=SHADOW_ONLY
  ```
- **R3 绝对禁令（Hub Invariants in R3）**：
  - Hub **MUST NOT** 自动替换当前生产生效的 Champion 模型。
  - Hub **MUST NOT** 自动修改线上实时生产路由权重（Live Routing Weights）。
  - Hub **MUST NOT** 依据单次或少数样本直接将模型晋升至生产主路由。
  - Hub **MUST NOT** 自动批准任何 STD-025 Owner Action 请求（所有资源动作强制停留于 `APPROVAL_REQUIRED`）。
  - Hub **MUST NOT** 未经审批下载或安装任意模型文件。
  - Hub **MUST NOT** 自动删除或卸载已存在的 Ollama 模型（`OLLAMA_REMOVE_MODEL` 严格禁用）。
  - Hub **MUST NOT** 自动升级 CPA 容器或修改机器级基础设施。
  - Hub **MUST NOT** 绕过 R2 审批网关或修改 Sidecar / AI-KB 业务流水线。
- **R3 授权范畴（Permitted Autonomous Actions）**：
  - Hub **MAY** 自动侦察（Discover）、初筛（Shortlist）、探针验证（Probe）、公平挑战（Challenge）、多维比选（Compare）、沉淀证据（Learn）、输出建议（Recommend）以及生成处于待审批状态的资源变更动作请求（`APPROVAL_REQUIRED Owner Action Requests`）。
  - **核心定则**：`RECOMMENDATION != EXECUTION`；`CHALLENGE_WINNER != AUTOMATIC_PRODUCTION_PROMOTION`。

### 1.2 自学习边界 (Self-Learning Boundary)
- R3 所谓的“学习（Learning）”严格限定为：**持久化与聚合真实的结构化评估度量数据（Structured Metrics），并将其用于优化后续挑战者准入筛选与可解释推荐。**
- 系统 **MUST NOT** 进行任何神经网络模型微调、权重训练或保存用户 Prompt/文档用于训练。

---

## 2. 候选模型侦察源注册表 (Scout Source Registry)

Hub **MUST** 建立规范的侦察源注册表（Scout Source Registry），统一管理多渠道模型目录发现。

### 2.1 规范数据源分类 (Source Classes)
1. `ACTIVE_RUNTIME_CATALOG`：本地活跃运行时目录（如 Local CPA、Cloud CPA、Ollama 已安装模型）。
2. `OWNER_CANDIDATE_CATALOG`：资源所有者（如 AI-KB）在清单或配置中声明的候选目录。
3. `PROVIDER_DECLARED_CATALOG`：上游供应商明确声明且通过可信凭据代理暴露的官方模型目录。
4. `OPTIONAL_PUBLIC_METADATA_CATALOG`：公开合规元数据目录（如模型库索引）。严禁无节制爬取网页或调用未文档化私有接口。

### 2.2 侦察源事实要素与零凭据原则
每个 Scout Source **MUST** 包含以下元数据：
- `source_id`：全局唯一数据源标识。
- `source_type`：枚举类（上述四类之一）。
- `owner`：归属方标识（如 `AI-KB`、`PLATFORM`）。
- `provider`：可信供应商标识（若不可判定为 null，严禁猜测）。
- `trust_level`：可信级别（`AUTHORITATIVE_RUNTIME`, `VERIFIED_OWNER`, `UNVERIFIED_PUBLIC`）。
- `endpoint_ref`：逻辑端点引用（若适用）。
- `credential_ref`：逻辑凭据引用（严禁明文凭据）。
- `enabled`：启用状态布尔值。
- `discovery_interval_seconds`：周期轮询间隔（秒）。
- `last_success_at` / `last_error`：最近成功时间与错误信息。
- `catalog_generation`：目录抓取世代递增序号。
- **零敏感原则**：侦察源中 **MUST NOT** 存储任何 API Key、密码、Token 或授权头部明文。

### 2.3 来源故障非单点故障原则 (Non-SPOF Invariant)
- 当某一侦察源（如 Cloud CPA 隧道抖动或公共元数据源不可用）发生异常时，Hub **MUST** 记录错误并进入退避（Backoff），**MUST NOT** 引起 Hub 服务不可用或阻塞模型请求路由。
- Hub **MUST** 降级复用上一代有效快照继续执行安全比选。

---

## 3. 候选模型可用性分级与零信任归属 (Candidate Availability & Zero-Trust Provenance)

### 3.1 候选可用性三级分类 (Candidate Availability Classes)
发现的模型候选者 **MUST** 显式标记其物理可用性状态：
1. `AVAILABLE_NOW`（即时可用）：已通过已验证的运行时通道（如已启动的 Local CPA、已加载的 Ollama）完全可调用。
2. `OWNER_ACTION_REQUIRED`（需资源动作）：当前尚未就绪可调用，但存在规范且已实现的 STD-025 Owner Action 可以使其就绪（例如 Owner 声明的 Ollama 候选模型，可通过 `OLLAMA_PULL_MODEL` 完成拉取）。
3. `METADATA_ONLY`（仅元数据存在）：仅存在于外部公开目录或概念设计中，当前无规范受控的自动化拉取/安装路径。
- **铁律**：`METADATA_ONLY` 候选模型 **MUST NOT** 作为可调用对象参与任何实际技术挑战！

### 3.2 零信任模型供应商溯源 (Zero-Trust Model Provenance)
- 严禁通过模型名称前缀或子串推断供应商（如模型名称包含 "gemini" 绝不等于真实供应商为 Google；包含 "qwen" 绝不等于真实供应商为 Alibaba；包含 "claude" 绝不等于真实供应商为 Anthropic）。
- 供应商归属 **MUST** 仅来源于：权威运行时元数据、Owner Manifest、供应商目录权威映射或经校验的数据源元数据。否则 `provider = null`，标记为 `UNVERIFIED`。

---

## 4. 侦察战役与冠军/挑战者语义 (Scout Campaign & Champion-Challenger Semantics)

### 4.1 战役作用域约束 (Scoped Campaign Identity)
挑战比选 **MUST NOT** 构建跨领域通用跑分天梯榜。每次侦察战役（Scout Campaign）**MUST** 严格绑定特定业务上下文：
- `campaign_id`：战役全局唯一标识。
- `consumer`：消费方应用（如 `claude-code`, `ai-kb`, `vtip-ai-sidecar`）。
- `task_family`：任务族（如 `coding_agent`, `knowledge_distillation`, `structured_report_generation`）。
- `capability_profile`：能力档案要求（如 `agent_coding_high_quality`）。

### 4.2 冠军语义规范 (Champion Semantics)
- **定义**：Champion（现任冠军）指在特定消费方 + 任务族 + 能力档案上下文下的**当前对比基准锚点（Comparison Anchor）**，绝不代表“全局最佳模型”。
- Champion 可以是：当前生效的生产路由赢家（`PRODUCTION_ROUTE_WINNER`）、历史最高置信度标杆模型（`HISTORICAL_LEADER`）或平台显式固化的基准线（`PLATFORM_PINNED_BASELINE`）。
- 战役一旦创建，Champion 身份与快照 **MUST** 冻结，**MUST NOT** 在战役执行中途静默漂移。

### 4.3 挑战者准入硬门槛 (Challenger Selection Hard Gates)
候选模型进入可挑战候选池前 **MUST** 通过硬门槛准入校验：
1. 物理可用性：必须为 `AVAILABLE_NOW`。
2. 隔离状态：绝不能处于 `QUARANTINED` 或 `REJECTED` 状态。
3. 能力档案：必须具备任务族要求的核心能力（如经 L1/L2 验证）。
4. 协议兼容性：针对 Coding Agent / Claude Code，`AGENT_COMPATIBLE` 是进行全量智能体挑战的**刚性前置条件**。状态为 `AGENT_UNKNOWN` 或 `AGENT_INCOMPATIBLE` 的模型 **MUST NOT** 执行智能体挑战。
5. 配额与退避状态：未处于活跃的 429 退避或熔断期。

---

## 5. 公平性规范与挑战套件注册表 (Fairness Specification & Challenge Suites)

### 5.1 生产策略与挑战公平性解耦定则 (Separation of Policy and Fairness)
- **铁律**：**生产路由策略偏好绝不得扭曲挑战技术测量的客观性**。
- 例如：生产环境中对 Qwen 模型存在 `QWEN_LAST_RESORT`（-40分）的后备兜底惩罚策略。但在 Scout 挑战中，**MUST** 记录 Qwen 的纯技术客观表现（`RAW_CHALLENGE_CAPABILITY`），绝不得将生产惩罚减扣到挑战测量中。
- 最终比选结论与推荐可同时说明客观技术能力与平台生产合规策略。

### 5.2 冻结公平性规范 (Frozen Fairness Specification)
战役内的所有候选模型（包括 Champion 与 Challengers）**MUST** 在完全相同的条件下执行评测：
- 相同的测试用例、相同的提示词版本、相同的工具定义、相同的验收条件；
- 相同的超时限制、相同的重试预算、相同的隔离执行沙箱与固化的基础测试夹具；
- 相同的最大 Token 预算、相同的评测器版本、相同的采样温度（支持时为确定性输出）。
- 每次战役 **MUST** 计算并持久化 `fairness_spec_hash`，确保全量对齐。

### 5.3 挑战测试套件分类 (Challenge Suite Registry)
1. `TECHNICAL_MICROBENCH`：通用技术能力微基准（如结构化输出合规性、基础推理）。由 Hub 拥有并管理。
2. `AGENT_MICROBENCH`：智能体编程闭环微基准（如沙箱文件读写、工具调用收敛、单测修复验证）。由 Hub 拥有并执行于独立临时沙箱。
3. `CONSUMER_BUSINESS_EVALUATION`：特定业务质量评估。
   - **所有权原则**：Hub **MUST NOT** 虚构或篡改业务事实！AI-KB 独家拥有知识提炼质量评测与黄金基准；Sidecar 独家拥有事实防护与业务合规裁决。Hub 仅消费其结构化事实。
   - 对于缺乏业务样本的新候选者，其业务质量指标 **MUST** 明确标记为 `BUSINESS_QUALITY = UNKNOWN`，严禁赋予虚假的中间分。

### 5.4 编程智能体微基准沙箱隔离与零泄露 (Coding Agent Microbench Invariants)
- 智能体编程挑战 **MUST** 在临时独立的沙箱环境（如临时目录）中运行，测试完成后自动销毁。
- 测试过程中产生的补丁代码、源代码、文档及交互 Prompt/Response **MUST NOT** 沉淀至模型记忆持久化表中。
- 挑战记录仅可记录：用例标识、哈希值、工具结果枚举、通过状态、执行延迟、重试次数与失败阶段。

---

## 6. 挑战记忆、时间衰减与预算治理 (Memory, Decay & Budget Governance)

### 6.1 专属挑战记忆记录 (Dedicated Challenge Memory)
挑战结果按 6 元组键独立维护：`(consumer, task_family, capability_profile, logical_model_id, channel, challenge_suite_version)`。
追踪指标包括：
- `sample_count`（样本总数）
- `completion_rate`（任务完成率）
- `technical_pass_rate`（技术通过率）
- `tool_loop_pass_rate`（工具循环通过率）
- `targeted_test_pass_rate`（定向单测通过率）
- `latency_p50_ms` / `latency_p95_ms`（P50/P95 延迟）
- `retry_rate`（重试率）
- `failure_stage_distribution`（失败阶段分布统计）
- `recent_evidence_weight`（有效近期证据权重）
- `confidence`（治理置信度）
- `last_challenged_at`（最近挑战时间）
- `memory_epoch`（模型记忆代际）

### 6.2 时间衰减与代际隔离 (Time Decay & Epoch Isolation)
- 遵循 STD-022 规范，历史挑战证据按半衰期进行指数衰减，近期证据赋予更高权重。
- 系统同时保留全量历史审计视图（`ALL_TIME`）与有效近期视图（`EFFECTIVE`）。
- 当模型上游指纹（`model_fingerprint`）发生实质性变更时，递增 `memory_epoch`，旧代际的挑战证据不得主导新代际的比选。

### 6.3 探索与冷启动插槽 (Exploration & Cold-Start Slots)
- 为防止新验证模型永久饥饿（Starvation），调度器应采用保守探索插槽：分配固定名额给高置信度挑战者，并预留小比例冷启动插槽给零样本新模型。
- 单次冷启动测试成功绝不能直接使模型晋升为冠军。

### 6.4 严格预算与配额治理 (Budget & Quota Governance)
Scout 调度器 **MUST** 严格遵守预算上限：
- 单周期最大候选数（`max_candidates_per_cycle`）
- 单周期最大挑战数（`max_challenges_per_cycle`）
- 最大并发挑战数（`max_concurrent_challenges`）
- 单周期/单日最大 Token 预算（`max_token_budget_per_cycle`, `max_token_budget_per_day`）
- 供应商级错误冷却与退避（`per_provider_cooldown`）
- 单次挑战超时上限与 Owner Action 生成预算。
- 遭遇 429 配额用尽时，立即挂起该供应商调度，防止发生探针风暴或 API 费用失控。

---

## 7. 帕累托多维比选与可解释推荐 (Pareto Comparison & Explainable Recommendations)

### 7.1 多维帕累托比选结论 (Multi-Dimensional Pareto Conclusions)
比选必须基于硬门槛、多维指标与帕累托前沿分析，严禁输出单一黑盒分：
1. `CHALLENGER_DOMINATES`：挑战者在所有关键维度均优于或等于现任冠军，且至少有一项显著领先。
2. `CHAMPION_RETAINS`：现任冠军在核心指标上依然全面稳固领先。
3. `TRADEOFF`：挑战者与冠军互有胜负（例如任务完成率更高但 P95 延迟较长），存在明确工程权衡。
4. `INSUFFICIENT_EVIDENCE`：样本量不足或置信度未达到阈值，无法做出确定性结论。
5. `TECHNICALLY_INELIGIBLE`：挑战者发生协议异常、工具解析失败或未通过前置探针。
6. `BUSINESS_EVIDENCE_REQUIRED`：技术微基准虽通过，但缺少必要业务域质量数据。
7. `OWNER_ACTION_REQUIRED`：具备理论潜力但处于未安装状态，需资源所有者执行动作。

### 7.2 规范治理建议类型 (Recommendation Types)
- `PROMOTION_RECOMMENDED`（建议晋升）
- `PROMOTION_NOT_RECOMMENDED`（建议不予晋升）
- `MORE_EVIDENCE_REQUIRED`（建议补充证据）
- `DEMOTION_RECOMMENDED`（建议降级）

### 7.3 晋升建议准入不变式 (Promotion Preconditions)
输出 `PROMOTION_RECOMMENDED` **MUST** 严格满足：
1. 样本数达标（`sample_count >= MIN_PROMOTION_SAMPLES`，通常 >= 10）；
2. 治理置信度高（`confidence >= 0.80`）；
3. 无硬性技术崩溃；
4. 关键能力维度均已通过真实验证；
5. 包含结构化可解释原因组合（`component_reasons`）。
- **铁律**：`PROMOTION_RECOMMENDED` 仅为治理层建议，`production_promoted` 字段必须恒为 `false`，绝不触发生产自动变更！

---

## 8. 资源所有者动作集成与 Ollama 资源预检 (Owner Action Integration & Resource Preflight)

### 8.1 规范动作集成 (STD-025 Compatible Request Generation)
- 当高价值候选模型处于 `OWNER_ACTION_REQUIRED`（如 Owner 声明的未拉取 Ollama 模型）时，Hub **MAY** 依据 STD-025 生成一个动作类型为 `OLLAMA_PULL_MODEL` 的 Owner Action Request。
- 生成的请求状态 **MUST** 严格初始化为 `APPROVAL_REQUIRED`，Hub **MUST NOT** 自动批准。
- 若不存在支持的规范动作路径，系统 **MUST** 返回 `NO_CANONICAL_OWNER_ACTION_AVAILABLE`，严禁编造非规范动作。

### 8.2 Ollama 资源预检 (Ollama Resource Preflight)
在生成 `OLLAMA_PULL_MODEL` 建议前，系统应基于非敏感机器事实（预估模型尺寸、剩余磁盘空间、GPU/显存分类、RAM）进行前置可行性评估：
- 若缺乏权威显存规格元数据，`resource_fit` **MUST** 标记为 `UNKNOWN`，严禁虚报 `PASS`。

### 8.3 严禁静默删除模型 (No Automatic Model Removal)
- R3 严禁自动生成 `OLLAMA_REMOVE_MODEL` 请求。破坏性动作（`DESTRUCTIVE`）在生产治理中保持全面禁用。

---

## 9. 零指标污染与测试隔离不变式 (Zero Contamination & Test Isolation Invariants)

### 9.1 四重零双计不变式 (Four Zero Double-Counting Invariants)
Scout 挑战与影子评估产生的所有流量均为自治探针流量，必须严格隔离：
```text
SCOUT_L1_DOUBLE_COUNT=false
SCOUT_CODING_OUTCOME_DOUBLE_COUNT=false
SCOUT_AIKB_QUALITY_DOUBLE_COUNT=false
SCOUT_SIDECAR_BUSINESS_DOUBLE_COUNT=false
```
1. **L1 零双计**：严禁将挑战请求计入 Layer 1 生产 API 成功与流量统计。
2. **Coding Outcome 零膨胀**：微基准挑战执行目的为 `SCOUT_CHALLENGE`，严禁增加生产 Coding Outcome 样本计数。
3. **AI-KB 零污染**：严禁将合成挑战记入真实知识库问答或提炼质量长程记忆。
4. **Sidecar 零污染**：严禁将合成挑战记入真实业务合规评分。

### 9.2 关键路径零阻塞 (Routing Critical Path Isolation)
- 侦察调度、目录抓取与影子挑战评测完全位于主路由选择路径之外（`AUTOPILOT_ON_CRITICAL_PATH=false`）。
- 生产路由 `POST /api/model/select` 延迟指标 **MUST** 保持 P95 <= 50ms。

### 9.3 测试数据库物理隔离 (Test/Production Datastore Isolation)
- 自动化测试与验收测试 **MUST** 注入独立的测试数据库。测试执行前后，生产数据库中合成测试记录必须保持为 0：
  ```text
  LIVE_SYNTHETIC_SCOUT_ROWS_BEFORE_TESTS=0
  LIVE_SYNTHETIC_SCOUT_ROWS_AFTER_TESTS=0
  ```
