---
document_id: "DOC-STANDARDS-RELEASE-OPERATIONS"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "RELEASE_OPERATIONS"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "5e17c0ef560ab8abafe880b988d70f85f380a104"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "Release & Operations Manual for AI-Engineering-Standards v3.0.0 covering Draft PR gate, independent review, main CI verification, and Annotated Tag governance."
history_reference: "standards/13-git-release/STD-017-git-release-versioning.md"
primary_entrypoint: true
content_sha256: "sha256:7be94368a1ceb8f8bba773cd39f07a1490aa73618a3d1fe69752f163b9eed64e"
---


# 发布、部署与运维手册 (Release & Operations Manual)

## 1. 官方主干发布与 Tag 签发规程 (`D2` / `D3` / `STD-017` / `STD-032`)

1. **独立分支开发与本地全量门禁**：
   - 从干净 `main` 基线创建特性分支（如 `feat/standards-baseline-sync-governance`）。
   - 依 SemVer 规则更新 `VERSION` 与 `CHANGELOG.md`。
   - 本地运行 Schema、17 项文档集合、权威基线、跨会话交接、官方同步工具与全量单元测试门禁，确保 `exit_code=0`。
2. **Draft PR 与远端 CI 验证**：
   - 推送特性分支至远端并创建指向 `main` 的 **Draft PR**，触发 `.github/workflows/standards-ci.yml` 在远端 GitHub Actions Runner 上完成跨平台（Linux + Windows）验证。
3. **独立 ChatGPT 审核与 Owner 批准 (`D2=APPROVED`)**：
   - 将 Draft PR 审查包提交给 ChatGPT 进行跨文档及事实独立审核。
   - 涉及规范语义或破坏性 Schema 变更时，必须由仓库所有者（Owner）明确批准后方可合入 `main`。
4. **合入 `main` 与正式 Annotated Tag 签发**：
   - 经 Owner 批准并合入 `main` 后，等待 `main` 分支 CI 运行全绿。
   - 基于通过 `main` CI 的 Commit 创建 Annotated Tag（`git tag -a vX.Y.Z -m "Release vX.Y.Z"`）并推送远端。

## 2. 回滚与应急处置规程

- **规范发布前阻断**：若 Draft PR 远端 CI、ChatGPT 审核或 Owner 审批未通过，保持 Draft 状态在特性分支修正，严禁合入 `main` 或创建正式 Tag。
- **下游工程同步回滚**：若下游工程在升级后发现回归异常，执行 `python tools/standards_sync/cli.py rollback --project-root <PROJECT_ROOT>` 立即恢复 `previous_locks` 中的上一版已验证四元组锁定。
