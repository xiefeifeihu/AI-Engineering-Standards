# STD-014: Testing Standard (跨项目分层测试规范)

```text
STANDARD_ID=STD-014
VERSION=2.11.0
STATUS=ACTIVE
SCOPE=AI-Engineering-Standards、AI-Engineering-Hub 及跨工程自动化测试
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-30
RELATED_STANDARDS=STD-001, STD-007, STD-009, STD-010, STD-015, STD-016, STD-019, STD-020, STD-023, STD-031, STD-032, STD-033, STD-034, STD-035
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 分层测试体系要求

1. **非破坏性原则 (Non-Destructive Testing)**：
   测试用例 **MUST NOT** 调用破坏性清空命令，**MUST NOT** 删除真实生产数据集或清空历史有效审计日志。
2. **Standards 仓库测试**：
   必须包含自动化 Schema 校验脚本（`tools/validate-schemas.py`），对所有在册 JSON Schema（`schemas/*.schema.json`）进行有效性、边界样例及正反向契约测试。
3. **Hub 仓库测试**：
   包含针对性单元测试、API 契约集成测试与端到端 Playwright UI 验收测试。

---

## 2. 四层测试矩阵 (Four-Level Testing Matrix)

所有 AI 工程仓库 **MUST** 实现以下四层测试，并按顺序执行：

| 层级 | 名称 | 触发时机 | 工具 | 目标 |
|------|------|----------|------|------|
| **L1 - SMOKE** | 冒烟测试 | 每次提交 | pytest / shell | 核心路径可用性验证（< 30s）|
| **L2 - CORE** | 核心回归 | 每次提交 / 里程碑 | pytest | 所有单元 + API 集成（< 5min）|
| **L3 - DEEP** | 深度验收 | 涉及 UI / 里程碑发布前 | pytest + Playwright | 端到端 UI 验收、双主题、行为验证（< 15min）|
| **L4 - DIAGNOSTIC** | 诊断探针 | 按需 / 生产巡检 | 自定义脚本 | 健康探针、性能基线、Schema 与契约合规 |

### L1 - SMOKE 冒烟测试约束
- **MUST** 在 < 30 秒内完成。
- **MUST** 只测试应用启动、核心路由可达性和关键配置加载。
- **MUST NOT** 依赖外部公网或真实计费 AI 服务。

### L2 - CORE 核心回归约束
- **MUST** 覆盖所有业务逻辑单元（模型路由、资源注册、健康判定等）。
- **MUST** 包含 API 契约合规测试（按 STD-009、STD-010 等）。
- **MUST NOT** 运行 Playwright 浏览器用例（保留给 L3 深度验收）。

### L3 - DEEP 深度验收约束
- **MUST** 使用 Playwright Headless 模式运行（参见 STD-015）。
- **MUST** 生成截图和视频证据，输出到 `.artifacts/acceptance/<TASK>/<VERSION>/`。
- **MUST** 覆盖明亮/暗黑双主题无错切换。
- **MUST** 在涉及 UI 变更、跨组件集成或里程碑验收时按风险与产品基线触发，验证完整用户旅程。

### L4 - DIAGNOSTIC 诊断探针约束
- **MUST** 包含 Schema 合规校验（`tools/validate-schemas.py`）。
- **MUST** 报告模型健康状态与 KPI 指标基线。
- **MAY** 包含性能回归测试。

---

## 3. 测试输出与证据规范

1. 所有测试输出 **MUST** 输出到 `.artifacts/acceptance/<TASK>/<VERSION>/logs/`。
2. Playwright 截图 **MUST** 存放于 `.artifacts/acceptance/<TASK>/<VERSION>/screenshots/`。
3. Playwright 视频 **MUST** 存放于 `.artifacts/acceptance/<TASK>/<VERSION>/videos/`。
4. 测试日志与媒体制品 **MUST NOT** 提交到 Git（受 `.gitignore` 严格排除）。

---

## 4. 失败处理规范

1. 任何层级测试失败 **MUST** 阻断发布流程。
2. 失败报告 **MUST** 包含：失败测试名称、错误信息、复现步骤与对应 Commit。
3. **MUST NOT** 跳过或注释失败测试来强制通过，必须修复根本原因。

---

## 5. 两阶段自动化测试（Stage 1 / Stage 2）

**此处阶段是“发布前候选验证 / 部署后生产验收”两次验收，不是把 L1-L4 层级缩减为两级。**

| 阶段 | 执行时点 | 真实环境要求 | 核心目的 | 结论字段 |
|---|---|---|---|---|
| Stage 1 - `PRE_RELEASE_QUALIFICATION` | Push main、main CI 及生产部署之前/期间的候选验证 | 隔离测试环境或候选构建，必要时 Mock 外部系统并明确标注 | 检查安全、逻辑、兼容性与是否允许进入部署 | `PRE_RELEASE_STATUS` |
| Stage 2 - `POST_DEPLOY_REAL_ACCEPTANCE` | 部署当前 `LIVE_COMMIT` 后，正式 Release 与 Tag 前 | 真实服务端口、真实网络和所需依赖；真实浏览器模拟业务操作；只读或受控测试数据 | 检查用户是否真正能使用已经部署的功能和业务结果是否符合产品基线 | `POST_DEPLOY_STATUS` |

1. Stage 1 的通过只表示允许生产部署，不能取代 Stage 2。
2. Stage 2 的运行必须和当前 `LIVE_COMMIT`、镜像身份及当次 `run_id` 绑定，既查界面交互、也查实际后端数据/业务结果，不是仅检查 HTTP 200、页面有数据、截图存在。
3. 必须从 `docs/PRODUCT-BASELINE.md` 或等效正式产品基线中生成关键旅程的**覆盖矩阵**，列明已覆盖、未覆盖、阻断、风险和断言；样本中人工质量评价或不可安全自动化的生产写入须显式 `DEFERRED`。
4. **最终裁决以 Stage 2 的真实生产业务验收为准**：Stage 2 Fail/Block/Not Verifiable 即使 Stage 1 全绿也不得宣布生产 PASS；Stage 1 失败同样不得进入部署。关键问题失败必须留复现证据并按发布策略回滚。
5. 对非运行时制品允许 `NON_RUNTIME_ARTIFACT` 特例，以真实发布制品与消费端 Schema/契约验收替代服务模拟；不得声称做过线上真实交互。
6. Stage 2 自动化可替代已被充分覆盖的重复人工验证；**不得等同于全部主观人工采纳或未覆盖场景**。
7. 正式原始证据分别保存于 `.artifacts/acceptance/<TASK>/<VERSION>/pre_release/` 与 `post_deploy/`，包括运行命令、输出、实际断言、数据来源、浏览器动作和同版本身份核验。静态脚本生成结论、截图复用或生产端口旁路均为 FAIL。

---

## 6. AI 智能体自主测试设计契约与闭环流程 (AI Autonomous Test Design Contract)

为杜绝“依赖用户逐条提出测试用例”、“ChatGPT 每次重新生成提示词”、“代码写完后缺乏业务覆盖”等脱节问题，全平台要求所有受管工程的编程智能体在执行开发、重构、Bug 修复、接口调整与依赖升级时，**自主履行测试设计与用例维护职责**。

### 6.1 编码前必读八项事实源输入 (Eight Pre-Coding Inputs)
编码智能体进入任务后，**MUST** 首先自动读取以下 8 项输入：
1. `docs/PROJECT-BLUEPRINT.md`（项目定位、能力愿景与演进里程碑）
2. `docs/PRODUCT-BASELINE.md`（产品业务入口、功能清单、系统边界与不可退化约束）
3. `docs/SYSTEM-ARCHITECTURE.md`（组件拓扑、调用流向与安全边界）
4. `docs/API-CONTRACT.md`（协议契约、Schema 约束与错误码字典）
5. `docs/TEST-ACCEPTANCE.md`（当前最新全量测试用例基线与历史回归矩阵）
6. **本次任务描述与 Git Diff**（变更代码行、修改的文件与新增接口）
7. **历史 Bug 与回归用例清单**（过往缺陷根因与边界陷阱）
8. **上次真实运行验收报告**（最近一次生产环境实际执行证据）

### 6.2 智能体自主测试闭环 13 阶段 (Autonomous 13-Stage Loop)
智能体 **MUST** 自主闭环推进以下 13 阶段：
```text
需求分析 ──► 变更影响分析 ──► 风险识别 ──► 已有用例匹配 ──► 发现测试缺口 ──► 新增/更新用例
   │
   ▼
编写测试代码 ──► 执行测试 ──► 修复缺陷 ──► 回归验证 ──► 更新测试基线 ──► 提交源码与文档 ──► 发布前与部署后测试
```

1. **需求分析 (Requirement Analysis)**：提取本次任务涉及的核心产品功能与用户旅程。
2. **变更影响分析 (Change Impact Analysis)**：分析代码 Diff 影响的模块、API、前端按钮与持久化数据，输出 `impact_analysis`。
3. **风险识别 (Risk Identification)**：识别边界异常、鉴权穿透、超时重试、状态不一致与外部依赖风险。
4. **已有用例匹配 (Case Matching)**：对照 `docs/TEST-ACCEPTANCE.md`，匹配已有稳定 Case ID。
5. **发现测试缺口 (Coverage Gap Discovery)**：定位哪些新代码路径、异常分支或前端交互尚无对应测试。
6. **新增/更新用例设计 (Case Generation & Update)**：补充覆盖缺口的测试用例，分配稳定 Case ID。
7. **编写测试代码 (Test Implementation)**：在 `tests/` 目录中实现强断言的测试代码。
8. **执行测试 (Test Execution)**：真实运行测试命令，采集退出码与原始标准输出。
9. **修复缺陷 (Defect Resolution)**：根据测试失败日志精准修复源码缺陷。
10. **回归验证 (Regression Verification)**：运行关联回归测试，确保新代码未破坏既有功能。
11. **更新测试基线 (Baseline Update)**：同步更新 `docs/TEST-ACCEPTANCE.md`，固化新 Case ID 与映射。
12. **提交源码与文档 (Atomic Commit)**：测试代码、业务源码与基线文档在同一原子变更中提交。
13. **发布前后两阶段测试 (Pre- & Post-Release Testing)**：按 STD-014 §5 与 STD-032 执行两阶段验证。

> **有效性原则**：智能体测试设计不追求盲目增加无意义测试数量，重点在于**提升测试有效性、消除边界盲区、强化断言严格度并对齐真实产品基线**。

---

## 7. 测试设计方法论与断言严格度准则 (Methodologies & Assertion Rigor)

智能体在设计测试用例时，**MUST** 组合以下工程测试方法论：

1. **需求与用户旅程驱动测试**：从用户第一视角验证完整操作闭环（操作 -> API -> 持久化 -> UI 反馈）。
2. **风险驱动测试 (Risk-Driven)**：优先覆盖高危资产（鉴权、计费、路由、数据写操作）。
3. **接口契约测试 (API Contract)**：基于 JSON Schema / OpenAPI 验证请求参数、响应结构及枚举字典。
4. **状态机与转换测试 (State Machine)**：测试状态生命周期的全覆盖及非法转换阻断（如 `DRAFT -> PROD` 未经审阅阻断）。
5. **边界值与异常输入测试**：测试空值、超长字符串、非法编码、特殊字符注入及边界极值。
6. **数据一致性与幂等性测试**：验证重复调用不产生多余副作用，事务回滚保持原子性。
7. **并发、超时、重试与恢复测试**：验证高并发竞争、下游超时降级、退避重试及熔断恢复。
8. **安全、授权与费用保护测试**：零密钥防泄露验证、越权访问拦截、大模型 Token 额度防穿透。
9. **属性测试与变异测试 (Property & Mutation Testing)**：在适用场景下验证不变式假设。
10. **真实生产用户行为测试**：模拟真实用户网络环境与浏览器的实际交互。

### 7.1 历史缺陷生命周期准则 (Defect Lifecycle Rule)
对所有历史 Bug 与线上故障，智能体 **MUST** 遵循：
> **先写失败用例复现缺陷 ──► 针对性修复代码 ──► 验证用例转绿 ──► 永久保留为回归用例**。
严禁为了让流水线通过而删除、修改或 `@unittest.skip` 历史回归用例。

### 7.2 断言严格度与反造假准则 (Assertion Rigor & Truth Invariants)
1. **正向用例强制验证真实业务终态**：
   - 正向业务用例 **MUST** 严格断言实际业务结果（如模型推理生成的真实非空文本、数据库写入的新记录、状态字段更新为期望值）。
   - **MUST NOT** 将技术层面的 `HTTP 200`、目录存在静态文件或返回 `BLOCK` / `CONFIGURED` / `MOCK_ONLY` 视为正向业务 PASS。
2. **负向用例强制验证阻断与降级**：
   - 负向测试用例（如非法 Token、越权参数）**MUST** 严格断言预期的阻断行为（如 HTTP 401/403/422，错误信息匹配安全字典）。
   - 负向用例若意外返回业务成功（200 SUCCESS），**MUST** 判定为测试失败。
3. **严禁弱化断言 (Prohibition of Weakened Assertions)**：
   - 严禁编写 `assert True`、`assert 1 == 1`、`pass` 或仅断言对象非空而忽略业务内容的敷衍断言。

---

## 8. 统一持续测试基线与覆盖门禁 (Continuous Baseline & Coverage Gate)

每个受管工程 **MUST** 按 STD-035 规范在 `docs/TEST-ACCEPTANCE.md` 中维护统一且唯一的测试用例基线。

### 8.1 结构化覆盖验证报告契约 (`test-coverage-verification.schema.json`)
在流水线与发布门禁中，智能体 **MUST** 生成符合 `schemas/test-coverage-verification.schema.json` 的机器可读覆盖报告，并通过 `tools/validate_test_coverage.py` 严格核验：

1. **变更影响覆盖**：核验本次变更影响的需求（`impacted_requirements`）是否均有对应的 Case ID。
2. **关键 Case ID 执行证据**：核验所有 `required_case_ids`（P0 级）均在当次测试中真实执行，且具备原始日志或截图证据（`evidence_ref`）。
3. **状态准确分类**：严禁模糊处理状态，必须精准标示：
   - `PASS`：真实执行且业务断言全部通过。
   - `FAIL`：真实执行且断言失败。
   - `BLOCK`：环境受阻或前置条件不满足。
   - `NOT_RUN`：未运行（严禁冒充 PASS）。
   - `SIMULATED`：候选阶段模拟/Mock 运行。
   - `NOT_VERIFIABLE`：当前环境无法验证。
   - `DEFERRED`：涉及真实生产费用或不可自动化写入而受控延期。
4. **P0 必测门禁**：任一 P0 级 Required 用例缺失、未执行或结果非 PASS，总体状态 **MUST** 判定为 `BLOCK` / `FAIL`，严禁发布。
5. **历史用例防静默移除**：对比历史基线，任何既有用例若不再适用，**MUST** 在 `retired_cases` 中显式注明废弃理由与替代用例，严禁静默删除历史用例。
6. **风险驱动测试集选择 (Risk-Driven Selection)**：在日常局部小修改中，允许智能体根据变更影响分析针对性运行相关组件测试与冒烟集，不强制每次微小提交运行全量数十分钟的超长测试套件；但正式发布候选与部署后验收 **MUST** 完整覆盖关键发布矩阵。
