---
document_id: "DOC-MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v300"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "DECISION_RECORD"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "5e17c0ef560ab8abafe880b988d70f85f380a104"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: "DOC-MIGRATION-GUIDE-STD-035"
change_summary: "Cross-project migration guide for Standards v3.0.0: 12 formal document types, ENGINEERING_BASELINE auto-maintenance, HISTORICAL_ARCHIVE removal & reclassification, ChatGPT+Owner approval contract, STD-020 automated handoff, and official standards_sync toolchain."
history_reference: null
primary_entrypoint: false
---

# Standards v3.0.0 跨工程迁移指南：权威基线自动维护、双层审批与版本受控同步

> **关联任务**：`STANDARDS-BASELINE-SYNC-GOVERNANCE-IMPLEMENTATION-001`  
> **已批准设计决策**：`D1=APPROVED`、`D2=APPROVED`、`D3=APPROVED`、`D4=APPROVED`、`D5=APPROVED`  
> **适用消费端工程**：`AI-Engineering-Hub`、`AI-KB`、`vtip-platform-catalog`、`vtip-ai-sidecar`

---

## 1. 核心架构与规范变更摘要 (`v2.11.0` -> `v3.0.0`)

1. **正式文档类型收敛为 12 类 (`D1=APPROVED` / `STD-035` v3.0.0)**：
   - 12 类正式 `document_type`：`PROJECT_BLUEPRINT`、`PRODUCT_BASELINE`、`SYSTEM_ARCHITECTURE`、`TECHNICAL_DESIGN`、`API_CONTRACT`、`PROTOTYPE_UX`、`TEST_ACCEPTANCE`、`RELEASE_OPERATIONS`、`DECISION_RECORD`、`CROSS_SESSION_HANDOFF`、`DOCUMENT_INDEX`、`ENGINEERING_BASELINE`。
   - **破坏性枚举调整**：`HISTORICAL_ARCHIVE` 从 `schemas/documentation-metadata.schema.json` 的 `document_type` 枚举中正式移除。历史归档回归**文档生命周期状态**（`status=ARCHIVED` 或 `SUPERSEDED`，且强制 `primary_entrypoint: false`）与**目录存储分类**（如 `docs/archive/`、`docs/99-历史归档/`），历史文档必须保留其原始语义 `document_type`（如 `TEST_ACCEPTANCE`、`DECISION_RECORD`、`DOCUMENT_INDEX` 等），不得静默篡改历史文档正文含义。
2. **当前权威基线自动维护 (`ENGINEERING_BASELINE` / `docs/当前权威基线.md`)**：
   - 新增唯一正式入口 `docs/当前权威基线.md`，由官方工具 [`tools/generate_engineering_baseline.py`](../../tools/generate_engineering_baseline.py) 从 10 类正式文档与 9 类实时工程事实确定性生成，严禁手工捏造或将未核实内容混入已核实工程事实。
3. **生命周期与双层审批状态解耦 (`D2=APPROVED` / `STD-035` §4 / `STD-034` §16)**：
   - `status`（生命周期：`CANDIDATE`、`IN_REVIEW`、`ACTIVE`、`SUPERSEDED`、`ARCHIVED`）与 `approval_status`（审批状态：`NOT_SUBMITTED`、`IN_REVIEW`、`AI_APPROVED`、`OWNER_APPROVAL_REQUIRED`、`OWNER_APPROVED`、`REJECTED`、`BLOCKED`）严格分离。
   - ChatGPT 独立审核记录（`chatgpt_review`）与 Owner 批准记录（`owner_approval`）分开持久化，绑定 `TASK_ID`、`CANDIDATE_COMMIT`、`CONTENT_SHA256`。编程智能体严禁自行标记 `AI_APPROVED`、`OWNER_APPROVED`、`HUMAN_ACCEPTED`。
4. **跨会话交接自动采集 (`STD-020` v2.0.0)**：
   - 唯一当前交接入口为 `docs/CROSS-SESSION-HANDOFF.md`，任务级正式快照为 `handoff/<TASK-ID>-<VERSION>-handoff.md`，临时交接为 `.artifacts/handoff/temporary/`。由 [`tools/generate_handoff.py`](../../tools/generate_handoff.py) 自动采集 11 项实时工程事实。
