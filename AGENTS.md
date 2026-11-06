# AI Engineering Standards — 编码智能体工程治理入口 (AGENTS.md)

> **权威性声明**：本文件 (`AGENTS.md`) 是 `AI-Engineering-Standards` 仓库的项目级编码智能体（Claude Code、Codex、Antigravity 等）统一规则入口。本仓库是全平台工程规范的**唯一事实源 (Single Source of Truth)**（覆盖 `STD-001` 至 `STD-035`；精确版本与锁定状态以 [`VERSION`](./VERSION)、[`standards.lock.json`](./standards.lock.json) 及 [`docs/当前权威基线.md`](./docs/当前权威基线.md) 为准，禁止在说明文档中手工硬编码版本号）。

---

## 1. 强制遵守的十五项工程治理铁律 (Rules A–O, `STD-034`)

- **A. 开始工作先核验 Git 和 Standards**：每次开始任务前，必须首先核验当前 Git 分支、HEAD Commit、工作区修改状态（`git status -sb`），以及 `VERSION`、`standards.lock.json` 与 `HEAD Commit`。
- **B. Standards 是统一规范唯一事实源**：`AI-Engineering-Standards` 是统一规范唯一事实源。下游仓库仅维护 Thin Reference 与机器门禁，不得复制完整 Standards 正文，不得在 `AGENTS.md` / `CLAUDE.md` / `README.md` 中手工写死固定版本号。
- **C. 保护正式 main 与分支安全 (`STD-034`)**：严禁直接在未经验证的 `main` 分支上随意提交或开发。所有开发必须从干净基线创建独立分支。向 `origin/main` 同步前必须通过本地校验与测试，且必须等待目标 Commit 在 GitHub Actions 上的真实远端 CI 全绿；涉及跨文档/规范语义或破坏性 Schema 变更时，必须完成独立 ChatGPT 审核与 Owner 批准（`D2=APPROVED`）；严禁强推（`git push --force`）、严禁绕过分支保护、严禁伪造测试。
- **D. 保护现有工作区**：严禁覆盖、丢弃或清理工作区中已有的未提交修改或历史验收成果。严禁使用 `git reset --hard`、`git clean -fd`、`git push --force`。
- **E. 严格遵守跨仓修改边界**：严格遵循仓库边界（`STD-002` / `STD-017` / `STD-034`），未经任务显式授权不得跨仓修改其他工程（AI-Hub、AI-KB、Sidecar、VTIP）。
- **F. 不提交 Secrets、生产报告正文和私人配置**：严格执行零密钥准则（`STD-007`），不得向 Git 或交付包提交任何密钥、Token、私钥或私人配置。
- **G. 实际运行测试后才能报告 PASS**：所有测试状态必须基于真实执行的测试命令、`exit_code=0` 及原始测试日志输出（`STD-014`）。智能体必须自主履行测试设计与覆盖分析职责，关键 P0 必测用例必须具备真实执行证据，正向业务不能以 BLOCK/CONFIGURED 伪造 PASS，严禁弱化断言或删除用例。
- **H. 单元测试不能替代 Playwright 和真实业务验收**：单元测试仅验证局部逻辑，涉及 UI 变更时必须执行 Playwright 真实浏览器验收（`STD-015`）。正式部署后必须在真实生产入口（`LIVE_COMMIT`）执行端到端业务验收，严禁使用候选端口或 Mock 冒充生产测试。
- **I. 不得伪造模型执行、构建和运行 Commit**：严禁伪造 `SOURCE_COMMIT`、`BUILD_COMMIT`、`LIVE_COMMIT`（`STD-031` / `STD-032`）。
- **J. 不得用静态 JSON 制造高质量验收结果**：严禁编写静态生成脚本伪造测试或验收结果。
- **K. 不得将 HTTP 200 自动认定为业务采纳**：技术请求返回 `HTTP 200` 不等于业务采纳或编码交付完成（`STD-010` / `STD-023`）。正向用例必须验证真实业务成功终态，负向用例必须验证预期阻断。
- **L. 不得伪造独立审核或所有者批准状态 (`D2` / `STD-034 §16`)**：编程智能体严禁自行标记或伪造 `AI_APPROVED`、`OWNER_APPROVED`、`HUMAN_ACCEPTED`。未经真实独立审核与 Owner 批准，不得晋升正式文档或合并受控基线。
- **M. 正式发布必须执行有效 Standards 的 CI/CD**：正式发布必须执行 Schema 校验、文档集合校验、权威基线一致性校验、跨会话交接校验、官方同步工具校验与契约测试门禁。
- **N. 验收目录与 ZIP 目录必须区分**：过程验收证据目录（`.artifacts/acceptance/`）与正式交付 ZIP 目录（`.artifacts/packages/`）必须严格隔离。
- **O. 没有全部证据时不得报告 OVERALL=PASS**：任一关键门禁失败、必交证据缺失或存在未闭环项时，严禁报告 `OVERALL=PASS` 或 `OVERALL_STATUS=PASS`。

---

## 2. `.artifacts/` 制品目录强制规范 (`STD-016` / `STD-019` / `STD-032` / `STD-034`)

1. **`.artifacts/acceptance/<TASK_ID>/v<VERSION>/`**：仅存放过程验收证据（`manifest.json`、`acceptance_report.md`、`test_results.txt`）。
2. **`.artifacts/packages/`**：唯一合法存放正式 Acceptance ZIP 的目录（如 `Acceptance-<TASK_ID>-v<VERSION>.zip` 及 `.sha256`）。
3. **`.artifacts/handoff/temporary/`**：存放跨会话临时交接文档（`STD-020`）。
4. **Git 严格排除**：`.artifacts/` 不得进入 Git。

---

## 3. 标准验证与测试入口

```powershell
python tools/validate-schemas.py
python tools/validate-documentation-collection.py --project-root . --schema schemas/documentation-metadata.schema.json --check-templates
python tools/generate_engineering_baseline.py --project-root . --verify-only
python tools/standards_sync/cli.py verify-lock --project-root .
python tools/validate_test_coverage.py templates/test-coverage-verification.template.json
python -m unittest discover -s tests -v
python scripts/package_acceptance.py --task-id <TASK_ID> --version <VERSION>
```
