# CLAUDE.md — AI Engineering Standards 编程客户端入口

> **唯一事实源引用**：本文件是 Claude Code 等客户端的薄入口（Thin Reference），完整工程治理规则请遵循本仓库根目录 [`AGENTS.md`](./AGENTS.md) 与 [`STD-034`](./standards/00-governance/STD-034-coding-agent-execution-governance.md)。

## 1. 核心约束
- 开始任务前必须先阅读 [`AGENTS.md`](./AGENTS.md)，核验 Git 分支、`VERSION`（`2.5.0`）与 `HEAD Commit`。
- 严禁直接修改 `main` 分支，严禁使用 `git reset --hard`、`git clean -fd`、`git push --force`。
- `.artifacts/acceptance/<TASK_ID>/v<VERSION>/` 仅存放过程证据；正式 ZIP 唯一合法路径为 `.artifacts/packages/`；跨会话交接位于 `.artifacts/handoff/temporary/`。

## 2. 必跑校验命令
```powershell
python tools/validate-schemas.py
python scripts/package_acceptance.py --task-id <TASK_ID> --version 2.5.0
```