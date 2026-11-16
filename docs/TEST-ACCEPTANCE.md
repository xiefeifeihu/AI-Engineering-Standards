---
document_id: "DOC-STANDARDS-TEST-ACCEPTANCE"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "TEST_ACCEPTANCE"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "9687f961b22df612c4311961e06fc1c1fd508c37"
applies_to_release: "v3.0.0"
last_updated: "2026-11-16"
supersedes: null
change_summary: "补充 Std-020 F01-F07 回归验收用例及历史快照、消费端工作区边界测试。"
history_reference: "CHANGELOG.md"
primary_entrypoint: true
content_sha256: null
---


# 测试策略、用例基线与验收手册 (Test & Acceptance Baseline)

## 1. 分层测试架构与执行入口 (`STD-014` / `STD-034`)

- **Schema 与契约层校验**：`python tools/validate-schemas.py`（覆盖全部 30 个 JSON Schema 语法、正负样本与双路径 Manifest Schema 等价性断言）。
- **文档集合与模板校验**：`python tools/validate-documentation-collection.py --project-root . --check-templates`（覆盖 12 类正式文档模板与 17 项集合规则）。
- **权威基线确定性校验**：`python tools/generate_engineering_baseline.py --project-root . --verify-only`（验证 18 项基线要素、6 项动态溯源属性及无冲突确定性生成）。
- **单元测试与契约回归套件**：`python -m unittest discover -s tests -v`（覆盖 `tests/` 下全部自动化测试模块）。

## 2. 核心必测用例矩阵 (P0 持续用例基线)

| 用例 ID | 测试分类 | 测试目标 | 预期结果与强断言 | 自动化测试位置 |
| :--- | :--- | :--- | :--- | :--- |
| `TC-SCHEMA-001` | Schema 测试 | 全部 30 个 Schema 合法性与 12 个文档模板合规 | Draft 2020-12 校验全绿；12 个模板全部通过 Frontmatter 校验 | `tests/test_baseline_sync_and_approval_governance.py` |
| `TC-SCHEMA-002` | Schema 负向测试 | 拦截已移除的 `HISTORICAL_ARCHIVE` 作为 `document_type` | `jsonschema.ValidationError` 精确拦截 | `tests/test_baseline_sync_and_approval_governance.py` |
| `TC-DOC-001` | 文档集合测试 | 缺失 `DOCUMENT-INDEX` 或缺失 `ENGINEERING_BASELINE` | 校验失败并返回 `MISSING_DOCUMENT_INDEX` / `MISSING_ENGINEERING_BASELINE` | `tests/test_baseline_sync_and_approval_governance.py` |
| `TC-DOC-002` | 文档集合测试 | 缺失唯一主入口或同一类型存在多个 `ACTIVE` 主入口 | 校验失败并拒绝自动猜测主入口 | `tests/test_baseline_sync_and_approval_governance.py` |
| `TC-DOC-003` | 文档集合测试 | 坏链、坏锚点、`project_id` 错误、归档文档标为主入口 | 精确识别并返回对应错误码 | `tests/test_baseline_sync_and_approval_governance.py` |
| `TC-DOC-004` | 文档集合测试 | 缺少审批证据或跨文档 `source_commit` 不一致/不存在 | 精确阻断并返回 `SOURCE_COMMIT_MISMATCH` / `UNVERIFIABLE_SOURCE_COMMIT` | `tests/test_baseline_sync_and_approval_governance.py` |
| `TC-SYNC-001` | 同步工具测试 | 最新正式 Tag 发现、SemVer 排序、Tag 对象与 Peeled Commit 校验 | 正确识别最新 Tag，拦截未打 Tag Commit、Tag 漂移、降级与未发布 Commit | `tests/test_baseline_sync_and_approval_governance.py` |
| `TC-SYNC-002` | 同步工具测试 | CI 失败阻断、网络超时返回 `NOT_VERIFIABLE`、晋升与回滚闭环 | `ci_status!=PASS` 阻断晋升；超时返回 `NOT_VERIFIABLE`；`rollback` 精确恢复历史锁 | `tests/test_baseline_sync_and_approval_governance.py` |
| `TC-APPR-001` | 审批真实性测试 | 拦截编程智能体自批 `AI_APPROVED` / `OWNER_APPROVED` | 拒绝 `CODING_AGENT` 审批人；篡改文档正文或 Commit 后原审批立即失效 | `tests/test_baseline_sync_and_approval_governance.py` |
| `TC-PLAT-001` | 跨平台测试 | 扫描 `tools/` 无硬编码 `D:/Projects` 等机器私有路径 | Windows 与 Linux 环境统一通过 | `tests/test_baseline_sync_and_approval_governance.py` |


## 3. 消费端集成契约测试

- `TC-CONSUMER-001`：缺少 `standards.lock.json` 时，版本比较/影响分析不得静默回退到固定历史版本。
- `TC-CONSUMER-002`：发现工具只能访问官方仓库 `xiefeifeihu/AI-Engineering-Standards`，任意 Fork 或非官方 Remote 必须阻断。
- `TC-CONSUMER-003`：模板不得将某一历史正式版本写成所有工程的默认最新版本。
- `TC-CONSUMER-004`：迁移计划仅将 AI-Engineering-Hub 标记为首个试点；AI-KB、VTIP、SideCar 不得被静态标记为兼容或要求升级。
- `TC-CONSUMER-005`：兼容性维度未执行测试/安全/业务回归时，结果必须保持 `NOT_RUN` 或 `NOT_VERIFIABLE`，不得汇总为 `COMPATIBLE`。
- `TC-CONSUMER-006`：官方 Tag 祖先核验区分 Git 退出码 0/1/其他；对象缺失必须为 `NOT_VERIFIABLE`，不得误报 `NOT_ON_MAIN_BRANCH`。
- `TC-CONSUMER-007`：本地 Clone 发现结果不得冒充官方远端 main；多行 HTML 注释中的历史版本和 SHA 不得被扫描为当前规则，任意 Windows 盘符/UNC 绝对路径必须带文件行号报告。
- `TC-CONSUMER-008`：消费端 HEAD 与 Standards 输入/目标 Commit 独立记录；工作区 DIRTY 或 HEAD 不可读时 `CONSUMER_VERIFICATION_STATUS=NOT_VERIFIABLE`，影响分析不得报告完整兼容。
- `TC-CONSUMER-009`：历史快照只有在记录的 local_head 与当前分支 HEAD 相同或经 Git 对象图证明为当前分支/官方 main 祖先时才豁免 24 小时窗口；非祖先与谱系不可核验分别阻断。
- `TC-CONSUMER-010`：历史快照的 captured_at、分支身份、local_head 和 remote main at capture 必须与真实 Git 历史一致；不得通过手工改时间或仅添加 RELEASED/COMPLETED 标记绕过。
