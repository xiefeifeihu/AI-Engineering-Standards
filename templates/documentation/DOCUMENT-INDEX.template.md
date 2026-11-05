---
document_id: "DOC-INDEX-001"
document_version: "2.0.0"
project_id: "example-project"
document_type: "DOCUMENT_INDEX"
status: "ACTIVE"
applies_to_release: "v1.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "工程文档总索引（统一12类正式文档与历史归档分类）"
history_reference: null
primary_entrypoint: true
source_commit: "0000000000000000000000000000000000000000"
approval_scope: "AI_APPROVABLE"
approval_status: "AI_APPROVED"
---

# 项目文档总索引 (Document Index)

## 1. 十二类正式权威文档表 (Canonical Living Documents)
| 编号 | 文档类型 (`document_type`) | 权威入口路径 | 文档 ID | 当前版本 | 生命周期状态 (`status`) | 审批状态 (`approval_status`) | 职责概述 |
|:---|:---|:---|:---|:---|:---|:---|:---|
| 01 | `PROJECT_BLUEPRINT` | `docs/PROJECT-BLUEPRINT.md` | DOC-PROJECT-BLUEPRINT-001 | 1.0.0 | ACTIVE | OWNER_APPROVED | 最新全量项目规划蓝图 |
| 02 | `PRODUCT_BASELINE` | `docs/PRODUCT-BASELINE.md` | DOC-PRODUCT-BASELINE-001 | 1.0.0 | ACTIVE | OWNER_APPROVED | 最新权威产品功能基线 |
| 03 | `SYSTEM_ARCHITECTURE` | `docs/SYSTEM-ARCHITECTURE.md` | DOC-SYSTEM-ARCHITECTURE-001 | 1.0.0 | ACTIVE | OWNER_APPROVED | 最新系统架构与拓扑 |
| 04 | `TECHNICAL_DESIGN` | `docs/TECHNICAL-DESIGN.md` | DOC-TECHNICAL-DESIGN-001 | 1.0.0 | ACTIVE | AI_APPROVED | 核心模块技术方案 |
| 05 | `API_CONTRACT` | `docs/API-CONTRACT.md` | DOC-API-CONTRACT-001 | 1.0.0 | ACTIVE | OWNER_APPROVED | 接口与数据契约 |
| 06 | `PROTOTYPE_UX` | `docs/PROTOTYPE-UX.md` | DOC-PROTOTYPE-UX-001 | 1.0.0 | ACTIVE | AI_APPROVED | 可交互原型与交互规范 |
| 07 | `TEST_ACCEPTANCE` | `docs/TEST-ACCEPTANCE.md` | DOC-TEST-ACCEPTANCE-001 | 1.1.0 | ACTIVE | AI_APPROVED | 测试规范与持续验收基线 |
| 08 | `RELEASE_OPERATIONS` | `docs/RELEASE-OPERATIONS.md` | DOC-RELEASE-OPERATIONS-001 | 1.0.0 | ACTIVE | AI_APPROVED | 发布、运维与恢复手册 |
| 09 | `DECISION_RECORD` | `docs/DECISION-RECORD.md` | DOC-DECISION-RECORD-001 | 1.0.0 | ACTIVE | OWNER_APPROVED | 已批准架构决策记录 |
| 10 | `CROSS_SESSION_HANDOFF` | `docs/CROSS-SESSION-HANDOFF.md` | DOC-CROSS-SESSION-HANDOFF-001 | 2.0.0 | ACTIVE | AI_APPROVED | 当前跨会话工作交接 |
| 11 | `DOCUMENT_INDEX` | `docs/DOCUMENT-INDEX.md` | DOC-INDEX-001 | 2.0.0 | ACTIVE | AI_APPROVED | 工程文档总索引 |
| 12 | `ENGINEERING_BASELINE` | `docs/当前权威基线.md` | DOC-ENGINEERING-BASELINE-001 | 1.0.0 | ACTIVE | AI_APPROVED | 当前权威基线自动综合视图 |

## 2. 历史归档映射表 (Historical Archive Classification Mapping)
> 历史归档文档保留原有业务 `document_type`，生命周期状态设为 `ARCHIVED` 或 `SUPERSEDED`，且 `primary_entrypoint: false`。

| 归档路径 | 原语义类型 (`document_type`) | 生命周期状态 | 历史版本 | 关联 Tag | 替代它的权威文档 | 说明 |
|:---|:---|:---|:---|:---|:---|:---|