5. **Standards 四元组精确锁定与官方同步工具 (`D3`–`D5=APPROVED` / `STD-034` §4)**：
   - 各工程根目录统一通过 `standards.lock.json`（校验 Schema：[`schemas/standards-lock.schema.json`](../../schemas/standards-lock.schema.json)）锁定精确四元组：`version`、`tag`、`tag_object_sha`、`peeled_commit`，并维护 `previous_locks` 历史栈以支持一键回滚。
   - 严禁在 `AGENTS.md`、`CLAUDE.md`、`README.md` 中手工硬编码最新 Standards 版本号。
   - 统一使用 Standards 官方工具 [`tools/standards_sync/cli.py`](../../tools/standards_sync/cli.py) 执行 8 个子命令：`discover`、`verify-lock`、`compare`、`impact`、`prepare-upgrade`、`validate-upgrade`、`promote`、`rollback`。
6. **Engineering Manifest Schema 统一 (`STD-001`)**：
   - [`schemas/engineering-manifest.schema.json`](../../schemas/engineering-manifest.schema.json) 为唯一权威 Schema，[`governance/engineering-manifest-schema.json`](../../governance/engineering-manifest-schema.json) 保持字节级兼容镜像，同时兼容四大工程现有 `engineering-manifest.yaml`。

---

## 2. 相关规范一致性审查 (`STD-017` 与 `STD-032`)

在本次实施中，已对 [`STD-017`](../../standards/13-git-release/STD-017-git-release-versioning.md) 与 [`STD-032`](../../standards/13-git-release/STD-032-release-engineering-contract.md) 进行逐条一致性核查：

| 审查对象 | 核查结论 | 独立影响分析 |
| :--- | :--- | :--- |
| **`STD-017` (Git Release & Versioning)** | **完全一致，无需修改规范语义** | `STD-017` §2 规定破坏性 Schema 变更（如移除枚举值）必须递增 `MAJOR` 版本号，并要求 Annotated Tag (`git tag -a vX.Y.Z`) 与 `VERSION` 文件严格对齐。本次因移除 `HISTORICAL_ARCHIVE` 枚举将 `VERSION` 升至 `3.0.0`，且 `standards.lock.json` 强制校验 `tag_object_sha` 与 `peeled_commit`，完全符合 `STD-017`。 |
| **`STD-032` (Release Engineering Contract)** | **完全一致，无需修改规范语义** | `STD-032` 定义的 12 阶段发布流水线、10 项全绿门禁（`MAIN_COMMIT_VERIFIED` 等）与五态 Commit 一致性（`LOCAL_HEAD == REMOTE_HEAD == TAG_COMMIT == BUILD_COMMIT == LIVE_COMMIT`）与本次 `D3=APPROVED`（正式 Tag 必须来自经过 `main` CI 验证的 Commit）完全正交互补，不存在任何规范冲突。 |

---

## 3. 四大消费端工程兼容性影响评估矩阵（基于只读实测核验）

以下数据来自对四大工程本地只读工作区的实测扫描与 `tools/standards_sync/cli.py impact` 评估：

