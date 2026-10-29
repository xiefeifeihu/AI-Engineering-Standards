# STD-032: AI Platform Release Engineering Contract (AI 平台发布工程契约规范)

```text
STANDARD_ID=STD-032
VERSION=2.10.0
STATUS=ACTIVE
SCOPE=跨项目生产级 CI/CD 与发布工程契约、统一 ReleaseProfile 分级发布架构 (PERSONAL_LOCAL, MAINTAINER_RELEASE, HIGH_ASSURANCE) (AI-Engineering-Hub, AI-KB, vtip-ai-sidecar, vtip-platform-catalog)、12阶段标准发布流水线、审批交接契约、多部署模式适配、五态Commit一致性证明、强制自动化门禁、制品不可变性与技术中立回滚契约
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-29
RELATED_STANDARDS=STD-001, STD-007, STD-014, STD-016, STD-017, STD-019, STD-030, STD-031, STD-033, STD-034
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。


### 1.3 统一 ReleaseProfile 分级发布架构 (Unified ReleaseProfile Architecture)

为解决不同工程场景（单人开发、团队协作、高保障生产）治理成本与安全要求的平衡问题，全平台统一建立三类 ReleaseProfile。受管工程必须在 `engineering-manifest.yaml` 或发布审批策略中显式声明所采用的 Profile，严禁未经声明隐式降级：

1. **`PERSONAL_LOCAL`（单人所有者本地生产模式）**：
   - **适用场景**：开发者个人控制并运行于本机（Windows 11 / WSL2 / Docker、Linux 桌面或单机进程）的项目（如 AI-Engineering-Hub、AI-KB、个人测试 Sidecar）。
   - **角色与权限**：同一自然人可以同时为开发者、GitHub 仓库所有者和本机生产发布操作者。**不要求建立 PR**：Agent 可在经授权的仓库直接更新 `main`；必须先通过发布前本地验证，推送后再由远端 `main` CI 独立验证；受保护分支若禁止直接推送必须遵守现有 GitHub 权限策略，不得强推或绕过保护。代码合入与生产部署授权严格分离。
   - **免除要求**：不强制要求第二个独立审批人、GitHub Environment Required Reviewers、Prevent Self-review、独立硬件签名密钥、RSA-PSS 本地审批工具、分布式防重放签名服务或 12 个物理独立执行器。
   - **支持的审批模式**：
     1) `OWNER_LOCAL_CONSENT`（交互确认模式）：每次部署需所有者当次明确交互确认（`OWNER_LOCAL_CONSENT_RECORDED`），严禁编码智能体伪造。
     2) `AUTO_AFTER_GREEN`（全绿自动化发布模式）：个人本机明确声明的自动部署策略。不强制每次人工交互弹窗，但必须在以下 **10 项全绿门禁 (10 Mandatory Green Gates)** 全部无条件满足并完成机器取证后，才允许受控执行器自动推进生产部署与冒烟验收：
        - **门禁 1 (MAIN_COMMIT_VERIFIED)**：真实 GitHub 远端 `main` HEAD 与拟发布精确 40 位 Commit 严格一致；本地 `main` 已同步并通过源码与工作区状态审计。**不检查 PR、也不把 PR 当作强制阶段**。
        - **门禁 2 (REMOTE_CI_PASS)**：**发布目标 `main` Commit** 对应的 GitHub Actions 远端 CI 必须实际完成且 `conclusion=success`；功能分支 CI 不能替代。
        - **门禁 3 (AUTOMATED_TESTS_PASS)**：发布前独立候选环境中，单元、契约、集成与适用的端到端测试真实执行且通过，保留原始日志。
        - **门禁 4 (PLAYWRIGHT_PASS)**：涉及 UI 变更时在候选环境完成真实 Chromium/Playwright 自动化测试；无 UI 变更须提供可复核的范围判定并标明 `NOT_APPLICABLE`。此项仅说明发布前验证通过，不替代真实生产浏览器验收。
        - **门禁 5 (SECRETS_SCAN_PASS)**：严格执行 `STD-007` 零密钥门禁，无明文 API Key、Token、私钥泄露。
        - **门禁 6 (SOURCE_BUILD_COMMIT_UNAMBIGUOUS)**：`SOURCE_COMMIT`、`BUILD_COMMIT`、`TARGET_COMMIT` 标识明确且严格一致。
        - **门禁 7 (BACKUP_AND_RESTORE_VERIFIED)**：真实生产数据库完成快照备份，且在隔离环境中校验恢复可用。
        - **门禁 8 (ROLLBACK_READY)**：目标 Docker 引擎已预置并核验上一版本健康镜像，安全回滚路径真实就绪。
        - **门禁 9 (CONTROLLED_WSL_EXECUTOR)**：必须由受控本地 WSL 执行器执行生产容器替换，严禁云端直接触碰生产环境。
        - **门禁 10 (HEALTH_AND_SMOKE_RUNNABLE)**：部署前确认真实生产探针、自动化回归脚本和回滚执行器均已就绪；**不允许凭“可运行”宣称生产验收已成功**。部署后必须执行 §2.2 的第二阶段。
   - **安全与审计属性**：`AUTO_AFTER_GREEN_VERIFIED` 仅表示允许开始受控生产部署。十项发布前机器门禁任一失败必须阻断部署。部署之后的 `POST_DEPLOY_REAL_ACCEPTANCE` 是另一个独立且不可省略的门禁；失败时不可打正式 Tag，必须执行故障处置或回滚，不得借发布前测试覆盖失败事实。

2. **`MAINTAINER_RELEASE`（团队协作维护者发布模式）**：
   - **适用场景**：多人协同开发工程。
   - **协作机制**：标准本身不要求 PR。可由有权限的 Maintainer 在现有仓库规则下把受审代码提交到 `main`，依赖独立 `main` CI 与真实维护者授权发布；组织现存强制代码审查或分支保护不得绕过。团队审批和生产发布权限不得因取消 PR 而被取消。

3. **`HIGH_ASSURANCE`（高保障严格发布模式）**：
   - **适用场景**：对发布完整性与密码学审计有极高要求的关键环境。
   - **安全机制**：完整保留 `STD-032 v2.6.0` 规范的 12 阶段物理生命周期、独立审批身份、RSA-PSS 硬件密钥签名核验、防重放及 Fail Closed 严格阻断机制。
   - **禁止降级**：绝不允许因为存在 PERSONAL_LOCAL 模式而削弱 HIGH_ASSURANCE 的安全约束。

---

## 1. 规范目标与架构原则 (Purpose & Architecture Principles)

本规范旨在建立 AI 平台生产级 CI/CD 与 Release Engineering 统一标准，规范跨工程流水线执行、审批到执行器交接、多部署模式适配及版本发布全周期闭环，彻底消除代码 (`LOCAL_HEAD`)、远端仓库 (`REMOTE_HEAD`)、版本标签 (`TAG_COMMIT`)、构建元数据 (`BUILD_COMMIT`) 与线上运行态 (`LIVE_COMMIT`) 之间的漂移与伪造问题。

### 1.1 云端 CI 与生产 CD 严格物理隔离原则 (Strict Cloud CI & Local CD Separation)
1. **GitHub-hosted Runner 权限边界**：GitHub 托管 Runner（如 `ubuntu-latest`）运行于公有云临时隔离容器中，**MUST NOT** 尝试直接访问或挂载开发者/生产主机的内部 Docker 守护进程，**MUST NOT** 开放未授权的公网 Docker TCP 端口（如 `2375/2376`），**MUST NOT** 在云端 Runner 尝试调用宿主机专有环境（如 `wsl.exe`）。
2. **生产部署由受控本地/目标执行器负责**：生产环境真实部署 **MUST** 由受控的本地执行器（如 WSL 执行器、专用 Self-Hosted Runner、受控自动化代理）在授权审查后独立执行。
3. **可信审批交接契约 (Trust Handoff)**：云端 CI 与本地生产 CD 执行器之间 **MUST** 通过机器可复核、防篡改的发布审批证据包进行安全交接。

### 1.2 制品不可变性与身份锁定 (Artifact Immutability & Identity Lock)
1. 生产发布只能部署已通过自动化门禁测试、源码经过静态安全扫描并固化确切 Commit 标识的制品。
2. 容器镜像 **MUST** 显式绑定 `BUILD_COMMIT`（完整 40 位 Git SHA，短 SHA 仅作展示）与带类型的不可变制品身份；禁止部署 `latest` 浮动标签作为生产正式镜像。`LOCAL_DOCKER_IMAGE_ID`（`docker inspect .Image`）、`OCI_MANIFEST_DIGEST`（镜像清单的内容摘要）、`REGISTRY_REPODIGEST`（仓库名加 `@sha256:`）是三种不同证据，**MUST NOT** 混用、自动截断或直接相互比较。非容器制品应使用完整文件 SHA256 和明确的制品种类。
3. 所有运行时探针 **MUST** 通过标准网络套接字与 HTTP/HTTPS 契约端点（如 `/health`、`/api/runtime/identity`）获取真实运行身份。

---

## 2. 12 阶段标准发布生命周期 (12-Stage Release Lifecycle)

AI 平台所有受管工程仓库在执行生产版本发布时 **MUST** 完整覆盖以下 12 个标准阶段，并遵循严格的时序因果律：

```text
SOURCE ──► DEV_TEST ──► SECURITY_SCAN ──► BUILD ──► PACKAGE ──► PUBLISH ──► RELEASE_APPROVAL ──► DEPLOY ──► RUNTIME_VERIFY ──► SMOKE_TEST ──► PRODUCTION_RELEASE ──► TAG
```

| 序号 | 阶段标识 | 阶段名称 | 核心职责与准出判据 |
| :--- | :--- | :--- | :--- |
| 1 | `SOURCE` | 规划、源码与基线核验 | 只读核验 VERSION、范围、完整 Commit 和 git status；源码已提交且工作区干净。PLAN/CODE 是 SOURCE 的前置活动，不另计发布阶段。 |
| 2 | `DEV_TEST` | **第一阶段：发布前自动化验证** | 在候选环境执行单元、契约、集成、受控 E2E 与安全测试，验证允许进入生产部署的前提。环境差异导致的生产能力未验证不得标记生产 PASS。 |
| 3 | `SECURITY_SCAN` | 安全与凭据扫描 | 执行零密钥扫描 (`secret scan`) 与依赖清单完整性核验，严禁明文 Token/私钥入库。 |
| 4 | `BUILD` | 构建元数据生成 | 执行 `build_metadata.py` 固化 `build_info.json` 与 `.build_commit`，绑定 `BUILD_COMMIT == LOCAL_HEAD`。 |
| 5 | `PACKAGE` | 制品打包与校验 | 生成发布包至 `.artifacts/packages/`，计算 `PACKAGE_SHA256` 并输出 `artifact_manifest.json`。 |
| 6 | `PUBLISH` | 远端分支同步核验 | 严格核验本地提交已推送到远端仓库 (`LOCAL_HEAD == REMOTE_HEAD`)。若本地与远端分支 Commit 不一致，必须判定 `FAIL`。 |
| 7 | `RELEASE_APPROVAL` | 生产发布审批门禁 | 校验结构化审批证据包（绑定仓库、分支、精确 Commit、制品 Digest、审批身份、一次性发布任务 ID）。无有效审批证据时 **MUST** 标记 `BLOCK` 并阻断后续发布。 |
| 8 | `DEPLOY` | 受控部署与运行态就绪 | 在经批准的目标环境下，使用受控部署执行器将目标版本部署就绪，通过运行时技术中立探针验证存活。 |
| 9 | `RUNTIME_VERIFY` | 运行态身份与一致性核验 | 严格校验运行态真实返回的身份：`LOCAL_HEAD == REMOTE_HEAD == BUILD_COMMIT == LIVE_COMMIT`（前置 Tag 未创建时允许 Tag 待创建状态）。 |
| 10 | `SMOKE_TEST` | **第二阶段：部署后真实环境自动化验收** | 对已部署目标版本使用真实生产入口、真实网络/数据库/网关与必要的安全测试账号，执行非破坏性业务任务与浏览器交互并核查真实结果；不是仅 HTTP 200 或容器健康检查。 |
| 11 | `PRODUCTION_RELEASE` | 生产验收裁决与封版 | 发布前门禁必须全部通过；**最终真实可用性结论以第二阶段在当前 LIVE_COMMIT 下的自动化业务验收为准**，生成双阶段独立原始证据和统一裁决。任一失败不得给出总体 PASS。 |
| 12 | `TAG` | 正式 Git Tag 固化与推送 | 生产验收确认后，创建正式语义化版本标签 `v<VERSION>` 锁定指向实际发布的精确 Commit，并推送至远端仓库。 |

---


### 2.1 阶段执行形式：HIGH_ASSURANCE 12 阶段与 PERSONAL_LOCAL 7 组逻辑门禁

1. **HIGH_ASSURANCE 严格 12 阶段**：必须按标准时序因果律依次执行 12 个独立物理阶段。
2. **PERSONAL_LOCAL 7 组逻辑门禁 (7 Logical Gate Groups)**：允许将 12 阶段合并为 7 组可追溯的逻辑核验门禁，不需要为生成报告而模拟 12 个独立物理进程；签名独立性只适用于显式选择的签名模式，不能移植为本机所有者交互模式的前置条件：
   - **`G1 SOURCE_AND_POLICY`**（源与策略核验）：核验分支、完整 Commit、工作区干净、ReleaseProfile 与合规策略。
   - **`G2 TEST_AND_SECURITY`**（测试与安全扫描）：真实执行单元/契约/集成测试及 Playwright 浏览器验收，执行零密钥扫描。
   - **`G3 BUILD_AND_PUBLISH`**（构建与远端同步）：生成不可变构建元数据，固化镜像 SHA/Digest，严格验证 `LOCAL_HEAD == REMOTE_HEAD`。
   - **`G4 OWNER_AUTHORIZATION / AUTO_AFTER_GREEN_GATE`**（授权与全绿门禁核验）：
     * 若配置为 `OWNER_LOCAL_CONSENT`：核验当次精确 Commit/Version/Digest，记录 `OWNER_LOCAL_CONSENT_RECORDED`；无授权则保持 `WAITING_OWNER_AUTHORIZATION`。
     * 若配置为 `AUTO_AFTER_GREEN`：机器强制核验完整 10 项门禁（main 目标 Commit 已验证、main 远端 CI、测试全过、Playwright、密钥扫描、Commit 一致、备份隔离恢复、旧版回滚就绪、受控本地执行器、健康与冒烟可执行）。无 UI 变更时 Playwright 只能凭源码差异证据标记 `NOT_APPLICABLE(NO_UI_CHANGE)`，不得伪装 PASS；非 WSL 形态的受控本地执行器须提交等效隔离/授权/审计证据并满足同一控制目标。其余门禁必须真实 PASS，缺一即 BLOCK。部署后仍须执行当次真实 Runtime Acceptance 和业务冒烟。
   - **`G5 BACKUP_AND_DEPLOY`**（备份与受控部署）：真实可写数据一致性备份、隔离恢复验证，通过受控本地执行器拉起目标容器。
   - **`G6 RUNTIME_AND_SMOKE`**（运行态与业务冒烟）：技术中立探针核验存活，严格校验四态一致（`LOCAL == REMOTE == BUILD == LIVE`），执行核心业务冒烟。
   - **`G7 RELEASE_TAG_AND_VERIFY`**（标签固化与独立核验）：生产验收确认后推送正式 Tag（`v<VERSION>`），并通过独立的 `git rev-parse` 核实五态一致（`TAG_COMMIT == LIVE_COMMIT`）。
3. **真实性与不可伪造性要求**：无论采用 12 阶段还是 7 组门禁，每个阶段/门禁必须记录真实 `started_at`、`finished_at`、`exit_code`、`input_commit`、`output_digest`、`evidence_ref` 与状态。必须区分部署前候选测试与部署后真实环境测试，严禁伪造耗时、以历史日志替代当次运行或填充未运行阶段为 `PASS`。

### 2.2 两阶段自动化测试与最终判定（强制）

1. **第一阶段：`PRE_RELEASE_QUALIFICATION`**。在任何生产写操作前执行候选版本的单元、契约、集成、安全、必要的浏览器 E2E、备份隔离恢复与构建一致性检查；**目标是判断是否允许部署**，而非证明实际生产业务已可用。完成后仅产生 `PRE_RELEASE_STATUS`，必须保留真实执行日志、Commit、制品身份与运行环境；失败一票否决。
2. **第二阶段：`POST_DEPLOY_REAL_ACCEPTANCE`**。受控部署后、正式发布裁决和 Tag 之前，针对**当前实际运行服务**的真实域名/端口/容器/网络/数据库/CPA/Ollama/外部依赖，使用真实浏览器、API、任务调用和可审计且非破坏性的模拟用户旅程检验业务结果。必须至少涵盖产品基线中的**关键操作入口、跨组件连接、实际数据读取/处理、真实响应内容、错误及降级路径**，按项目可验证的授权范围执行。输出每个用例的目标、真实输入类型、可见结果、关键断言、证据位置、LIVE_COMMIT、时间戳与状态。
3. **生产真实验收优先**：`PRE_RELEASE=PASS` 只能允许部署；若 `POST_DEPLOY=FAIL|BLOCK|NOT_VERIFIABLE`，总体必须 `BLOCK` 或 `FAIL`，禁止 Tag 与宣称生产可用。后者 PASS 不得冲销前者 FAIL。两者均通过且 Source/Build/Live 一致、回滚就绪时方可裁决 `PRODUCTION_RELEASE=PASS`。Tag 创建后必须独立校验最终五态一致。
4. **“真实”等效范围**：生产环境自动化测试应尽可能模拟真人的实际操作，包括真实浏览器点击、筛选、保存/读取或授权的沙盒写回、模型推理与业务结果比对；**覆盖到的操作可以代替重复手工测试**，但未覆盖的用例、主观质量/人工采纳、不可安全自动执行的写入仍要明确标 `DEFERRED` 或 `NOT_VERIFIABLE`，不得声称等于全部人工验收。真实生产测试必须采用只读、专用测试租户/数据或受控可回滚写入，绝不删除真实业务数据或消耗未经授权的付费额度。
5. **负面用例与异常检出**：必须验证真实权限拒绝、限流/额度异常、网络中断及恢复、路由不可用、空结果、错误提示、菜单可达与浏览器行为；不能以页面能加载、统计不为零或截图不同哈希作为核心通过条件。关键验证失败必须输出最小复现、根因线索和修复任务。
6. **证据隔离**：`.artifacts/acceptance/<TASK>/<VERSION>/pre_release/` 与 `post_deploy/` 必须分开；必须附带同一次执行 Run ID、目标 Commit、LIVE_COMMIT、执行入口和原始测试日志、截图/录像、探针输出。候选服务端口截图、旧版本截图、Mock 或静态 JSON 不得替代后者。
7. **没有长期运行服务的 Standards/文档/静态制品**：可显式声明 `deployment_kind=NON_RUNTIME_ARTIFACT` 并采用正式发布目标的真实制品/Schema/消费端契约验证；不能伪装执行过容器生产 E2E。正式测试范围之外的跨项目运行效果另记为 `DEFERRED`，不作为纯规范制品自身的运行服务测试。



## 3. 全局 Fail-Closed 门禁与时序契约 (Fail-Closed Gate & Ordering Contract)

### 3.1 全局 Fail-Closed 中止法则
1. **前置门禁阻断法则**：若流水线前置任一强制阶段（`SOURCE`/`CODE`、`DEV_TEST`、`SECURITY_SCAN`、`BUILD`、`PACKAGE`、`PUBLISH`、`RELEASE_APPROVAL`）判定为 `FAIL` 或 `BLOCK`，流水线 **MUST** 立即执行全局 Fail-Closed 中止，**MUST NOT** 继续执行 `DEPLOY` 等具有破坏性或写操作的后续阶段。
2. **未执行阶段标注**：因前置失败中止而未执行的后续阶段，**MUST** 显式标记为 `BLOCK` 并设置 `executed=false`，并记录中止原因（`reason: "Skipped due to upstream stage failure"`），严禁静默吞掉或虚假标记为 `PASS`。

### 3.2 RUNTIME_VERIFY 与 TAG 的正确时序契约
1. **时序因果律**：在正式发布成功前，正式 Release Tag 尚未创建。在第 9 阶段 (`RUNTIME_VERIFY`) 与第 10 阶段 (`SMOKE_TEST`) 执行时，**MUST NOT** 强制要求一个尚未创建的正式 Tag 已经存在并匹配。
2. **阶段判定准则**：
   - 在部署后核验阶段 (`RUNTIME_VERIFY`)：核心核验四态一致性 `LOCAL_HEAD == REMOTE_HEAD == BUILD_COMMIT == LIVE_COMMIT`。Tag 状态标记为 `PENDING_STAGE_12_CREATION` 或核验本地候选标签。
   - 在标签固化阶段 (`TAG`)：仅在 `PRODUCTION_RELEASE` 验收确认 `PASS` 后，由受控流水线为目标 Commit 创建并推送正式 Tag（`v<VERSION>`），实现最终完整的五态一致性闭环：
     ```text
     LOCAL_HEAD == REMOTE_HEAD == BUILD_COMMIT == LIVE_COMMIT == TAG_COMMIT
     ```

---

## 4. 审批到执行器交接契约 (Approval to Executor Handshake Contract)


### 4.0 ReleaseProfile 与审批模式映射规则
1. **HIGH_ASSURANCE**：审批模式必须为 `GITHUB_ENVIRONMENT_REVIEW` 或 `LOCAL_AUTHORIZED_KEY`。必须执行严格的独立人工审查与密码学签名验证。
2. **PERSONAL_LOCAL**：审批模式支持配置为 `OWNER_LOCAL_CONSENT` 或 `AUTO_AFTER_GREEN`（亦支持经配置的 `LOCAL_AUTHORIZED_KEY` / `GITHUB_ENVIRONMENT_REVIEW`）。`OWNER_LOCAL_CONSENT` 要求所有者当次真实交互且绑定完整任务与制品身份，但不要求第二审批人、独立硬件签名或 GitHub Required Reviewers；`AUTO_AFTER_GREEN` 由独立核验真实机器证据的受控本地执行器在十项门禁满足后自动放行，不要求每次人工点击。
3. **MAINTAINER_RELEASE**：审批模式允许为 `MAINTAINER_APPROVAL` 或 `GITHUB_ENVIRONMENT_REVIEW`。

### 4.1 严禁单凭布尔值冒充正式审批
1. **禁止假审批**：流水线与部署执行器 **MUST NOT** 仅凭命令行参数 `--release-approved`、`--approved` 或环境变量 `RELEASE_APPROVAL=APPROVED` 单独判定为正式生产审批。
2. **结构化审批证据包 (Approval Evidence)**：正式审批 **MUST** 提供符合规范的审批证据包（`approval_evidence.json`），包含：
   - `approval_token_id`：唯一审批凭证标识符。
   - `one_time_release_task_id`：一次性关联的任务 ID。
   - `repository`：受管目标仓库名称。
   - `target_branch`：目标发布分支。
   - `target_version`：目标发布版本。
   - `target_commit`：目标精确 Commit SHA。
   - `package_digest`：构建制品的 SHA256 摘要。
   - `approver`：审批人身份标识。
   - `approval_source`：审批源标识（按 §4.0 对应的 `OWNER_LOCAL_CONSENT`、`AUTO_AFTER_GREEN`、`MAINTAINER_APPROVAL`、`GITHUB_ENVIRONMENT_REVIEW` 或 `LOCAL_AUTHORIZED_KEY`）。
   - `approved_at`：审批通过时间戳。
   - `status`：审批状态（`APPROVED`）。
   - `integrity_hash`：可选传输完整性摘要，**不构成审批真实性证明**。可信来源验证 **MUST** 按审批模式区分：签名模式验证固定公钥签名、GitHub 模式验证认证 API、`OWNER_LOCAL_CONSENT` 验证本机可信操作者交互与一次性消费记录、`AUTO_AFTER_GREEN` 验证全部独立机器门禁原始证据。普通 JSON、布尔值、摘要或 Agent 自填姓名均不能单独证明授权。
3. **执行器核验四项准则**：
   - 证据中的 `repository` 与本地项目工程标识一致。
   - 证据中的 `target_commit` 与部署目标 Commit 完全一致。
   - 证据中的 `package_digest` 与本地构建制品 SHA256 完全一致。
   - 证据未过期且 `one_time_release_task_id` 匹配当前发布任务。

### 4.2 GitHub Environment Review 审查与状态核查
1. 本节的 GitHub 审批限制仅在选定 `GITHUB_ENVIRONMENT_REVIEW` 时适用；密钥签名要求仅在选定 `LOCAL_AUTHORIZED_KEY` 时适用。全部 Profile **MUST** 显式选择 §4.0 允许的唯一审批模式，未配置有效策略 MUST BLOCK，禁止某个审批模式失败后隐式降级到另一个模式。选用 `GITHUB_ENVIRONMENT_REVIEW` 时，生产作业 **MUST** 绑定 `environment: production`，配置 Required Reviewers、Prevent Self-review 和仅允许 main 分支的限制；不得把这些条件强加给 `PERSONAL_LOCAL + OWNER_LOCAL_CONSENT` 或 `PERSONAL_LOCAL + AUTO_AFTER_GREEN`。
2. 本地执行器在检查远端审批状态时，若无法直接核验 GitHub API（如无有效 `GH_TOKEN` 或网络受限），**MUST** 将环境审查标记为 `NOT_VERIFIABLE`，严禁在无证据时冒充 `PASS`。

### 4.3 按 ReleaseProfile 区分审批来源、验证和一次性消费

1. **共同强制项**：审批字段本身不能建立信任。所有发布必须绑定完整仓库、`main`、40 位目标 Commit、目标版本、**带类型的不可变制品身份**、有效期、一次性任务 ID 和当次受控执行器；执行器必须在替换服务或修改生产数据之前核验审批策略与证据，并通过持久化原子事务消费任务 ID。过期、重放、身份不符、环境变化或证据不可核验 MUST BLOCK。无论模式如何，Source/Build/Live/Tag、备份隔离恢复、回滚和 Runtime Acceptance **MUST** 保持真实。
2. **`PERSONAL_LOCAL + OWNER_LOCAL_CONSENT`**：同一自然人可为开发者、仓库所有者与本机操作者。所有者 **MUST** 在本次可信本机操作界面明确确认或拒绝，该界面必须展示仓库、版本、完整 Commit、制品类型与完整身份、任务 ID、目标环境和变更摘要；确认事件必须由受控本地授权组件从真实操作者会话采集，并绑定当前候选、有效期、一次性任务 ID、可信会话和审计记录。编码 Agent **MUST NOT** 代按确认键、注入交互输入、预生成批准票据或通过可编辑 JSON 模拟。无需第二审批人、GitHub Environment Required Reviewers 或硬件签名；若执行器无法区分真人交互与 Agent 操作，必须 `WAITING_OWNER_AUTHORIZATION`，不得自称已获确认。JSON Schema 结构校验不构成人类交互真实性证明。
3. **`PERSONAL_LOCAL + AUTO_AFTER_GREEN`**：该模式不需要逐次人工点击，但必须预先在受信策略中显式启用，并由受控本地执行器逐项核验 §1.3 的 **全部 10 项** 门禁的真实外部证据（包括精确 Commit 已同步并固定在远端 main、当前 main 对应的远端 CI、真实测试输出、密钥扫描、制品身份、隔离恢复、上一稳定版本回滚、受控执行器和部署后健康/冒烟）。单个布尔字段或自填的 `PASS` 不构成证据。无 UI 变化时 Playwright 可记录 `NOT_APPLICABLE`，但必须有实际 diff 与适用性判定原始证据；没有数据库的工程必须证明可写状态盘点和应恢复资产，不得假绿。非 WSL 部署可以用经过授权、隔离且可审计的同等本地执行器满足第九门禁，不能直接跳过。满足后记录 `AUTO_AFTER_GREEN_VERIFIED`；任一必要证据缺失即 BLOCK。
4. **`MAINTAINER_RELEASE`**：通过受认证的 Maintainer/Environment 审查机制确定授权，不允许把个人本地自动放行策略映射到团队发布。执行器必须验证受信身份与仓库授权权限。
5. **`HIGH_ASSURANCE`**：严格沿用独立审批身份、认证 GitHub Environment 审批或 §4.4 受保护硬件/独立账号密钥模式，MUST 验证 Required Reviewers、防自审、受保护分支、审批签名及独立信任边界（按选择模式适用），不可降级。
6. **远端 CI 与一次性防重放**：所有模式均必须从受信远端 GitHub API 校验目标 main Commit 与对应远端 CI、仓库权限及已配置分支保护，不要求查询 PR；在本机受控执行器中核验一次性任务账本。历史证据可作为诊断参考，但不能充当新目标版本的 Live 验收。不可核验则报告 `NOT_VERIFIABLE` 并阻断生产裁决。

### 4.4 受保护本地密钥审批配置 (LOCAL_AUTHORIZED_KEY)

1. **适用条件**：只有当前私有仓库套餐确实不提供 Environment Required Reviewers 时，治理方 MAY 通过正式发布策略启用本模式。MUST 记录仓库可见性、账户套餐证据来源、功能限制与核验时间。代码分支保护与 Environment 部署审核是不同能力，不能相互替代证明。API 缺失字段 MUST 记为 NOT_VERIFIABLE，不能猜测套餐或据此自动启用。用户/管理员提供的套餐证据 MUST 与 API 实测字段分开记录。官方功能说明：<https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments>。
2. **候选不等于批准**：云端 workflow 只生成 Candidate / UNAPPROVED 交接制品；`environment: production` 作业运行或成功不代表人工批准。本模式的云端候选生成不依赖不可用的 Required Reviewers，但仍 MUST 验证 main-only、真实 CI 和不可变镜像。执行器 MUST 明确拒绝缺失签名或未知策略。
3. **独立边界**：密钥 MUST 由独立人工审批身份持有，禁止编码 Agent、CI Runner、部署身份读取、导出或无人工交互调用。MUST 使用需每次真人确认的硬件密钥或受独立账号保护的不可导出密钥；单纯软件文件权限、`human_present=true`、自填账户名或新建同用户密钥不构成隔离证明。若 Agent 具有可绕过隔离的管理员权限，MUST 使用独立设备/硬件确认边界或 BLOCK。私钥 MUST NOT 位于任一项目仓库、`.artifacts`、环境变量、日志或 Agent 可读目录。Agent MUST NOT 点击确认、输入 PIN、签署或保存可复用审批令牌。
4. **注册与吊销**：受控策略 MUST 固定公钥 SPKI DER SHA256 指纹、算法、审批主体、独立签名边界的外部核验证据引用、有效期与撤销状态。密钥注册/轮换/撤销 MUST 独立人工治理，不允许发布候选携带新公钥建立信任。未知、过期、撤销或缺少可独立核验边界的密钥 MUST BLOCK。签名必须按固定算法与受信公钥验证，禁止算法协商或信任输入中的任意公钥。
5. **签署内容**：签名 MUST 覆盖 `release-approval.schema.json` 的完整 payload：schema/domain、repository、main、完整 source SHA、目标版本、镜像完整 digest、workflow 路径、run ID/attempt、最新 main CI run ID、候选摘要、变更摘要 SHA256、签发与过期时间、一次性 release_task_id、审批身份和决定。所有值 MUST 从经认证远端事实与已审候选重建并逐项比较；不能信任本地传入的 SHA 或 digest。main 在签署到部署期间变化 MUST 撤销候选并重新执行。
6. **规范化与算法**：本契约 v1 使用 UTF-8 编码的 ASCII 字符串字段、整数和无嵌套浮点数的 payload；拒绝重复 JSON key、未知字段与非规范值；按字段字典序、无空白分隔符序列化（Python 等价 `json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')`）。签名固定为 RSA-PSS-SHA256、MGF1-SHA256、salt length 32、公钥至少 3072 bits。公钥指纹为 SPKI DER 的 SHA256；signature 为严格 base64。有效期最长 24 小时，UTC 秒精度，未来签发、已过期或时间不可核验 MUST BLOCK。摘要不是签名。
7. **人工操作**：独立审批工具 MUST 在同一次交互中展示任务 ID、版本、完整 SHA、完整镜像 digest、workflow/CI run 和完整变更摘要，并允许明确签署或拒绝。显示内容和签署字节 MUST 对应同一候选。拒绝决定不能用于部署。生产代码不得提供生成 Mock 人工审批的选项。签名验证成功只证明密钥持有，不能单独证明人工在场；还 MUST 验证注册边界和提供方的每次确认机制。
8. **防重放和竞态**：执行器 MUST 在任何 docker pause/stop/up 或持久数据修改前完成全部审批校验，核验撤销状态、当前 main、CI 与镜像，并以持久化原子事务消费任务 ID。账本 MUST 由受控执行器保护，不得因更换工作区或删除普通 artifact 而重置。失败重试需要新的候选和审批；审批不能跨版本、run attempt、仓库或镜像复用。
9. **测试与证据**：至少覆盖有效签名、篡改/伪造、错误仓库/SHA/digest/版本/run、未知/撤销密钥、过期/未来时间、重放、自审、缺少人工在场、未知模式和 GitHub 正反路径。Mock 仅用于隔离测试，MUST NOT 作为生产批准或边界证明。schema 合法不等于签名有效，更不等于人工审批可信。

