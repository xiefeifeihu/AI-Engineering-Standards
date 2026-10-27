# STD-035: Documentation Lifecycle & Project Baseline Contract (全生命周期工程文档与产品基线契约规范)

```text
STANDARD_ID=STD-035
VERSION=2.9.1
STATUS=ACTIVE
SCOPE=全平台受管工程仓库 (AI-Engineering-Hub, AI-Engineering-Standards, AI-KB, vtip-ai-sidecar, vtip-platform-catalog 及未来所有受管项目)
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-27
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

### 3.2 DOCUMENT_INDEX 独立语义与主入口排他性
1. **独立类型与权威入口**：`DOCUMENT-INDEX.md` (或根目录索引文件) **MUST** 使用 `document_type: DOCUMENT_INDEX` 与 `primary_entrypoint: true`。每个工程内 **MUST** 仅存在唯一活跃的文档总索引。
2. **严禁占用蓝图主入口**：文档总索引 **MUST NOT** 使用 `document_type: PROJECT_BLUEPRINT` 或声明替代项目蓝图。`PROJECT_BLUEPRINT` 是规划蓝图的专属类型，具有独立的权威主入口（`docs/PROJECT-BLUEPRINT.md`）。


## 1. 目标与治理背景 (Background & Objectives)

为杜绝各受管工程在多会话、多智能体协作中出现的“仅有零散增量交接报告、缺乏最新全量文档事实源、历史决策相互矛盾、产品职责无意遗失、架构图与代码脱节”等工程退化问题，本规范定义平台统一的**全生命周期工程文档与产品基线契约**：

1. **最新全量与历史演进双重保证**：每个工程 **MUST** 始终维护一份最新的、完整的全量文档集合，任何人或智能体进入项目均可独立理解完整项目蓝图、产品职责与架构；同时 **MUST** 完整保留历史演进过程与架构决策记录。
2. **唯一权威入口原则 (Single Canonical Entrypoint)**：同一种正式文档类型在项目主干中 **MUST** 仅存在唯一权威活跃入口（`PRIMARY_ENTRYPOINT=true`），严禁维护多份相互矛盾的“最新”副本。
3. **结构化文档元数据**：所有正式文档 **MUST** 包含结构化元数据头，支持自动化检查器验证其版本、状态、生效发布版本与替代关系。
4. **图文同源与制品隔离**：架构图 **MUST** 具备可维护源文件与对应的高清导出图；过程日志、媒体截图与运行证据 **MUST** 归档至 `.artifacts/`，**MUST NOT** 污染 Git 文档目录。

---

## 2. 十二种正式文档类型规范 (Twelve Formal Document Types)

受管工程根据项目规模可适当合并部分章节，但以下 12 项文档职责 **MUST** 明确存在、可检索并可追溯：

| 编号 | 文档类型 (DOCUMENT_TYPE) | 标准文件名建议 | 职责说明 |
|:---|:---|:---|:---|
| **01** | `PROJECT_BLUEPRINT` | `PROJECT-BLUEPRINT.md` | 项目规划蓝图：背景、定位、终态愿景、能力全景图、演进路线与里程碑。 |
| **02** | `PRODUCT_BASELINE` | `PRODUCT-BASELINE.md` | 产品基线：业务入口、功能清单、用户角色、菜单页面职责、系统边界、冻结决策与不可退化约束。 |
| **03** | `SYSTEM_ARCHITECTURE` | `SYSTEM-ARCHITECTURE.md` | 系统架构：逻辑架构、关键组件、调用拓扑、部署边界、数据流图与高可用设计。 |
| **04** | `TECHNICAL_DESIGN` | `TECHNICAL-DESIGN.md` | 技术方案：核心模块实现、状态机、并发模型、算法设计与依赖拓扑。 |
| **05** | `API_CONTRACT` | `API-CONTRACT.md` | 接口与数据契约：OpenAPI / JSON Schema 引用、错误码字典、协议向后兼容性契约。 |
| **06** | `PROTOTYPE_UX` | `PROTOTYPE-UX.md` | 可交互原型与交互规范：页面交互流程、视觉基线、DEMO / STAGING / PROD 环境模式标注。 |
| **07** | `TEST_ACCEPTANCE` | `TEST-ACCEPTANCE.md` | 测试规范与验收标准：分层测试策略（L1-L4）、验收矩阵、必测场景与门禁条件。 |
| **08** | `RELEASE_OPERATIONS` | `RELEASE-OPERATIONS.md` | 发布运维与应急恢复手册：部署流程、环境配置、服务入口、备份与隔离恢复校验、回滚步骤与排错清单。 |
| **09** | `DECISION_RECORD` | `DECISION-RECORD.md` / `adr/` | 架构与产品决策记录 (ADR)：重大设计选型、决策背景、权衡考量与后果。 |
| **10** | `CROSS_SESSION_HANDOFF`| `CROSS-SESSION-HANDOFF.md` | 跨会话交接：与 `STD-020` 协同，记录当前版本状态、已完成事项、未竟事项与下一步操作指南。 |
| **11** | `HISTORICAL_ARCHIVE` | `archive/<version>/` | 历史版本归档：重大发布版本的冻结快照，支持溯源比对。 |
| **12** | `DOCUMENT_INDEX` | `DOCUMENT-INDEX.md` | 工程文档总索引：汇总项目所有权威有效文档入口、历史归档映射与生命周期状态。 |

---

## 3. 文档元数据契约 (Document Metadata Contract)

所有纳入受管的正式工程文档 **MUST** 在文件顶部包含 YAML Frontmatter 格式的结构化元数据块，并符合 `schemas/documentation-metadata.schema.json` 校验：

```markdown
---
document_id: "DOC-HUB-PRODUCT-BASELINE-001"
document_version: "1.2.0"
project_id: "ai-engineering-hub"
document_type: "PRODUCT_BASELINE"
status: "ACTIVE"
applies_to_release: "v0.21.10"
last_updated: "2026-10-27"
supersedes: "DOC-HUB-PRODUCT-BASELINE-000"
change_summary: "统一产品基线至最新全量正文，规范控制平面与网关职责"
history_reference: "docs/archive/v0.21.9/AI-Hub-Product-Baseline.md"
primary_entrypoint: true
---
```

### 3.1 字段语义与约束
1. `document_id` (string, 必须): 全局或项目内唯一文档标识，格式建议 `DOC-<PROJECT>-<TYPE>-<SEQ>`。
2. `document_version` (string, 必须): 文档语义化版本，格式 `X.Y.Z`。
3. `project_id` (string, 必须): 所属工程标识，必须与 `engineering-manifest.yaml` 中的 `project.id` 一致。
4. `document_type` (string, 必须): 必须取自 11 种正式类型枚举值之一：
   `PROJECT_BLUEPRINT`, `PRODUCT_BASELINE`, `SYSTEM_ARCHITECTURE`, `TECHNICAL_DESIGN`, `API_CONTRACT`, `PROTOTYPE_UX`, `TEST_ACCEPTANCE`, `RELEASE_OPERATIONS`, `DECISION_RECORD`, `CROSS_SESSION_HANDOFF`, `HISTORICAL_ARCHIVE`, `DOCUMENT_INDEX`。
5. `status` (string, 必须): 枚举值 `DRAFT` | `REVIEW` | `ACTIVE` | `SUPERSEDED` | `ARCHIVED`。
6. `applies_to_release` (string, 必须): 该文档生效对应的工程发布版本（如 `v0.21.10`）。
7. `last_updated` (string, 必须): ISO 8601 日期格式 `YYYY-MM-DD`。
8. `supersedes` (string/null, 可选): 被当前版本替代的历史文档 ID 或版本。
9. `change_summary` (string, 必须): 本次文档变更要点摘要。
10. `history_reference` (string/null, 可选): 关联的历史归档快照或 Git 引用相对路径。
11. `primary_entrypoint` (boolean, 必须): 是否为该类型的当前唯一活跃入口。项目中同一 `document_type` 下 **MUST** 有且仅有一个文件的 `primary_entrypoint` 为 `true`。

---

## 4. 最新全量与历史演进机制 (Full Latest & Historical Governance)

### 4.1 项目规划蓝图演进机制 (`PROJECT_BLUEPRINT`)
1. **全量维护**：工程规划蓝图 **MUST** 保持最新全量，涵盖背景定位、建设目标、已交付能力、待建设路线图与风险约束。
2. **严禁碎片化补丁累加**：新功能规划提出时，必须以“提案 -> 评审 -> 合并入主蓝图 -> 归档历史提案”的生命周期推进。任何进入项目的人员均只需阅读最新的 `PROJECT-BLUEPRINT.md` 即可获得项目全貌。

### 4.2 产品基线不退化机制 (`PRODUCT_BASELINE`)
1. **产品职责防丢失**：产品基线 **MUST** 明确记录所有已交付业务入口、功能清单与冻结决策。
2. **版本化基线**：在小版本升级或日常开发中，**MUST NOT** 无意删除、弱化或遗漏既有已交付功能的产品职责；功能变更或下线必须通过显式 ADR 决策批准。

### 4.3 架构图与架构说明规范 (`SYSTEM_ARCHITECTURE`)
1. **图文同源**：系统架构文档 **MUST** 包含文字说明与系统架构图，且图与文 **MUST** 描述完全一致的架构版本。
2. **源文件可维护性**：架构图 **MUST** 提供可编辑源文件（如 `.drawio`, `.puml`, `.mermaid`）并存放于文档同级或 `assets/` 目录。
3. **高清导出要求**：导出的图片格式优先选用高清 PNG 或 SVG，复杂系统拓扑推荐 4K 分辨率（3840×2160），保证文字清晰易辨。
4. **禁止临时路径侵入**：架构图中 **MUST NOT** 包含诸如 `D:\Projects\_ReleaseDeps\...` 或临时开发目录的物理绝对路径。

### 4.4 历史归档与溯源机制 (`HISTORICAL_ARCHIVE`)
1. **归档目录规范**：历史快照应按发布版本存放于 `docs/archive/<VERSION>/`。
2. **只读保护**：归档目录中的历史文档其 `status` **MUST** 为 `ARCHIVED` 或 `SUPERSEDED`，且 `primary_entrypoint` **MUST** 为 `false`。
3. **禁止静默删除**：在整理清理过时文档时，**MUST NOT** 直接删除承载历史产品决策的文档，必须先登记在 `DOCUMENT-INDEX.md` 并移动至 `docs/archive/` 留存。

---

## 5. 跨会话与智能体交接协同规范 (Cross-Session Agent Collaboration)

1. **会话启动优先读取清单**：新启动的聊天会话或编码智能体（Claude Code、Codex、Antigravity）在执行开发任务前，**MUST** 优先读取以下核心文件：
   - `docs/DOCUMENT-INDEX.md`（项目文档主索引）
   - `docs/PROJECT-BLUEPRINT.md`（最新规划蓝图）
   - `docs/PRODUCT-BASELINE.md`（最新产品基线）
   - `docs/SYSTEM-ARCHITECTURE.md`（最新系统架构）
   - `docs/04-API契约/` 或 `docs/API-CONTRACT.md`（最新接口契约）
   - `docs/CROSS-SESSION-HANDOFF.md` 或最近的交接文档（`STD-020`）
2. **交接禁止凭空推测**：交接文档必须基于真实代码、Git HEAD、测试输出与运行身份填写，严禁仅凭会话自然语言猜测项目全部历史设计。

---

## 6. 项目文档主索引规范 (`DOCUMENT-INDEX.md`)

每个受管工程的 `docs/` 目录根下 **MUST** 维护一份 `DOCUMENT-INDEX.md`，作为该工程文档体系的统一入口：
1. **权威最新文档表**：列出当前生效的所有 11 类文档权威入口路径、文档 ID、版本及状态。
2. **历史归档映射表**：列出已归档历史文档、被替代版本、归档路径与关联发布 Tag。
3. **机器校验门禁**：工程交付门禁（`verify_delivery_contract.py`）将自动核验 `DOCUMENT-INDEX.md` 中引用的所有活跃文档真实存在且元数据符合 Schema。


---

## 5. 工程级文档集合与索引验证规则 (Project-Level Collection Governance)

除单份文档 Frontmatter 符合 Schema 之外，工程 CI/CD 与交付门禁 **MUST** 强制执行工程级文档集合验证（`tools/validate-documentation-collection.py`）：

1. **同类文档唯一活跃主入口**：对于每一个 `document_type`，整个工程内 **MUST** 有且仅有一个文档标记为 `status: ACTIVE` 且 `primary_entrypoint: true`。严禁同类文档存在多个活跃主入口。
2. **文档类型语义纯洁**：`DOCUMENT-INDEX.md` 必须为 `DOCUMENT_INDEX`，不得占用 `PROJECT_BLUEPRINT` 或其他专业文档类型。
3. **项目标识完全一致**：文档 Frontmatter 中的 `project_id` **MUST** 与当前工程根目录 `engineering-manifest.yaml` 中的 `project.id` 保持完全一致（包含大小写）。
4. **权威入口真实存在**：文档索引表中的所有权威入口路径（如 `docs/PROJECT-BLUEPRINT.md`）**MUST** 在文件系统中真实存在且大小大于 0 字节。
5. **历史归档映射真实存在**：文档索引“历史归档映射表”中声明的所有历史文件相对路径 **MUST** 在文件系统中真实存在。
6. **历史文档生命周期隔离**：历史归档目录（如 `docs/archive/`）下的文档 **MUST NOT** 标记为 `status: ACTIVE` 或 `primary_entrypoint: true`，必须为 `ARCHIVED` 或 `SUPERSEDED`。
7. **架构图与图源同源**：系统架构文档引用的所有架构图，**MUST** 同时提供可维护源文件（如 Mermaid 代码块、`.drawio` 或 `.puml` 源文件）及对应的高清导出图。
8. **交付模板合规**：`templates/documentation/` 下的所有标准模板 **MUST** 全部通过 `documentation-metadata.schema.json` 强校验。