| 评估维度 | `AI-Engineering-Hub` | `AI-KB` (`ai-kb-infra`) | `vtip-platform-catalog` | `vtip-ai-sidecar` |
| :--- | :--- | :--- | :--- | :--- |
| **当前分支 / HEAD** | `feat/ai-hub-r8.6.10-...` (`808e2ca0294d`) | `feature/vault-owner-api-m4` (`9e5f166d8ef7`) | `codex/Jira-AG-008-R4` (`5ca15a013e08`) | `codex/sidecar-standards-docs-repo-alignment` (`19d3cf0ca9b1`) |
| **当前产品版本** | `0.22.9` | `0.9.1` | `2.7.0` | `0.15.3` |
| **当前 Standards 锁定** | `2.11.0` (`5e17c0ef560a`)（位于 `engineering-manifest.yaml` + `compatibility_matrix.yaml`，缺 `standards.lock.json`） | `v2.11.0` (`5e17c0ef560a`)（已有 `standards.lock.json` 3 字段，缺 `tag_object_sha` 等） | `v2.10.0` (`ba25353ec0f2`, tag obj `370ba069d22f`)（位于 `compatibility_matrix.yaml`，缺 `standards.lock.json`） | `v2.9.1` (`152af72f6a3a`, tag obj `7162878de422`)（位于 `compatibility_matrix.yaml` + `engineering-manifest.yaml`，缺 `standards.lock.json`） |
| **目标 Standards 版本** | `v3.0.0` | `v3.0.0` | `v3.0.0` | `v3.0.0` |
| **是否需要迁移 (`MIGRATION_REQUIRED`)** | `true` | `true` | `true` | `true` |
| **1. Schema 兼容性** | `BREAKING`（需重分类 2 个 `HISTORICAL_ARCHIVE` + 7 个自定义类型） | `BREAKING`（需重分类 14 个 `HISTORICAL_ARCHIVE`） | `BREAKING`（需重分类 1 个 `HISTORICAL_ARCHIVE`） | `BREAKING`（需重分类 20 个 `HISTORICAL_ARCHIVE`） |
| **2. `AGENTS.md` 硬编码** | 存在硬编码 `2.11.0` 及 `5e17c0ef...`（且 `scripts/agent/preflight.py:237-240` 断言该字符串） | 无硬编码（已引用 `standards.lock.json`） | 第 3 行硬编码 `v2.10.0` | 硬编码 `v2.9.1` 及 Commit |
| **3. `CLAUDE.md` 硬编码** | 存在硬编码 `2.11.0` 及 `5e17c0ef...` | 无硬编码（已引用 `standards.lock.json`） | 无硬编码 | 硬编码 `v2.9.1` 及 Commit |
| **4. Engineering Manifest** | `COMPATIBLE`（统一 Schema 已兼容 `app/manifest.py` 与测试） | `COMPATIBLE` | `COMPATIBLE`（已兼容可选 `lifecycle_policy`） | `COMPATIBLE` |
| **5. 文档元数据 (`HISTORICAL_ARCHIVE`)** | **2 个文件**使用 `HISTORICAL_ARCHIVE`；另有 7 个文件使用非标类型（`GOVERNANCE_REPORT` 等） | **14 个文件**使用 `HISTORICAL_ARCHIVE`（均已 `status: ARCHIVED, primary_entrypoint: false`） | **1 个文件** `docs/archive/BASELINE-HISTORY.md` 使用 `HISTORICAL_ARCHIVE` | **20 个文件**使用 `HISTORICAL_ARCHIVE`（含 1 个 `ACTIVE` 主入口 `docs/HISTORICAL-ARCHIVE.md` + 19 个归档文件） |
| **6. 文档集合校验 (`STD-035`)** | 需新增 `docs/当前权威基线.md` (`ENGINEERING_BASELINE`) 并更新 `docs/文档总索引.md` | 需新增 `docs/当前权威基线.md` 并更新 `tools/verify_delivery_contract.py:48` | 需新增 `docs/当前权威基线.md` 并更新 `docs/DOCUMENT-INDEX.md` | 需新增 `docs/当前权威基线.md`、归档 `docs/HISTORICAL-ARCHIVE.md` 并更新 `docs/DOCUMENT-INDEX.md` |
| **7. 测试门禁 (`STD-014`)** | `COMPATIBLE` | `COMPATIBLE` | `COMPATIBLE` | `COMPATIBLE` |
| **8. 发布门禁 (`STD-032`)** | `COMPATIBLE` | `COMPATIBLE` | `COMPATIBLE` | `COMPATIBLE` |
| **9. 安全门禁 (`STD-007`)** | `COMPATIBLE` | `COMPATIBLE` | `COMPATIBLE` | `COMPATIBLE` |
| **10. 业务接口与运行时契约** | `COMPATIBLE`（零 HTTP/Runtime 破坏） | `COMPATIBLE`（零 HTTP/Runtime 破坏） | `COMPATIBLE`（零 HTTP/Runtime 破坏） | `COMPATIBLE`（零 HTTP/Runtime 破坏） |
| **审批要求 (`APPROVAL_REQUIREMENT`)** | `OWNER_APPROVAL_REQUIRED` | `OWNER_APPROVAL_REQUIRED` | `OWNER_APPROVAL_REQUIRED` | `OWNER_APPROVAL_REQUIRED` |

---

## 4. `HISTORICAL_ARCHIVE` 历史文档逐工程 37 份明细清单与语义映射表

> **只读边界声明 (`STD-034` Rule E)**：本清单仅在 `AI-Engineering-Standards` 作为迁移指导事实规范沉淀，**严禁跨仓修改** 下游四大工程任何代码与文件。下游各工程在正式启动 `v3.0.0` 升级任务前保持独立只读。