### 4.5 不可变制品身份与证据类型（禁止混用）

1. `LOCAL_DOCKER_IMAGE_ID`：本地 Docker `docker image inspect .Id` 和运行容器 `docker inspect .Image` 表示本地镜像配置对象身份，格式 `sha256:<64 hex>`。构建后与运行容器 **MUST** 使用同类值逐字节比较，不能拿本地 Image ID 冒充 OCI Registry Manifest Digest。
2. `OCI_MANIFEST_DIGEST`：OCI 镜像清单内容摘要 `sha256:<64 hex>`，可能与 Image ID 不同；仅与实际拉取或发布的同一 OCI 清单摘要比较。
3. `REGISTRY_REPODIGEST`：`registry/repository@sha256:<64 hex>`，包含仓库引用和 Registry 返回的清单摘要；核验时必须绑定仓库名和清单身份，不能丢弃仓库部分与本地 Image ID 比较。
4. `FILE_SHA256`：非容器制品的完整文件 SHA256，必须附制品路径/名称和非容器部署方式。两个 `sha256:` 字符串相同格式并不意味着同类证据可比较。
5. 结构化契约使用 `artifact_identity.kind` 和 `artifact_identity.value`，运行时按 kind 校验，绝不跨类型宽松匹配。不得通过前缀截断、镜像 Tag、`latest` 或值互相包含替代精确核验。

