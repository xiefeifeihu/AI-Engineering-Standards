# STD-035: Documentation Lifecycle & Project Baseline Contract (全生命周期工程文档与当前权威基线契约规范)

```text
STANDARD_ID=STD-035
VERSION=3.0.0
STATUS=ACTIVE
SCOPE=全平台受管工程仓库 (AI-Engineering-Hub, AI-Engineering-Standards, AI-KB, vtip-ai-sidecar, vtip-platform-catalog 及未来所有受管项目)
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-11-05
SCHEMA_REF=schemas/documentation-metadata.schema.json, schemas/engineering-baseline.schema.json, schemas/documentation-approval.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 目标与治理背景 (Background & Objectives)

为杜绝各受管工程在多会话、多智能体协作中出现的“仅有零散增量交接报告、缺乏最新全量文档事实源、历史决策相互矛盾、产品职责无意遗失、架构图与代码脱节、未核实内容混入工程基线”等工程退化问题，本规范定义平台统一的**全生命周期工程文档与当前权威基线契约**：

1. **最新全量与历史演进双重保证**：每个工程 **MUST** 始终维护一份最新的、完整的全量文档集合，任何人或智能体进入项目均可独立理解完整项目蓝图、产品职责、架构与当前权威基线；同时 **MUST** 完整保留历史演进过程与架构决策记录。
2. **唯一权威入口原则 (Single Canonical Entrypoint)**：同一种正式文档类型在项目主干中 **MUST** 仅存在唯一权威活跃入口（`status: ACTIVE` 且 `primary_entrypoint: true`），严禁维护多份相互矛盾的“最新”副本，冲突文档 **MUST NOT** 自动选择胜出者。
3. **结构化元数据、生命周期与审批分离**：所有正式文档 **MUST** 包含 YAML Frontmatter 元数据头，严格分离文档生命周期状态（`status`）与独立审核批准状态（`approval_status`），避免将 AI 审核通过直接等同于正式生效。
4. **当前权威基线确定性生成**：通过 `ENGINEERING_BASELINE`（正式入口 `docs/当前权威基线.md`）自动汇聚 11 类正式文档与 10 类实时核验工程事实，严禁将历史记录、未核实内容或设计建议混入已核实工程事实。

---

## 2. 十二种正式文档类型规范 (Twelve Formal Document Types)

受管工程的正式文档体系由以下 **12 种正式文档类型 (`document_type`)** 组成：

| 编号 | 文档类型 (`document_type`) | 标准主入口路径建议 | 核心职责说明 |
|:---|:---|:---|:---|
| **01** | `PROJECT_BLUEPRINT` | `docs/PROJECT-BLUEPRINT.md` | 项目规划蓝图：背景、定位、终态愿景、能力全景图、演进路线与里程碑。 |
| **02** | `PRODUCT_BASELINE` | `docs/PRODUCT-BASELINE.md` | 产品基线：业务入口、功能清单、用户角色、页面职责、系统边界、冻结决策与不可退化约束。 |
| **03** | `SYSTEM_ARCHITECTURE` | `docs/SYSTEM-ARCHITECTURE.md` | 系统架构：逻辑架构、关键组件、调用拓扑、部署边界、数据流图与高可用设计。 |
| **04** | `TECHNICAL_DESIGN` | `docs/TECHNICAL-DESIGN.md` | 技术方案：核心模块实现、状态机、并发模型、算法设计与依赖拓扑。 |
| **05** | `API_CONTRACT` | `docs/API-CONTRACT.md` | 接口与数据契约：OpenAPI / JSON Schema 引用、CLI/API 契约、错误码字典与向后兼容性契约。 |
| **06** | `PROTOTYPE_UX` | `docs/PROTOTYPE-UX.md` | 可交互原型与交互规范：页面交互流程、视觉基线、DEMO / STAGING / PROD 环境模式标注。 |
| **07** | `TEST_ACCEPTANCE` | `docs/TEST-ACCEPTANCE.md` | 测试规范与持续验收基线：分层测试策略（L1-L4）、需求映射、稳定 Case ID、强断言规则与缺陷回归矩阵。 |
| **08** | `RELEASE_OPERATIONS` | `docs/RELEASE-OPERATIONS.md` | 发布运维与应急恢复手册：部署流程、环境配置、服务入口、备份与隔离恢复校验、回滚步骤与排错清单。 |
| **09** | `DECISION_RECORD` | `docs/DECISION-RECORD.md` | 架构与产品决策记录 (ADR)：重大设计选型、决策背景、权衡考量、审批状态与后果。 |
| **10** | `CROSS_SESSION_HANDOFF` | `docs/CROSS-SESSION-HANDOFF.md` | 跨会话交接：与 `STD-020` 协同，唯一当前交接主入口，自动汇总 Git、锁文件、测试、CI、阻塞项与下一会话启动指引。 |
| **11** | `DOCUMENT_INDEX` | `docs/DOCUMENT-INDEX.md` | 工程文档总索引：汇总项目所有权威有效文档入口、适用性声明、历史归档映射与生命周期状态。 |
| **12** | `ENGINEERING_BASELINE` | `docs/当前权威基线.md` | 当前权威基线：工程正式资料和实时核验事实的自动生成综合视图（引用原始权威资料与实时工程取证）。 |

### 2.1 `DOCUMENT_INDEX` 与 `ENGINEERING_BASELINE` 强制存在性
1. **文档总索引强制存在**：每个受管工程 **MUST** 真实存在 `docs/DOCUMENT-INDEX.md`（或中文受管主索引 `docs/文档总索引.md`），其 `document_type` **MUST** 为 `DOCUMENT_INDEX`，`status` **MUST** 为 `ACTIVE`，且 `primary_entrypoint` **MUST** 为 `true`。文档总索引 **MUST NOT** 占用 `PROJECT_BLUEPRINT` 或其他类型。
2. **当前权威基线强制存在**：每个受管工程 **MUST** 真实存在 `docs/当前权威基线.md`（或英文同义主入口 `docs/ENGINEERING-BASELINE.md`），其 `document_type` **MUST** 为 `ENGINEERING_BASELINE`，`status` **MUST** 为 `ACTIVE`，且 `primary_entrypoint` **MUST** 为 `true`。

### 2.2 文档类型适用性规则 (`document_type_applicability`)
1. **默认全量适用**：默认情况下，12 种正式文档类型在受管工程中均适用，且每种适用文档类型在整个工程内 **MUST** 有且仅有一个文档标记为 `status: ACTIVE` 且 `primary_entrypoint: true`。
2. **显式不适用声明与理由记录**：对于纯后端无界面服务或非运行时制品仓库（`deployment_kind: NON_RUNTIME_ARTIFACT`），若特定类型（如 `PROTOTYPE_UX`）确不适用，工程 **MUST** 在 `engineering-manifest.yaml` 的 `project.document_type_applicability.<TYPE>` 中显式声明 `applicable: false` 并填写非空的 `justification`（理由说明），同时在 `DOCUMENT-INDEX.md` 中登记不适用理由；**MUST NOT** 静默忽略或缺失主入口。`DOCUMENT_INDEX` 与 `ENGINEERING_BASELINE` 永远适用，不得声明为不适用。

### 2.3 历史归档分类（`HISTORICAL_ARCHIVE` 不再作为 `document_type`）
1. **归档属于生命周期与存储分类**：自 `v3.0.0` 起，`HISTORICAL_ARCHIVE` **不再作为正式 `document_type` 枚举值**。历史归档通过文档生命周期状态（`status: ARCHIVED` 或 `SUPERSEDED`）、入口标记（`primary_entrypoint: false`）及归档目录（如 `docs/archive/<VERSION>/` 或 `docs/99-历史归档/`）表达。
2. **保留原有语义类型**：任何归档或被替代的历史文档 **MUST** 保留其原本的业务语义 `document_type`（例如历史产品基线仍为 `PRODUCT_BASELINE`，历史测试报告仍为 `TEST_ACCEPTANCE`，历史架构记录仍为 `SYSTEM_ARCHITECTURE` 或 `DECISION_RECORD`），同时设置 `status: ARCHIVED`（或 `SUPERSEDED`）与 `primary_entrypoint: false`。
3. **禁止静默改变历史文档含义**：迁移既有使用 `document_type: HISTORICAL_ARCHIVE` 的历史文档时，**MUST** 根据文档实际标题、正文语义和历史上下文映射回准确的 12 类正式 `document_type` 之一，并在 `DOCUMENT-INDEX.md` 历史归档映射表中登记，**MUST NOT** 篡改历史正文或静默丢弃历史文档。

---

## 3. 文档元数据、生命周期与审批契约 (Metadata, Lifecycle & Approval Contract)

所有纳入受管的正式工程文档 **MUST** 在文件顶部包含 YAML Frontmatter 格式的结构化元数据块，并通过 `schemas/documentation-metadata.schema.json` 校验：

```markdown
---
document_id: "DOC-STD-ENGINEERING-BASELINE-001"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "ENGINEERING_BASELINE"
status: "ACTIVE"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "自动生成当前权威基线综合视图，汇聚11类正式文档与10类实时工程事实"
history_reference: null
primary_entrypoint: true
source_commit: "5e17c0ef560ab8abafe880b988d70f85f380a104"
approval_scope: "AI_APPROVABLE"
approval_status: "AI_APPROVED"
approval_evidence_ref: "docs/approvals/DOC-STD-ENGINEERING-BASELINE-001.approval.json"
---
```

### 3.1 核心元数据字段约束
1. `document_id` (`string`, 必填): 唯一文档标识，匹配 `^DOC-[A-Za-z0-9_-]+$`。
2. `document_version` (`string`, 必填): 文档语义化版本 `X.Y.Z`。
3. `project_id` (`string`, 必填): 所属工程标识，**MUST** 与 `engineering-manifest.yaml` 中的 `project.id` 完全一致。
4. `document_type` (`string`, 必填): **MUST** 取自 §2 定义的 12 种正式文档类型枚举值之一。
5. `status` (`string`, 必填): 文档生命周期状态，枚举值 `CANDIDATE` | `IN_REVIEW` | `ACTIVE` | `SUPERSEDED` | `ARCHIVED`（兼容期接受历史别名 `DRAFT` | `REVIEW`）。
6. `applies_to_release` (`string`, 必填): 生效对应的工程发布版本（如 `v3.0.0`）。
7. `last_updated` (`string`, 必填): ISO 8601 日期 `YYYY-MM-DD`。
8. `supersedes` (`string|null`, 可选): 被当前版本替代的历史文档 ID。
9. `change_summary` (`string`, 必填): 变更要点摘要（不少于 5 个字符）。
10. `history_reference` (`string|null`, 可选): 关联的历史归档快照路径。
11. `primary_entrypoint` (`boolean`, 必填): 是否为该类型的当前唯一主入口。在正式发布生效状态下主入口 `status` **MUST** 为 `ACTIVE`；在 PR 审核阶段候选主入口文档保持 `IN_REVIEW`；当 `status` 为 `ARCHIVED` 或 `SUPERSEDED` 时，`primary_entrypoint` **MUST** 为 `false`。
12. `source_commit` (`string|null`, 正式活跃文档必填): 文档事实所依据的 Git Commit SHA（严格 40 位十六进制完整 SHA），**MUST** 能够在仓库 Git 历史中真实核验。
13. `approval_scope` (`string`, 可选): `AI_APPROVABLE` | `OWNER_MANDATORY`。
14. `approval_status` (`string`, 可选): `NOT_SUBMITTED` | `IN_REVIEW` | `AI_APPROVED` | `OWNER_APPROVAL_REQUIRED` | `OWNER_APPROVED` | `REJECTED` | `BLOCKED`。
15. `approval_evidence_ref` / `approval_record` (`string|object`, 可选): 指向或内嵌符合 `schemas/documentation-approval.schema.json` 的真实审批证据。

### 3.2 完整治理生命周期与状态分离设计
文档演进全周期包含以下状态流转，且将**文档生命周期状态 (`status`)** 与**审批状态 (`approval_status`)** 严格分离：
1. `CANDIDATE`：编程智能体生成或修订文档候选稿（`approval_status: NOT_SUBMITTED`）。
2. `IN_REVIEW`：提交独立审核阶段，由 ChatGPT 执行跨文档一致性与事实核查（`approval_status: IN_REVIEW`）。
3. `AI_APPROVED` / `OWNER_APPROVED`（属于 `approval_status`）：
   - **模式 A（不需要所有者批准，`AI_APPROVABLE`）**：ChatGPT 完成独立审核并批准，记录 `approval_status: AI_APPROVED`。
   - **模式 B（必须所有者批准，`OWNER_MANDATORY`）**：ChatGPT 完成审核并提出精确审批事项（先记为 `OWNER_APPROVAL_REQUIRED`），所有者可在 ChatGPT 聊天中或受控记录中明确批准，记录 `approval_status: OWNER_APPROVED`。ChatGPT 审核记录与 Owner 批准记录 **MUST** 分开记录。
4. `ACTIVE`（属于 `status`）：**严禁把 AI 审核通过直接等同于正式生效**。文档晋升为 `status: ACTIVE` **MUST** 同时满足以下 **7 项生效门禁**：
   - 1) 内容完整（无未决占位符或缺失必填章节）；
   - 2) 来源真实（`source_commit` 真实存在且引用的代码/证据可核查）；
   - 3) Schema 通过（Frontmatter 及配套结构化 JSON 通过 Schema 校验）；
   - 4) 跨文档一致（与主索引、清单、架构、接口契约无冲突，无重复主入口）；
   - 5) 审批策略满足（符合 §3.3 审批范围要求且具备真实可核验审批证据）；
   - 6) Git 固化（已提交至受控 Git 分支）；
   - 7) 对应正式分支及 CI 符合发布策略（main CI 通过后正式生效并同步至 Project Sources）。
5. `SUPERSEDED`：被新版本正式文档替代，`primary_entrypoint: false`。
6. `ARCHIVED`：归档至 `docs/archive/<VERSION>/` 等历史目录只读封存，`primary_entrypoint: false`。

### 3.3 两种审批范围界定与防伪契约
1. **AI 可审核批准范围 (`AI_APPROVABLE`)**：
   - 自动生成基线视图（`ENGINEERING_BASELINE`）；
   - 文档索引更新（`DOCUMENT_INDEX`）；
   - 已批准事实的汇总与跨会话交接刷新（`CROSS_SESSION_HANDOFF`）；
   - Git 和 CI 证据刷新；
   - 链接及格式修复；
   - 不改变既有决策含义的文档整理。
2. **Owner 必须批准范围 (`OWNER_MANDATORY`)**：
   - 产品范围变化（`PRODUCT_BASELINE` / `PROJECT_BLUEPRINT` 职责增删改）；
   - 架构决策变化（`SYSTEM_ARCHITECTURE` / `DECISION_RECORD`）；
   - API 语义变化（`API_CONTRACT`）；
   - 安全与权限边界变化；
   - 数据所有权变化（`STD-002`）；
   - 正式 Standards 规范语义变化；
   - 破坏性 Schema 变化；
   - 不可逆迁移及重大兼容性变化。
   - **默认保守原则**：当不确定某项修改是否需要 Owner 批准时，**MUST** 默认归入 `OWNER_MANDATORY`，要求 Owner 批准。
3. **审批证据强制绑定与防伪铁律**：
   - 每份审批证据（`schemas/documentation-approval.schema.json`）**MUST** 完整关联以下 9 项字段：`TASK_ID`、`REPOSITORY`、`CANDIDATE_COMMIT`、`CONTENT_SHA256`、`REVIEWER_TYPE`、`REVIEW_RESULT`、`APPROVAL_STATUS`、`APPROVED_AT`、`APPROVAL_REFERENCE`。
   - **禁止智能体自批**：生成候选文档的编程智能体 **MUST NOT** 自行设置或伪造 `AI_APPROVED`、`OWNER_APPROVED`、`HUMAN_ACCEPTED`。缺少真实审核证据时，严禁填写通过。
   - **内容变更自动失效**：一旦目标文档正文（`CONTENT_SHA256`）或绑定的候选提交发生改变，原有审批记录立即失效（`STALE`），**MUST** 重新执行审核。

---

## 4. `ENGINEERING_BASELINE` 当前权威基线设计规范 (`docs/当前权威基线.md`)

### 4.1 定位与边界
1. **正式入口**：`docs/当前权威基线.md`（或 `docs/ENGINEERING-BASELINE.md`），`document_type: ENGINEERING_BASELINE`，`primary_entrypoint: true`。
2. **核心属性**：它是工程正式资料和实时核验事实的**自动生成综合视图**（配套机器可读结构化文件遵循 `schemas/engineering-baseline.schema.json`）。
3. **四不原则**：
   - **不是**第二套产品规格；
   - **不是**第二套架构文档；
   - **不是**第二套接口定义；
   - **不是**人工随意编辑的汇总报告。
   所有条目 **MUST** 显式引用原始权威资料路径与文档 ID。

### 4.2 强制信息来源
基线生成器（`tools/generate_engineering_baseline.py`）**MUST** 聚合以下两类权威输入：
1. **十类正式文档事实源**：
   - 1) `PROJECT-BLUEPRINT`
   - 2) `PRODUCT-BASELINE`
   - 3) `SYSTEM-ARCHITECTURE`
   - 4) `TECHNICAL-DESIGN`
   - 5) `API-CONTRACT`
   - 6) `DECISION-RECORD`
   - 7) `TEST-ACCEPTANCE`
   - 8) `RELEASE-OPERATIONS`
   - 9) `DOCUMENT-INDEX`
   - 10) `CROSS-SESSION-HANDOFF`
2. **九类实时工程事实**：
   - `Git`（当前分支、本地 HEAD、工作区状态）
   - `GitHub main`（远端 `origin/main` 精确 Commit）
   - `Git Tag`（最新正式附注 Tag、Tag Object SHA 与 Peeled Commit）
   - `VERSION`（根目录 `VERSION` 文件）
   - `CI`（最近 GitHub Actions 运行状态与 Run ID）
   - `Build`（最近构建元数据与制品摘要）
   - `Runtime`（在线运行态核验事实或 `NON_RUNTIME_ARTIFACT` 声明）
   - `Acceptance`（最近验收证据状态）
   - `Test Evidence`（实际执行的单元/契约/集成测试结果）
   - `Standards Lock`（`standards.lock.json` 与 `engineering-manifest.yaml` 锁定一致性）

### 4.3 基线十八项必填内容
每份 `ENGINEERING_BASELINE` **MUST** 至少包含以下 18 项结构化章节与字段：
1. 工程身份与定位 (`project_identity`)
2. 当前产品版本 (`product_version`)
3. 正式产品功能及职责 (`product_capabilities`)
4. 当前架构边界 (`architecture_boundaries`)
5. 接口契约入口 (`api_contract_entrypoints`)
6. 已批准 ADR (`approved_adrs`)
7. 当前 Standards 锁定 (`standards_lock`)
8. Git 分支及 Commit 身份 (`git_identity`)
9. 最近 CI 事实 (`recent_ci_facts`)
10. 最近 Build 事实 (`recent_build_facts`)
11. Runtime 核验事实 (`runtime_verification_facts`)
12. 测试和验收事实 (`test_and_acceptance_facts`)
13. 未决问题 (`open_issues`)
14. 待审批事项 (`pending_approvals`)
15. 证据来源 (`evidence_sources`)
16. 来源 Commit (`source_commit`)
17. 核验时间 (`verified_at`)
18. 内容摘要 (`content_sha256`)

### 4.4 动态事实溯源与状态枚举铁律
1. **动态事实六元组**：所有动态工程事实（CI、Build、Runtime、Test/Acceptance 及 `evidence_sources` 清单）**MUST** 完整记录：
   - `repository`
   - `source_path`
   - `source_commit`
   - `evidence_ref`
   - `observed_at`
   - `verification_status`
2. **六态严格区分**：`verification_status` **MUST** 仅取自以下 6 个标准枚举值：
   - `PASS`：经真实运行/探针核验通过，且具备非空、真实存在的 `evidence_ref`；
   - `FAIL`：核验执行但未通过；
   - `BLOCK`：前置条件不满足、门禁拦截或存在冲突；
   - `NOT_RUN`：尚未执行该项测试或构建；
   - `NOT_VERIFIABLE`：因无网络、无远端凭据或非本机运行环境导致当前无法核实；
   - `STALE`：存在历史记录但对应的 Commit 已落后于当前 `source_commit`。
3. **事实防污染与确定性生成**：
   - **严禁混入未核实内容**：历史记录、未核实内容或 `PROPOSED` 设计建议 **MUST** 隔离在“未决问题 (`open_issues`)”或“待审批事项 (`pending_approvals`)”中，**MUST NOT** 混入已核实工程事实。
   - **确定性生成**：相同输入事实 **MUST** 产生完全相同的文档内容与 `content_sha256`（仅 `observed_at` / `verified_at` 时间字段除外）。
   - **冲突阻断**：当基线生成失败、缺失核心权威文档或发现来源事实冲突（如 `VERSION` 与 Manifest/锁文件冲突、存在多个同类型活跃主入口）时，生成器 **MUST** 立即失败退出，**MUST NOT** 覆盖或晋升正式基线。

---

## 5. 最新全量与历史演进机制 (Full Latest & Historical Governance)

1. **规划蓝图与产品基线防退化 (`PROJECT_BLUEPRINT` / `PRODUCT_BASELINE`)**：新功能规划合并入主蓝图，已交付业务职责与冻结决策写入产品基线；未获 `OWNER_APPROVED` 的 ADR 批准，**MUST NOT** 删除或弱化既有产品功能职责。
2. **系统架构图文同源 (`SYSTEM_ARCHITECTURE`)**：系统架构文档 **MUST** 包含文字说明与架构图，并提供可维护源文件（`.mermaid`、`.drawio`、`.puml`）与高清导出图（PNG/SVG），严禁包含临时开发路径。
3. **测试验收持续闭环 (`TEST_ACCEPTANCE`)**：在 `docs/TEST-ACCEPTANCE.md` 中持续维护四层测试策略、需求映射、稳定 Case ID、强断言与历史缺陷回归矩阵。
4. **历史归档只读保护**：归档于 `docs/archive/<VERSION>/`（或 `docs/99-历史归档/`）的历史文档 **MUST** 保持原有的业务 `document_type`，并将 `status` 设为 `ARCHIVED` 或 `SUPERSEDED`、`primary_entrypoint` 设为 `false`。严禁直接删除承载历史决策的文档。

---

## 6. 正式文档与普通参考资料区分规则 (Formal Documents vs Reference Materials)

1. **正式受管文档 (Formal Managed Documents)**：
   - 凡位于 12 类正式文档标准主入口路径（如 `docs/DOCUMENT-INDEX.md`、`docs/当前权威基线.md`、`docs/PROJECT-BLUEPRINT.md` 等）、或在 `DOCUMENT-INDEX.md`“权威最新文档表 / 历史归档映射表”中登记为受管文档、或顶部包含 `document_type` YAML Frontmatter 的 Markdown 文件，均属于正式受管文档，**MUST** 完整包含合规 Frontmatter 并通过 `documentation-metadata.schema.json` 校验。
2. **普通参考资料 (Ordinary Reference Materials)**：
   - 仓库中的普通说明文件（如子目录 `README.md`、工具使用说明、未声明为正式受管主入口的辅助研究笔记、历史归档附件）若未包含 YAML Frontmatter 且未被登记为 12 类正式文档主入口，校验器将其识别为普通参考资料，**MUST NOT** 强制要求所有普通说明文件都添加正式文档 Frontmatter；但普通参考资料 **MUST NOT** 冒充任何正式文档类型的主入口。

---

## 7. 项目文档主索引规范 (`DOCUMENT-INDEX.md`)

每个受管工程的 `docs/` 目录下 **MUST** 维护唯一活跃的 `DOCUMENT-INDEX.md`（或 `docs/文档总索引.md`）：
1. **权威最新文档表**：完整列出 12 类正式文档的适用性、权威入口路径、文档 ID、版本、生命周期状态 (`status`)、审批状态 (`approval_status`) 与职责概述。
2. **不适用类型登记表（如有）**：与 `engineering-manifest.yaml` 的 `project.document_type_applicability` 一致，记录不适用类型及理由。
3. **历史归档映射表**：列出已归档历史文档的归档路径、保留的语义 `document_type`、历史版本、关联 Tag 与替代它的活跃文档 ID。

---

## 8. 跨会话与智能体交接协同规范 (Cross-Session Agent Collaboration)

1. **新会话启动必读顺序**：任何新启动的聊天会话或编码智能体在执行任务前，**MUST** 按以下顺序读取工程事实源并核验实时状态：
   - 1) `docs/DOCUMENT-INDEX.md`（工程文档总索引）
   - 2) `docs/当前权威基线.md`（当前权威基线 `ENGINEERING_BASELINE`）
   - 3) `docs/CROSS-SESSION-HANDOFF.md`（当前跨会话交接 `STD-020`）
   - 4) `docs/PROJECT-BLUEPRINT.md` 与 `docs/PRODUCT-BASELINE.md`
   - 5) `docs/SYSTEM-ARCHITECTURE.md`、`docs/TECHNICAL-DESIGN.md`、`docs/API-CONTRACT.md`
   - 6) `docs/TEST-ACCEPTANCE.md` 与 `docs/DECISION-RECORD.md`
2. **实时核验铁律**：新会话 **MUST** 重新核验实时 Git、Standards 锁定、CI 与 Runtime 状态，**MUST NOT** 仅凭旧会话聊天摘要推断当前工程事实。

---

## 9. 工程级文档集合与索引验证门禁 (`tools/validate-documentation-collection.py`)

工程 CI/CD 与交付门禁 **MUST** 强制执行 `tools/validate-documentation-collection.py`，真实阻断以下 17 类违规情形：
1. **12 类正式文档定义统一**：拒绝非法的 `document_type` 枚举值。
2. **`ENGINEERING_BASELINE` 纳入 Schema**：核验基线文档元数据及动态事实结构。
3. **`HISTORICAL_ARCHIVE` 归档分类核验**：若发现遗留 `document_type: HISTORICAL_ARCHIVE`，阻断并提示迁移至原语义 `document_type` + `status: ARCHIVED` + `primary_entrypoint: false`。
4. **章节结构完整**：正式规范与基线文档章节编号连续、无重复章节。
5. **`DOCUMENT-INDEX` 必须真实存在**：缺失或删除 `DOCUMENT-INDEX` 主入口立即判定 `FAIL`。
6. **`ENGINEERING_BASELINE` 必须真实存在**：缺失或删除 `ENGINEERING_BASELINE` 主入口立即判定 `FAIL`。
7. **每个适用文档类型唯一活跃主入口**：每个适用 `document_type` **MUST** 有且仅有 1 个 `status: ACTIVE` 且 `primary_entrypoint: true` 的文档；缺失（0 个）或存在多个（>1 个）均立即判定 `FAIL`。
8. **缺少正式文档 Frontmatter 必须阻断**：任何标准主入口文件或索引登记的正式文档若缺失 YAML Frontmatter，立即判定 `FAIL`。
9. **项目 ID 与 Manifest 一致**：文档 `project_id` 与 `engineering-manifest.yaml` 的 `project.id` 不一致时立即判定 `FAIL`。
10. **所有索引引用必须真实存在**：`DOCUMENT-INDEX` 中引用的所有文件路径必须真实存在且文件大小 `> 0`。
11. **所有内部 Markdown 链接及锚点必须有效**：正式文档中的相对路径链接及 `#heading-anchor` 锚点若指向不存在的文件或标题锚点，立即判定 `FAIL`。
12. **历史文档不得成为活跃主入口**：归档目录（`archive/`、`99-历史归档/`、`历史档案/`）下的文档或状态为 `ARCHIVED`/`SUPERSEDED` 的文档若标记为 `status: ACTIVE` 或 `primary_entrypoint: true`，立即判定 `FAIL`。
13. **所有标准模板必须通过 Schema**：`templates/documentation/*.template.md` 必须 100% 通过 `documentation-metadata.schema.json` 校验。
14. **审批状态必须与实际审批证据一致**：声明 `AI_APPROVED` 或 `OWNER_APPROVED` 时，必须具备匹配的审批证据、正确的 `content_sha256` 与 `candidate_commit`，严禁智能体自填审批通过。
15. **来源 Commit 必须能够核验**：`source_commit` 必须是合法的 Git Commit SHA 且在当前仓库（或引用的目标仓库）Git 对象库中可核验。
16. **冲突文档不得自动选择胜出者**：发现同类型多个 `primary_entrypoint: true` 或重复 `document_id` 时，必须直接报错阻断，严禁按文件名排序或时间静默挑选。
17. **缺少证据不能填写 `PASS`**：动态核验事实若状态为 `PASS` 但缺失有效 `evidence_ref`，立即判定 `FAIL`。

### 9.1 跨平台与零硬编码路径调用规范
校验器 **MUST** 支持 Windows、WSL、Linux 与 GitHub Actions，严禁硬编码依赖 `D:/Projects/AI-Engineering-Standards`，并统一支持以下参数与环境变量：
- `--project-root <PATH>`：被校验工程根目录（默认 `.`）；
- `--standards-root <PATH>`：Standards 仓库根目录（可选，默认依次读取 `--standards-root`、环境变量 `AI_ENGINEERING_STANDARDS_ROOT`、工具自身所在仓库根路径）；
- `--schema <PATH>`：显式指定 `documentation-metadata.schema.json` 路径。