### 4.1 `AI-Engineering-Hub`（共 2 份 `HISTORICAL_ARCHIVE` 文档）
- **审计分支 (`branch`)**：`feat/ai-hub-vault-owner-consumer-migration`
- **事实 Commit (`source_commit`)**：`09c8bc0ae9b79f61e5d0cfb88e22c6fdd8ce1267`
- **核验时间戳 (`timestamp`)**：`2026-11-05T12:52:15+08:00`

| 序号 | 相对路径 | 原始类型 | 映射语义类型 | 适用性 | 测试状态 | 内容摘要 (SHA-256) |
|:---|:---|:---|:---|:---|:---|:---|
| 1 | `docs/99-历史归档/v0.17.0/R7测试与验收手册.md` | `HISTORICAL_ARCHIVE` | `TEST_ACCEPTANCE` | `applicable: true` | `NOT_VERIFIED` | `sha256:9dac48a91dafdae1258e189166740a62f2197a3013b437731fb849cb87889438` |
| 2 | `docs/99-历史归档/v0.21.1/历史文档清单与索引.md` | `HISTORICAL_ARCHIVE` | `DOCUMENT_INDEX` | `applicable: true` | `NOT_VERIFIED` | `sha256:27c7b4edf276b9cea24187e9505efbdd326836e011fb0b402746a4929ea43d49` |

### 4.2 `AI-KB`（共 14 份 `HISTORICAL_ARCHIVE` 文档）
- **审计分支 (`branch`)**：`## HEAD (no branch)`
- **事实 Commit (`source_commit`)**：`9e5f166d8ef75568447569538a22ede0a5d54d4f`
- **核验时间戳 (`timestamp`)**：`2026-11-04T20:43:47+08:00`

| 序号 | 相对路径 | 原始类型 | 映射语义类型 | 适用性 | 测试状态 | 内容摘要 (SHA-256) |
|:---|:---|:---|:---|:---|:---|:---|
| 1 | `docs/archive/v0.9.0/01-AIKB-系统架构蓝图.md` | `HISTORICAL_ARCHIVE` | `SYSTEM_ARCHITECTURE` | `applicable: true` | `NOT_VERIFIED` | `sha256:2b492f2ba240a42eb8b9315f0b43f3854b81bc3b9dbf9e994e7e1084e18682e7` |
| 2 | `docs/archive/v0.9.0/02-AIKB-产品需求与演进规划.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:9d94c89f60d471894452c7c91ebd0eecafbf3d0129fd8816f8d66862aeb2cffe` |
| 3 | `docs/archive/v0.9.0/04-AIKB-外部系统与接口说明.md` | `HISTORICAL_ARCHIVE` | `API_CONTRACT` | `applicable: true` | `NOT_VERIFIED` | `sha256:7241ea3d8015fed85136c1743958ba8c75179975b8043c3d71d4867623ca2174` |
| 4 | `docs/archive/v0.9.0/06-AIKB-部署与运维手册.md` | `HISTORICAL_ARCHIVE` | `RELEASE_OPERATIONS` | `applicable: true` | `NOT_VERIFIED` | `sha256:1c11cedae097f9ff73a7da1c31834c6d26e9e88699a8ebbac2e22cb080633d67` |
| 5 | `docs/archive/v0.9.0/07-AIKB-关键架构决策.md` | `HISTORICAL_ARCHIVE` | `SYSTEM_ARCHITECTURE` | `applicable: true` | `NOT_VERIFIED` | `sha256:3ae3864b52dee48c975d9ab0cf7b8bc90a42b5fce49c35307c3aec1e03a12158` |
| 6 | `docs/历史档案/2026-10-10-HISTORICAL-2、项目完整记忆.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:bb7169934b33b582bcba7d0edda18bd74af78cf91822c0a77df6926e4c9c8936` |
| 7 | `docs/历史档案/2026-10-10-HISTORICAL-3、当前交接.md` | `HISTORICAL_ARCHIVE` | `CROSS_SESSION_HANDOFF` | `applicable: true` | `NOT_VERIFIED` | `sha256:45e47b2bc13cac9d713ff287bca1edb87651bee8b6a7a195ee8845843de87efb` |
| 8 | `docs/历史档案/2026-10-10-HISTORICAL-4、版本记录.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:2fb0591f7d3412d0120284033540da0fada95937bf5a59ba54ed4414cd4136c1` |
| 9 | `docs/历史档案/2026-10-10-HISTORICAL-5、会话索引.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:fd4999e08b53ea3983da32f9002cb7c7403de9e090fd25070f27cb6505d2faf3` |
| 10 | `docs/历史档案/2026-10-10-HISTORICAL-6、最终运行状态.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:306539e861994888faa0cbfeabb1b4e13f8fd85d3f87bdaf6c534b96938f2586` |
| 11 | `docs/历史档案/2026-10-10-HISTORICAL-7、恢复指南.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:77e57dc85e184a597cfdbb2f02fdd2e8196ed209c811f5f286493432412b2e94` |
| 12 | `docs/历史档案/2026-10-10-HISTORICAL-9、开发现场交接.md` | `HISTORICAL_ARCHIVE` | `CROSS_SESSION_HANDOFF` | `applicable: true` | `NOT_VERIFIED` | `sha256:eb88ad690bfc95935bc81180add28fba1e81714d00457bf0a9fdf1b42e1de5d6` |
| 13 | `docs/历史档案/2026-10-10-HISTORICAL-AI-KB-共享推理资源画像.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:f1e2a9794d0fc9873915cb07b8673903efb4e1543ab8610031bf816068c8b2ac` |
| 14 | `docs/历史档案/2026-10-10-HISTORICAL-AI-KB-网络配置画像.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:40697a4aec823cc9b2254fd9b9f125c6cfa0b0773fc547986704ec3f75cb363d` |

