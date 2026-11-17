---
document_id: "DOC-STANDARDS-TECHNICAL-DESIGN"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "TECHNICAL_DESIGN"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "9687f961b22df612c4311961e06fc1c1fd508c37"
applies_to_release: "v3.0.0"
last_updated: "2026-11-16"
supersedes: null
change_summary: "补充消费端身份、远端发现来源与历史快照 Git 谱系验证设计。"
history_reference: "CHANGELOG.md"
primary_entrypoint: true
content_sha256: null
---


# 技术方案与详细设计 (Technical Design)

## 1. 确定性权威基线生成算法 (`tools/generate_engineering_baseline.py`)

- **输入源严格限定**：仅读取 `engineering-manifest.yaml`、`VERSION`、`standards.lock.json`、11 类 `ACTIVE` 主入口文档（`PROJECT_BLUEPRINT` 至 `CROSS_SESSION_HANDOFF`）及实时 Git/CI/测试事实。
- **确定性哈希计算 (`compute_deterministic_baseline_sha256`)**：对基线结构化载荷递归剥离时间字段（`observed_at`、`verified_at`、`content_sha256`），按 UTF-8 字典序序列化为紧凑 JSON 后计算 `sha256:<64-hex>`，保证相同输入事实产生完全相同的正文与内容摘要。
- **冲突阻断 (Fail-Closed)**：当任一必选源文档缺失、同一类型存在多个主入口、`project_id` 不一致、`source_commit` 跨文档冲突或 `standards.lock.json` 与 `engineering-manifest.yaml` 不一致时，立即返回非零退出码并拒绝生成或覆盖 `docs/当前权威基线.md`。

### 1.1 校验 Scope 彻底解耦 (F10)

基线生成器彻底解耦 **Standards 自身发布证据核验** 与 **消费端工程基线核验**：
- **`--scope consumer` (默认)**：仅核验工程仓库自身 `source_commit`、文档完整性、SHA256、Git 快照及消费端实时 CI 证据；遇到缺失或无法联网时正确记录为 `NOT_RUN` / `NOT_VERIFIABLE`，绝不加载或强校验 Standards 自身的 PR9、STD-018、STD-019 发布证据。
- **`--scope standards-release` (Standards CI 显式调用)**：执行全量严格核验，涵盖三作用域（PR9 历史证据、STD-018 当前快照、STD-019 最终发布证据）语义事实与 Git 快照。

## 2. 双层审批与防伪造校验设计 (`tools/validate_approval_contract.py`)

- **生命周期与审批分离**：文档 YAML Frontmatter 中 `status` 表示文档生命周期，`approval_status` 表示审核批准状态。当 `status: ACTIVE` 时，若 `approval_scope: OWNER_APPROVAL_REQUIRED`，则 `approval_status` 必须为 `OWNER_APPROVED`；若未声明 `approval_scope`，默认按 `OWNER_APPROVAL_REQUIRED` 校验。
- **反自批与防篡改校验**：`validate_approval_record()` 强制拦截 `reviewer_type` 为 `CODING_AGENT` / `SELF` 的记录，强制校验 `chatgpt_review` 与 `owner_approval` 分离存储，并比对文档当前正文 SHA-256 与审批记录绑定的 `content_sha256` 及 `candidate_commit`；一旦正文或 Commit 发生变更，原审批记录立即判定为 `STALE_APPROVAL_HASH_MISMATCH`。

## 3. 官方同步工具与 11 步状态机 (`tools/standards_sync/`)

- **精确 Tag 发现 (`discover`)**：通过 `git ls-remote --tags` 解析全部 SemVer 标签，区分 Annotated Tag Object SHA (`refs/tags/vX.Y.Z`) 与 Peeled Commit SHA (`refs/tags/vX.Y.Z^{}`)，按 `(major, minor, patch)` 严格排序，禁止按字符串排序。
- **四元组校验 (`verify-lock`)**：校验 `standards.lock.json` 的 Schema 合规性、Tag 存在性、`tag_object_sha` 真实性、`peeled_commit` 一致性、对应 Commit 的 `VERSION` 文件一致性，以及 `peeled_commit` 是否位于 `main` 分支祖先链上。
- **受控晋升与回滚 (`promote` / `rollback`)**：`promote` 强制验证非降级、`ci_status == PASS`、`validate_upgrade_candidate == PASS` 及有效审批记录，晋升前自动将当前锁定压入 `previous_locks` 栈；`rollback` 从 `previous_locks` 弹出最近一次已验证锁定并原子写回 `standards.lock.json` 与 `engineering-manifest.yaml`。


### 3.1 消费端身份、发现来源与历史快照验证（Std-020）

