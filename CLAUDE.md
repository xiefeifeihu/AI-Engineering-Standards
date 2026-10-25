# AI Engineering Standards — Claude Code 交互上下文

- 仓库定位：全平台统一工程规范唯一事实源（Single Source of Truth，当前版本 `2.5.1`）。
- 规范范围：`STD-001` 至 `STD-034`、JSON Schema 清单、通用模板。
- 开始任务前必须先阅读 [`AGENTS.md`](./AGENTS.md)，核验 Git 分支、`VERSION`（`2.5.1`）与 `HEAD Commit`。
- 严禁直接向 `main` 分支提交；所有修改通过独立分支与 PR 合入。

## 常用命令

```powershell
python tools/validate-schemas.py
python scripts/package_acceptance.py --task-id <TASK_ID> --version 2.5.1
```