### 4.6 不依赖 PR 的 main 提交与自动化 CD 边界

1. **取消 PR 强制机制**：本标准所有 ReleaseProfile 均不把 PR 创建/合并作为发布合规的前置门禁。开发者可以先在本地隔离分支做发布前测试，再以非强推方式更新 main；个人本机仓库在策略允许时也可以直接提交至 main。若 GitHub 仓库实际配置禁止直接推送，**MUST** 遵循受保护分支规则，不能要求 Agent 违规绕过；由仓库所有者调整可行的受控分支策略后方可采用无 PR 流程。
2. **主要事实源**：发布对象唯一是远端 `main` 的精确 40 位 Commit。任何独立功能分支、暂存区或候选镜像的测试都不能替代该 Commit 的 `main` CI。单人项目可在策略声明下由编程 Agent 自动提交、Push、等待远端 main CI 全绿，无需人工点击合并。
3. **严格独立的两阶段自动化**：发布前机器门禁全部真实通过、审批模式满足后才允许部署；部署后必须执行第二次生产入口的真实业务自动化验收。后者决定生产可用性最终结论，失败须阻断发布封版和 Tag，并执行回滚/问题修复。
4. **保持高保障边界**：`MAINTAINER_RELEASE`、`HIGH_ASSURANCE` 的维护者或独立人工审批要求保持不变；取消 PR **不等于** 取消审查人或批准、远端 CI、审计、反重放和不可变制品身份。
5. **严格禁止假完成**：只在本地完成开发、只有功能分支 CI、生产仍运行旧容器、未执行真实业务验收、旧截图和旧验收包均不可宣称生产 PASS。


