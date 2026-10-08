# STD-027: Safe Autonomous Promotion and Canary Routing Contract (安全自主模型晋升与金丝雀路由契约规范)

```text
STANDARD_ID=STD-027
VERSION=1.9.0
STATUS=ACTIVE
SCOPE=Model Ops Autopilot 生产路由安全自主晋升：硬证据门禁、金丝雀受控分流、持续监控验证、自动回滚与滞后防抖、可解释治理契约
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-08
RELATED_STANDARDS=STD-008, STD-009, STD-010, STD-019, STD-020, STD-021, STD-022, STD-023, STD-024, STD-025, STD-026
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 架构目标与双边界自主原则 (Architectural Goal & Hard Ownership Boundaries)

在 AI 平台架构演进中，Model Ops 运维自治进入 R4 阶段（安全自主晋升与金丝雀分流）。
系统核心目标**不是**让 Hub 任意替换全量生产模型（`UNRESTRICTED_AUTONOMOUS_ROUTING`），而是：
> **“在严格受控的安全包络（Safety Envelope）内，使 Hub 能够基于充分多维、经过校验的真实硬证据，将已就绪且安全的挑战者（Challenger）自主推入受限金丝雀（Canary）阶段，实施连续在线校验，并在遭遇任何安全违背时以毫秒级自愈能力自动回滚。”**

R4 自主性定性为：
```text
AUTONOMY_CLASS=SAFE_AUTONOMOUS_CANARY
```
绝对不是全量或无约束的生产替换。

### 1.1 严格所有权边界 (Hard Ownership Boundaries)
- **Hub 自主可变更范畴（Hub May Autonomously Mutate ONLY）**：
  - Hub 自身拥有的运行时路由策略状态（Routing Policy State）与金丝雀权重。
- **Hub 绝对禁止自主变更外部基础设施（Hub MUST NOT Autonomously Mutate External Infrastructure）**：
  - AI-KB 基础设施、卷与知识库。
  - Local CPA 本地中继与 Cloud CPA 云端中继的容器生命周期。
  - Ollama 服务及物理模型文件的下载/删除（`OLLAMA_PULL_MODEL` / `OLLAMA_REMOVE_MODEL`）。
  - Docker 守护进程与容器资源。
  - SSH 隧道、系统网关及机器级凭据。
  - 外部软件工程代码仓库与配置。
- **资源所有者动作保持审批模式（Owner Actions Remain APPROVAL_REQUIRED）**：
  - R4 阶段 **MUST NOT** 自动批准 STD-025 Owner Action 请求。
  - 严禁自动执行拉取模型、卸载模型、重启中继或升级容器。

---

## 2. 全局模式与作用域模式 (Global Mode vs Scoped Mode)

### 2.1 全局默认影子模式 (Global Default SHADOW_ONLY)
平台全局默认自治模式保持为：
```text
GLOBAL_AUTOPILOT_MODE=SHADOW_ONLY
```

### 2.2 四元组作用域隔离 (Scoped Autonomy Key)
系统引入独立的作用域级自治治理，作用域键（Scope Key）由四元组严格唯一定义：
```text
ScopeKey = (consumer, task_family, capability_profile, virtual_profile)
```

### 2.3 R4 初始白名单作用域 (Initial Allowlisted Scope)
R4 阶段唯一允许进入 `SAFE_AUTONOMOUS` 的白名单作用域为：
```text
consumer = "claude-code"
task_family = "coding_agent"
capability_profile = "agent_coding_high_quality"
virtual_profile = "hub-code-auto"
```
所有未明确列入白名单的作用域（包括 Sidecar、AI-KB 知识库问答、VTIP 业务工作流、`hub-code-local` 以及其他消费者）**MUST** 继承 `SHADOW_ONLY`，严禁跨域推断或泛化开启自主晋升。

---

## 3. 正交路由分流状态机 (Orthogonal Routing Rollout State Machine)

系统 **MUST NOT** 将路由分流状态与 STD-024 模型生命周期状态（`lifecycle_state`）混淆重载。二者属于正交维度：
- STD-024 模型生命周期可能已是 `PRODUCTION_ELIGIBLE`；
- 但其在具体业务作用域下的路由状态可以是 `CANARY_ACTIVE` 或 `CANARY_HOLD`。

### 3.1 规范路由分流状态 (Canonical Rollout States)
| 状态枚举 | 状态含义与操作语义 |
| :--- | :--- |
| `NOT_ELIGIBLE` | 证据不足或硬性门禁未通过，不可进入金丝雀分流 |
| `ELIGIBLE` | 通过全量硬证据门禁，具备进入金丝雀试验资格 |
| `CANARY_PENDING` | 已生成金丝雀准备事务，快照已固化，等待下发 |
| `CANARY_ACTIVE` | 处于金丝雀受控分流阶段（权重 5% 或 10%），持续接收真实流量 |
| `CANARY_HOLD` | 处于观察期且流量或时间尚未满足晋阶条件，保持当前分流并持续观测 |
| `ROLLBACK_PENDING` | 检测到安全指标违背或异常，已锁定回滚流程 |
| `ROLLED_BACK` | 已自动恢复冠军原状路由，候选模型进入冷却期 |
| `PROMOTION_READY` | 已完成受控金丝雀观察验证，等待后续治理阶段决策（R4 停留于此，不自动替换） |
| `FULL_PROMOTION_BLOCKED` | 平台硬性封顶：R4 严禁进入 100% 全量生产自主替换 |

---

## 4. 安全自主晋升硬门禁与证据策略 (Hard Gates & Minimum Evidence Policy)

### 4.1 19 项全量硬门禁 (19 Mandatory Hard Gates)
挑战者模型进入 `CANARY_PENDING` / `CANARY_ACTIVE` **MUST** 严格同时通过以下 19 项硬门禁，任一项失败即判定为 `NO_AUTONOMOUS_PROMOTION`：
1. `lifecycle_state == PRODUCTION_ELIGIBLE`（或规范等效已通过分级验证状态）；
2. 运行时物理可用性健康（`runtime_availability == healthy / AVAILABLE_NOW`）；
3. 模型未被隔离（`not quarantined`）；
4. 模型未处于临时不可用状态（`not TEMP_UNAVAILABLE`）；
5. 熔断器未开启（`circuit_breaker_open == false`）；
6. 核心能力探针通过（`required_capability == PROBE_VERIFIED`）；
7. 面向 Claude Code 作用域：工具链协议完全兼容（`agent_compatible == true`）；
8. 存在完全匹配的精确作用域证据（Exact Key Match）；
9. 有效样本量达标（`sample_count >= 10`）；
10. 治理置信度达标（`confidence >= 0.90`）；
11. 证据观察窗口处于近期有效窗口内（半衰期衰减后未过期）；
12. 零遗留严重技术失败（`critical_technical_failures == 0`）；
13. 未处于上游配额暂停期（`quota_paused == false`）；
14. Scout 侦察样本来源可信且溯源完整；
15. Gateway 执行来源溯源可信且完整；
16. 当前内存代际与证据代际一致（`memory_epoch_match == true`）；
17. 挑战测试套件版本属于受控受信任版本；
18. 自治预算池充足（未触碰 Token/调用配额上限）；
19. 作用域显式开启 `SAFE_AUTONOMOUS` 且全局自治 Kill Switch 未触发。

### 4.2 最小证据策略 (Minimum Evidence Thresholds)
针对 R4 Claude Code 作用域：
- 精确键有效样本量：`sample_count >= 10`
- 治理置信度：`confidence >= 0.90`
- 技术完成率：`technical_completion_rate >= 0.95`
- Agent 工具循环通过率：`agent_tool_loop_pass_rate >= 0.95`
- 定向单测通过率：`targeted_acceptance_pass_rate >= 0.95`
- 近期严重技术故障数：`0`
- 近期熔断器触发数：`0`
- 近期协议失败数：`0`
- **铁律**：若现有真实证据不满足阈值，**MUST NOT** 人工降低门槛，输出 `MORE_EVIDENCE_REQUIRED` 为规范结果。

### 4.3 真实结果安全性与技术金丝雀定性 (Technical Canary Only)
- Scout 微基准测试仅代表技术层面可调用与协议健全，不能自动等价于真实业务卓越度。
- R4 阶段允许标注为 `TECHNICAL_CANARY_ONLY`，但 **MUST** 在元数据与 UI 中明确标识。
- 技术金丝雀绝不能直接视为“业务级冠军”。

---

## 5. 安全金丝雀权重与确定性分流 (Canary Weights & Deterministic Bucketing)

### 5.1 严格权重上限 (Bounded Canary Weights)
- R4 阶段自治金丝雀最高允许权重：
  ```text
  MAX_AUTONOMOUS_CANARY_WEIGHT = 0.10 (10%)
  ```
- 允许的阶梯阶段：
  - 第 1 阶段：`5%` (`0.05`)
  - 第 2 阶段：`10%` (`0.10`)
- R4 **MUST NOT** 自动晋升至 25%、50% 或 100%。

### 5.2 确定性非敏感哈希分流 (Deterministic Stable Hashing)
- 分流 **MUST NOT** 采用单次请求纯随机数。
- **MUST** 使用非敏感路由标识计算稳定哈希桶：
  ```text
  bucket_hash = SHA256(scope_id + ":" + stable_bucket_key + ":" + routing_revision) % 10000 / 10000.0
  ```
- 同一会话（Session）或稳定请求桶在同一路由版本下保持一致分流。
- 严禁持久化用户个人敏感数据（PII）。

### 5.3 冻结候选计划保护 (Frozen Plan Invariant)
- 历史已绑定的冻结候选计划（如特定会话已固定模型，或已指明 Candidate Plan）**MUST NOT** 受到金丝雀策略重路由干扰。
- 金丝雀分流仅对完全动态（Dynamic Unbound）请求生效。

### 5.4 精确金丝雀模型绑定 (Exact Canary Binding)
- 一旦请求被确定性分配至金丝雀，系统 **MUST** 尝试调度该金丝雀模型。
- 若金丝雀模型执行失败触发降级至 Champion，系统 **MUST** 记录：
  ```text
  CANARY_FAILED + CHAMPION_FALLBACK_SUCCEEDED
  ```
  该次降级成功绝不能作为金丝雀模型的成功证据！

---

## 6. 观察窗口、相对安全比对与自主回滚 (Observation Window, Relative Safety & Rollback)

### 6.1 观察窗口双重条件 (Observation Dual-Gate)
每个金丝雀阶段晋级 **MUST** 同时满足样本量与留存时间双重要求：
- `5%` 阶段晋升至 `10%`：
  - 金丝雀有效观测样本：`>= 10`
  - 最小留存观察时间（Dwell Time）：`>= 15 分钟`
- `10%` 阶段：
  - 最小留存观察时间：`>= 30 分钟`
  - 有效观测样本：`>= 20`
  - 达到后进入 `PROMOTION_READY`，等待人工或后续治理阶段介入。
- 若流量不足，保持 `CANARY_HOLD`，不得自动假定通过。

### 6.2 相对 Champion 降级比对 (Relative Safety Comparison)
不得仅基于绝对静态指标判断金丝雀健康。必须比对并发 Champion 表现：
- 错误率恶化预算：`canary_error_rate - champion_error_rate > 0.05`（超出 5% 容忍度即触发回滚）；
- 延迟恶化预算：`canary_p95_latency > 1.5 * champion_p95_latency` 或绝对超出 SLO；
- Agent 工具循环失败率显著升高。

### 6.3 自主回滚硬触发器 (Autonomous Rollback Hard Triggers)
回滚速度必须快于晋升。发生以下任意情形时，系统 **MUST** 立即将金丝雀权重置为 0% 并切回 Champion：
1. 物理运行时服务离线或返回不可达；
2. 熔断器处于开启状态；
3. Agent 协议兼容性断言失败；
4. 连续技术失败次数达阈值（`consecutive_failures >= 2`）；
5. 错误率超出 Champion 降级预算；
6. 工具调用解析失败次数超标；
7. 延迟严重超时违背 SLO；
8. 触发供应商 Quota / 429 暂停；
9. 选定模型与实际网关执行模型标识不符；
10. 网关溯源凭证不匹配；
11. 模型指纹变更引发 `memory_epoch` 代际不一致；
12. 触发人工覆盖或全局 Kill Switch。
- **自主回滚属性**：属于 Hub 纯内部安全保护，**无需**人工事前审批。

### 6.4 滞后与防抖冷却 (Hysteresis & Rollback Cooldown)
- 触发回滚后，候选模型进入冷却期（Cooldown）：
  ```text
  ROLLBACK_COOLDOWN_SECONDS >= 3600 (>= 60 分钟)
  ```
- 冷却期内系统 **MUST NOT** 再次将该模型推入金丝雀。
- 晋升门槛必须严于回滚门槛，防止反复振荡（Anti-Flapping）。

---

## 7. 冠军快照保留、CAS 事务与人工覆盖 (Snapshot, CAS & Overrides)

### 7.1 现任冠军不可变快照 (Champion Routing Snapshot)
在金丝雀生效前，系统 **MUST** 持久化现任 Champion 的只读快照：
- `snapshot_id`
- `scope_id`
- `champion_model_id` / `champion_channel`
- `candidate_plan`
- `policy_version`
- `routing_revision`
- `captured_at`
回滚时必须精确恢复至此快照对应的路由配置。

### 7.2 路由策略原子 CAS 机制 (Routing Policy CAS)
路由策略变更必须遵循版本号比较并交换（Compare-and-Swap）：
```text
ROUTING_POLICY_CAS = true
```
若并发请求中当前路由版本号与期望版本号不匹配，变更立即中止，防止覆盖管理员配置。

### 7.3 人工覆盖优先级第一原则 (Operator Override Precedence)
人工操作具有最高权威，支持：
- `PIN_CHAMPION`：固定主模型，冻结自治；
- `DISABLE_CANARY`：停用金丝雀；
- `FORCE_ROLLBACK`：强制回滚；
- `FREEZE_AUTONOMY`：冻结作用域；
- `UNFREEZE_AUTONOMY`：解冻作用域。
操作审计记录永久保存，Autopilot 必须立即生效服从。

### 7.4 全局安全阻断开关 (Global Autonomy Kill Switch)
平台支持一键全局开关：
```text
AUTONOMY_KILL_SWITCH = true
```
- 一旦开启，所有自主晋升全部停止；所有活跃金丝雀立即归零恢复至 Champion；
- Kill Switch 状态必须在数据库中持久化，重启后依然生效；
- 不影响常规模型探测与只读监控。

---

## 8. 可解释性审计与指标零污染 (Explainability & Zero Contamination)

### 8.1 晋升与回滚全要素可解释性 (Full Explainability)
- 晋升决策快照必须完整记录：为什么合格、样本量、置信度、Champion 差异、为何权重安全、回滚前置条件。
- 回滚事件必须完整记录：触发的硬门禁、异常时间戳、与 Champion 的恶化差值、恢复的快照版本、冷却截止时间。
- 决策快照与审计记录 **MUST NOT** 包含任何用户 Prompt 或敏感上下文。

### 8.2 零双计与零污染指标不变式 (Zero Double-Counting Invariants)
```text
AUTONOMY_L1_DOUBLE_COUNT = false
AUTONOMY_CODING_OUTCOME_DOUBLE_COUNT = false
AUTONOMY_CANARY_VALIDATION_TRAFFIC_ISOLATED = true
```
- 自治验证流量标记为 `AUTONOMY_CANARY_VALIDATION`，严禁计入 Layer 1 生产 API 成功率或 Layer 2 Coding Outcome 用户长程记忆。
- 测试必须在独立测试数据库中运行，生产数据库中合成测试记录严格为 0。

### 8.3 路由主链路延迟约束 (Critical Path Latency Budget)
- 自治分流消费预计算内存状态，禁止在选模关键路径同步执行数据库复杂聚合。
- 模型选择接口（`POST /api/model/select`）P95 延迟 **MUST** 保持在 50ms 以内（`SELECT_P95_MS <= 50`）。
