# STD-032: AI Platform Release Engineering Contract (AI 平台发布工程契约规范)

```text
STANDARD_ID=STD-032
VERSION=2.3.0
STATUS=ACTIVE
SCOPE=跨项目生产级 CI/CD 与发布工程契约 (AI-Engineering-Hub, AI-KB, vtip-ai-sidecar, vtip-platform-catalog)、12阶段标准发布流水线、五态Commit一致性证明、强制自动化门禁、制品与文档治理、技术中立回滚契约
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-13
RELATED_STANDARDS=STD-001, STD-007, STD-014, STD-016, STD-017, STD-019, STD-030, STD-031
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 规范目标与技术中立原则 (Purpose & Technology-Agnostic Principle)

本规范旨在建立 AI 平台生产级 CI/CD 与 Release Engineering 标准，彻底消除代码 (`LOCAL_HEAD`)、远端仓库 (`REMOTE_HEAD`)、版本标签 (`TAG_COMMIT`)、构建元数据 (`BUILD_COMMIT`) 与线上运行态 (`LIVE_COMMIT`) 之间的漂移与不一致问题。

### 1.1 技术中立约束 (Technology-Agnostic Invariant)
1. 发布流水线、门禁检查、运行时探针与回滚机制 **MUST** 保持技术中立，**MUST NOT** 绑定 Docker 守护进程（严禁强依赖 `/var/run/docker.sock`、`\\.\pipe\docker_engine` 或将 `docker ps`/`docker inspect` 作为唯一判据）。
2. 所有运行时探测 **MUST** 通过标准网络套接字（TCP Socket）与 HTTP/HTTPS 契约端点（如 `/health`、`/healthz`、`/api/runtime/identity`）及标准文件系统元数据 (`build_info.json`、`.build_commit`、`runtime_acceptance.json`) 完成。
3. 全面兼容 Windows 11 原生进程、WSL2、Linux 裸金属主机、虚拟环境与容器化部署形态。

---

## 2. 12 阶段标准发布生命周期 (12-Stage Release Lifecycle)

AI 平台所有受管工程仓库在执行生产版本发布时 **MUST** 完整覆盖以下 12 个标准阶段：

```text
PLAN ──► CODE ──► DEV_TEST ──► SECURITY_SCAN ──► BUILD ──► PACKAGE ──► PUBLISH ──► DEPLOY ──► RUNTIME_VERIFY ──► SMOKE_TEST ──► PRODUCTION_RELEASE ──► TAG
```

| 序号 | 阶段标识 | 阶段名称 | 核心职责与准出判据 |
| :--- | :--- | :--- | :--- |
| 1 | `PLAN` | 规划与基线核验 | 确认 `VERSION` 语义化版本号、变更范围及架构/文档治理边界合规。 |
| 2 | `CODE` | 源码就绪与干净工作区 | 代码提交完成，工作区检查 (`git clean`) 无未提交修改或非法跟踪文件。 |
| 3 | `DEV_TEST` | 开发分层测试 | 自动执行 `unit test`、`contract test`、`integration test`、`e2e` 测试并 100% 通过。 |
| 4 | `SECURITY_SCAN` | 安全与凭据扫描 | 执行零密钥扫描 (`secret scan`) 与依赖清单完整性核验，严禁明文 Token/私钥入库。 |
| 5 | `BUILD` | 构建元数据生成 | 执行 `build_metadata.py` 固化 `build_info.json` 与 `.build_commit`，绑定 `BUILD_COMMIT`。 |
| 6 | `PACKAGE` | 制品打包与校验 | 生成发布包与验收包至 `.artifacts/packages/`，计算 `PACKAGE_SHA256` 并输出 `artifact_manifest.json`。 |
| 7 | `PUBLISH` | 远端分支发布 | 将本地提交推送到远端仓库 (`git push remote`)，确保 `LOCAL_HEAD == REMOTE_HEAD`。 |
| 8 | `DEPLOY` | 部署与运行时探针 | 将当前构建部署至目标运行环境，通过技术中立 `runtime probe` 校验端口与服务可达。 |
| 9 | `RUNTIME_VERIFY` | 运行态五态一致性核验 | 严格校验 `LOCAL_HEAD == REMOTE_HEAD == TAG_COMMIT == BUILD_COMMIT == LIVE_COMMIT`。 |
| 10 | `SMOKE_TEST` | 最小业务冒烟验证 | 执行非破坏性只读 `minimal business verification`，验证核心业务契约可用。 |
| 11 | `PRODUCTION_RELEASE` | 生产验收封版 | 汇总生成并校验 `runtime_acceptance.json`，判定 `RUNTIME_ACCEPTANCE = PASS`。 |
| 12 | `TAG` | Git 版本标签固化与推送 | 创建语义化版本标签（如 `v0.20.1`）并推送至远端 (`push tag`)，锁定 `TAG_COMMIT`。 |

---

## 3. 统一 Release Pipeline 目录与脚本模板 (Unified Release Pipeline Layout)

四个核心工程项目（`AI-Engineering-Hub`、`AI-KB`、`vtip-ai-sidecar`、`vtip-platform-catalog`）**MUST** 统一维护 `scripts/release/` 目录，并包含以下四个标准模块：

```text
scripts/release/
  ├── release_pipeline.py    # 12阶段标准发布流水线编排与自动化门禁执行器
  ├── build_metadata.py      # 构建元数据生成器 (输出 build_info.json 与 .build_commit)
  ├── runtime_acceptance.py  # 技术中立运行时验收与五态 Commit 一致性校验器
  └── artifact_manifest.py   # .artifacts/ 结构治理、docs/ 卫生审计与 SHA256 清单生成器