---

## 5. 多部署模式适配契约 (Multi-Deployment Mode Support)

AI 平台发布工程规范必须支持多种运行部署形态，发布适配器与执行器 **MUST** 遵循统一接口契约，适配以下四种典型部署模式：

### 5.1 模式 A：本地 WSL Docker 部署模式 (Local WSL Docker)
- **适用场景**：AI-Engineering-Hub 等本地工程控制平面。
- **执行方式**：由受控脚本调用本地 `wsl.exe`，在隔离 Linux 子系统内执行 Docker 构建、启动与监控。
- **网络约束**：宿主机与 WSL 共享环回网络，通过端口映射或主机模式绑定服务。

### 5.2 模式 B：标准 Linux Docker / 容器化部署模式 (Linux Container)
- **适用场景**：标准 Linux 生产服务器、CI Runner 或容器编排平台。
- **执行方式**：通过标准 Docker CLI 或 Compose 工具，以非 root 用户执行容器编排。
- **约束**：使用固化镜像 Tag 与 Digest，不使用宿主机特定专有工具。

### 5.3 模式 C：受控远程部署模式 (Controlled Remote Deployment)
- **适用场景**：远程服务器、私有云宿主机节点。
- **执行方式**：通过经双向凭据认证的 CI/CD 代理或受控 SSH 通道下发已签名的发布包与审批凭证，远端节点核验签名后执行本地拉起。
- **安全约束**：严禁在公网开放无认证 Docker 守护进程端口。

