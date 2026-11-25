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
last_updated: "2026-11-23"
supersedes: null
change_summary: "v3.0.1 正式发布后更新发布证据索引与文档生命周期治理待审清单（保留 IN_REVIEW，不自批晋升 ACTIVE）。"
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
| 2 | `ENGINEERING_BASELINE` | [`docs/当前权威基线.md`](./当前权威基线.md) | `DOC-AI-ENGINEERING-STANDARDS-ENGINEERING-BASELINE-001` | `IN_REVIEW` | 11 类正式文档与 10 类实时工程事实自动生成综合视图 |
| 3 | `PROJECT_BLUEPRINT` | [`docs/PROJECT-BLUEPRINT.md`](./PROJECT-BLUEPRINT.md) | `DOC-STANDARDS-PROJECT-BLUEPRINT` | `IN_REVIEW` | 跨工程规范权威源顶层愿景、仓库边界与阶段演进蓝图 |
| 4 | `PRODUCT_BASELINE` | [`docs/PRODUCT-BASELINE.md`](./PRODUCT-BASELINE.md) | `DOC-STANDARDS-PRODUCT-BASELINE` | `IN_REVIEW` | `STD-001` 至 `STD-035` 规范族、30 个 Schema 与官方工具能力基线 |
| 5 | `SYSTEM_ARCHITECTURE` | [`docs/SYSTEM-ARCHITECTURE.md`](./SYSTEM-ARCHITECTURE.md) | `DOC-STANDARDS-SYSTEM-ARCHITECTURE` | `IN_REVIEW` | 唯一规范权威源架构、四库单向依赖拓扑与变更同步边界 |
| 6 | `TECHNICAL_DESIGN` | [`docs/TECHNICAL-DESIGN.md`](./TECHNICAL-DESIGN.md) | `DOC-STANDARDS-TECHNICAL-DESIGN` | `IN_REVIEW` | Schema 校验引擎、17 项文档集合校验器、基线生成器与 `standards_sync` 设计 |
| 7 | `API_CONTRACT` | [`docs/API-CONTRACT.md`](./API-CONTRACT.md) | `DOC-STANDARDS-API-CONTRACT` | `IN_REVIEW` | CLI 子命令契约、JSON Schema 契约与审批证据数据结构契约 |
| 8 | `PROTOTYPE_UX` | [`docs/PROTOTYPE-UX.md`](./PROTOTYPE-UX.md) | `DOC-STANDARDS-PROTOTYPE-UX` | `IN_REVIEW` | 非运行时规范制品库 CLI 诊断交互与 `STD-018` 中文展示规范映射 |
| 9 | `TEST_ACCEPTANCE` | [`docs/TEST-ACCEPTANCE.md`](./TEST-ACCEPTANCE.md) | `DOC-STANDARDS-TEST-ACCEPTANCE` | `IN_REVIEW` | Schema、文档集合、同步状态机、防伪造审批与跨平台测试基线 |
| 10 | `RELEASE_OPERATIONS` | [`docs/RELEASE-OPERATIONS.md`](./RELEASE-OPERATIONS.md) | `DOC-STANDARDS-RELEASE-OPERATIONS` | `IN_REVIEW` | `main` 主干 CI 门禁、Annotated Tag 附注标签发布、锁定晋升与回滚规程 |
| 11 | `DECISION_RECORD` | [`docs/DECISION-RECORD.md`](./DECISION-RECORD.md) | `DOC-STANDARDS-DECISION-RECORD` | `IN_REVIEW` | 已批准架构决策记录（含 `D1`–`D5` 正式批准记录） |
| 12 | `CROSS_SESSION_HANDOFF` | [`docs/CROSS-SESSION-HANDOFF.md`](./CROSS-SESSION-HANDOFF.md) | `DOC-AI-ENGINEERING-STANDARDS-CROSS-SESSION-HANDOFF-001` | `IN_REVIEW` | 当前活跃跨会话交接唯一入口（`STD-020` 自动采集） |

---

> **生命周期核验（Std-023 发布后核验）**：本表逐项反映各文件 Frontmatter 当前的真实 `status`，不因 `v3.0.0` / `v3.0.1` 已正式发布或 PR #13 / PR #14 已成功合入而自动提升为 `ACTIVE`。目前 12 类正式主入口文档（以及 2 份 `IN_REVIEW` 补充文档）均保持 `IN_REVIEW` 且尚缺与目标 `source_commit` + `content_sha256` 绑定的正式文档审批事件（`approval_evidence_ref: null`）；根据 `STD-035` §2、§3 与 `D2`，未经对应审批不得自批晋升。以上属于待闭环文档治理缺口，不影响已由 GitHub Actions `main` CI 签发的不可变 `v3.0.0` 与 `v3.0.1` 正式 Tag 的历史与发布事实。

### 1.1 待 Owner 审定清单 (Document Lifecycle Governance Gap, `OWNER_APPROVAL_REQUIRED`)

- **4 份 `AI_APPROVABLE` 主入口文档（`status=IN_REVIEW`, `approval_status=IN_REVIEW`, `approval_evidence_ref=null`）**：需独立 ChatGPT 技术审核并绑定目标 Commit 与 `content_sha256` 后方可受控晋升 `ACTIVE`：
  - `docs/DOCUMENT-INDEX.md` (`DOC-STANDARDS-DOCUMENT-INDEX`)
  - `docs/当前权威基线.md` (`DOC-AI-ENGINEERING-STANDARDS-ENGINEERING-BASELINE-001`)
  - `docs/PROTOTYPE-UX.md` (`DOC-STANDARDS-PROTOTYPE-UX`)
  - `docs/CROSS-SESSION-HANDOFF.md` (`DOC-AI-ENGINEERING-STANDARDS-CROSS-SESSION-HANDOFF-001`)
