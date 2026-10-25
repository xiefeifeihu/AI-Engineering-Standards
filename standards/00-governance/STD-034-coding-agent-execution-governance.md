# STD-034: Coding Agent Execution Governance & Machine Gate Contract (跨工程编程智能体执行治理与强制机器门禁规范)

```text
STANDARD_ID=STD-034
VERSION=2.6.0
STATUS=ACTIVE
SCOPE=全平台受管工程仓库 (AI-Engineering-Hub, AI-Engineering-Standards, AI-KB, vtip-ai-sidecar, vtip-platform-catalog)
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-23
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
2. **十五项强制工程铁律 (`Rules A–O`)**：每个项目的 `AGENTS.md` **MUST** 完整声明并执行以下 15 项核心治理规则：
   - **Rule A（开始工作先核验 Git 和 Standards）**：开始任务前必须先执行只读基线核查，核验当前 Git 分支、`LOCAL_HEAD`、`REMOTE_HEAD`、`MAIN_HEAD`、`WORKTREE_STATUS`（`git status -sb`），以及 `AI-Engineering-Standards` 的当前 `VERSION` 与 `HEAD Commit`。
   - **Rule B（Standards 是统一规范唯一事实源）**：`AI-Engineering-Standards` 是全平台工程规范唯一事实源（Single Source of Truth）。业务与平台仓库不得复制完整 Standards 正文或另立冲突规范。
   - **Rule C（不直接修改 `main`）**：严禁直接在 `main` / `master` 分支上开发或直接向 `main` 提交代码；必须从干净基线创建独立分支并通过 PR 与 CI 门禁合入。
   - **Rule D（保护现有工作区）**：严禁覆盖、丢弃或清理工作区中已有的未提交修改或历史验收成果；严禁使用 `git reset --hard`、`git clean -fd`、`git push --force`。
   - **Rule E（严格遵守跨仓修改边界）**：严格遵循 `STD-002` / `STD-017` 及任务授权范围，严禁越权修改未授权仓库。
   - **Rule F（零密钥与隐私保护）**：严格执行 `STD-007`，严禁向 Git、日志或交付包提交任何 Token、API Key、Cookie、Authorization 头、私钥、真实生产完整正文或私人本地配置（如 `.env`、`settings.local.json`）。
   - **Rule G（实际运行测试后才能报告 `PASS`）**：所有测试状态必须基于真实执行的测试命令、`exit_code=0` 及原始测试日志输出（`STD-014`），严禁未运行或失败时报告 `PASS`。
   - **Rule H（单元测试不能替代 Playwright 和真实业务验收）**：单元测试仅验证局部逻辑，不得替代涉及 UI 变更时的 Playwright 真实浏览器验收（`STD-015`）及端到端真实业务链路验收。
   - **Rule I（不得伪造模型执行、构建和运行 Commit）**：严禁伪造模型调用记录、耗时、Token 用量，严禁伪造 `SOURCE_COMMIT`、`BUILD_COMMIT`、`LIVE_COMMIT` 或容器/进程运行身份证据（`STD-031` / `STD-032`）。
   - **Rule J（不得用静态 JSON 制造高质量验收结果）**：严禁编写静态生成脚本或手写 JSON 汇总文件来冒充真实测试结果、Playwright 验收结果或运行时探针证据。
   - **Rule K（不得将 HTTP 200 自动认定为业务采纳或编码交付完成）**：技术请求返回 `HTTP 200`（或仅完成 Stage A 执行事件上报 / `MODEL_EXECUTION_SUCCESS`）不等于业务采纳或编码交付完成；必须完成 Stage B 业务质量评估或 `STD-023` 编码交付阶段验证后才能认定对应阶段通过。
   - **Rule L（不得自动提交人工审核 `PASS`）**：未经真实人工审阅确认，编程智能体不得自动提交或伪造 `human_review` / `HUMAN_ACCEPTED` 为 `PASS`。
   - **Rule M（正式发布必须执行有效 Standards 的 CI/CD）**：正式发布与里程碑验收必须执行符合当前有效 Standards（`STD-031`、`STD-032`、`STD-033`、`STD-034`）的真实 CI/CD 与交付契约校验门禁。
   - **Rule N（验收目录与 ZIP 目录必须区分）**：过程验收证据目录（`.artifacts/acceptance/`）与正式交付 ZIP 目录（`.artifacts/packages/`）必须严格隔离，严禁将正式交付 ZIP 存放在 `acceptance` 目录或仓库根目录下。
   - **Rule O（没有全部证据时不得报告 `OVERALL=PASS`）**：任一关键门禁失败、必交证据缺失、未知字段被填为 `PASS` 或存在未闭环项时，严禁报告 `OVERALL=PASS` 或 `OVERALL_STATUS=PASS`。
3. **资源所有权与测试入口声明**：`AGENTS.md` **MUST** 明确声明本仓库允许修改的目录范围、属主资源边界（`STD-002`）、标准预检入口（`scripts/agent/preflight.py`）、测试命令入口与统一验收打包入口（`scripts/package_acceptance.py`）。

---

## 2. `CLAUDE.md` 编程客户端适配规则 (Coding Client Adapter Contract)

1. **客户端专用入口**：每个受管工程仓库根目录 **MUST** 提供 `CLAUDE.md`（并可选提供 `.agent/rules/engineering.md`），作为 Claude Code 等终端/IDE 智能体启动时自动加载的上下文入口。
2. **禁止重复维护规则副本**：`CLAUDE.md` **MUST** 显式引用同仓库的 `AGENTS.md` 与中央 `AI-Engineering-Standards`，仅包含客户端特定的启动命令、网关接入上下文（如 `Start-Claude-via-Hub.ps1`、`x-task-id`、`x-run-id`）与常用验证命令，**MUST NOT** 复制一份完整的 Standards 正文，亦 **MUST NOT** 定义与 `AGENTS.md` 冲突的规则。

---

## 3. 项目级 Thin Reference 引用模式 (Thin Reference Pattern)

1. **唯一事实源原则**：`AI-Engineering-Standards` 仓库是所有 `STD-*` 规范正文与 JSON Schema 的唯一事实源。
2. **薄引用约束 (Thin Reference)**：各受管工程仓库的 `AGENTS.md`、`CLAUDE.md`、`.agent/rules/engineering.md` 及 `docs/` **MUST** 采用薄引用模式（通过标准编号 `STD-001`–`STD-034`、文件路径与版本号引用中央规范）。
3. **禁止跨库复制规范正文**：任何受管业务或平台仓库的 `docs/` 目录下 **MUST NOT** 存放 `STD-*.md` 规范副本，自动化门禁检测到复制的 `STD-*.md` 文件时 **MUST** 直接阻断。

---

## 4. Standards 版本与 Commit 锁定 (Standards Version & Commit Lock)

1. **显式版本与 Commit 绑定**：受管工程的 `compatibility_matrix.yaml`、运行时探针（`/health`、`/api/runtime/identity`）及每次验收的 `manifest.json` **MUST** 显式记录当前生效的 `standards_version` 与 `standards_commit`（7–40 位真实 Git SHA）。
2. **不可降级阻断原则 (Fail-Closed on Missing/Stale Standards)**：当开发预检门禁（`scripts/agent/preflight.py`）或 CI 校验门禁无法读取所需的 `AI-Engineering-Standards` 仓库、`VERSION` 文件或检测到版本低于最低要求时，门禁 **MUST** 立即阻断（返回非零退出码并标记 `BLOCK` / `FAIL`），**MUST NOT** 静默降级使用硬编码的过时版本号（如 `v2.1.1`）继续放行。

---

## 5. Agent 任务启动 Preflight (`scripts/agent/preflight.py`)

每个受管工程仓库 **MUST** 提供并维护 `scripts/agent/preflight.py`（复用 `scripts/release/` 基础能力），在智能体开始编码任务及提交前自动核验以下 8 项核心指标：
1. **仓库身份 (Repository Identity)**：核验当前工作目录 Git 根路径与项目标识一致。
2. **Git 分支 (Branch Guard)**：核验当前分支非空且严禁处于 `main` 或 `master` 分支（只读审计模式除外）。
3. **工作区状态 (Worktree Hygiene)**：核验工作区修改状态（`git status -sb`），检测是否存在未授权修改或残留冲突标记。
4. **Standards 版本与 Commit (Standards Lock)**：真实验证中央 `AI-Engineering-Standards` 可读、`VERSION` 合法且达到最低版本要求、`HEAD Commit` 真实存在。
5. **工程 Manifest (`engineering-manifest.yaml`)**：核验项目 `engineering-manifest.yaml` 存在且符合 `STD-001` Schema 要求。
6. **任务授权范围 (Authorized Scope)**：核验当前分支相对于基线修改的文件列表均在授权目录范围内，且未跨仓修改禁改工程。
7. **有效发布脚本 (Release Scripts Presence)**：核验 `scripts/release/` 标准组件及唯一打包器 `scripts/package_acceptance.py` 存在且有效。
8. **Git 安全状态 (Git Safety State)**：核验 `.artifacts/` 已被 `.gitignore` 排除且 `git ls-files .artifacts` 为空，无跨系统文件权限污染或锁文件残留。

---

## 6. 任务 Context 与 Git 分支关联 (Task Context & Git Branch Association)

1. **结构化任务标识传递**：通过 AI-Hub 编程网关（Coding Gateway）或选模路由（`/api/model/select`）执行的编码任务 **MUST** 通过结构化上下文传递任务身份：
   - HTTP Headers：`x-task-id`、`x-run-id`、`x-turn-id`、`x-trace-id`
   - 或网关任务路径：`/task/{task_id}/run/{run_id}/v1/messages`、`/task/{task_id}/run/{run_id}/v1/chat/completions`
2. **三层追踪粒度**：
   - **一个用户编码任务 (`task_id`)**：对应一个稳定的 `task_id` 与独立 Git 分支。
   - **一次智能体执行会话 (`run_id`)**：每次启动客户端或恢复会话生成（或显式指定）独立的 `run_id`。
   - **多轮工具调用 (`turn_id` & `decision_id`)**：同一会话内的多轮请求（包括 `tool_use` / `tool_result`、上下文压缩、模型切换、请求重试、任务恢复）**MUST** 保持相同的 `task_id` 和 `run_id`，并为每一轮请求生成独立的 `turn_id` 与选模决策标识（`selection_decision_id` / `decision_id`）。
3. **严禁猜测关联**：网关与诊断系统 **MUST NOT** 通过正则表达式从 Prompt 正文猜测 `task_id`，亦 **MUST NOT** 仅凭请求时间戳、模型名称或相似 Prompt 猜测任务归属。历史未携带任务上下文的调用 **MUST** 保持只读事实（标记为 `NOT_RECORDED`），不得事后篡改。

---

## 7. 修改文件授权范围 (Authorized File Modification Scope)

1. **任务级仓库白名单**：每个编码任务必须在启动前明确允许维护的仓库列表与严禁修改的仓库列表。
2. **自动越界拦截**：`scripts/agent/preflight.py` 与 CI 门禁 **MUST** 检查受管仓库的 `git status --porcelain` 与分支差异；一旦发现禁改仓库发生工作区脏改动或未授权路径变更，门禁 **MUST** 立即判定 `FAIL`。

---

## 8. 测试与证据真实性 (Test & Evidence Authenticity)

1. **真实执行强制要求 (`STD-014` / `STD-015`)**：单元测试、契约测试、集成测试与 Playwright 浏览器端到端测试 **MUST** 真实运行并采集原始标准输出日志（`test_results.txt`）与退出码（`exit_code=0`）。
2. **UI 变更强制真机浏览器验证**：凡涉及前端脚本（如 `app/static/app.js`）、模板或样式变更，**MUST** 运行真实 Chromium/Playwright 测试并生成与当前代码版本一致的真实截图与报告，严禁仅跑后端 pytest 即宣称 UI 修复完成。
3. **反造假校验**：门禁脚本 **MUST** 校验测试日志非空、包含真实用例统计、无失败用例，且截图文件大小、PNG 头部及哈希真实有效。

---

## 9. 唯一 Acceptance 打包器 (`scripts/package_acceptance.py`)

1. **单仓唯一打包入口**：每个受管工程仓库 **MUST** 仅维护一个正式验收打包脚本 `scripts/package_acceptance.py`。严禁在 `scripts/` 或 `tools/` 下保留或新建竞争性版本化打包器（如 `package_v0214_acceptance.py`、`package_release_r*.py`）。
2. **Manifest 驱动与完整性核验**：打包器 **MUST** 读取 `.artifacts/acceptance/<TASK_ID>/v<VERSION>/manifest.json`，逐项核验清单内所有文件真实存在、`size > 0` 且与实际字节数一致、`sha256` 64 位十六进制摘要完全匹配。
3. **禁止自引用哈希与固定输出路径**：
   - `manifest.json` **MUST NOT** 包含最终 ZIP 包自身的 `sha256` 字段。
   - 正式交付 ZIP 包 **MUST** 唯一输出至 `.artifacts/packages/Acceptance-<TASK_ID>-v<VERSION>.zip`（或仓库标准命名），并在外部生成同名 `.sha256` 校验文件，随后执行真实解压与全文件哈希复核。

---

## 10. CI/CD 强制门禁 (Mandatory CI/CD & Delivery Gates)

每个受管工程必须建立或复用正式 CI 工作流与机器校验门禁（如 `scripts/ci/verify_delivery_contract.py` 及 `scripts/release/release_pipeline.py`），自动执行以下 12 项强制检查：
1. `AGENTS.md` 与 `CLAUDE.md` 存在性、Rules A–O 完整性及无冲突校验。
2. `AI-Engineering-Standards` 引用、版本号与 Commit 真实性校验（不可读取时阻断）。
3. Git 分支（非 `main` 开发）与工作区干净度校验。
4. 单元测试、契约测试、集成测试与 UI 自动化测试真实通过校验。
5. 真实 Playwright 执行日志与截图证据校验。
6. 唯一发布/验收打包脚本（`scripts/package_acceptance.py`）合规性校验（无重复版本化打包器）。
7. 正式 Acceptance ZIP 必须且只能位于 `.artifacts/packages/`（严禁出现在 `.artifacts/acceptance/` 或仓库根目录）。
8. ZIP 内 `manifest.json`、外部 `.sha256` 与实际解压文件逐字节一致性校验。
9. `SOURCE_COMMIT` / `BUILD_COMMIT` / `LIVE_COMMIT` 真实身份一致性校验。
10. 业务评估结果（Stage B）与编码结果（Coding Outcome）真实性校验，严禁用模拟 `PASS` 替代。
11. 标准测试任一未通过时，严禁执行正式发布或标记发布成功。
12. 验收报告（`acceptance_report.md`）声明的状态与底层 JSON 原始证据完全一致，无自相矛盾。

> [!IMPORTANT]
> **托管 Runner 与本机生产探针边界**：GitHub 托管 Runner 无法直接访问用户宿主机本地回环生产端口（如 `127.0.0.1:80`、`127.0.0.1:8799`）。在无本机生产验证能力的环境中，严禁伪造或 Mock 生产探针通过；此时 `LIVE_STATUS` **MUST** 如实报告为 `BLOCK` 或 `NOT_VERIFIABLE`。唯有在具备权限与安全边界的本机环境或受控本机 Runner 上实测通过后，方可报告 `LIVE_STATUS=PASS`。

---

## 11. Runtime 与 Git 五态身份 (`5-Way Identity Invariant`)

正式发布与运行时验收 **MUST** 满足 `STD-031`、`STD-032`、`STD-033` 定义的五态 Commit 一致性：
```text
LOCAL_HEAD == REMOTE_HEAD == TAG_COMMIT == BUILD_COMMIT == LIVE_COMMIT
```
任何一项不一致或无法验证时，`SOURCE_BUILD_LIVE_MATCH` **MUST** 报告为 `FAIL` 或 `BLOCK`，严禁报告 `PASS`。

---

## 12. Coding Outcome 真实结果上报 (`STD-023` Lifecycle States)

针对编程智能体与代码工程任务，系统 **MUST** 根据 `STD-023` 严格区分以下 8 个递进交付状态，严禁仅凭网关或模型推理返回 `HTTP 200` 自动判定编码交付成功：
1. `MODEL_EXECUTION_SUCCESS`：模型推理请求（如 `/v1/messages`）返回 HTTP 200 且生成有效响应。
2. `CODE_PATCH_APPLIED`：代码补丁已成功解析并应用至工作区（`patch_apply_success=true`）。
3. `TESTS_PASSED`：定向测试与核心回归测试真实运行通过（`targeted_tests_failed=0` 且 `core_regression_failed=0`）。
4. `CI_PASSED`：静态检查、契约校验与自动化门禁流水线全部通过。
5. `PACKAGE_VALIDATED`：通过唯一打包器生成正式交付包且通过 Manifest + SHA256 解压复核。
6. `DEPLOYED`：新构建版本已部署至目标运行环境并通过存活/就绪探针及五态 Commit 核验。
7. `TASK_COMPLETED`：工程任务全部技术与业务门禁闭环完成（`task_outcome=COMPLETED`）。
8. `HUMAN_ACCEPTED`：经真实人工审阅确认采纳合入（`integration_selected=true` / 人工审核通过）。

---

## 13. 未通过门禁禁止 `OVERALL_STATUS=PASS` (Strict Overall Status Gate)

1. **合法状态枚举**：所有阶段门禁、交接报告与最终交付摘要的状态字段 **MUST** 仅使用以下四个标准枚举值之一：
   - `PASS`
   - `FAIL`
   - `BLOCK`
   - `NOT_VERIFIABLE`
2. **一票否决铁律**：只要存在任一子门禁为 `FAIL`、`BLOCK` 或关键必验项为 `NOT_VERIFIABLE`，`OVERALL_STATUS`（或 `OVERALL`）**MUST NOT** 填为 `PASS`。严禁因部分测试通过就宣布全量 `PASS`。

---

## 14. 跨 Windows / WSL 的 Git 安全规则 (Cross-OS Git Safety)

1. **禁止破坏性 Git 命令**：在 Windows PowerShell 与 WSL2 环境中 **MUST NOT** 执行 `git reset --hard`、`git clean -fd`、`git push --force` 或未经授权的分支删除。
2. **路径与权限安全**：跨 Windows（`D:\Projects\...`）与 WSL2（`/mnt/d/Projects/...`）操作同一 Git 工作区时，**MUST** 避免并发执行写操作导致 `.git/index.lock` 争用，并保持 `core.fileMode=false` 与一致的换行符配置，防止因跨系统文件权限位差异产生虚假全量 Diff。

---

## 15. 非法制品路径与 `docs/` 污染自动检测 (Automated Artifact & Docs Hygiene Detection)

1. **非法 ZIP 与根目录散落制品检测**：机器门禁 **MUST** 自动扫描仓库根目录、`.artifacts/acceptance/` 及 `docs/`：
   - 任何位于 `.artifacts/packages/` 之外的交付 `.zip` 包（Playwright `traces/` 子目录内专用 `trace.zip` 除外）均判定为违规。
   - 仓库根目录下不得残留临时验收包或未纳入规范的生成物。
2. **`docs/` 正式架构图白名单与测试截图隔离**：
   - `docs/01-架构设计/` 及 `docs/**/assets/` 下允许追踪正式架构图与正式项目设计图片（`.png`、`.jpg`、`.jpeg`、`.svg`）。
   - 除上述正式架构/设计资产目录外，`docs/` 其他子目录下 **MUST NOT** 存放任何 `.png`、`.jpg`、`.webp`、`.mp4`、`.webm`、`.zip`、`.log`、`.tmp` 文件；所有自动化测试截图、录像与日志 **MUST** 归档至 `.artifacts/`。

---

## 8. 生产发布与审批防伪铁律 (Release & Approval Anti-Spoofing Invariants)

1. **禁止绕过审批与伪造审批标记**：
   - 编程智能体 **MUST NOT** 自行生成或伪造生产审批凭证。
   - 严禁通过传入 `--release-approved` 或环境变量 `RELEASE_APPROVAL=APPROVED` 在无真实人工审批凭证时冒充正式发布审批。
2. **禁止伪造运行态身份与生产验收**：
   - 严禁在未获生产部署授权或未真实执行部署时，通过伪造 JSON 声明目标版本已成为 `LIVE_COMMIT`。
   - 严禁在远端 CI 失败时，将验收状态填写为 `REMOTE_CI_STATUS=PASS`。
3. **禁止擅自修改生产服务与网络环境**：
   - 严禁未经授权停止、替换或篡改运行于正式端口（如 Hub 端口 80、Sidecar 8799、CPA 18117/18317、AI-KB 18080/18090）的在线服务容器。
   - 严禁擅自修改外部属主仓库（AI-KB、Sidecar、Catalog）的物理凭据与运行配置。
4. **证据矛盾自动阻断**：
   - 当交付契约校验器或智能体自身发现制品与运行态证据存在矛盾时，**MUST** 立即将总状态标记为 `FAIL` 或 `BLOCK`，绝不允许隐瞒或强行通过。

### STD-032 审批配置协同 (2.6.0)

生产审批 MUST 使用 STD-032 §4 的显式互斥配置。审计 MUST 区分候选、加密签名验证和独立人工信任边界；schema 合法、workflow 成功、裸布尔值或 Agent 自签不得产生人工 PASS。未知/不可核验边界 MUST BLOCK，禁止自动降级。编码 Agent MUST NOT 注册自有密钥为审批身份、触发签署、输入 PIN 或保存可复用审批凭证。所有证据来源及未执行阶段 MUST 如实记录。
