# STD-028: Model Supply Autopilot and Autonomous Champion Management Contract (外部模型供给自治与冠军管理契约规范)

```text
STANDARD_ID=STD-028
VERSION=2.0.0
STATUS=ACTIVE
SCOPE=外部模型自动化供给发现、免费/试用定价分类、真实可用性微探针、智能体能力验证、CPA 事务性自动接入、配额健康退避自愈、多目标经济路由、自治 Champion 梯度放量与回滚契约
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-08
RELATED_STANDARDS=STD-008, STD-009, STD-010, STD-021, STD-022, STD-023, STD-024, STD-025, STD-026, STD-027
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 架构目标与双边界自治原则 (Architectural Goal & Hard Ownership Boundaries)

在 AI 平台架构演进中，Model Ops 运维自治进入 R5 阶段（Model Supply Autopilot & Champion Management）。
系统核心目标是从单纯“静态配置与被动管理已有模型”升级为：
> **“主动感知与发现外部可用模型供给，基于真实机器可读目录与定价事实分类免费/试用资源，实施零敏感凭据低成本真实可用性微探针，经智能体能力验证后，通过 AI-KB 资源所有者执行平面实施受控事务性 CPA 接入；建立全周期配额健康监控与退避自愈通道；在生产路由中支持兼顾稳定 Champion 与免费容量道（Free Capacity Lane）的多目标经济调度，实施严谨梯度放量（5% -> 10% -> 25% -> 50% -> 100%）与秒级安全回滚。”**

### 1.1 严格所有权边界 (Hard Ownership Boundaries)
- **Hub 控制平面拥有（Hub Owns）**：
  - 外部模型供给源注册表 (`Source Registry`) 与机器可读目录发现 (`Discovery Catalog`)。
  - 免费/试用与定价分类状态 (`Pricing Classification`)。
  - 零密钥低成本真实可用性探针 (`Availability Probes`)。
  - 智能体能力与协议验证测试 (`Capability Verification & Scout Integration`)。
  - 上游配额与限流健康监控 (`Quota & Rate-Limit Monitor`)。
  - 长期供给运维记忆沉淀 (`Model Supply Memory`)。
  - 策略预授权判定与 Owner Action 请求构造 (`Owner Action Requests`)。
  - 多目标经济路由策略与免费容量道 (`Free Capacity Lane Routing`)。
  - 候选模型放量阶段流转、防抖回滚与自治 Champion 决策 (`Champion Management`)。
- **AI-KB 资源所有者执行平面拥有（AI-KB Remains Resource Owner）**：
  - Local CPA 本地中继与 Cloud CPA 云端中继的物理配置与生命周期守护。
  - 机器级真实凭证持有与 `credential_ref` 本地映射解析。
  - CPA 配置原子变更、配置语法校验、配置快照与物理回滚。
  - CPA 容器优雅重启/重载与宿主机健康检查。
  - 事实结果采集与非敏感执行事实回传。
- **Hub 绝对禁令（Hub Invariants）**：
  - Hub **MUST NOT** 直接修改 CPA 配置文件或 Docker Compose 清单。
  - Hub **MUST NOT** 持久化或导出供应商原始 API Key、密码或私钥。
  - Hub **MUST NOT** 直接重启 CPA 容器或执行底层系统命令。
  - Hub **MUST NOT** 自动创建外部账号、规避验证码或轮换账号逃避免费配额限制。
  - Hub **MUST NOT** 实施无节制互联网 HTML 爬虫，仅允许官方 API 与机器可读元数据目录。

---

## 2. 供给源注册表与源类型规范 (Model Supply Source Registry)

系统 **MUST** 维护规范的外部供给源注册表，每一条供给源记录包含：
- `source_id`：唯一供给源标识。
- `source_type`：规范源类型枚举：
  - `CPA_EXISTING_CATALOG`：已接入 CPA 的现有模型目录。
  - `OPENROUTER_CATALOG`：OpenRouter 官方机器可读模型目录与聚合。
  - `HUGGINGFACE_INFERENCE_PROVIDERS`：Hugging Face 官方推理供应商与模型元数据。
  - `GENERIC_OPENAI_COMPATIBLE`：标准通用 OpenAI 兼容接口源。
  - `OWNER_CONFIGURED_PROVIDER`：由资源所有者配置的可信供应商端点。
- `trust_level`：可信等级 (`TRUSTED`, `OPERATOR_APPROVED`, `UNVERIFIED`, `BLOCKED`)。
- `credential_state`：凭据状态 (`NOT_REQUIRED`, `AVAILABLE`, `MISSING`, `EXPIRED`, `INVALID`)。
- `credential_ref`：仅存储非敏感凭据引用，严禁包含明文 Secret。
- `rate_limit_policy`：请求限流与探测退避策略。

---

## 3. 免费/试用定价分类与防伪定价规范 (Free/Trial Pricing Classification)

模型名称包含 "free" 字符绝对不能作为免费凭证。定价判定 **MUST** 基于官方权威数据源：

### 3.1 规范定价类别 (`pricing_class`)
- `FREE_NOW`：官方明确声明当前提示词与生成调用均为零单价（$0.00 / 0元）。
- `ZERO_PRICE_MODEL`：官方针对特定模型设立的长期永久零费率。
- `TRIAL_CREDIT`：提供新用户注册赠送的额度包或限时试用 Token。
- `LIMITED_FREE_TIER`：每日/每月有固定免费配额，超出后转入付费或拦截。
- `PAID`：正常按量或包月付费模型。
- `UNKNOWN`：无法获取权威定价元数据，默认视为非免费。
- `EXPIRED`：试用期结束或免费策略已失效。

### 3.2 供给稳定性分级 (`supply_stability_class`)
- `STABLE`：高可用可信商业保障模型或本地稳定私有部署。
- `EPHEMERAL_FREE`：上游第三方提供的临时/实验性免费算力资源，极易发生突发离线或限流。
- `TRIAL`：限时试用资源。
- `UNKNOWN`：稳定性未建立基线。
- **铁律**：`EPHEMERAL_FREE` 与 `TRIAL` 资源 **MUST** 具备健康稳定的 Champion 作为主备回退路由，**严禁**直接晋升为 100% 永久 Champion。

---

## 4. 供给可用性状态机与轻量级真实微探针 (Availability State Machine & Cheap Probe)

### 4.1 供给可用性状态枚举 (`supply_availability_state`)
```text
DISCOVERED -> (CREDENTIAL_REQUIRED | TERMS_REQUIRED | PROBE_READY)
  -> PROBE_READY -> AVAILABLE
  -> (RATE_LIMITED | QUOTA_EXHAUSTED | TEMP_UNAVAILABLE | AUTH_FAILED | PROVIDER_UNAVAILABLE)
  -> (RECOVERY_PROBE -> AVAILABLE)
  -> (DISABLED | RETIRED)
