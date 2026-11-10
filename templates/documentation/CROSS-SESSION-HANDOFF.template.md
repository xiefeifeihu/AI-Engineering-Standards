---
document_id: "DOC-CROSS-SESSION-HANDOFF-001"
document_version: "2.0.0"
project_id: "example-project"
document_type: "CROSS_SESSION_HANDOFF"
status: "CANDIDATE"
applies_to_release: "v1.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "跨会话工作交接自动化契约模板 (STD-020 v2.0.0)"
history_reference: null
primary_entrypoint: true
source_commit: null
approval_scope: "AI_APPROVABLE"
approval_status: "NOT_SUBMITTED"
content_sha256: null
approval_evidence_ref: null
---

# 跨会话工作交接 (Cross-Session Handoff)

> **强制规则 (`STD-020` v2.0.0)**：本文件是工程唯一当前交接主入口（`docs/CROSS-SESSION-HANDOFF.md`）。新会话进入仓库时必须重新核验实时 Git、Standards 锁定、CI 与 Runtime 事实，严禁仅凭旧聊天摘要推断工程状态。

## 1. 当前 Git 与分支身份 (`git_state`)
- **当前分支 (`branch`)**：`main`
- **本地 HEAD (`local_head`)**：`0000000000000000000000000000000000000000`
- **远端 HEAD (`remote_head`)**：`0000000000000000000000000000000000000000`
- **工作区干净度 (`worktree_clean`)**：`true`
- **工作区状态摘要 (`status_summary`)**：`## main...origin/main`

## 2. 当前 Standards 锁定 (`standards_lock`)
- **规范仓库 (`repository`)**：`xiefeifeihu/AI-Engineering-Standards`
- **锁定版本 (`version`)**：`3.0.0`
- **锁定 Tag (`tag`)**：`v3.0.0`
- **Tag Object SHA (`tag_object_sha`)**：`0000000000000000000000000000000000000000`
- **Peeled Commit (`peeled_commit`)**：`0000000000000000000000000000000000000000`

## 3. 实际测试结果汇总 (`test_results`)
- **核验状态 (`verification_status`)**：`NOT_RUN`
- **执行命令 (`command`)**：`python -m unittest discover -s tests -v`
- **退出码 (`exit_code`)**：`null`
- **通过 / 失败数**：`0 / 0`
- **证据引用 (`evidence_ref`)**：`NOT_RUN`

## 4. 远端 CI 关联 (`ci_run`)
- **Run ID (`run_id`)**：`null`
- **工作流 (`workflow`)**：`.github/workflows/standards-ci.yml`
- **目标 Commit (`commit`)**：`NOT_RUN`
- **核验状态 (`verification_status`)**：`NOT_RUN`
- **证据引用 (`evidence_ref`)**：`NOT_RUN`

## 5. 已完成事项 (`completed_items`)
- 暂无（以实时采集为准）。

## 6. 未完成事项 (`pending_items`)
- 暂无（以实时采集为准）。

## 7. 阻断项 (`blockers`)
- 无阻断项。

## 8. 已批准决策 (`approved_decisions`)
- 记录已获 `OWNER_APPROVED` 或 `AI_APPROVED` 的正式决策及引用。

## 9. 待审批建议事项 (`proposed_items`)
- 记录状态为 `PROPOSED` 的待审批事项（严禁混入已批准决策）。

## 10. 下一会话启动指引 (`next_session_guide`)
1. **必读文档顺序**：
   - `docs/DOCUMENT-INDEX.md`
   - `docs/当前权威基线.md`
   - `docs/CROSS-SESSION-HANDOFF.md`
   - `docs/PROJECT-BLUEPRINT.md`
   - `docs/PRODUCT-BASELINE.md`
   - `docs/SYSTEM-ARCHITECTURE.md`
   - `docs/API-CONTRACT.md`
2. **启动实时重核验命令**：
   - `git status -sb && git rev-parse HEAD`
   - `python tools/standards_sync/cli.py verify-lock --project-root .`
   - `python tools/validate-documentation-collection.py --project-root .`