### 4.3 `vtip-platform-catalog`（共 1 份 `HISTORICAL_ARCHIVE` 文档）
- **审计分支 (`branch`)**：`codex/Jira-AG-008-R4`
- **事实 Commit (`source_commit`)**：`5ca15a013e083a6856c8f16b15eeceddf2e388bd`
- **核验时间戳 (`timestamp`)**：`2026-10-29T15:34:57+08:00`

| 序号 | 相对路径 | 原始类型 | 映射语义类型 | 适用性 | 测试状态 | 内容摘要 (SHA-256) |
|:---|:---|:---|:---|:---|:---|:---|
| 1 | `docs/archive/BASELINE-HISTORY.md` | `HISTORICAL_ARCHIVE` | `PRODUCT_BASELINE` | `applicable: true` | `NOT_VERIFIED` | `sha256:200e37209305ee4b6150fb9d3fbaade468b9aab0452817ce69877dab898121dd` |

### 4.4 `vtip-ai-sidecar`（共 20 份 `HISTORICAL_ARCHIVE` 文档）
- **审计分支 (`branch`)**：`codex/sidecar-standards-docs-repo-alignment`
- **事实 Commit (`source_commit`)**：`19d3cf0ca9b116aa8506b1725d50e51a38508a3d`
- **核验时间戳 (`timestamp`)**：`2026-10-28T21:58:16+08:00`

