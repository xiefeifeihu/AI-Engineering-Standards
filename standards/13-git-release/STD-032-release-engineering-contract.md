# STD-032: AI Platform Release Engineering Contract (AI 平台发布工程契约规范)

```text
STANDARD_ID=STD-032
VERSION=2.6.0
STATUS=ACTIVE
SCOPE=跨项目生产级 CI/CD 与发布工程契约 (AI-Engineering-Hub, AI-KB, vtip-ai-sidecar, vtip-platform-catalog)、12阶段标准发布流水线、审批交接契约、多部署模式适配、五态Commit一致性证明、强制自动化门禁、制品不可变性与技术中立回滚契约
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-25
RELATED_STANDARDS=STD-001, STD-007, STD-014, STD-016, STD-017, STD-019, STD-030, STD-031, STD-033, STD-034
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 规范目标与架构原则 (Purpose & Architecture Principles)

本规范旨在建立 AI 平台生产级 CI/CD 与 Release Engineering 统一标准，规范跨工程流水线执行、审批到执行器交接、多部署模式适配及版本发布全周期闭环，彻底消除代码 (`LOCAL_HEAD`)、远端仓库 (`REMOTE_HEAD`)、版本标签 (`TAG_COMMIT`)、构建元数据 (`BUILD_COMMIT`) 与线上运行态 (`LIVE_COMMIT`) 之间的漂移与伪造问题。

### 1.1 云端 CI 与生产 CD 严格物理隔离原则 (Strict Cloud CI & Local CD Separation)
1. **GitHub-hosted Runner 权限边界**：GitHub 托管 Runner（如 `ubuntu-latest`）运行于公有云临时隔离容器中，**MUST NOT** 尝试直接访问或挂载开发者/生产主机的内部 Docker 守护进程，**MUST NOT** 开放未授权的公网 Docker TCP 端口（如 `2375/2376`），**MUST NOT** 在云端 Runner 尝试调用宿主机专有环境（如 `wsl.exe`）。
2. **生产部署由受控本地/目标执行器负责**：生产环境真实部署 **MUST** 由受控的本地执行器（如 WSL 执行器、专用 Self-Hosted Runner、受控自动化代理）在授权审查后独立执行。
3. **可信审批交接契约 (Trust Handoff)**：云端 CI 与本地生产 CD 执行器之间 **MUST** 通过机器可复核、防篡改的发布审批证据包进行安全交接。

### 1.2 制品不可变性与身份锁定 (Artifact Immutability & Identity Lock)
1. 生产发布只能部署已通过自动化门禁测试、源码经过静态安全扫描并固化确切 Commit 标识的制品。
2. 容器镜像 **MUST** 显式绑定 `BUILD_COMMIT`（完整 40 位 Git SHA，短 SHA 仅作展示）与唯一的 Image Digest / ID；禁止部署 `latest` 浮动标签作为生产正式镜像。
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
| 2 | `DEV_TEST` | 开发分层测试 | 真实执行 `unit test`、`contract test`、`integration test`、`e2e` 测试并 100% 通过（`exit_code=0`）。 |
| 3 | `SECURITY_SCAN` | 安全与凭据扫描 | 执行零密钥扫描 (`secret scan`) 与依赖清单完整性核验，严禁明文 Token/私钥入库。 |
| 4 | `BUILD` | 构建元数据生成 | 执行 `build_metadata.py` 固化 `build_info.json` 与 `.build_commit`，绑定 `BUILD_COMMIT == LOCAL_HEAD`。 |
| 5 | `PACKAGE` | 制品打包与校验 | 生成发布包至 `.artifacts/packages/`，计算 `PACKAGE_SHA256` 并输出 `artifact_manifest.json`。 |
| 6 | `PUBLISH` | 远端分支同步核验 | 严格核验本地提交已推送到远端仓库 (`LOCAL_HEAD == REMOTE_HEAD`)。若本地与远端分支 Commit 不一致，必须判定 `FAIL`。 |
| 7 | `RELEASE_APPROVAL` | 生产发布审批门禁 | 校验结构化审批证据包（绑定仓库、分支、精确 Commit、制品 Digest、审批身份、一次性发布任务 ID）。无有效审批证据时 **MUST** 标记 `BLOCK` 并阻断后续发布。 |
| 8 | `DEPLOY` | 受控部署与运行态就绪 | 在经批准的目标环境下，使用受控部署执行器将目标版本部署就绪，通过运行时技术中立探针验证存活。 |
| 9 | `RUNTIME_VERIFY` | 运行态身份与一致性核验 | 严格校验运行态真实返回的身份：`LOCAL_HEAD == REMOTE_HEAD == BUILD_COMMIT == LIVE_COMMIT`（前置 Tag 未创建时允许 Tag 待创建状态）。 |
| 10 | `SMOKE_TEST` | 最小业务冒烟验证 | 执行非破坏性只读业务验证，验证核心功能与 API 契约可用。 |
| 11 | `PRODUCTION_RELEASE` | 生产验收裁决与封版 | 汇总各阶段真实证据生成 `release_execution_report.json`，判定全流水线通过。 |
| 12 | `TAG` | 正式 Git Tag 固化与推送 | 生产验收确认后，创建正式语义化版本标签 `v<VERSION>` 锁定指向实际发布的精确 Commit，并推送至远端仓库。 |

---

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
   - `approval_source`：审批源标识（如 `GITHUB_ENVIRONMENT_REVIEW` / `LOCAL_AUTHORIZED_KEY`）。
   - `approved_at`：审批通过时间戳。
   - `status`：审批状态（`APPROVED`）。
   - `integrity_hash`：传输完整性摘要，**不构成审批真实性证明**；真实性必须由可信发行者签名（验证固定公钥与签名算法）或认证的审批服务 API 独立验证。
3. **执行器核验四项准则**：
   - 证据中的 `repository` 与本地项目工程标识一致。
   - 证据中的 `target_commit` 与部署目标 Commit 完全一致。
   - 证据中的 `package_digest` 与本地构建制品 SHA256 完全一致。
   - 证据未过期且 `one_time_release_task_id` 匹配当前发布任务。

### 4.2 GitHub Environment Review 审查与状态核查
1. 发布策略 **MUST** 显式选择唯一审批模式 `GITHUB_ENVIRONMENT_REVIEW` 或 `LOCAL_AUTHORIZED_KEY`，且在受控仓库通过独立 PR 和真实 CI 审查。未配置策略 MUST BLOCK；禁止在 GitHub 审批失败时自动降级。使用 `GITHUB_ENVIRONMENT_REVIEW` 时，涉及生产发布的作业 **MUST** 绑定 `environment: production`，配置 Required Reviewers、Prevent Self-review 和仅允许 main 分支的限制；所有原有严格验证仍然适用。
2. 本地执行器在检查远端审批状态时，若无法直接核验 GitHub API（如无有效 `GH_TOKEN` 或网络受限），**MUST** 将环境审查标记为 `NOT_VERIFIABLE`，严禁在无证据时冒充 `PASS`。

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


### 4.3 审批来源验证与一次性消费
审批字段本身不能建立信任。GitHub 模式执行器 MUST 从认证审批服务读取审批人身份与决定；本地密钥模式 MUST 按 §4.4 验证签名和独立信任边界。发起人、编码 Agent、自动发布执行身份不得充当审批身份。部署输入 MUST 绑定完整仓库、分支、40 位 Commit、不可变制品 Digest、目标版本、审批有效期及一次性任务 ID。GitHub 模式执行器 MUST 验证受保护环境的 Required Reviewers、防止自审、分支限制与发布权限；权限不足或字段不可获取时报告 NOT_VERIFIABLE 并阻断。

两种模式均 MUST 验证 GitHub 认证 API 提供的可信工作流路径、运行 ID 与 attempt、精确源 SHA、该运行生成的不可变交接制品以及目标 main Commit 的最新成功 CI。GitHub 模式还 MUST 核验真实审批历史。一次性任务 ID MUST 在替换服务前通过持久化事务消费；重放或失败重试需要新审批任务。不得将自填姓名、字符串 APPROVED、普通 SHA256 或可编辑本地 JSON 视作签名。

### 4.4 受保护本地密钥审批配置 (LOCAL_AUTHORIZED_KEY)

1. **适用条件**：只有当前私有仓库套餐确实不提供 Environment Required Reviewers 时，治理方 MAY 通过正式发布策略启用本模式。MUST 记录仓库可见性、账户套餐证据来源、功能限制与核验时间。PR rulesets、分支保护审批计数与 Environment 部署审核是不同能力，不能相互替代证明。API 缺失字段 MUST 记为 NOT_VERIFIABLE，不能猜测套餐或据此自动启用。用户/管理员提供的套餐证据 MUST 与 API 实测字段分开记录。官方功能说明：<https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments>。
2. **候选不等于批准**：云端 workflow 只生成 Candidate / UNAPPROVED 交接制品；`environment: production` 作业运行或成功不代表人工批准。本模式的云端候选生成不依赖不可用的 Required Reviewers，但仍 MUST 验证 main-only、真实 CI 和不可变镜像。执行器 MUST 明确拒绝缺失签名或未知策略。
3. **独立边界**：密钥 MUST 由独立人工审批身份持有，禁止编码 Agent、CI Runner、部署身份读取、导出或无人工交互调用。MUST 使用需每次真人确认的硬件密钥或受独立账号保护的不可导出密钥；单纯软件文件权限、`human_present=true`、自填账户名或新建同用户密钥不构成隔离证明。若 Agent 具有可绕过隔离的管理员权限，MUST 使用独立设备/硬件确认边界或 BLOCK。私钥 MUST NOT 位于任一项目仓库、`.artifacts`、环境变量、日志或 Agent 可读目录。Agent MUST NOT 点击确认、输入 PIN、签署或保存可复用审批令牌。
4. **注册与吊销**：受控策略 MUST 固定公钥 SPKI DER SHA256 指纹、算法、审批主体、独立签名边界的外部核验证据引用、有效期与撤销状态。密钥注册/轮换/撤销 MUST 独立人工治理，不允许发布候选携带新公钥建立信任。未知、过期、撤销或缺少可独立核验边界的密钥 MUST BLOCK。签名必须按固定算法与受信公钥验证，禁止算法协商或信任输入中的任意公钥。
5. **签署内容**：签名 MUST 覆盖 `release-approval.schema.json` 的完整 payload：schema/domain、repository、main、完整 source SHA、目标版本、镜像完整 digest、workflow 路径、run ID/attempt、最新 main CI run ID、候选摘要、变更摘要 SHA256、签发与过期时间、一次性 release_task_id、审批身份和决定。所有值 MUST 从经认证远端事实与已审候选重建并逐项比较；不能信任本地传入的 SHA 或 digest。main 在签署到部署期间变化 MUST 撤销候选并重新执行。
6. **规范化与算法**：本契约 v1 使用 UTF-8 编码的 ASCII 字符串字段、整数和无嵌套浮点数的 payload；拒绝重复 JSON key、未知字段与非规范值；按字段字典序、无空白分隔符序列化（Python 等价 `json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')`）。签名固定为 RSA-PSS-SHA256、MGF1-SHA256、salt length 32、公钥至少 3072 bits。公钥指纹为 SPKI DER 的 SHA256；signature 为严格 base64。有效期最长 24 小时，UTC 秒精度，未来签发、已过期或时间不可核验 MUST BLOCK。摘要不是签名。
7. **人工操作**：独立审批工具 MUST 在同一次交互中展示任务 ID、版本、完整 SHA、完整镜像 digest、workflow/CI run 和完整变更摘要，并允许明确签署或拒绝。显示内容和签署字节 MUST 对应同一候选。拒绝决定不能用于部署。生产代码不得提供生成 Mock 人工审批的选项。签名验证成功只证明密钥持有，不能单独证明人工在场；还 MUST 验证注册边界和提供方的每次确认机制。
8. **防重放和竞态**：执行器 MUST 在任何 docker pause/stop/up 或持久数据修改前完成全部审批校验，核验撤销状态、当前 main、CI 与镜像，并以持久化原子事务消费任务 ID。账本 MUST 由受控执行器保护，不得因更换工作区或删除普通 artifact 而重置。失败重试需要新的候选和审批；审批不能跨版本、run attempt、仓库或镜像复用。
9. **测试与证据**：至少覆盖有效签名、篡改/伪造、错误仓库/SHA/digest/版本/run、未知/撤销密钥、过期/未来时间、重放、自审、缺少人工在场、未知模式和 GitHub 正反路径。Mock 仅用于隔离测试，MUST NOT 作为生产批准或边界证明。schema 合法不等于签名有效，更不等于人工审批可信。

### 6.3 恢复验证
备份 MUST 覆盖所有实际可写数据挂载，使用数据库一致性备份或经授权的写入静止窗口；仅复制 data/ 不代表完整备份。上线前 MUST 将备份在隔离目录实际恢复并核验摘要与数据库完整性。恢复失败 MUST 阻断部署。回滚 MUST 停止写入后恢复数据并验证原编排归属、健康、Commit 及完整镜像身份，重复执行仍应收敛。备份与原编排配置可能含私人数据，MUST 不进入 Git、日志与验收交付包。
