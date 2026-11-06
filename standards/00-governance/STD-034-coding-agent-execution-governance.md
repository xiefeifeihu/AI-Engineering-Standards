# STD-034: Coding Agent Execution Governance & Machine Gate Contract (跨工程编程智能体执行治理与强制机器门禁规范)

```text
STANDARD_ID=STD-034
VERSION=3.0.0
STATUS=ACTIVE
SCOPE=全平台受管工程仓库 (AI-Engineering-Hub, AI-Engineering-Standards, AI-KB, vtip-ai-sidecar, vtip-platform-catalog)
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-11-05
SCHEMA_REF=schemas/standards-lock.schema.json, schemas/documentation-approval.schema.json, schemas/test-coverage-verification.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. `AGENTS.md` 项目级规则契约 (Project-Level Agent Rule Contract)

1. **根目录唯一权威入口**：每个受管工程仓库根目录 **MUST** 维护 `AGENTS.md`，作为进入该仓库的所有编程智能体（Claude Code、Codex、Antigravity 等）的统一项目级工程治理入口。
2. **禁止在说明文档中手工写死最新 Standards 版本**：`AGENTS.md`、`CLAUDE.md`、`README.md` 等项目说明文档 **MUST NOT** 长期手工硬编码最新 Standards 版本号或 Commit SHA；应引用仓库根目录的 `standards.lock.json`（及 Standards 自身的 `VERSION` 文件）作为版本锁定的唯一机器可读事实源。
3. **十五项强制工程铁律 (`Rules A–O`)**：每个项目的 `AGENTS.md` **MUST** 完整声明并执行以下 15 项核心治理规则：
   - **Rule A（开始工作先核验 Git 和 Standards）**：开始任务前必须先执行只读基线核查，核验当前 Git 分支、`LOCAL_HEAD`、`REMOTE_HEAD`、`MAIN_HEAD`、`WORKTREE_STATUS`（`git status -sb`），并通过官方同步工具核验 `standards.lock.json` 的精确 `VERSION`、`TAG`、`TAG_OBJECT_SHA` 与 `PEELED_COMMIT`，并检查是否存在最新正式发布版本。
   - **Rule B（Standards 是统一规范唯一事实源）**：`AI-Engineering-Standards` 是全平台工程规范唯一事实源（Single Source of Truth）。业务与平台仓库不得复制完整 Standards 正文或另立冲突规范，亦不得各自维护一套私有的 Tag 发现与版本比较脚本。
   - **Rule C（保护正式 main 与受控分支治理）**：严禁直接在未经验证的 `main` 分支上随意提交或开发。在 `CONTROLLED_IMPLEMENTATION_WITH_INDEPENDENT_REVIEW` 或 `MAINTAINER_RELEASE` 模式下，所有开发必须从干净基线创建独立分支并通过 PR 交由 ChatGPT 独立审核与（必要时）Owner 批准。在 `PERSONAL_LOCAL` 声明下遵循 `STD-032` / `STD-034`，向 `origin/main` 同步前必须通过本地校验与测试，且必须等待目标 `main` Commit 在 GitHub Actions 上的真实远端 CI 全绿；严禁强推（`git push --force`）、严禁绕过分支保护、严禁伪造测试。
   - **Rule D（保护现有工作区）**：严禁覆盖、丢弃或清理工作区中已有的未提交修改或历史验收成果；严禁使用 `git reset --hard`、`git clean -fd`、`git push --force`。
   - **Rule E（严格遵守跨仓修改边界）**：严格遵循 `STD-002` / `STD-017` 及任务授权范围，严禁越权修改未授权仓库。
   - **Rule F（零密钥与隐私保护）**：严格执行 `STD-007`，严禁向 Git、日志或交付包提交任何 Token、API Key、Cookie、Authorization 头、私钥、真实生产完整正文或私人本地配置（如 `.env`、`settings.local.json`）。
   - **Rule G（实际运行测试后才能报告 `PASS`）**：所有测试状态必须基于真实执行的测试命令、`exit_code=0` 及原始测试日志输出（`STD-014`），严禁未运行或失败时报告 `PASS`。
   - **Rule H（发布前与部署后两次自动化）**：单元、契约、集成和候选 Playwright 是发布前质量门禁；正式部署后必须再对真实 LIVE 服务执行实际用户任务与端到端业务自动化验证（`STD-014`、`STD-015`、`STD-031`）。严禁使用临时开发端口或 Mock 冒充生产测试，仅有发布前绿灯不得宣称生产功能已验收。
   - **Rule I（不得伪造模型执行、构建和运行 Commit）**：严禁伪造模型调用记录、耗时、Token 用量，严禁伪造 `SOURCE_COMMIT`、`BUILD_COMMIT`、`LIVE_COMMIT` 或容器/进程运行身份证据（`STD-031` / `STD-032`）。
   - **Rule J（不得用静态 JSON 制造高质量验收结果）**：严禁编写静态生成脚本或手写 JSON 汇总文件来冒充真实测试结果、Playwright 验收结果或运行时探针证据。
   - **Rule K（不得将 HTTP 200 自动认定为业务采纳或编码交付完成）**：技术请求返回 HTTP 200（或仅完成 Stage A 执行事件上报 / `MODEL_EXECUTION_SUCCESS`）不等于业务采纳或编码交付完成；正向用例必须断言真实业务终态，负向用例必须断言预期阻断。
   - **Rule L（不得自动提交人工或独立 AI 审核 `PASS`）**：未经真实独立审核确认，编程智能体不得自行设置或伪造 `AI_APPROVED`、`OWNER_APPROVED`、`HUMAN_ACCEPTED` 或 `OWNER_LOCAL_CONSENT_RECORDED`。不确定是否需要 Owner 批准时，默认要求 Owner 批准。
   - **Rule M（正式发布必须执行有效 Standards 的 CI/CD）**：正式发布与里程碑验收必须执行符合当前有效 Standards 的真实 CI/CD 与交付契约校验门禁，并依据声明的 `ReleaseProfile` 严格执行对应门禁。
   - **Rule N（验收目录与 ZIP 目录必须区分）**：过程验收证据目录（`.artifacts/acceptance/`）与正式交付 ZIP 目录（`.artifacts/packages/`）必须严格隔离，严禁将正式交付 ZIP 存放在 `acceptance` 目录或仓库根目录下。
   - **Rule O（生产实际验收与全证据闭环优先）**：任一关键门禁失败、部署后真实业务验收失败/不可核验、必交证据缺失、未知字段被填为 `PASS` 或存在未闭环关键项时，严禁报告 `OVERALL=PASS` 或 `OVERALL_STATUS=PASS`。
4. **资源所有权与测试入口声明**：`AGENTS.md` **MUST** 明确声明本仓库允许修改的目录范围、属主资源边界（`STD-002`）、标准预检入口、测试命令入口与统一验收打包入口（`scripts/package_acceptance.py`）。

---

## 2. `CLAUDE.md` 编程客户端适配规则 (Coding Client Adapter Contract)

1. **客户端专用入口**：每个受管工程仓库根目录 **MUST** 提供 `CLAUDE.md`（并可选提供 `.agent/rules/engineering.md`），作为 Claude Code 等终端/IDE 智能体启动时自动加载的上下文入口。
2. **禁止重复维护规则副本与禁止写死版本**：`CLAUDE.md` **MUST** 显式引用同仓库的 `AGENTS.md`、`standards.lock.json` 与中央 `AI-Engineering-Standards`，仅包含客户端特定的启动命令、网关接入上下文与常用验证命令，**MUST NOT** 复制完整的 Standards 正文，**MUST NOT** 硬编码会随升级漂移的 Standards 版本号，亦 **MUST NOT** 定义与 `AGENTS.md` 冲突的规则。

---

## 3. 项目级 Thin Reference 引用模式 (Thin Reference Pattern)

1. **唯一事实源原则**：`AI-Engineering-Standards` 仓库是所有 `STD-*` 规范正文、JSON Schema 与官方同步工具（`tools/standards_sync/`）的唯一事实源。
2. **薄引用约束 (Thin Reference)**：各受管工程仓库的 `AGENTS.md`、`CLAUDE.md`、`.agent/rules/engineering.md` 及 `docs/` **MUST** 采用薄引用模式（通过标准编号 `STD-001`–`STD-035`、文件路径与 `standards.lock.json` 锁定引用中央规范）。
3. **禁止跨库复制规范正文与同步工具实现**：任何受管业务或平台仓库 **MUST NOT** 存放 `STD-*.md` 规范副本，亦 **MUST NOT** 复制完整的 Standards Tag 发现、版本比较与 Schema 差异分析实现；下游工程仅允许维护最薄的引导调用封装。

---

## 4. Standards 精确版本锁定与受控自动同步契约 (Standards Exact Lock & Controlled Sync Contract)

### 4.1 `standards.lock.json` 唯一版本锁定事实源
1. **精确四要素锁定**：正式工程执行 **MUST** 在仓库根目录通过 `standards.lock.json`（符合 `schemas/standards-lock.schema.json`）精确锁定：
   - `repository`（如 `"xiefeifeihu/AI-Engineering-Standards"`）
   - `version`（精确 SemVer，如 `"3.0.0"`）
   - `tag`（正式附注 Tag，如 `"v3.0.0"`）
   - `tag_object_sha`（40 位附注 Tag 对象 SHA）
   - `peeled_commit`（40 位 `refs/tags/<tag>^{}` 指向的 `main` Commit SHA）
   - `locked_at`（UTC 时间戳）
   - `lock_reason`（锁定或升级原因）
   - `approval_evidence_ref`（审批证据引用）
   - `previous_locks`（保留的历史锁定记录列表）
2. **禁止使用浮动 `main` 代替正式执行锁定**：正式发布Tag必须来自经过 `main` CI 验证的 Commit；任何工程在正式执行期间 **MUST** 保持精确版本锁定，**MUST NOT** 使用浮动的 `refs/heads/main` 或未打标提交代替正式锁定。
3. **Manifest 一致性与兼容矩阵边界**：
   - 工程 `engineering-manifest.yaml` 中的 Standards 信息 **MUST** 与 `standards.lock.json` 完全一致，CI 必须强制检查二者一致性。
   - `compatibility_matrix.yaml` 只负责表达组件间的版本兼容关系范围，**MUST NOT** 成为第二个独立的版本锁定事实源。

### 4.2 官方同步工具 (`tools/standards_sync/`)
由 `AI-Engineering-Standards` 仓库独立设计、实现和维护 `tools/standards_sync/`，跨平台支持 Windows、WSL、Linux 与 GitHub Actions（零固定 Windows 本地路径依赖），统一提供 8 个标准子命令：
1. `discover`：自动发现远端最新正式 SemVer 附注 Tag，核验 `tag_object_sha`、`peeled_commit`、`VERSION` 文件一致性、`main` HEAD 祖先关系及 `main` CI 真实通过状态。
2. `verify-lock`：核验当前工程 `standards.lock.json` 与 `engineering-manifest.yaml` 一致性，检测 Tag 对象漂移、无 Tag 伪装或未发布提交。
3. `compare`：按 SemVer 比较当前工程锁定版本与目标正式版本（严禁自动降级），自动执行规范正文条款差异分析与 JSON Schema 差异分析（必填字段变化、枚举变化、新增/废弃条款）。
4. `impact`：针对下游消费端工程执行兼容性影响分析（覆盖 Schema、`AGENTS.md`、`CLAUDE.md`、Engineering Manifest、文档元数据、文档集合校验、测试门禁、发布门禁、安全门禁、业务接口与运行时契约）。
5. `prepare-upgrade`：自动生成升级候选包与迁移计划（`.artifacts/standards_upgrade/`）。
6. `validate-upgrade`：在候选环境执行工程兼容性回归测试并汇总结果。
7. `promote`：核验审批契约（`AI_APPROVED` 或 `OWNER_APPROVED`）与测试通过证据后，保留历史锁定并原子更新 `standards.lock.json` 与 `engineering-manifest.yaml`。
8. `rollback`：从 `previous_locks` 历史锁定记录安全回滚至上一已验证版本。

### 4.3 消费端接入与受控升级（Consumer Adoption & Controlled Upgrade）

1. **接入采用显式授权**：Standards 提供统一发现、比较、兼容性分析和受控升级能力，但不代表所有受管工程自动加入升级计划。每个消费工程 **MUST** 由其 Owner 在本工程 compatibility matrix 或正式决策中明确是否接入、适用版本、巡检频率和审批范围。未作出接入决定的工程 **MAY** 继续使用当前已验证 Lock，不得被标记为兼容或被自动升级。
2. **首个消费端试点**：v3.0.0 首个试点为 `AI-Engineering-Hub`。AI-KB、VTIP、SideCar 不属于本轮迁移范围；其后续接入由各工程 Owner 独立决定。不得从 AI-Hub 的试点结果推导其他工程兼容性或升级批准。
3. **已批准接入的工程**：仅对已明确选择接入的工程，在其约定的任务启动/巡检触发点执行以下受控升级状态机：
```text
DISCOVER ──► VERIFY ──► COMPARE ──► IMPACT_ANALYSIS ──► GENERATE_CANDIDATE ──► RUN_COMPATIBILITY_TESTS ──► CHATGPT_REVIEW ──► OWNER_APPROVAL_IF_REQUIRED ──► PROMOTE ──► LOCK ──► EXECUTE
```
- **升级门禁裁决状态**：
  - 兼容性测试或校验失败：`UPGRADE_BLOCKED`（严禁静默跳过或降级）；
  - 网络或远端 API 不可用：`NOT_VERIFIABLE`（严禁用本地缓存冒充最新官方版本；允许使用经过验证的已锁定版本离线工作，但必须明确标记最新版本无法核验 `remote_latest_status=NOT_VERIFIABLE`）；
  - 涉及破坏性 Schema 变更、主版本升级或重大治理决策：`OWNER_APPROVAL_REQUIRED`；
  - 全部兼容性门禁通过且仅属兼容刷新无需人工批准：经 ChatGPT 独立审核后记录 `AI_APPROVED`。
- 在新版本升级与审批晋升完成前，**MUST NOT** 把旧锁定版本伪称为最新版本。

---

## 5. Agent 任务启动 Preflight (`scripts/agent/preflight.py`)

每个受管工程仓库 **MUST** 提供并维护预检门禁，在智能体开始编码任务及提交前自动核验以下 9 项核心指标：
1. **仓库身份 (Repository Identity)**：核验当前工作目录 Git 根路径与项目标识一致。
2. **Git 分支 (Branch Guard)**：核验当前分支非空且严禁在未经授权的 `main` 或 `master` 分支直接开发（只读审计模式除外）。
3. **工作区状态 (Worktree Hygiene)**：核验工作区修改状态（`git status -sb`），检测是否存在未授权修改或残留冲突标记。
4. **Standards 精确锁定与同步核验 (`standards.lock.json`)**：调用 `tools/standards_sync` 验证 `standards.lock.json` 与 `engineering-manifest.yaml` 一致，`VERSION`、`TAG`、`TAG_OBJECT_SHA`、`PEELED_COMMIT` 真实有效。
5. **工程 Manifest (`engineering-manifest.yaml`)**：核验项目 `engineering-manifest.yaml` 存在且符合权威 Schema `schemas/engineering-manifest.schema.json`（`STD-001`）要求。
6. **任务授权范围 (Authorized Scope)**：核验当前分支相对于基线修改的文件列表均在授权目录范围内，且未跨仓修改禁改工程。
7. **有效发布脚本 (Release Scripts Presence)**：核验发布组件及唯一打包器 `scripts/package_acceptance.py` 存在且有效。
8. **Git 安全状态 (Git Safety State)**：核验 `.artifacts/` 已被 `.gitignore` 排除且 `git ls-files .artifacts` 为空，无跨系统文件权限污染或锁文件残留。
9. **ReleaseProfile 适配核验**：核验项目 `engineering-manifest.yaml` 中声明的 `release_profile` 与当前发布模式匹配，检查是否具备相应的授权与门禁配置。

---

## 6. 任务 Context 与 Git 分支关联 (Task Context & Git Branch Association)

1. **结构化任务标识传递**：通过 AI-Hub 编程网关（Coding Gateway）或选模路由（`/api/model/select`）执行的编码任务 **MUST** 通过结构化上下文传递任务身份：
   - HTTP Headers：`x-task-id`、`x-run-id`、`x-turn-id`、`x-trace-id`
   - 或网关任务路径：`/task/{task_id}/run/{run_id}/v1/messages`、`/task/{task_id}/run/{run_id}/v1/chat/completions`
2. **三层追踪粒度**：
   - **一个用户编码任务 (`task_id`)**：对应一个稳定的 `task_id` 与独立 Git 分支。
   - **一次智能体执行会话 (`run_id`)**：每次启动客户端或恢复会话生成（或显式指定）独立的 `run_id`。
   - **多轮工具调用 (`turn_id` & `decision_id`)**：同一会话内的多轮请求 **MUST** 保持相同的 `task_id` 和 `run_id`，并为每一轮请求生成独立的 `turn_id` 与选模决策标识。
3. **严禁猜测关联**：网关与诊断系统 **MUST NOT** 通过正则表达式从 Prompt 正文猜测 `task_id`。历史未携带任务上下文的调用 **MUST** 保持只读事实（标记为 `NOT_RECORDED`）。

---

## 7. 修改文件授权范围 (Authorized File Modification Scope)

1. **任务级仓库白名单**：每个编码任务必须在启动前明确允许维护的仓库列表与严禁修改的仓库列表。
2. **自动越界拦截**：预检与 CI 门禁 **MUST** 检查受管仓库的 `git status --porcelain` 与分支差异；一旦发现禁改仓库发生工作区脏改动或未授权路径变更，门禁 **MUST** 立即判定 `FAIL`。

---

## 8. 测试与证据真实性与持续覆盖治理 (Test & Evidence Authenticity & Continuous Coverage)

1. **真实执行强制要求 (`STD-014` / `STD-015`)**：单元测试、契约测试、集成测试与 Playwright 浏览器端到端测试 **MUST** 真实运行并采集原始标准输出日志（`test_results.txt`）与退出码（`exit_code=0`）。
2. **UI 变更强制真机浏览器验证**：凡涉及前端脚本、模板或样式变更，**MUST** 运行真实 Chromium/Playwright 测试并生成与当前代码版本一致的真实截图与报告。
3. **AI 智能体自主测试设计契约**：智能体在编码前必须读取核心事实源，自主完成 13 阶段测试闭环，维护 `docs/TEST-ACCEPTANCE.md`，输出结构化覆盖报告（`schemas/test-coverage-verification.schema.json`）。
4. **十项反向欺诈行为机器阻断 (`tools/validate_test_coverage.py`)**：严格检测并阻断正向业务 `BLOCK`/`CONFIGURED`/`MOCK_ONLY` 伪造 `PASS`、关键 P0 缺少执行记录、测试未运行、生产验收使用 Mock、候选端口冒充生产、弱化断言、报错截图、测试 Commit 不一致、缺失影响分析及静默移除历史用例。

---

## 9. 唯一 Acceptance 打包器 (`scripts/package_acceptance.py`)

1. **单仓唯一打包入口**：每个受管工程仓库 **MUST** 仅维护一个正式验收打包脚本 `scripts/package_acceptance.py`。
2. **Manifest 驱动与完整性核验**：打包器 **MUST** 读取 `.artifacts/acceptance/<TASK_ID>/v<VERSION>/manifest.json`，逐项核验清单内所有文件真实存在、`size > 0` 且 `sha256` 完全匹配。
3. **禁止自引用哈希与固定输出路径**：`manifest.json` **MUST NOT** 包含最终 ZIP 包自身的 `sha256` 字段；正式交付 ZIP 包 **MUST** 唯一输出至 `.artifacts/packages/Acceptance-<TASK_ID>-v<VERSION>.zip` 并执行真实解压与全文件哈希复核。

---

## 10. CI/CD 强制门禁 (Mandatory CI/CD & Delivery Gates)

每个受管工程必须建立或复用正式 CI 工作流与机器校验门禁，自动执行以下强制检查：
1. `AGENTS.md` 与 `CLAUDE.md` 存在性、Rules A–O 完整性、无冲突及无硬编码过时版本校验。
2. `standards.lock.json` 与 `engineering-manifest.yaml` 一致性及 Tag/Commit 真实性校验。
3. 文档集合、当前权威基线（`ENGINEERING_BASELINE`）、跨会话交接（`CROSS_SESSION_HANDOFF`）、内部 Markdown 链接与锚点完整性校验（`tools/validate-documentation-collection.py`）。
4. 文档与升级审批契约真实性校验（`tools/validate_approval_contract.py`）。
5. 单元测试、契约测试、集成测试与跨平台（Windows / Linux）测试真实通过校验。
6. 唯一验收打包脚本与制品目录卫生校验。
7. 零密钥安全扫描（`STD-007`）。

---

## 11. Runtime 与 Git 五态身份 (`5-Way Identity Invariant`)

正式发布与运行时验收 **MUST** 满足 `STD-031`、`STD-032`、`STD-033` 定义的五态 Commit 一致性：
```text
LOCAL_HEAD == REMOTE_HEAD == TAG_COMMIT == BUILD_COMMIT == LIVE_COMMIT
```
任何一项不一致或无法验证时，`SOURCE_BUILD_LIVE_MATCH` **MUST** 报告为 `FAIL` 或 `BLOCK`，严禁报告 `PASS`。

---

## 12. Coding Outcome 真实结果上报 (`STD-023` Lifecycle States)

系统 **MUST** 根据 `STD-023` 严格区分 8 个递进交付状态（`MODEL_EXECUTION_SUCCESS`、`CODE_PATCH_APPLIED`、`TESTS_PASSED`、`CI_PASSED`、`PACKAGE_VALIDATED`、`DEPLOYED`、`TASK_COMPLETED`、`HUMAN_ACCEPTED`），严禁仅凭网关或模型推理返回 `HTTP 200` 自动判定编码交付成功。

---

## 13. 未通过门禁禁止 `OVERALL_STATUS=PASS` (Strict Overall Status Gate)

1. **合法状态枚举**：所有阶段门禁、交接报告与最终交付摘要的状态字段 **MUST** 严格区分 `PASS`、`FAIL`、`BLOCK`、`NOT_RUN`、`NOT_VERIFIABLE`、`STALE`。
2. **一票否决铁律**：只要存在任一子门禁为 `FAIL`、`BLOCK` 或关键必验项为 `NOT_RUN` / `NOT_VERIFIABLE` / `STALE`，`OVERALL_STATUS`（或 `OVERALL`）**MUST NOT** 填为 `PASS`。

---

## 14. 跨 Windows / WSL / Linux 的 Git 与路径安全规则 (Cross-OS Git & Path Safety)

1. **禁止破坏性 Git 命令**：严禁执行 `git reset --hard`、`git clean -fd`、`git push --force` 或未经授权的分支删除。
2. **禁止固定 Windows 本地路径依赖**：所有官方工具、校验器与测试脚本 **MUST** 支持 Windows、WSL、Linux 与 GitHub Actions，**MUST NOT** 依赖固定的 `D:/Projects/AI-Engineering-Standards` 等本地绝对路径。

---

## 15. 非法制品路径与 `docs/` 污染自动检测 (Automated Artifact & Docs Hygiene Detection)

1. **非法 ZIP 与根目录散落制品检测**：任何位于 `.artifacts/packages/` 之外的交付 `.zip` 包均判定为违规。
2. **`docs/` 正式架构图白名单与测试截图隔离**：除 `docs/01-架构设计/` 及 `docs/**/assets/` 下的正式架构与设计图外，`docs/` 其他子目录下 **MUST NOT** 存放测试截图、录像、日志或临时压缩包。

---

## 16. 生产发布、文档治理与 ChatGPT/Owner 审批防伪铁律 (Approval & Anti-Spoofing Contract)

1. **五步文档与规范治理闭环**：
   ```text
   编程智能体维护正式文档/候选变更 ──► ChatGPT 跨文档及事实独立审核 ──► 根据审批策略判断是否需要所有者批准 ──► Git 固化 ──► Project Sources 同步已批准基线
   ```
2. **ChatGPT 独立审核与 Owner 批准分离记录**：
   - **模式 A (`AI_APPROVED`)**：当变更严格属于 `STD-035` §3.3 的 `AI_APPROVABLE` 范围时，由独立审核阶段的 ChatGPT 完成审核并批准，记录 `AI_APPROVED`。
   - **模式 B (`OWNER_APPROVED`)**：当变更涉及产品范围、架构决策、API 语义、安全权限边界、数据所有权、正式 Standards 规范语义、破坏性 Schema 或不可逆迁移（或不确定是否需要 Owner 批准）时，ChatGPT 完成独立审核并提交精确审批事项（标记 `OWNER_APPROVAL_REQUIRED`），由所有者在 ChatGPT 聊天中或正式审批记录中明确批准后，记录 `OWNER_APPROVED`。
3. **审批证据九要素与防伪验证 (`tools/validate_approval_contract.py`)**：
   - 所有审批证据必须绑定 `TASK_ID`、`REPOSITORY`、`CANDIDATE_COMMIT`、`CONTENT_SHA256`、`REVIEWER_TYPE`、`REVIEW_RESULT`、`APPROVAL_STATUS`、`APPROVED_AT`、`APPROVAL_REFERENCE`。
   - 编程智能体 **MUST NOT** 自行宣布 ChatGPT 已经批准，**MUST NOT** 伪造聊天审批记录或数字签名，**MUST NOT** 将设计决策阶段的批准等同于具体代码/文档 Diff 的最终批准。
   - 审批绑定的 `CANDIDATE_COMMIT` 或 `CONTENT_SHA256` 发生变化后，原审批自动失效，必须重新提交审核。
4. **生产发布审批协同 (`STD-032`)**：生产环境部署审批继续严格执行 `STD-032` §4 的显式互斥策略与一次性消费防重放机制。