| 序号 | 相对路径 | 原始类型 | 映射语义类型 | 适用性 | 测试状态 | 内容摘要 (SHA-256) |
|:---|:---|:---|:---|:---|:---|:---|
| 1 | `docs/archive/commit-080bd1fdc93ddefb64682ee959c4b19c530708e7/source-contract.md` | `HISTORICAL_ARCHIVE` | `API_CONTRACT` | `applicable: true` | `NOT_VERIFIED` | `sha256:6ea23c96d8873c543667955b9d9a703fc446db0eb35327ffd5f4837d10ff63b1` |
| 2 | `docs/archive/commit-0eb7515447c367baf51419f85aafa235c5f1785d/AG-016-R5-R2-IMPLEMENTATION-SUMMARY.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:6f51b7fd4f4178dd20283ae9710c584d37f9d27232f098264389f5df35cf7b5e` |
| 3 | `docs/archive/commit-0eb7515447c367baf51419f85aafa235c5f1785d/AG-016-R5-R3-ROUTING-PRIORITY-FIX.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:64a9af988cbb4bac0c44e6d30d97ad3f422562f61ce95bcf6db175f434c3900d` |
| 4 | `docs/archive/commit-0eb7515447c367baf51419f85aafa235c5f1785d/AG-016-R6-IMPLEMENTATION-SUMMARY.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:7ef5229e455a25f2b0f52a36c2be7c71b87edbf9106d1e1c18824cddd8407eee` |
| 5 | `docs/archive/commit-0f9e6d6a949ec757331b2d12ed7b13ff87f3136c/ROOT_DOCUMENT_INVENTORY.md` | `HISTORICAL_ARCHIVE` | `DOCUMENT_INDEX` | `applicable: true` | `NOT_VERIFIED` | `sha256:4421b24242cc8599642c264aaa4c34a46eb1419885dde51917f798532d6c9c5d` |
| 6 | `docs/archive/commit-0f9e6d6a949ec757331b2d12ed7b13ff87f3136c/workspace_cleanup_plan.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:f9eb1a61fdfce4399b732b74e32c80241f6b6ef7dcf140e00ea937df25af61c8` |
| 7 | `docs/archive/commit-1c1d8c662b2f38c114d0147bc61aee4d1f2f2e3d/README.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:acd761ca1193900181d0d2217be424f514debb43cf3a1b1e7d846dd60fdd3c16` |
| 8 | `docs/archive/commit-26dfcac64f7cebd591ee72de42c2673132cb7a40/JiraAi-AG-016-R4-FINAL-REPORT.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:546a28998820d07c7e4b6cf9160d7e55561467801749c78f886b2311d198b68d` |
| 9 | `docs/archive/commit-63558d27543c12607a2a68ea0f431c48fa96df50/VTIP-AI-SIDECAR-共享推理资源画像.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:195b35e901fc5f4a7e53d3ce63abdfefa420f137f7a7ffa33b5b275f47452b9c` |
| 10 | `docs/archive/commit-e5973867a1cddc79d71a5736c30b89f79723df2e/AI-NETWORK-STANDARD.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:4a322590f44f9d15c4e6a0dcab984c3618f41ccc9afbffaf7860cd22310e5b8c` |
| 11 | `docs/archive/commit-e5973867a1cddc79d71a5736c30b89f79723df2e/AI-SHARED-RESOURCE-STANDARD.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:f33fa2d43a383ac48f0cfc4b33aa19423bb673c8d509b958675cec4e8ea91a3b` |
| 12 | `docs/archive/commit-e5973867a1cddc79d71a5736c30b89f79723df2e/VTIP-AI-SIDECAR-网络配置画像.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:17e76455172fc4f812d674ef3160f53d1433b1e728f1d39f09820bd9ccd22604` |
| 13 | `docs/archive/v0.11.0/VTIP-AI-SIDECAR-HANDOFF-20260918.md` | `HISTORICAL_ARCHIVE` | `CROSS_SESSION_HANDOFF` | `applicable: true` | `NOT_VERIFIED` | `sha256:fa084d3d54dbe66d5f3ee0f59746cbb3b1a05123f419879c5ede9603aac77c5f` |
| 14 | `docs/archive/v0.11.3/JiraAi-AG-016-R5-FINAL-HANDOFF.md` | `HISTORICAL_ARCHIVE` | `CROSS_SESSION_HANDOFF` | `applicable: true` | `NOT_VERIFIED` | `sha256:283065fc18c8a93b10053d6af17554e1e5233843fd61f6f5ed653ec08472c4cc` |
| 15 | `docs/archive/v0.15.2/evidence-identity-consistency.md` | `HISTORICAL_ARCHIVE` | `DECISION_RECORD` | `applicable: true` | `NOT_VERIFIED` | `sha256:1d30804f8c9627d55470de5e76511a7d91d0dd662d910cc6dcd32d9fdf245726` |
| 16 | `docs/archive/v0.3.1/VTIP-AI-SIDECAR-HANDOFF-20260911.md` | `HISTORICAL_ARCHIVE` | `CROSS_SESSION_HANDOFF` | `applicable: true` | `NOT_VERIFIED` | `sha256:d896872f5a7788599e0f567fdfc02be31378ef319afa3b3a35d2b9a5f6cfbe76` |
| 17 | `docs/archive/v0.5.0/UPSTREAM-DAILY-SEMANTIC-CONTRACT-REF.md` | `HISTORICAL_ARCHIVE` | `API_CONTRACT` | `applicable: true` | `NOT_VERIFIED` | `sha256:e9ba44b8ded379e61986a03a100445112cbf1225e97d00570ed0ec8cf27ad0db` |
| 18 | `docs/archive/v0.5.0/VTIP-AI-SIDECAR-HANDOFF-20260914.md` | `HISTORICAL_ARCHIVE` | `CROSS_SESSION_HANDOFF` | `applicable: true` | `NOT_VERIFIED` | `sha256:87083122543f3ea125cd2f10a94753dfe99960129f0bd1b5056ae20fa9250e8d` |
| 19 | `docs/archive/v0.7.0/VTIP-AI-SIDECAR-HANDOFF-20260916.md` | `HISTORICAL_ARCHIVE` | `CROSS_SESSION_HANDOFF` | `applicable: true` | `NOT_VERIFIED` | `sha256:5aeefd02f5ca721f1ddb4438367465af18f675134fb4384e1d2f03188b4cc5ed` |
| 20 | `docs/HISTORICAL-ARCHIVE.md` | `HISTORICAL_ARCHIVE` | `DOCUMENT_INDEX` | `applicable: true` | `NOT_VERIFIED` | `sha256:a9760a4c931342d46528825b8ceeab868b9317afec01384cf918e800e168dace` |

