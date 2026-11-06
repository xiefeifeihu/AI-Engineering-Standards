# AI Engineering Standards — Claude Code 交互上下文 (CLAUDE.md)

- 仓库定位：全平台统一工程规范唯一事实源（Single Source of Truth，精确版本以 [`VERSION`](./VERSION) 与 [`standards.lock.json`](./standards.lock.json) 为准，禁止手工写死固定版本号）。
- 规范范围：`STD-001` 至 `STD-035`、JSON Schema 清单（`schemas/`）、通用模板（`templates/`）与官方同步及治理工具（`tools/`）。
- 开始任务前必须先阅读 [`AGENTS.md`](./AGENTS.md)、[`docs/DOCUMENT-INDEX.md`](./docs/DOCUMENT-INDEX.md)、[`docs/当前权威基线.md`](./docs/当前权威基线.md) 与 [`docs/CROSS-SESSION-HANDOFF.md`](./docs/CROSS-SESSION-HANDOFF.md)，核验 Git 分支、`VERSION`、`standards.lock.json` 与 `HEAD Commit`。
- 严禁直接向 `main` 分支提交；严禁自行伪造 `AI_APPROVED`、`OWNER_APPROVED`、`HUMAN_ACCEPTED`。

## 常用命令

```powershell
python tools/validate-schemas.py
python tools/validate-documentation-collection.py --project-root . --check-templates
python tools/generate_engineering_baseline.py --project-root . --verify-only
python tools/standards_sync/cli.py verify-lock --project-root .
python -m unittest discover -s tests -v
```
