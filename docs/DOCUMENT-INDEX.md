---
document_id: "DOC-STANDARDS-DOCUMENT-INDEX"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "DOCUMENT_INDEX"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "AI_APPROVABLE"
approval_evidence_ref: null
source_commit: "9687f961b22df612c4311961e06fc1c1fd508c37"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "Canonical 12-type documentation index for AI-Engineering-Standards v3.0.0 (STD-035)."
history_reference: "CHANGELOG.md"
primary_entrypoint: true
content_sha256: null
---


# 文档总索引 (Document Index)

> **工程标识**：`ai-engineering-standards`  
> **规范依据**：[`STD-035`](../standards/17-documentation/STD-035-documentation-lifecycle.md) v3.0.0  
> **单一权威规则**：本索引是 `AI-Engineering-Standards` 仓库文档集合的唯一总入口。12 类正式工程文档中每类仅允许存在唯一一份 `primary_entrypoint: true` 的主入口文档；候选 PR 阶段为 `IN_REVIEW`，正式发布后才可转为 `ACTIVE`。

---

## 1. 12 类正式文档权威入口清单

| 序号 | 文档类型 (`document_type`) | 权威文档路径 | 文档 ID (`document_id`) | 状态 | 职责说明 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `DOCUMENT_INDEX` | [`docs/DOCUMENT-INDEX.md`](./DOCUMENT-INDEX.md) | `DOC-STANDARDS-DOCUMENT-INDEX` | `IN_REVIEW` | 全库文档集合总入口、适用性声明与归档导航 |
| 2 | `ENGINEERING_BASELINE` | [`docs/当前权威基线.md`](./当前权威基线.md) | `DOC-AI-ENGINEERING-STANDARDS-ENGINEERING-BASELINE-001` | `ACTIVE` | 11 类正式文档与 10 类实时工程事实自动生成综合视图 |
| 3 | `PROJECT_BLUEPRINT` | [`docs/PROJECT-BLUEPRINT.md`](./PROJECT-BLUEPRINT.md) | `DOC-STANDARDS-PROJECT-BLUEPRINT` | `ACTIVE` | 跨工程规范权威源顶层愿景、仓库边界与阶段演进蓝图 |
| 4 | `PRODUCT_BASELINE` | [`docs/PRODUCT-BASELINE.md`](./PRODUCT-BASELINE.md) | `DOC-STANDARDS-PRODUCT-BASELINE` | `ACTIVE` | `STD-001` 至 `STD-035` 规范族、30 个 Schema 与官方工具能力基线 |
| 5 | `SYSTEM_ARCHITECTURE` | [`docs/SYSTEM-ARCHITECTURE.md`](./SYSTEM-ARCHITECTURE.md) | `DOC-STANDARDS-SYSTEM-ARCHITECTURE` | `ACTIVE` | 唯一规范权威源架构、四库单向依赖拓扑与变更同步边界 |
| 6 | `TECHNICAL_DESIGN` | [`docs/TECHNICAL-DESIGN.md`](./TECHNICAL-DESIGN.md) | `DOC-STANDARDS-TECHNICAL-DESIGN` | `ACTIVE` | Schema 校验引擎、17 项文档集合校验器、基线生成器与 `standards_sync` 设计 |
| 7 | `API_CONTRACT` | [`docs/API-CONTRACT.md`](./API-CONTRACT.md) | `DOC-STANDARDS-API-CONTRACT` | `ACTIVE` | CLI 子命令契约、JSON Schema 契约与审批证据数据结构契约 |
| 8 | `PROTOTYPE_UX` | [`docs/PROTOTYPE-UX.md`](./PROTOTYPE-UX.md) | `DOC-STANDARDS-PROTOTYPE-UX` | `ACTIVE` | 非运行时规范制品库 CLI 诊断交互与 `STD-018` 中文展示规范映射 |
| 9 | `TEST_ACCEPTANCE` | [`docs/TEST-ACCEPTANCE.md`](./TEST-ACCEPTANCE.md) | `DOC-STANDARDS-TEST-ACCEPTANCE` | `ACTIVE` | Schema、文档集合、同步状态机、防伪造审批与跨平台测试基线 |
| 10 | `RELEASE_OPERATIONS` | [`docs/RELEASE-OPERATIONS.md`](./RELEASE-OPERATIONS.md) | `DOC-STANDARDS-RELEASE-OPERATIONS` | `ACTIVE` | `main` 主干 CI 门禁、Annotated Tag 附注标签发布、锁定晋升与回滚规程 |
| 11 | `DECISION_RECORD` | [`docs/DECISION-RECORD.md`](./DECISION-RECORD.md) | `DOC-STANDARDS-DECISION-RECORD` | `ACTIVE` | 已批准架构决策记录（含 `D1`–`D5` 正式批准记录） |
| 12 | `CROSS_SESSION_HANDOFF` | [`docs/CROSS-SESSION-HANDOFF.md`](./CROSS-SESSION-HANDOFF.md) | `DOC-AI-ENGINEERING-STANDARDS-CROSS-SESSION-HANDOFF-001` | `ACTIVE` | 当前活跃跨会话交接唯一入口（`STD-020` 自动采集） |

---

## 2. 补充规范、接入协议与迁移资料（`primary_entrypoint: false`）

- [`docs/Standards消费端接入与工具使用协议.md`](./Standards消费端接入与工具使用协议.md)：共享工具、模板、版本锁定、CI 接入及升级回滚的消费端统一协议。
- [`docs/migration/MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md`](./migration/MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md)：Standards 正式发布后以 AI-Hub 为首个消费端试点的迁移方案。
- [`docs/目录导航.md`](./目录导航.md)：仓库目录和文件的中文（英文）职责导航。
- [`docs/migration/MIGRATION-GUIDE-AI-DRIVEN-TEST-GOVERNANCE-v2.11.0.md`](./migration/MIGRATION-GUIDE-AI-DRIVEN-TEST-GOVERNANCE-v2.11.0.md)：`v2.11.0` AI 自主测试设计与持续用例治理迁移指南。
- [`docs/migration/MIGRATION-GUIDE-STD-035.md`](./migration/MIGRATION-GUIDE-STD-035.md)：`v2.9.0` 工程文档生命周期初始接入指南（已由 `v3.0.0` 迁移指南演进替代）。
