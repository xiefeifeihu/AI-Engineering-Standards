---
document_id: "DOC-STD014-CONTINUOUS-TEST-GOVERNANCE-PROPOSAL"
document_version: "0.1.0"
project_id: "ai-engineering-standards"
document_type: "DECISION_RECORD"
status: "DRAFT"
applies_to_release: "future-after-v2.10.0"
last_updated: "2026-10-29"
supersedes: null
change_summary: "Propose a lightweight mandatory product-derived AI-generated test case lifecycle and evidence mapping across projects"
history_reference: null
primary_entrypoint: false
---

# Standards 变更提案：产品基线驱动的 AI 持续用例生成与覆盖验收

> **提案状态 DRAFT，尚非正式 Standards。** 正式事实源仍是 v2.10.0（ba25353ec0f2ba28f187a356ebaeda0cb13e2edd）。修订应由 Standards Owner Agent 完成源码、Schema、Template、Validator、正反契约测试、main CI、正式 Tag；未通过不能自动要求各项目采用本草案。

## 1. 问题陈述

现行 STD-014 已要求四层测试、两阶段发布前后验收、从 PRODUCT-BASELINE 生成用户旅程覆盖矩阵。但缺少可执行的**每次变更影响分析 -> 新用例设计 -> 回归断言 -> 测试代码 -> 生产实测 -> 证据追溯**闭环。业务功能可能多年存在而仍不在测试用例内，出现「26 tests PASS 但运营业务未测」「正向推理 BLOCK 也能 PASS」「发布 Cloud CPA 控制台但生产测试只有临时 Uvicorn 用例」等现象。

目标不是堆测试数量或引入复杂测试平台，而是在既有四层分级和两阶段发布之上加入持续更新的用例基线和关键断言的机器判定。

## 2. 拟修订正式条款

### STD-014：AI 智能体测试设计责任

1. 每次新增功能、修改业务行为、修复缺陷、升级协议/标准/依赖、变更路由/鉴权/运维生命周期，编码 Agent **MUST** 先读取该仓库 PRODUCT-BASELINE、API-CONTRACT、TEST-ACCEPTANCE、Git Diff、相关历史 Bug 与上一版验收报告。
2. Agent **MUST** 自动生成变更影响清单：需求 ID / 产品旅程 -> 涉及模块、API、菜单 -> 已有 Case ID -> 新增或需修改测试 -> 风险 -> 实际用例执行证据。不得依赖用户逐个列测试用例。
3. Bug 修复 **MUST** 有可复现的缺陷用例（失败证据或明确的回归缺口）和对应的修复后回归通过证据；不能通过删除测试、放宽结果允许集合、注释/skip 核心用例让状态变绿。
4. 正向业务用例 **MUST** 检查业务终态和输出；例如真实推理 SUCCESS 要明确等于 PASS，不能将 BLOCK/CONFIGURED、HTTP 200、目录有数据、截图存在判为真实业务成功。
5. 自动补充否定/边界/异常/状态机/重试/并发/数据隔离/成本与权限场景，尤其对历史出现过的虚假绿色结论要增加**反向证据校验用例**。
6. 各项目维护一个版本化权威 TEST_ACCEPTANCE 文档和稳定 Case ID；按项目大小与风险，最小字段为：case_id、requirement_ref、risk、stage、expected_outcome、test_ref、last_run/status、evidence_ref。可以用 Markdown + 机器生成 JSON，不强制采购测试管理平台。
7. 不以固定测试数量、截图张数或覆盖率百分比作为唯一门禁；按风险明确所有 P0关键旅程及变更相关 P1 用例的实际执行状态。P0 必测用例没有运行证据必须 BLOCK；非关键用例不适用时标明理由，不能静默忽略。
8. 单次开发运行影响测试 + 关键业务冒烟；候选发布按 STD-014 L1-L4 完整适用集合；部署后真实用户旅程必须在 LIVE_COMMIT 对应生产入口执行。外部受控系统的写入、破坏性操作和可能计费的测试不得无授权触发，使用安全夹具或只读 API，清晰标示 SIMULATED / DEFERRED 不替代生产 PASS。
9. 允许一个 Agent 负责测试设计与编码，但要求**可复核断言**、证据绑定、至少一个 negative canary；可用独立测试 Agent 审阅难以覆盖的 P0 风险场景，非强制额外组织审批。
10. Agent 可自行生成和维护用例，不需要 ChatGPT 每次重发提示词。ChatGPT/产品负责人提出的新用户场景是额外输入，不是唯一测试来源。

### STD-015：浏览器接受性断言

