# STD-015: Playwright Acceptance Standard (Playwright 界面与端到端验收规范)

```text
STANDARD_ID=STD-015
VERSION=2.11.0
STATUS=ACTIVE
SCOPE=所有 Web UI 控制台、前端脚本与端到端用户旅程的自动化回归与真实验收
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-30
RELATED_STANDARDS=STD-014, STD-016, STD-018, STD-019, STD-031, STD-032, STD-034, STD-035
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 运行模式与分层定位 (Execution Modes & Layering)

Playwright 测试统一归属于 **L3 - DEEP（深度端到端验收）** 及两阶段发布验收（`PRE_RELEASE` 候选验证与 `POST_DEPLOY` 真实生产验证）。**MUST NOT** 将浏览器测试混入 L2 CORE 快速单元回归中。

测试 **MUST** 明确声明运行模式，三种模式各有约束：

| 模式 | 说明 | Headless | 截图 | 视频 | 触发时机 |
|------|------|----------|------|------|----------|
| **AUTOMATED_TEST** | 变更自动化验证（L3 DEEP） | **MUST** Headless | 失败时或关键节点 | 可选 | 涉及 UI / 端到端变更或候选验证 |
| **ACCEPTANCE** | 正式里程碑验收（L3 DEEP） | **MUST** Headless | **MUST** 关键状态截图 | **MUST** 完整交互录制 | 发布前候选与部署后验收 |
| **DEMO** | 演示 / 人机展示（有界面） | **MUST NOT** Headless | **SHOULD** 截图 | **SHOULD** 录制 | 按需人工审阅 |

---

## 2. 界面业务结果强断言准则 (Strong Business Outcome Assertions)

为彻底杜绝“页面点击了就当成功”、“前端有按钮但后端未闭环”、“存在截图但页面显示 Error”等虚假验收现象，Playwright 测试 **MUST** 遵循强断言闭环：

### 2.1 五步操作闭环断言 (Five-Step Action-to-State Assertion)
对页面上的所有关键操作、配置修改与业务触发按钮，测试用例 **MUST** 覆盖：
```text
用户操作 (Click/Input) ──► 触发 API 请求 (Network Hook) ──► 等待持久化状态响应 ──► 页面重载或二次查询 ──► 提取权威证据
```
1. **禁止表面级断言**：仅仅断言元素可见 (`is_visible`)、元素被点击 (`click`) 或页面加载成功，**MUST NOT** 视为业务功能通过。
2. **状态与异常严格捕获**：
   - **加载中状态 (Loading)**：必须断言从加载动画平滑转为最终渲染内容，超时未结束判定为 FAIL。
   - **空状态与异常状态 (Empty & Error)**：严格区分数据为空 (`empty-state`) 与系统错误 (`error-state`)；页面出现未捕获的报错提示、失败徽标（`badge-danger`）或 Toast 异常信息时，**MUST** 判定为 FAIL。
   - **浏览器控制台与网络故障**：Playwright 监听器 **MUST** 捕获 `pageerror`（未捕获的 JS 异常）与 `requestfailed`（非预期的网络请求失败），任一严重报错均阻断验收。
3. **截图有效性核验**：
   - 截图存在不代表业务成功；测试判定逻辑 **MUST NOT** 仅凭截图文件哈希无重复即判定 PASS。
   - 截图必须与对应阶段绑定的 Commit、测试 Case ID 及真实输出状态相互印证。

---

## 3. 环境隔离与真实端点约束 (Environment & Endpoint Invariants)

### 3.1 候选环境测试 (PRE_RELEASE Candidate Verification)
- 在发布前候选构建与 CI 环境中，允许使用隔离的临时服务端口（如 `http://127.0.0.1:8000`）或受控的网络 Mock（如 `route.fulfill`），用于确定性检验前端渲染、CSS 布局与数据交互逻辑。
- 候选环境测试结论仅能标示为 `PRE_RELEASE_STATUS=PASS`，**严禁声称其为生产已验收**。

### 3.2 部署后生产验收 (POST_DEPLOY LIVE_BROWSER)
- 部署目标版本后执行的端到端浏览器验收，**MUST** 使用 `LIVE_BROWSER` 模式。
- **MUST** 指向实际生产暴露的正式入口与端口（如 Hub 的 `80`，Sidecar 的 `8799`，VTIP 的 `8787`，或生产 HTTPS 域名）。
- **MUST NOT** 使用临时开发端口（如 8000、8080、3000、5000）或模拟 Mock 冒充生产端点。
- 必须通过接口核验当前运行态身份（`LIVE_COMMIT`）与发布目标 Commit 严格一致。

---

## 4. 多主题与关键业务矩阵覆盖

1. **多主题无闪烁验证**：
   - **MUST** 验证明亮模式（Light）与暗黑模式（Dark）切换，校验背景色、文字对比度及图标适配，切换过程无 FOUC（样式未加载闪烁）。
2. **核心业务场景矩阵**：
   - 验证服务实例健康呈现（常驻服务与按需服务状态准确区分）；
   - 验证冷启动 / 0 调用状态下成功率与延迟规范展示「暂无数据」，而非显示 `NaN` 或空白崩溃；
   - 验证所有系统状态枚举完全标准化、中文化呈现；
   - 验证 KPI 卡片数值与点击筛选联动行为；
   - 验证输入校验（超长 Prompt、非法字符、格式错误等）在界面的优雅降级与用户友好提示。

---

## 5. 证据存储与打包规范

1. 每次 Playwright 验收运行 **MUST** 输出至 `.artifacts/acceptance/<TASK-ID>/<VERSION>/`：
   - 截图目录：`screenshots/`
   - 录屏目录：`videos/`
   - 跟踪链路：`traces/`（按需开启）
2. 运行完成后生成 `manifest.json`，详细记录运行时间戳、Playwright 与 Chromium 版本、屏幕分辨率、测试 Case ID 清单与执行结果。
3. 过程媒体文件受 `.gitignore` 严格排除，**严禁将测试截图与视频提交到 Git**。正式验收 ZIP 必须通过 `scripts/package_acceptance.py` 打包至 `.artifacts/packages/`。