### 5.4 模式 D：非容器化原生进程应用 (Bare-Metal / Virtualenv Process)
- **适用场景**：Python 原生后台服务、纯脚本工具、定时守护进程。
- **执行方式**：通过 `systemd`、`supervisord`、Windows 服务或指定进程管理器管理生命周期。
- **技术中立探针**：统一通过 TCP 套接字监听、HTTP `/health` 探针与本地 PID 存活检查判定就绪。

---

## 6. 技术中立回滚与环境自愈契约 (Rollback & Healing Contract)

### 6.1 数据备份完备性与目录隔离
1. 执行任何容器或服务替换前，执行器 **MUST** 首先将运行时数据（`data/`）及编排配置（`compose.yaml`）完整备份至 `.artifacts/backups/` 目录。
2. 备份目录 **MUST** 与正式业务数据物理隔离，并在备份完成后生成 `backup_manifest.json` 记录文件清单与校验哈希。

### 6.2 容器与服务编排回滚可靠性
1. **防容器命名冲突**：回滚操作停止并清理失败容器时，**MUST** 通过原编排项目停止并重建失败服务，保留服务归属标签与配置，严禁产生容器名称冲突（如 `ai-engineering-hub-rollback` 再次执行冲突）。
2. **编排工具可再管理性**：回滚后容器 **MUST** 保持标准服务名称（如 `ai-engineering-hub`），确保日常 `docker compose` 工具仍可继续无缝管理服务。
3. **旧镜像确定性锁定**：回滚镜像 **MUST** 锁定至完整的不可变 Image ID 或 Digest（Tag 只能作展示，不能作为恢复身份），严禁使用未经固化的模糊镜像。
4. **幂等性**：连续多次触发回滚操作 **MUST** 保证幂等安全，不导致服务雪崩或进一步破坏。
5. **回滚审计留痕**：回滚执行完成后 **MUST** 输出 `rollback_audit.json`，完整记录回滚原因、耗时、前置与恢复后的 Commit 身份。


### 6.3 恢复验证
备份 MUST 覆盖所有实际可写数据挂载，使用数据库一致性备份或经授权的写入静止窗口；仅复制 data/ 不代表完整备份。上线前 MUST 将备份在隔离目录实际恢复并核验摘要与数据库完整性。恢复失败 MUST 阻断部署。回滚 MUST 停止写入后恢复数据并验证原编排归属、健康、Commit 及完整镜像身份，重复执行仍应收敛。备份与原编排配置可能含私人数据，MUST 不进入 Git、日志与验收交付包。