```

### 4.2 真实可用性微探针规范 (Cheap Real Availability Probe)
- HTTP 200 仅代表上游 HTTP 网关连通，**不等于模型真实可用**。
- 微探针 **MUST** 发送最小 Token 测试请求（`max_tokens=1`），断言其成功生成有效响应。
- 探针 **MUST** 遵循严格 SSRF 防护规则：禁止访问内网保留私网 IP、禁止非 HTTP/HTTPS 协议、禁止携带敏感请求头。
- 探针 Token 消耗与并发受到每日预算硬限制，防止探索过程产生异常计费。

---

## 5. CPA 事务性接入契约与预授权安全策略 (CPA Onboarding & Preauthorized Execution)

### 5.1 接入路径安全双分类
- **路径 A：`PREAUTHORIZED_AUTOMATIC`（策略预授权自动接入）**：
  仅在满足全部前置条件时允许免人工交互执行：
  1. 目标供应商适配器已被列入白名单且经受信任审核；
  2. 机器级凭据引用 `credential_ref` 在 AI-KB 侧已就绪；
  3. 服务条款此前已由运维人员确认接受；
  4. 目标端点符合网络白名单；
  5. 属于非破坏性操作（仅向现有供应商路由追加模型名与别名）；
  6. 存在完整的预备快照与秒级回滚预案；
  7. AI-KB 资源所有者策略显式允许该动作预授权。
- **路径 B：`APPROVAL_REQUIRED`（审批流接入）**：
  新供应商引入、新凭证配置、新外网域名、服务条款变更、高风险全局配置调整 **MUST** 提交人工审批，严禁系统静默降级为预授权。

### 5.2 事务性接入时序 (CPA Mutation Transaction)
1. **SNAPSHOT**：AI-KB 执行器备份当前 CPA 配置文件快照；
2. **VALIDATE**：校验请求的模型路由参数语法；
3. **APPLY**：原子写入临时文件并原子替换主配置；
4. **RESTART**：优雅重启 CPA 容器并进行 18117 健康检查；
5. **FAILSAFE**：若启动失败或健康检查超时，立即恢复快照并重启恢复，拒绝脏配置；
6. **VERIFY**：Hub 触发独立重发现，向 CPA 端点发起真实低成本调用验证新模型，断言 `fallback_count == 0`；
7. **CATALOG INVARIANT**：验证原有 100+ 已接入模型未被覆盖或丢失。

---

## 6. 配额健康监控、退避机制与自愈恢复 (Quota Monitoring, Backoff & Recovery)

### 6.1 配额状态枚举 (`quota_state`)
`UNKNOWN`, `HEALTHY`, `LOW`, `RATE_LIMITED`, `EXHAUSTED`, `TRIAL_EXPIRED`。

### 6.2 零滥用自愈准则
- 收到 429 或配额耗尽信号时，系统 **MUST** 立即暂停该供给路由，解析 `Retry-After` 头并启动退避计时器。
- 系统 **MUST NOT** 采用多账号轮换轮询规避上游限制。
- 退避计时结束后，自愈调度器执行 `RECOVERY_PROBE`，确认恢复后平滑重新开启纳管。

---

## 7. 多目标经济路由与免费容量道 (Cost-Aware & Free Capacity Lane Routing)

### 7.1 约束多目标优化原则 (Constrained Multi-Objective Optimization)
平台路由选择遵循严格硬门禁优先排序：
`硬能力门禁 (Capabilities) -> 硬健康门禁 (Health) -> 硬配额门禁 (Quota) -> 质量得分 (Quality) -> 稳定性 (Reliability) -> 延迟 (Latency) -> 成本 (Cost) -> 配额余量 (Quota Headroom)`。
- **铁律：`FREE_MODEL_ALWAYS_WINS = false`**。零价格模型若不能满足硬性代码完成率或 Agent 协议循环，绝不能胜出。

### 7.2 免费容量道 (`FREE_CAPACITY_LANE`)
- 当且仅当免费/试用供给通过能力与健康门禁时，允许将其作为“免费容量道”承接受控动态流量；
- 必须始终保留健康稳定 Champion 作为故障瞬间兜底（Fallback）；
- 配额处于 `LOW` 时自动缩减流量占比；配额 `EXHAUSTED` 时流量占比归零，对终端用户完全透明无感。

---

## 8. 自治 Champion 梯度放量与回滚硬门禁 (Champion Management & 5-Stage Rollout)

### 8.1 规范放量阶段 (Canonical Rollout Stages)
```text
CANARY_5 (5%) -> CANARY_10 (10%) -> RAMP_25 (25%) -> RAMP_50 (50%) -> PROMOTION_READY -> CHAMPION_ACTIVE (100%)
```

### 8.2 100% 全量生产 Champion 晋升硬门禁 (Full Champion Hard Gates)
挑战者晋升为 100% 全量 Champion **MUST** 同时满足以下硬性条件，缺一不可：
1. 继承并通过 STD-027 全部 19 项硬门禁；
2. 具备充分的生产流量真实观测样本（不仅仅是 Scout 合成评测）；
3. 治理置信度达标（`confidence >= 0.95`）；
4. 供给稳定性级别为 `STABLE`（`EPHEMERAL_FREE` 与 `TRIAL` 默认触发 `FULL_CHAMPION_BLOCKED`）；
5. 上游配额充足，具备承担 100% 生产峰值流量的确定性预算；
6. 近期无严重故障、无熔断、无供应商突发故障；
7. 成功走完 5% -> 10% -> 25% -> 50% 阶梯且留存观测时间（Dwell Time）达标；
8. 全局 Kill Switch 未开启，操作人员未设置冻结（Freeze）；
9. 前任 Champion 完整快照已安全固化；
10. 回滚机制处于秒级就绪状态。

### 8.3 滞后防抖与秒级回滚 (Anti-Flapping & Autonomous Rollback)
- 回滚速度必须快于晋升。
- 遭遇异常立即回退至前任 Champion 快照，并将异常模型置于冷却期（`cooldown >= 3600s`）。
- 严禁因临时免费资源的频繁出现造成系统 Champion 震荡。

---

## 9. 审计证明与可解释性原则 (Audit Provenance & Explainability)

系统做出的每一次发现、探针、定价分类、CPA 接入、分流调整及 Champion 决策 **MUST** 提供完全可解释的理由码（`reason_code`）与中文说明（`reason_cn`）：
- 为什么发现该模型；
- 为什么判定为免费/试用；
- 真实调用微探针是否成功及延迟；
- 为什么自动接入或未接入 CPA；
- 剩余配额与重置时间；
- 为什么被选中或被降级。
