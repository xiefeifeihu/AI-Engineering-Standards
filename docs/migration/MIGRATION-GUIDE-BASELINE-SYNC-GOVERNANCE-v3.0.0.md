---
document_id: "DOC-MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v300"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "DECISION_RECORD"
status: "ACTIVE"
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

## 4. `HISTORICAL_ARCHIVE` 历史文档逐工程重分类清单（共 37 个文件）

遵循 `D1=APPROVED`：**严禁删除历史文档或静默篡改历史文档正文含义**。仅将 YAML Frontmatter 中的 `document_type: "HISTORICAL_ARCHIVE"` 恢复为其真实业务语义类型，并确保 `status: "ARCHIVED"`（或 `"SUPERSEDED"`）且 `primary_entrypoint: false`：

### 4.1 `AI-Engineering-Hub`（2 个 `HISTORICAL_ARCHIVE` 文件 + 7 个自定义类型文件）
- `docs/99-历史归档/v0.17.0/R7测试与验收手册.md`：`document_type: "HISTORICAL_ARCHIVE"` -> `"TEST_ACCEPTANCE"`（保持 `status: "ARCHIVED"`, `primary_entrypoint: false`）。
- `docs/99-历史归档/v0.21.1/历史文档清单与索引.md`：`document_type: "HISTORICAL_ARCHIVE"` -> `"DOCUMENT_INDEX"`（保持 `status: "ARCHIVED"`, `primary_entrypoint: false`）。
- 另有 7 个自定义类型文件需映射为标准 12 类（`primary_entrypoint: false`）：
  - `docs/00-治理基线/文档治理审计报告.md` (`GOVERNANCE_REPORT` -> `DECISION_RECORD`)
  - `docs/00-治理基线/工程清理报告.md` (`GOVERNANCE_REPORT` -> `DECISION_RECORD`)
  - `docs/04-测试与验收/测试用例目录.md` (`TEST_CASE_CATALOG` -> `TEST_ACCEPTANCE`)
  - `docs/04-测试与验收/验收证据规范.md` (`TEST_EVIDENCE_GUIDE` -> `TEST_ACCEPTANCE`)
  - `docs/04-测试与验收/测试执行手册.md` (`TEST_EXECUTION_GUIDE` -> `TEST_ACCEPTANCE`)
  - `docs/99-历史归档/v0.21.1/R8.2前序任务台账与历史记录.md` (`GOVERNANCE_REPORT` -> `DECISION_RECORD`)
  - `docs/99-历史归档/v0.21.1/历史版本演进与审计汇总.md` (`GOVERNANCE_REPORT` -> `DECISION_RECORD`)

### 4.2 `AI-KB`（14 个 `HISTORICAL_ARCHIVE` 文件）
- `docs/archive/v0.9.0/API-CONTRACT-v0.9.0.md` -> `document_type: "API_CONTRACT"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/archive/v0.9.0/DECISION-RECORD-v0.9.0.md` -> `document_type: "DECISION_RECORD"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/archive/v0.9.0/PRODUCT-BASELINE-v0.9.0.md` -> `document_type: "PRODUCT_BASELINE"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/archive/v0.9.0/RELEASE-OPERATIONS-v0.9.0.md` -> `document_type: "RELEASE_OPERATIONS"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/archive/v0.9.0/TEST-ACCEPTANCE-v0.9.0.md` -> `document_type: "TEST_ACCEPTANCE"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/历史档案/HISTORICAL-ARCHIVE.md` -> `document_type: "DOCUMENT_INDEX"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/历史档案/AI-KB-V1-002-模型治理交接记录.md` -> `document_type: "CROSS_SESSION_HANDOFF"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/历史档案/AI-KB-V1-004-知识引擎核心方案.md` -> `document_type: "TECHNICAL_DESIGN"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/历史档案/AI-KB-V1-005-解析器增强设计.md` -> `document_type: "TECHNICAL_DESIGN"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/历史档案/AI-KB-V1-006-混合检索架构演进.md` -> `document_type: "SYSTEM_ARCHITECTURE"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/历史档案/AI-KB-V1-007-前端工作台重构记录.md` -> `document_type: "PROTOTYPE_UX"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/历史档案/AI-KB-V1-008-两阶段发布验收记录.md` -> `document_type: "TEST_ACCEPTANCE"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/历史档案/AI-KB-V1-009-安全治理审计记录.md` -> `document_type: "DECISION_RECORD"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)
- `docs/历史档案/AI-KB-V1-010-历史阶段总结归档.md` -> `document_type: "DECISION_RECORD"` (`status: "ARCHIVED"`, `primary_entrypoint: false`)

### 4.3 `vtip-platform-catalog`（1 个 `HISTORICAL_ARCHIVE` 文件）
- `docs/archive/BASELINE-HISTORY.md`：`document_type: "HISTORICAL_ARCHIVE"` -> `"DECISION_RECORD"`（保持 `status: "ARCHIVED"`, `primary_entrypoint: false`）。

### 4.4 `vtip-ai-sidecar`（20 个 `HISTORICAL_ARCHIVE` 文件）
- `docs/HISTORICAL-ARCHIVE.md`：`document_type: "HISTORICAL_ARCHIVE"` -> `"DOCUMENT_INDEX"`，`status: "ACTIVE"` -> `"ARCHIVED"`，`primary_entrypoint: true` -> `false`（移入或作为归档索引保留，由 `docs/当前权威基线.md` 承担第 12 类正式主入口）。
- `docs/archive/**` 下其余 19 个历史文档：按各自原始职责映射为 `DECISION_RECORD`、`TEST_ACCEPTANCE`、`TECHNICAL_DESIGN`、`RELEASE_OPERATIONS`、`CROSS_SESSION_HANDOFF`，保持 `status: "ARCHIVED"`, `primary_entrypoint: false`。

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
