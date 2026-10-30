---
document_id: "DOC-TEST-ACCEPTANCE-001"
document_version: "1.1.0"
project_id: "example-project"
document_type: "TEST_ACCEPTANCE"
status: "ACTIVE"
applies_to_release: "v1.1.0"
last_updated: "2026-10-30"
supersedes: "DOC-TEST-ACCEPTANCE-000"
change_summary: "升级为 STD-014/STD-035 统一持续测试用例基线规范模板"
history_reference: null
primary_entrypoint: true
---

# 测试规范与持续验收基线 (Test & Acceptance Baseline)

> **治理契约**：本文件遵循 `STD-014`（分层测试与自主用例生成）、`STD-015`（Playwright 浏览器端到端验收）、`STD-031`（运行时验收）、`STD-032`（发布工程与两阶段验收）、`STD-034`（智能体执行治理与防造假门禁）及 `STD-035`（全生命周期文档契约）。每个工程仓库必须维护且仅维护一份最新全量的 `docs/TEST-ACCEPTANCE.md`，并在每次功能变更、Bug 修复与迭代发布时持续增量更新用例基线与执行映射。

---

## 1. 测试策略与分层架构 (Test Strategy & Architecture)

全平台严格执行四层分级与发布两阶段自动化验收体系：

### 1.1 四层测试分级 (Four-Level Testing Matrix)
- **L1 - SMOKE (快速冒烟)**：核心路径启动与依赖配置健康，执行耗时 < 30 秒，不依赖外部网络与模型 API。
- **L2 - CORE (单元与契约)**：全量业务逻辑单元、API 契约一致性（OpenAPI / JSON Schema）、状态机转换与边界值验证（禁止启动浏览器）。
- **L3 - DEEP (运行时与 Playwright 界面验收)**：端到端用户旅程、明暗双主题切换、关键按钮与交互后真实持久化数据校验（Headless 模式，录像与截图归档至 `.artifacts/`）。
- **L4 - DIAGNOSTIC (诊断与探针)**：运行时探针、KPI 基线、内存/连接池检测及跨组件拓扑连通性校验。

### 1.2 发布两阶段验收因果律 (Two-Stage Release Acceptance)
1. **Stage 1 (PRE_RELEASE_QUALIFICATION)**：
   - 候选环境执行 L1-L3 测试，验证逻辑正确性与部署准入，允许受控 Mock 与异常注入。
   - 结论通过仅表示允许进入部署阶段，严禁将其作为生产已可用的依据。
2. **Stage 2 (POST_DEPLOY_REAL_ACCEPTANCE)**：
   - 在部署后的真实目标环境入口（绑定的 `LIVE_COMMIT`）执行真实生产冒烟与用户旅程。
   - 必须断言真实业务输出（如模型推理实际成功响应、数据库持久化记录、UI 状态恢复），严禁以 HTTP 200、目录有文件或静态截图存在冒充业务 PASS。

---

## 2. 产品需求与测试映射矩阵 (Requirement-to-Test Mapping)

| 需求 ID | 产品功能与用户旅程 | 风险等级 | 适用阶段 | 覆盖用例 (Case ID) | 测试状态 |
|:---|:---|:---|:---|:---|:---|
| `REQ-FEAT-001` | 用户认证与 Token 鉴权 | `HIGH` | PRE / POST | `TC-AUTH-001`, `TC-AUTH-002` | `PASS` |
| `REQ-FEAT-002` | 模型路由智能决策 | `CRITICAL` | PRE_RELEASE | `TC-ROUTING-001`, `TC-ROUTING-002` | `PASS` |
| `REQ-FEAT-003` | 控制大盘 UI 与暗黑主题 | `MEDIUM` | PRE / POST | `TC-UI-DASHBOARD-001` | `PASS` |
| `REQ-FEAT-004` | 任务执行结果异步回写 | `HIGH` | POST_DEPLOY | `TC-ASYNC-RESULT-001` | `DEFERRED` |

---

## 3. 权威测试用例清单 (Canonical Test Case Inventory)