---

## 5. 各工程分步升级步骤与回滚方案

### 5.1 标准受控升级步骤 (`MIGRATION_PLAN`)

当 `AI-Engineering-Standards` `v3.0.0` 经独立 ChatGPT 审核与 Owner 批准并合入 `main`、打上正式 Annotated Tag `v3.0.0` 且远端 `main` CI 全绿后，各下游工程按以下步骤升级：

1. **自动发现与验证最新正式 Tag**：
   ```powershell
   python <STANDARDS_ROOT>/tools/standards_sync/cli.py discover
   ```
2. **执行工程级兼容性影响分析并生成升级候选**：
   ```powershell
   python <STANDARDS_ROOT>/tools/standards_sync/cli.py impact --project-root .
   python <STANDARDS_ROOT>/tools/standards_sync/cli.py prepare-upgrade --project-root . --target-tag v3.0.0 --target-version 3.0.0 --target-tag-object-sha <TAG_OBJECT_SHA> --target-peeled-commit <PEELED_COMMIT>
   ```
3. **重分类历史归档文档并移除硬编码版本号**：
   - 按上文第 4 节清单更新 `HISTORICAL_ARCHIVE` 文件的 `document_type`、设置 `status: ARCHIVED` 与 `primary_entrypoint: false`。
   - 将 `AGENTS.md` / `CLAUDE.md` 中硬编码的 `2.9.1` / `2.10.0` / `2.11.0` 替换为对 `standards.lock.json` 的引用（`AI-Engineering-Hub` 同步更新 `scripts/agent/preflight.py:237-240` 读取 `standards.lock.json`；`AI-KB` 移除本地旧 `tools/standards.py` 副本并改调官方 `tools/standards_sync/cli.py`）。
4. **生成 `docs/当前权威基线.md` 与 `docs/CROSS-SESSION-HANDOFF.md`**：
   ```powershell
   python <STANDARDS_ROOT>/tools/generate_engineering_baseline.py --project-root .
   python <STANDARDS_ROOT>/tools/generate_handoff.py --project-root . --task-id <TASK_ID> --version <PROJECT_VERSION>
   ```
5. **运行升级兼容性验证与全量测试**：
   ```powershell
   python <STANDARDS_ROOT>/tools/standards_sync/cli.py validate-upgrade --project-root .
   python <STANDARDS_ROOT>/tools/validate-documentation-collection.py --project-root .
   ```
6. **经独立审核/Owner 批准后正式晋升锁定**：
   ```powershell
   python <STANDARDS_ROOT>/tools/standards_sync/cli.py promote --project-root . --target-tag v3.0.0 --target-version 3.0.0 --target-tag-object-sha <TAG_OBJECT_SHA> --target-peeled-commit <PEELED_COMMIT> --approval-file <APPROVAL_JSON>
   ```

### 5.2 标准回滚方案 (`ROLLBACK_PLAN`)

若任一下游工程在升级或回归测试中出现不兼容或阻断：
1. 执行官方回滚命令，自动从 `standards.lock.json#previous_locks` 恢复上一个已验证的精确四元组锁定（并同步写回 `engineering-manifest.yaml`）：
   ```powershell
   python <STANDARDS_ROOT>/tools/standards_sync/cli.py rollback --project-root .
   ```
2. 重新验证回滚后的锁定状态与文档校验：
   ```powershell
   python <STANDARDS_ROOT>/tools/standards_sync/cli.py verify-lock --project-root .
   ```