```

---

## 4. 强制自动化门禁 (Mandatory Automated Gates)

任何生产版本发布前 **MUST** 自动执行并通过以下六大核心门禁，任一门禁失败 **MUST** 立即阻断发布 (`FAIL`)：

1. **SOURCE 门禁**：
   - `git clean`：工作区必须干净（`git status --porcelain` 为空），无未提交源码改动。
   - `secret scan`：全仓扫描零明文 API Key、Token、Password、私钥。
2. **DEV_TEST 门禁**：
   - `unit test`：核心模块单元测试通过。
   - `contract test`：Standards JSON Schema 与接口契约测试通过。
   - `integration test`：子系统与跨模块集成测试通过。
   - `e2e`：端到端验收测试通过。
3. **BUILD 门禁**：
   - `generate build metadata`：自动生成 `build_info.json`，确保 `BUILD_COMMIT == LOCAL_HEAD`。
4. **PACKAGE 门禁**：
   - `artifact sha256`：计算制品包 SHA256 摘要，生成 `artifact_manifest.json`，校验正式 ZIP 仅存于 `.artifacts/packages/`。
5. **DEPLOY 门禁**：
   - `runtime probe`：通过技术中立 HTTP/TCP 探针验证服务存活与就绪状态。
6. **SMOKE 门禁**：
   - `minimal business verification`：执行最小业务只读验证（如路由决策、能力大盘、健康契约、只读预览），严禁产生破坏性副作用。

---

## 5. Git 发布与 Tag 规范 (Git Release & Tag Contract)

### 5.1 强制四步发布序列
任何生产版本发布 **MUST** 严格执行以下 Git 序列：
1. **Commit**：提交所有经测试验证的代码与文档变更。
2. **Push Remote**：将当前分支推送至远端仓库 (`git push origin <branch>`)。
3. **Create Tag**：基于当前发布 Commit 创建标准语义化版本标签 `v<MAJOR>.<MINOR>.<PATCH>`（例如：`v0.20.1`）。
4. **Push Tag**：将版本标签推送至远端仓库 (`git push origin v0.20.1`)。

### 5.2 五态 Commit 一致性铁律 (5-Way Commit Identity Invariant)
生产验收 **MUST** 提供真实可核验的证据，证明以下五个 Commit 标识完全一致：
- `LOCAL_HEAD`：本地 Git 仓库 `HEAD` Commit。
- `REMOTE_HEAD`：远端仓库对应分支最新 Commit。
- `TAG_COMMIT`：当前版本 Git Tag（如 `v0.20.1`）指向的 Commit。
- `BUILD_COMMIT`：`build_info.json` / `.build_commit` 固化的构建 Commit。
- `LIVE_COMMIT`：线上运行服务（通过 `/health` 或 `/api/runtime/identity` 实时返回）的 Commit。

```text
LOCAL_HEAD == REMOTE_HEAD == TAG_COMMIT == BUILD_COMMIT == LIVE_COMMIT
```

---

## 6. Artifact 与文档治理规范 (Artifact & Documentation Governance)

### 6.1 `.artifacts/` 统一目录结构
所有非源码生成的报告、制品包、截图与验收证据 **MUST** 统一收敛至仓库根目录下的 `.artifacts/`（并在 `.gitignore` 中排除），标准结构如下：

```text
.artifacts/
  ├── acceptance/    # 阶段验收报告与专项验收输出
  ├── packages/      # 正式发布包与 Acceptance-*.zip (正式ZIP唯一合法目录)
  ├── screenshots/   # UI 自动化验收截图证据
  └── evidence/      # 流水线报告、artifact_manifest.json、五态一致性与测试证据