| Case ID | 需求关联 | 优先级 | 执行阶段与模式 | 测试代码入口 (`test_path::test_name`) | 业务预期结果与断言严格度 | 当前状态 | 证据引用 (.artifacts/) |
|:---|:---|:---:|:---|:---|:---|:---:|:---|
| `TC-AUTH-001` | `REQ-FEAT-001` | `P0` | PRE_RELEASE<br>`AUTOMATED_UNIT` | `tests/unit/test_auth.py::test_valid_login` | Token 签发合法且 Payload 角色正确；强业务断言 | `PASS` | `evidence/pre/test_results.txt` |
| `TC-AUTH-002` | `REQ-FEAT-001` | `P0` | PRE_RELEASE<br>`AUTOMATED_CONTRACT` | `tests/contract/test_auth.py::test_invalid_token_401` | 严格返回 401 且拒绝越权访问；负向阻断断言 | `PASS` | `evidence/pre/test_results.txt` |
| `TC-ROUTING-001`| `REQ-FEAT-002` | `P0` | PRE_RELEASE<br>`AUTOMATED_UNIT` | `tests/unit/test_router.py::test_champion_selection` | 高画质与低延迟诉求准确匹配最优通道；强业务断言 | `PASS` | `evidence/pre/test_results.txt` |
| `TC-UI-DASH-001`| `REQ-FEAT-003` | `P1` | POST_DEPLOY<br>`LIVE_BROWSER` | `tests/e2e/test_dashboard.py::test_ui_theme_toggle` | 按钮点击 -> 属性变更 -> 无控制台 JS 报错 -> 截图核验 | `PASS` | `evidence/post/screenshots/` |
| `TC-ASYNC-001`  | `REQ-FEAT-004` | `P1` | POST_DEPLOY<br>`LIVE_API` | `tests/runtime/test_async.py::test_result_callback` | 真实长任务回调；涉及三方生产写入，受控延期 | `DEFERRED` | 见已知缺口说明 |

> **注：用例断言严格度准则**：
> 1. 正向用例必须断言真实业务终态（例如真实的成功报文、正确字段值），严禁将 `BLOCK`、`CONFIGURED` 或简单的 `HTTP 200` 视为测试 PASS。
> 2. 负向用例必须断言阻断原因（如 HTTP 401/403/422）及预期的安全边界。
> 3. 严禁弱化断言（如 `assert True`、`assert 1==1` 或无断言执行）。

---

## 4. 历史缺陷复现与永久回归矩阵 (Historical Defect Regression Matrix)

对所有生产级故障与历史 Bug，智能体必须遵循**先编写复现用例、再修复代码、最后纳入永久自动化回归**原则：

| 缺陷编号 (Defect ID) | 关联需求 | 根本原因描述 | 复现测试用例 | 修复代码 Commit | 永久回归测试入口 | 验证状态 |
|:---|:---|:---|:---|:---|:---|:---:|
| `BUG-2026-042` | `REQ-FEAT-001` | Token 过期边界时间差导致重试死循环 | `TC-AUTH-REG-042` | `abc1234` | `tests/regression/test_bug_042.py` | `PASS` |
| `BUG-2026-078` | `REQ-FEAT-002` | 备用通道健康状态未初始化导致穿透 | `TC-ROUTING-REG-078` | `def5678` | `tests/regression/test_bug_078.py` | `PASS` |

---

## 5. 已知测试缺口与延期项 (Known Test Gaps & Deferred Items)

对于涉及真实生产费用、外部生产数据破坏性修改或需人工主观审阅的场景，必须在此登记，严禁在自动化流水线中静默忽略或虚构 PASS：

| 缺口 ID | 关联需求 | 风险等级 | 未覆盖/延期原因 | 阻断缓解措施 | 计划解决版本 |
|:---|:---|:---:|:---|:---|:---:|
| `GAP-001` | `REQ-FEAT-004` | `MEDIUM` | 涉及付费三方 SMS 短信验证码发送，自动化仅测试 Mock | PRE 使用 Mock 测试；POST 由人工抽样真实核验 | `v1.2.0` |

---

## 6. 测试代码与制品存储隔离规范 (Code & Artifact Isolation)

- **测试源码**：统一存放于 `tests/`（按 `unit/`, `contract/`, `integration/`, `runtime/`, `e2e/`, `regression/` 组织），受 Git 版本控制。
- **执行过程证据**：测试执行日志、Playwright 截图、录屏与 Trace 统一输出至 `.artifacts/acceptance/<TASK_ID>/v<VERSION>/`，受 `.gitignore` 严格排除，**严禁将测试媒体文件提交至 Git**。
- **发布制品包**：正式验收 ZIP 必须输出至 `.artifacts/packages/`，严禁存放在仓库根目录或过程证据目录下。

---

## 7. 追溯版本历史 (Traceable Version History)

| 文档版本 | 生效发布版本 | 修订日期 | 修订人 / Agent | 变更要点摘要 |
|:---|:---|:---|:---|:---|
| `1.1.0` | `v1.1.0` | `2026-10-30` | Standards Owner | 升级为持续用例基线规范模板，补充分层策略、稳定 Case ID 与回归矩阵 |
| `1.0.0` | `v1.0.0` | `2026-10-27` | Standards Owner | 初始文档基线模板 |
