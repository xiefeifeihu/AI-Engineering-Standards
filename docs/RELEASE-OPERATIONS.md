---
document_id: "DOC-STANDARDS-RELEASE-OPERATIONS"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "RELEASE_OPERATIONS"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "9687f961b22df612c4311961e06fc1c1fd508c37"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "Release & Operations Manual for AI-Engineering-Standards v3.0.0 covering Single Owner PR Merge approval governance, Draft PR gate, independent review, main CI verification, and Annotated Tag governance."
history_reference: "standards/13-git-release/STD-017-git-release-versioning.md"
primary_entrypoint: true
content_sha256: null
---


# 发布、部署与运维手册 (Release & Operations Manual)

## 1. 官方主干发布与 Tag 签发规程 (`D2` / `D3` / `STD-017` / `STD-032`)

1. **独立分支开发与本地全量门禁**：
   - 从干净 `main` 基线创建特性分支（如 `feat/standards-baseline-sync-governance`）。
   - 依 SemVer 规则更新 `VERSION` 与 `CHANGELOG.md`。
   - 本地运行 Schema、17 项文档集合、权威基线、跨会话交接、官方同步工具与全量单元测试门禁，确保 `exit_code=0`。
2. **Draft PR 与远端 CI 验证**：
   - 推送特性分支至远端并创建指向 `main` 的 **Draft PR**，触发 `.github/workflows/standards-ci.yml` 在远端 GitHub Actions Runner 上完成跨平台（Linux + Windows）验证。
3. **独立 ChatGPT 技术审查与单人 Owner PR 合并批准 (`GITHUB_PR_MERGE_EVENT`)**：
   - **单人 Owner 模式**：个人工程只有一个合法 Owner（GitHub 仓库实际所有者 `xiefeifeihu`），不要求第二名 Reviewer，不要求创建第二个 GitHub 账号，不要求团队会签或机器人审批。
   - **ChatGPT 技术审查**：将 Draft PR 审查包提交给 ChatGPT 进行跨文档及事实独立技术审查。ChatGPT 结论单独记录为 `READY_FOR_OWNER_MERGE`、`CHANGES_REQUESTED` 或 `BLOCK`；ChatGPT 不得代替 Owner 批准发布，智能体严禁自行批准。
   - **PR 合并即最终批准**：PR 合并前审批状态保持为 `OWNER_APPROVAL_REQUIRED`。PR 作者与仓库 Owner 为同一人时，允许 Owner 直接合并，无需提交自我 PR Review。Owner 通过 GitHub 将审查通过的 PR 合并入 `main` 作为最终批准动作。
   - **溯源真实性验证**：`tools/validate_approval_contract.py` 调用 GitHub PR API 验证 `merged=true`、`merged_by.login == 仓库 Owner`、`base.ref == "main"`、`head.sha == candidate_commit` 且 `merged_at` 非空后，方可将审批状态记录为 `OWNER_APPROVED`。PR 未合入前严禁伪造 `OWNER_APPROVED`。
4. **合入 `main` 与正式 Annotated Tag 自动化签发**：
   - 经 Owner 批准并合入 `main` 后，由 `main` Push 触发 `.github/workflows/standards-ci.yml` 双平台 CI 全量验证。
   - 双平台门禁全绿后，工作流中的 `publish-version-tag` 任务自动创建并推送附注标签（`git tag -a vX.Y.Z`）。
   - **自动化一致性铁律**：正式 Tag 由 GitHub Actions 自动化流程唯一签发，任何用户或智能体不得在自动化成功前手动重复创建或推送同名 Tag，严禁抢跑或伪造发布。

## 2. 回滚与应急处置规程

- **规范发布前阻断**：若 Draft PR 远端 CI、ChatGPT 审核或 Owner 审批未通过，保持 Draft 状态在特性分支修正，严禁合入 `main` 或创建正式 Tag。
- **下游工程同步回滚**：若下游工程在升级后发现回归异常，执行 `python tools/standards_sync/cli.py rollback --project-root <PROJECT_ROOT>` 立即恢复 `previous_locks` 中的上一版已验证四元组锁定。


