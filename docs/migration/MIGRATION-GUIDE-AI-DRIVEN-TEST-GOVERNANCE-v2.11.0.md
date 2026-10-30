---
document_id: "DOC-MIGRATION-GUIDE-AI-TEST-GOVERNANCE-v2110"
document_version: "1.0.0"
project_id: "ai-engineering-standards"
document_type: "DECISION_RECORD"
status: "ACTIVE"
applies_to_release: "v2.11.0"
last_updated: "2026-10-30"
supersedes: null
change_summary: "AI-Driven Autonomous Continuous Test Governance Migration Guide (STD-014/015/031/032/034/035 v2.11.0)"
history_reference: null
primary_entrypoint: false
---

# Standards v2.11.0 迁移指南：AI 自主测试设计与持续用例治理

> **版本定位**：`v2.11.0` 在 `v2.10.0` 基础上，正式确立 AI 智能体自主测试设计契约、持续用例基线维护与十项反向测试机器门禁，彻底终结“测试依赖用户逐条提出”、“ChatGPT 每次重新生成提示词”、“代码通过但业务未测”、“正向返回 BLOCK 冒充 PASS”等测试退化现象。

---

## 一、受管工程核心变更概览

1. **测试设计职责转移**：
   - 编码智能体（Claude Code、Codex、Antigravity 等）在任务开始前，**自动读取 8 项核心事实源**（蓝图、产品基线、系统架构、接口契约、测试基线、Git Diff、缺陷历史、上次真实运行验收报告）。
   - 自主执行 13 阶段闭环：需求分析 -> 变更影响分析 -> 风险识别 -> 已有用例匹配 -> 发现测试缺口 -> 新增/更新用例 -> 编写代码 -> 运行测试 -> 修复缺陷 -> 回归验证 -> 更新基线 -> 提交代码与文档 -> 发布前后测试。
2. **统一测试基线与稳定 Case ID**：
   - 各项目在 `docs/TEST-ACCEPTANCE.md`（按 STD-035 规范）中维护最新全量测试基线，包含测试策略、需求映射、稳定 Case ID、业务预期结果与断言严格度、历史缺陷复现回归矩阵与已知缺口。
3. **断言严格度与真实业务结果优先**：
   - 正向业务用例必须验证实际成功业务输出（如模型真实非空响应、数据库落库成功）；**严禁将 `BLOCK`、`CONFIGURED`、`MOCK_ONLY`、技术 `HTTP 200` 或目录存在文件判定为业务 PASS**。
   - 负向用例必须断言预期阻断（如 401/403/422，错误信息匹配安全字典）；负向用例意外返回 200 SUCCESS 判定为 FAIL。
   - 严禁弱化断言（如 `assert True`、`assert 1==1`、`pass` 或无断言）。
4. **两阶段发布前后测试延续与深化**：
   - `PRE_RELEASE_QUALIFICATION`：候选环境，允许受控 Mock 与异常注入，检验部署准入。
   - `POST_DEPLOY_REAL_ACCEPTANCE`：部署后在真实生产入口（`LIVE_COMMIT`）执行，验证实际业务输出与运行身份。严禁使用临时候选端口（如 8000、3000）或 Mock 冒充生产测试。
5. **轻量机器覆盖报告契约**：
   - 新增 `schemas/test-coverage-verification.schema.json` 与校验工具 `tools/validate_test_coverage.py`。
   - 机器强制检测并拦截 10 种欺诈/失误反向场景（正向 BLOCK 冒充 PASS、关键 P0 缺少执行证据、未运行测试函数、生产使用 Mock、候选端口冒充生产、弱化断言、截图包含 UI 报错、Commit 不一致、缺失影响分析、静默移除历史用例）。

---

## 二、受管项目平滑升级指引

各下游项目（AI-Hub、AI-KB、vtip-ai-sidecar、vtip-platform-catalog）无需采购大型测试管理平台，仅需按以下步骤完成标准化升级：

### 1. 更新测试基线文档
- 依据 `templates/documentation/TEST-ACCEPTANCE.template.md` 规范，初始化或升级项目本身的 `docs/TEST-ACCEPTANCE.md`。
- 将项目中分散的单元与端到端测试整理分配为稳定且可追溯的 Case ID（如 `TC-ROUTING-001`）。

### 2. 缺陷修复遵循三步闭环
- 每次收到 Bug 反馈，智能体必须：**先编写可稳定复现的失败用例 -> 修复源码 -> 验证用例转绿 -> 永久保留在回归用例库中**。
- 严禁注释、删除或跳过历史失败测试。

### 3. 生成与校验测试覆盖报告
- 在流水线或交付打包前，执行测试覆盖验证校验：
  ```powershell
  python tools/validate_test_coverage.py .artifacts/acceptance/<TASK_ID>/v<VERSION>/coverage_report.json --baseline docs/archive/<PREV_VERSION>/coverage_report.json
  ```
- 确保所有变更涉及的 P0 级必测用例均具备真实执行证据。

---

## 三、规范兼容性与免责声明

- **向前兼容性**：`two-stage-release-acceptance.schema.json` 保持向后兼容，可选扩展 `coverage_verification_ref`。
- **免除 PR 政策保持一致**：在 `PERSONAL_LOCAL` 发布模式下，依然保持 STD-034 Rule C，不强制创建或合并 PR，但必须等待目标 main Commit 在 GitHub Actions 上的真实 CI 全绿后才能推进发布。
- **保护生产资源与零凭据**：所有测试严禁向 Git 或交付包提交明文凭据，严禁在生产执行破坏性清库、重启或未授权付费 API 扫描。
