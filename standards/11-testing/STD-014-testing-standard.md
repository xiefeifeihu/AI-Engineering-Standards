# STD-014: Testing Standard (跨项目分层测试规范)

```text
STANDARD_ID=STD-014
VERSION=2.0.0
STATUS=ACTIVE
SCOPE=AI-Engineering-Standards、AI-Engineering-Hub 及跨工程自动化测试
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-29
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
   测试用例 **MUST NOT** 调用破坏性清空命令，**MUST NOT** 删除真实数据集或清空历史有效审计日志。
2. **Standards 仓库测试**：
   必须包含自动化 Schema 校验脚本（`tools/validate-schemas.py`），对所有 9 个 Schema 进行有效性与边界样例回归测试。
3. **Hub 仓库测试**：
   包含针对性单元测试、API 集成测试与端到端 Playwright UI 验收测试。

---

## 2. 四层测试矩阵 (Four-Level Testing Matrix)

所有 AI 工程仓库 **MUST** 实现以下四层测试，并按顺序执行：

| 层级 | 名称 | 触发时机 | 工具 | 目标 |
|------|------|----------|------|------|
| **L1 - SMOKE** | 冒烟测试 | 每次提交 | pytest / shell | 核心路径可用性验证（< 30s）|
| **L2 - CORE** | 核心回归 | 每次提交 / 里程碑 | pytest | 所有单元 + API 集成（< 5min）|
| **L3 - DEEP** | 深度验收 | 里程碑发布前 | pytest + Playwright | 端到端 UI 验收、主题、截图（< 15min）|
| **L4 - DIAGNOSTIC** | 诊断探针 | 按需/生产巡检 | 自定义脚本 | 健康探针、性能基线、Schema 合规 |

### L1 - SMOKE 冒烟测试约束
- **MUST** 在 < 30 秒内完成。
- **MUST** 只测试应用启动、核心路由可达性和关键配置加载。
- **MUST NOT** 依赖外部网络或真实 AI 服务。

### L2 - CORE 核心回归约束
- **MUST** 覆盖所有业务逻辑单元（模型路由、资源注册、健康判定等）。
- **MUST** 包含 API 契约合规测试（按 STD-009、STD-010 等）。
- **MUST NOT** 运行 Playwright 浏览器用例（保留给 L3）。

### L3 - DEEP 深度验收约束
- **MUST** 使用 Playwright Headless 模式运行（参见 STD-015）。
- **MUST** 生成截图和视频证据，输出到 `.artifacts/acceptance/<TASK>/<VERSION>/`。
- **MUST** 覆盖明亮/暗黑双主题。
- **MUST** 在涉及 UI、跨组件或发布里程碑时按风险与产品基线触发；可由自动发布流水线触发，不要求手工运行。

### L4 - DIAGNOSTIC 诊断探针约束
- **MUST** 包含 Schema 合规校验（`tools/validate-schemas.py`）。
- **MUST** 报告模型健康状态与 KPI 指标基线。
- **MAY** 包含性能回归测试。

---

## 3. 测试输出与证据规范

1. 所有测试输出 **MUST** 输出到 `.artifacts/acceptance/<TASK>/<VERSION>/logs/`。
2. Playwright 截图 **MUST** 存放于 `.artifacts/acceptance/<TASK>/<VERSION>/screenshots/`。
3. Playwright 视频 **MUST** 存放于 `.artifacts/acceptance/<TASK>/<VERSION>/videos/`。
4. 测试日志 **MUST NOT** 提交到 Git（受 `.gitignore` 排除）。

---

## 4. 失败处理规范

1. 任何层级测试失败 **MUST** 阻断发布流程。
2. 失败报告 **MUST** 包含：失败测试名称、错误信息、复现步骤。
3. **MUST NOT** 跳过或注释失败测试来强制通过，必须修复根本原因。

---

## 5. 两阶段自动化测试（Stage 1 / Stage 2）

**此处阶段是“发布前/部署后”两次验收，不是把 L1-L4 层级缩减为两级。**

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