## 3. 版本与发布生命周期（Version & Release Lifecycle）

Standards 的候选版本与正式发布版本必须严格区分：

| 状态 | 判定条件 | 是否可作为消费端最新正式版本 |
|---|---|---|
| `UNRELEASED` | 变更仅存在工作分支或 Draft PR；CHANGELOG 位于 `[Unreleased]` | 否 |
| `CANDIDATE` | 已有候选 `VERSION`、PR 和候选 Commit，但尚未合入 main | 否 |
| `OWNER_APPROVAL_REQUIRED` | ChatGPT 技术审查通过 (READY_FOR_OWNER_MERGE)，等待 Owner 最终合并 PR | 否 |
| `OWNER_APPROVED / MERGED` | Owner 通过 PR Merge (GITHUB_PR_MERGE_EVENT) 合入 main，main CI 正在运行或待签发 Tag | 否，仍需 main CI 全绿并签发 Tag |
| `RELEASED` | main CI 通过，正式 Annotated Tag 已创建并核验 Tag Object/Peeled Commit/VERSION 一致 | 是 |
| `SUPERSEDED` | 已被更新的正式 Release 替代 | 否，保留历史 |

- `VERSION` 是当前工作树声明的候选版本，不单独证明已发布。
- `CHANGELOG.md` 的 `[Unreleased]` 内容仅在正式 Tag 创建后，才可归档为带发布日期的版本章节。
- `standards.lock.json` 记录工程当前采用的正式版本，不得因候选分支的 `VERSION` 提前升级。
- 消费端发现到候选 Tag 或 main 上未发布 Commit 时，必须返回非正式状态，不得自动晋升。

### 3.1 官方正式版本的权威来源与发现语义 (Authoritative Source vs GitHub Releases)

1. **唯一权威来源：Git Annotated Tag**：
   - 官方正式版本的唯一事实源是 Canonical 规范仓库（`xiefeifeihu/AI-Engineering-Standards`）上的 **Git Annotated Tag**（`refs/tags/vX.Y.Z`）。
   - 判定标准：
     - Tag Object SHA 与 Peeled Commit SHA **严格不等**（拒绝未附注的 lightweight tag）；
     - Peeled Commit 必须是官方 `main` 分支的祖先提交（`git merge-base --is-ancestor <peeled_commit> refs/heads/main`）；
     - Peeled Commit 处的 `VERSION` 文件内容与 Tag 版本严格一致；
     - Peeled Commit 在 GitHub Actions 上的全量 CI 门禁真实运行全绿。
2. **严禁依赖 GitHub Release 对象 (`/releases/latest`)**：
   - GitHub Web 界面或 API 的 `/releases/latest` 返回的是 GitHub Release 对象，属于发布展示层，不等于 Git 真实 Tag。
   - 若某次规范发布仅通过 Git Annotated Tag 签发并推送，但未在 GitHub Web 上手动创建 Release 对象，`/releases/latest` 将停留在旧版本（如 `v2.6.0`），而真实最新正式 Tag 已推进至 `v2.11.0`。
   - 所有官方治理工具（`standards_sync discover`）及下游消费端验证 **MUST NOT** 调用 GitHub `/releases/latest` 接口，必须基于 `git ls-remote --tags` 查询 Annotated Tag。
3. **不可变四元组精确锁定**：
   - 下游工程执行治理时，`standards.lock.json` 必须严格锁定四元组：`repository`、`version`、`tag`、`tag_object_sha`、`peeled_commit`。
   - `standards_sync discover` 属于纯只读探测命令，严禁在未经过 `prepare-upgrade`、`validate-upgrade` 与 Owner 批准前自动修改消费工程的锁定版本。

## 4. 消费端发布边界

Standards v3.0.0 已正式发布。下游接入以 AI-Engineering-Hub 为首个消费端试点。试点计划、当前观测基线和验收边界见 [`migration/MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md`](./migration/MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md)。本 PR 不授权修改 Hub，也不授权 AI-KB、VTIP 或 SideCar 自动升级。其他工程是否接入必须由其各工程 Owner 单独批准。