```

1. **严禁污染 `docs/`**：`docs/` 目录下 **MUST NOT** 保存任何截图（`.png`、`.jpg`、`.webp`、`.webm`）、压缩包（`.zip`、`.tar.gz`）或临时日志（`.log`、`.tmp`）。
2. **正式 ZIP 唯一路径**：所有正式交付 ZIP（如 `Acceptance-<TASK_ID>.zip`）**MUST** 且只能保存在 `.artifacts/packages/`。

### 6.2 `docs/` 文档分类治理
1. 应用中心仓库（如 `AI-Engineering-Hub`）的 `docs/` 目录 **MUST** 仅保存以下 6 个标准子目录：
   - `01-架构设计`
   - `02-部署运维`
   - `03-开发规范`
   - `04-API契约`
   - `05-验收报告`
   - `06-交接手册`
2. **禁止跨库复制标准**：`AI-Engineering-Standards` 是平台规范的唯一事实源（Single Source of Truth），**MUST NOT** 将 Standards 规范文档复制到 `AI-Engineering-Hub/docs` 中。

---

## 7. 技术中立回滚规范 (Technology-Agnostic Rollback Contract)

### 7.1 回滚触发条件 (Rollback Triggers)
当发布过程中或发布后出现以下任一情形时，**MUST** 触发标准回滚流程：
1. `DEPLOY`、`RUNTIME_VERIFY` 或 `SMOKE_TEST` 阶段任一检查失败。
2. 五态 Commit 一致性校验失败（`LIVE_COMMIT != TAG_COMMIT`）。
3. 生产运行态存活/就绪探针连续失败或核心业务指标跌破安全阈值。

### 7.2 回滚执行与验证流程 (Rollback Procedure)
1. **定位回滚基线 (Last Known Good Tag)**：选择上一个通过生产验收的 Git Tag（`v<PREV_VERSION>`）及其在 `.artifacts/packages/` 中经 `SHA256` 校验匹配的发布制品包。
2. **恢复代码与构建元数据**：检出目标 Git Tag，执行 `scripts/release/build_metadata.py` 恢复对应版本的 `build_info.json` 与 `.build_commit`。
3. **技术中立重部署**：使用项目标准启动机制（原生进程、服务管理器或编排配置）重新加载目标版本应用，不依赖特定容器守护进程命令。
4. **回滚后强制验证**：重新执行 `DEPLOY`（运行时探针）、`RUNTIME_VERIFY`（确认 `LIVE_COMMIT == PREV_TAG_COMMIT`）与 `SMOKE_TEST`（最小业务验证），并将回滚记录写入 `.artifacts/evidence/`。