- **Commit 身份分离**：`INPUT_STANDARDS_COMMIT` 与 `TARGET_STANDARDS_COMMIT` 指向 Standards 仓库；`CONSUMER_COMMIT` 单独记录消费工程 HEAD。不得将两仓 Commit 混写为同一字段。
- **工作区绑定**：只有消费工程 HEAD 可读且 `git status --porcelain` 为空时，`CONSUMER_VERIFICATION_STATUS` 才能为 `PASS`。工作区为 `DIRTY` 或无法读取时，身份状态为 `NOT_VERIFIABLE`，影响分析保持 `PARTIAL`，不得声称完整兼容。
- **远端发现来源**：本地 Clone 仅证明本地 refs；没有独立查询官方远端时，`remote_latest_status` 为 `NOT_VERIFIABLE`。官方远端身份与本地对象谱系必须分别记录。
- **祖先判定**：`git merge-base --is-ancestor` 退出码 0 表示祖先、1 表示确证非祖先；其他退出码表示对象或命令不可核验，不得映射为非祖先。
- **历史快照**：历史发布/完成标记本身不构成免检凭据。只有记录的 `local_head` 与当前分支 HEAD 相同，或经 Git 对象图证明其为当前分支/官方 main 的祖先时，才可按历史快照豁免 24 小时新鲜度窗口；祖先关系无法核验或不成立时必须阻断历史豁免。生成器仍须核对 `captured_at` 时刻的提交和远端 main 快照。

### 3.2 历史 Lock 回滚与原子事务设计 (F11)

- **回滚强制 Owner 授权与官方 Tag 核验**：CLI `rollback` 子命令强制要求 `--rollback-authorization-ref`，默认 `require_authorization=True`，严禁智能体无授权直接修改锁文件；回滚前必须调用 `verify_official_historical_tag` 核验目标 Tag 在官方规范仓远端存在、Tag 对象与剥离提交匹配、以及位于官方 main 祖先链上；远端不可达返回 `NOT_VERIFIABLE`，不匹配返回 `FAIL`。
- **历史审批与回滚授权分离**：历史初始 bootstrap lock 的 `approval_evidence_ref` 为 `null` 属于历史客观事实，在 `schemas/standards-lock.schema.json` 中定义为合法；当前执行回滚时，通过 `rollback_authorization_ref` 单独绑定当前 Owner 授权。
- **历史 CI 真实性与晋升继承**：若历史 Lock 缺少 `ci_verification_status`，严格标记为 `NOT_VERIFIABLE`，严禁假定或自动回退为 `PASS`（杜绝违反 Rule G）；`promote_upgrade` 保存历史 Lock 至 `previous_locks` 时同样严格继承或默认 `NOT_VERIFIABLE`，杜绝虚标 `PASS`。
- **两文件原子事务**：`rollback_lock` 与 `promote_lock` 均采用 `execute_transactional_two_file_update`，先写入临时文件，再原子替换并同步刷新 `.bak` 备份；任一阶段失败自动回滚内存与磁盘状态，杜绝文件状态撕裂。

### 3.3 单 Owner 双 Commit PR Merge Event 审批契约 (F12 / 方案 C)

- **概念解耦与双向绑定完整性**：彻底消除消费端候选 Commit 与 Standards Peeled Commit 的概念混淆，审批记录显式包含 `commit_bindings`，明确 `consumer.candidate_commit` 与 `standards.peeled_commit`（包含 repository、target_tag、tag_object_sha、peeled_commit 4 项完整字段），以及包含 `ci_job_mapping_sha256` 与 `lock_manifest_sha256` 的 `content_bindings`。
- **记录与事件字段对齐与强时间校验**：审批记录与 `approval_event` 内的 `commit_bindings` 和 `content_bindings` 必须逐字段严格相等；`event_timestamp` 必须精确等于 GitHub PR API 返回的 `merged_at`。
- **GitHub PR Merge Provenance 与智能体边界**：通过 GitHub API 读取 PR Merge 事件，核验 `merged=true`、`merged_by` 为仓库属主、`base.ref=main`、`head.sha=consumer.candidate_commit`，严禁智能体自批或合并（`CODING_AGENT` 强阻断）。
- **禁止单 Commit 旁路绕过**：针对 `STANDARDS_LOCK_PROMOTION` 和 `LOCK_ROLLBACK` 作用域，强制要求双向绑定，禁止退化为单 Commit 遗留旁路。
- **枚举清理**：彻底废除未实现的 `SIGNED_OWNER_EVENT` 伪枚举。

### 3.4 官方验收打包器原子事务与静默回填根治

- **移除静默回填**：彻底移除 `package_acceptance.py` 对 `task_id` 和 `version` 的静默回填逻辑，缺失必需字段时立即抛出 `ValueError`，强制 `validate_acceptance_manifest` 发挥完整门禁作用。
- **临时写入与自校验后原子替换**：打包过程先写入 `.tmp_*.zip` 与 `.tmp_*.sha256`，在临时状态完成解包抽检与摘要校验；校验全绿后通过 `os.replace` 原子替换正式制品。
- **全失败场景原子回退**：发生任何异常时，恢复修改前的 `manifest.json`、还原既有正式制品（若存在备份），并清理所有临时文件，杜绝半成品残留。

## 4. 消费端接入模式与首个试点

- **共享实现原则**：消费工程通过固定版本的 Git 子模块（推荐路径 `.standards/`）或受控共享检出目录引用本仓库；不得复制后分叉维护公共脚本、Schema 和规范正文。
- **版本发现与执行分离**：官方 `main` 仅用于发现最新正式 Release；工程执行时必须使用 `standards.lock.json` 锁定的精确 Tag、Tag Object SHA 与 Peeled Commit。
- **首个消费端试点**：AI-Engineering-Hub。试点仅验证 Standards 接入、文档生成、规范校验、兼容性评估和升级/回滚契约；本 PR 不修改 Hub 源码。
- **其他工程**：AI-KB、VTIP、SideCar 均不属于本轮试点或迁移承诺；后续是否接入由各工程 Owner 独立决定。