- 澄清 AUTOMATED_TEST 与 L2 无浏览器约束的旧文案冲突；L3 Browser 的 PRE 和 POST 均可自动执行，按模式记录目标环境。
- 对所有关键按钮，断言 action -> API -> durable state / business output -> reload or query -> evidence；仅断言 is_visible / screenshot / click 不是完整业务测试。
- LIVE_BROWSER 必须写出生产 URL/端口、浏览器版本、Test ID/Case ID、真实响应信息、目标 Commit/镜像；临时 Uvicorn、route.fulfill Mock 只能作为 PRE_RELEASE 确定性测试证据。
- 页面包含 loading、empty、error、unknown，JS console/pageerror/requestfailed 需分类及强断言。
- 录屏与截图按现有 STD-015 规范保存；不能只看截图 Hash 无重复就断言业务内容正确。
- 将「每次 PR」触发语义改为「每次相关变更 / 候选验证」，不重新强制 PR。

### STD-034：编码 Agent 自动测试职责

- Agent 在编码前执行 impact_analysis，定位产品基线未覆盖用例、当前 Diff 受影响用例与最近故障复发用例。
- 对应的实施、测试、文档更新与缺陷回归必须在同一变更提交中被跟踪。
- 每轮自动生成 COVERAGE_GAP/CASE_GENERATED/CASE_EXECUTED/CASE_DEFERRED/CASE_BLOCKED 清单。
- 仅 Mock 成功而真实生产未调用不得标记业务真实成功；人工反馈 Stage C 无真实用户采纳不能自己推断。
- 允许 Agent 完整自主实施，禁止因缺乏强制 PR 而省略远端 main CI、生产回归与版本溯源。

### STD-035：唯一测试基线与历史

- 使用现有 document_type=TEST_ACCEPTANCE，建议根入口 docs/TEST-ACCEPTANCE.md，为最新完整 Test Case Baseline；该目录下版本化历史归档只做回溯。
- 按产品变更同步增加、更新、退休用例；退休必须附可核验产品决策，不能简单删除历史失败项。
- 测试源码在 Git；原始日志、Screenshots、Trace、录屏及敏感化脱敏信息只在 .artifacts。

## 3. 统一轻量机器契约建议

可复用现有 two-stage-release-acceptance schema，通过新增可选 coverage 证据引用（保持向后兼容）或附加独立 coverage-report Schema。最低字段：

- task_id, target_commit, standards_tag, baseline_version, run_id
- required_case_ids, impacted_requirements
- cases: case_id, requirement_ref, priority, execution_mode, stage, test_path, test_name, status, outcome_assertion, evidence_refs
- skipped/deferred reasons, uncovered P0 gaps, overall_status

校验逻辑：
- required_case_ids 每项必须有对应阶段的真实 test execution；缺失 BLOCK。
- P0 真正要求 PASS 的测试结果为 BLOCK/CONFIGURED/MOCK_ONLY 时，整个产品成功验收 BLOCK。
- LIVE_BROWSER 指向生产 URL/身份，不得使用候选端口的执行记录冒充。
- 旧截图、不同 Tag、错镜像、单一 HTTP 200、待部署容器不能作为生产验收成功的证据。
- 机器输出无人工 Token/密钥和个人隐私。

约束：只增强 STD-014/015/034/035 及其必要测试/Schema/Template，不新增额外人工审批，不强制所有任务运行 100+ 场景，不要求每次创建 PR，不跨仓直接修改生产配置。运行费用和执行时间按风险与变更选择适用套件。

## 4. Standards 工程任务执行与验证

1. Read full current STD-014/015/034/035 + related schema/tests and compare proposed additions against existing clauses.
2. Implement minimal normative changes and reconcile outdated statements (e.g. STD-014 old schema count, STD-015 per-PR trigger and L2 browser conflict) without breaking existing consumers.
3. Update tests and schema/template; add positive/negative coverage contract fixtures, including a test where positive inference returns BLOCK yet pytest exits 0 (must be rejected).
4. Run genuine Standards tests, ensure documentation collection validity, report any backwards incompatible constraint and migration plan.
5. Publish new SemVer via normal PERSONAL_LOCAL permitted main CI -> automatically tagged standard flow (not by simply editing VERSION).
6. Notify project owners to discover and **pin** new formal Tag; no direct modification of AI-HUB/AI-KB/SideCar/VTIP by the Standards Agent.

## 5. Hub 首个试点

Hub 当前 v0.22.8 的 105 个拟新增/复核 Case ID 位于分支 feat/ai-hub-continuous-test-baseline-r863 的 docs/TEST-ACCEPTANCE.md。该文档当前为 DRAFT/NOT_IMPLEMENTED，不得冒充 v0.22.8 已实现。由 Hub Agent 将本分支并入正式测试实现工作，先修 P0，再补关键业务旅程，更新 DOCUMENT-INDEX/INVENTORY，之后按两阶段发布。