- **8 份 `OWNER_MANDATORY` 主入口文档（`status=IN_REVIEW`, `approval_status=IN_REVIEW`, `approval_evidence_ref=null`）**：需 ChatGPT 独立复核及 Standards Owner 显式批准（绑定 `source_commit` / `candidate_commit` 与 `content_sha256`）后方可晋升 `ACTIVE`：
  - `docs/PROJECT-BLUEPRINT.md` (`DOC-STANDARDS-PROJECT-BLUEPRINT`)
  - `docs/PRODUCT-BASELINE.md` (`DOC-STANDARDS-PRODUCT-BASELINE`)
  - `docs/SYSTEM-ARCHITECTURE.md` (`DOC-STANDARDS-SYSTEM-ARCHITECTURE`)
  - `docs/TECHNICAL-DESIGN.md` (`DOC-STANDARDS-TECHNICAL-DESIGN`)
  - `docs/API-CONTRACT.md` (`DOC-STANDARDS-API-CONTRACT`)
  - `docs/TEST-ACCEPTANCE.md` (`DOC-STANDARDS-TEST-ACCEPTANCE`)
  - `docs/RELEASE-OPERATIONS.md` (`DOC-STANDARDS-RELEASE-OPERATIONS`)
  - `docs/DECISION-RECORD.md` (`DOC-STANDARDS-DECISION-RECORD`) — 另含 ADR `D10`、`D11`、`D12` 当前状态为 `IN_REVIEW`，待 Owner 审定。
- **2 份 `OWNER_MANDATORY` 补充文档（`primary_entrypoint: false`, `status=IN_REVIEW`）**：
  - `docs/Standards消费端接入与工具使用协议.md` (`DOC-STANDARDS-CONSUMER-PROTOCOL`)
  - `docs/migration/MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md` (`DOC-MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-V300`) — 其中 AI-Hub 首个消费端试点方案仍为 `PROPOSED / NOT_APPROVED`，须由 AI-Hub Owner 独立批准。
- **历史基线参考说明（无需晋升 `ACTIVE`）**：`docs/architecture/ARTIFACT-GOVERNANCE-V1.1.md`、`docs/architecture/STANDARDS-V1-ARCHITECTURE.md`、`docs/audit/STANDARDS-V1-AUDIT.md`、`docs/migration/MIGRATION-GUIDE-STD-032-NO-PR-TWO-STAGE-v2.10.0.md`、`docs/migration/MIGRATION-GUIDE-STD-035.md` 与 `docs/目录导航.md` 为历史或导览材料（无 Formal Frontmatter）；`MIGRATION-GUIDE-AI-DRIVEN-TEST-GOVERNANCE-v2.11.0.md` 与 `PROPOSAL-CONTINUOUS-AI-TEST-CASE-GOVERNANCE.md` 保持 `SUPERSEDED`。

## 2. 补充规范、发布证据、接入协议与迁移资料（`primary_entrypoint: false`）

- [`docs/release-evidence/v3.0.1.json`](./release-evidence/v3.0.1.json)：Standards `v3.0.1` 正式发布凭证（PR #13 候选来源 + PR #14 最终修复与合并来源，Main CI Run `45099701154` 全绿，Tag Object `a712e1689dbd62dc87ecb166e60cc17b6c7fa1c4` / Peeled `4facfdcd17a3003f04e7deaa3dbdcb320ff82afa`）。
- [`docs/release-evidence/std019-final-release.json`](./release-evidence/std019-final-release.json)：Standards `v3.0.0` 正式发布凭证（保留历史不可变，PR #10 合并，Main CI Run `42996232217` 全绿，Tag Object `8256bb384e62894219db0992a2cb57e16d4fa8cd` / Peeled `8b223019c254e0edeb94576b94af46c1e48b0316`）。
- [`docs/release-evidence/std018-current-snapshot.json`](./release-evidence/std018-current-snapshot.json) 与 [`docs/release-evidence/v3.0.0-reissue.json`](./release-evidence/v3.0.0-reissue.json)：`v3.0.0` 历史工程快照与 PR #9 发布过程凭证（保留历史不可变）。
- [`docs/Standards消费端接入与工具使用协议.md`](./Standards消费端接入与工具使用协议.md)：共享工具、模板、版本锁定、CI 接入及升级回滚的消费端统一协议。
- [`docs/migration/MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md`](./migration/MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md)：Standards 正式发布后以 AI-Hub 为首个消费端试点的迁移方案。
- [`docs/目录导航.md`](./目录导航.md)：仓库目录和文件的中文（英文）职责导航。
- [`docs/migration/MIGRATION-GUIDE-AI-DRIVEN-TEST-GOVERNANCE-v2.11.0.md`](./migration/MIGRATION-GUIDE-AI-DRIVEN-TEST-GOVERNANCE-v2.11.0.md)：`v2.11.0` AI 自主测试设计与持续用例治理迁移指南。
- [`docs/migration/MIGRATION-GUIDE-STD-035.md`](./migration/MIGRATION-GUIDE-STD-035.md)：`v2.9.0` 工程文档生命周期初始接入指南（已由 `v3.0.0` 迁移指南演进替代）。
