---
document_id: "DOC-STANDARDS-DECISION-RECORD"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "DECISION_RECORD"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "cdc3a7babe50fff69c52da406a0a2745b442ac14"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "Authoritative Architecture Decision Records (ADRs) for AI-Engineering-Standards including Owner-approved decisions D1 through D5."
history_reference: "CHANGELOG.md"
primary_entrypoint: true
content_sha256: null
---


# 架构与治理决策记录 (Architecture Decision Record - ADR)

## 1. 已由所有者正式批准的治理决策 (`D1`–`D5`)

| 决策编号 | 决策主题 | 决策内容摘要 | 审批状态 | 生效版本 |
| :--- | :--- | :--- | :--- | :--- |
| **`D1`** | 12 类正式文档分类与历史归档语义收敛 | 正式 `document_type` 调整为 12 类（新增 `ENGINEERING_BASELINE`，移除 `HISTORICAL_ARCHIVE` 枚举）。历史归档属于文档生命周期（`status=ARCHIVED` 或 `SUPERSEDED`, `primary_entrypoint=false`）及目录分类，保留原有语义类型，严禁静默篡改历史文档含义。 | `OWNER_APPROVED` | `v3.0.0` |
| **`D2`** | 双层文档治理与审批防伪造契约 | 建立“编程智能体维护 -> ChatGPT 跨文档及事实审核 -> 按策略判断 Owner 批准 -> Git 固化 -> Project Sources 同步”闭环。严格分离 `chatgpt_review` 与 `owner_approval` 记录，绑定文档版本、Commit 与 SHA-256；编程智能体严禁自行伪造 `AI_APPROVED`、`OWNER_APPROVED`、`HUMAN_ACCEPTED`；不确定时默认要求 Owner 批准。 | `OWNER_APPROVED` | `v3.0.0` |
| **`D3`** | 官方 `main` 唯一主干与四元组精确锁定 | `AI-Engineering-Standards` 官方 `main` 是唯一规范维护主干，正式 Tag 必须来自通过 `main` CI 的 Commit。各工程必须通过 `standards.lock.json` 精确锁定 `VERSION`、`TAG`、`TAG_OBJECT_SHA`、`PEELED_COMMIT`，禁止使用浮动 `main` 或在 `AGENTS.md`/`README.md` 手工硬编码版本号。 | `OWNER_APPROVED` | `v3.0.0` |
| **`D4`** | 规范与共享工具独立自治维护 | `AI-Engineering-Standards` 独立设计、实现和维护全部官方规范与共享工具（`tools/standards_sync/`），不将 `AI-KB` 或 `AI-Engineering-Hub` 作为工具属主或运行依赖。 | `OWNER_APPROVED` | `v3.0.0` |
| **`D5`** | 下游工程自动发现与受控升级策略 | 其他工程编码智能体在任务启动及巡检时自动发现最新正式发布规范；兼容性通过且满足审批策略后自动更新锁定，不兼容时强制 `BLOCK`（`UPGRADE_BLOCKED`），禁止静默跳过或降级。 | `OWNER_APPROVED` | `v3.0.0` |

## 2. 迁移与演进关联文档

- `v3.0.0` 跨工程迁移指南参见：[`docs/migration/MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md`](./migration/MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md)
- `v2.11.0` AI 自主测试治理迁移指南参见：[`docs/migration/MIGRATION-GUIDE-AI-DRIVEN-TEST-GOVERNANCE-v2.11.0.md`](./migration/MIGRATION-GUIDE-AI-DRIVEN-TEST-GOVERNANCE-v2.11.0.md)
