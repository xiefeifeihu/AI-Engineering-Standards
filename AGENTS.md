# AI Engineering Standards — 编码智能体工程治理入口 (AGENTS.md)

> **权威性声明**：本文件 (`AGENTS.md`) 是 `AI-Engineering-Standards` 仓库的项目级编码智能体（Claude Code、Codex、Antigravity 等）统一规则入口。本仓库是全平台工程规范的**唯一事实源 (Single Source of Truth)**（当前版本：`2.6.0`，覆盖 `STD-001` 至 `STD-034`）。

---

## 1. 强制遵守的十五项工程治理铁律 (Rules A–O, `STD-034`)

- **A. 开始工作先核验 Git 和 Standards**：每次开始任务前，必须首先核验当前 Git 分支、HEAD Commit、工作区修改状态（`git status -sb`），以及 `VERSION` 与 `HEAD Commit`。
- **B. Standards 是统一规范唯一事实源**：`AI-Engineering-Standards` 是统一规范唯一事实源。下游仓库仅维护 Thin Reference 与机器门禁，不得复制完整 Standards 正文。
- **C. 不直接修改 main**：严禁直接在 `main` 分支上开发或直接向 `main` 提交代码。必须从干净基线创建独立分支，通过 PR 与 Schema 校验门禁后合入。
- **D. 保护现有工作区**：严禁覆盖、丢弃或清理工作区中已有的未提交修改或历史验收成果。严禁使用 `git reset --hard`、`git clean -fd`、`git push --force`。
- **E. 严格遵守跨仓修改边界**：严格遵循仓库边界（`STD-002` / `STD-017` / `STD-034`），未经任务授权不得跨仓修改其他工程。
- **F. 不提交 Secrets、生产报告正文和私人配置**：严格执行零密钥准则（`STD-007`），不得向 Git 或交付包提交任何密钥、Token 或私人配置。
- **G. 实际运行测试后才能报告 PASS**：所有 Schema 与样例校验状态必须基于真实执行的 `python tools/validate-schemas.py`（`exit_code=0`）及原始日志输出（`STD-014`）。
- **H. 单元测试不能替代 Playwright 和真实业务验收**：涉及下游 UI 变更时必须执行 Playwright 真实浏览器验收（`STD-015`）。
- **I. 不得伪造模型执行、构建和运行 Commit**：严禁伪造 `SOURCE_COMMIT`、`BUILD_COMMIT`、`LIVE_COMMIT`（`STD-031` / `STD-032`）。
- **J. 不得用静态 JSON 制造高质量验收结果**：严禁编写静态生成脚本伪造测试或验收结果。
- **K. 不得将 HTTP 200 自动认定为业务采纳**：技术请求返回 `HTTP 200` 不等于业务采纳或编码交付完成（`STD-010` / `STD-023`）。
- **L. 不得自动提交人工审核 PASS**：未经真实人工审阅确认，不得自动标记人工审核为 `PASS`。
- **M. 正式发布必须执行有效 Standards 的 CI/CD**：正式发布必须执行 `python tools/validate-schemas.py` 与打包校验门禁。
- **N. 验收目录与 ZIP 目录必须区分**：过程验收证据目录（`.artifacts/acceptance/`）与正式交付 ZIP 目录（`.artifacts/packages/`）必须严格隔离。
- **O. 没有全部证据时不得报告 OVERALL=PASS**：任一关键门禁失败或证据缺失时，严禁报告 `OVERALL=PASS` 或 `OVERALL_STATUS=PASS`。

---

## 2. `.artifacts/` 制品目录强制规范 (`STD-016` / `STD-019` / `STD-032` / `STD-034`)

1. **`.artifacts/acceptance/<TASK_ID>/v<VERSION>/`**：仅存放过程验收证据（`manifest.json`、`acceptance_report.md`、`test_results.txt`）。
2. **`.artifacts/packages/`**：唯一合法存放正式 Acceptance ZIP 的目录（如 `Acceptance-<TASK_ID>-v<VERSION>.zip` 及 `.sha256`）。
3. **`.artifacts/handoff/temporary/`**：存放跨会话临时交接文档（`STD-020`）。
4. **Git 严格排除**：`.artifacts/` 不得进入 Git。

---

## 3. 标准验证与打包入口

```powershell
python tools/validate-schemas.py
python scripts/package_acceptance.py --task-id <TASK_ID> --version <VERSION>
```
