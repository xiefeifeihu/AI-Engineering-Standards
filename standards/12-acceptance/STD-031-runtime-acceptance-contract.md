# STD-031: Runtime Acceptance Contract (运行时验收契约规范)

```text
STANDARD_ID=STD-031
VERSION=2.2.0
STATUS=ACTIVE
SCOPE=跨项目生产级运行时验收契约 (AI-Hub, AI-KB, Sidecar, VTIP)、统一生命周期阶段 (SOURCE, BUILD, PACKAGE, DEPLOY, RUNTIME_VERIFY, SMOKE_TEST, PRODUCTION_READY)、技术中立性探针 (严禁绑定Docker)、统一验收报文与组件故障隔离
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-12
RELATED_STANDARDS=STD-001, STD-005, STD-012, STD-014, STD-015, STD-017, STD-030
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 规范目标与背景 (Purpose & Background)

随着 AI 平台生态由单一 Hub 扩展为覆盖控制中心 (AI-Hub)、知识库服务 (AI-KB)、智能体边车 (vtip-ai-sidecar) 和业务平台编目 (vtip-platform-catalog) 的多服务架构，必须建立统一、确定性、高可靠的生产级工程验收规范。

传统依赖环境特异性容器命令（如直接绑定 Docker 守护进程）或非标准脚本的做法，导致跨环境（Windows 原生、WSL2、Linux 裸金属服务器及容器化基础设施）运行时校验脆弱。本规范定义技术中立的 **运行时验收契约 (Runtime Acceptance Contract)**。

---

## 2. 统一生命周期阶段 (Unified Lifecycle Stages)

各被管系统在构建、发布与交付流水线中 **MUST** 遵循且支持以下 7 个标准生命周期阶段，并在每个阶段执行严格的验证检查：

```
SOURCE ──► BUILD ──► PACKAGE ──► DEPLOY ──► RUNTIME_VERIFY ──► SMOKE_TEST ──► PRODUCTION_READY
```

1. **SOURCE (源码就绪态)**:
   - 源码仓库分支合法性、未提交状态检查。
   - 零凭据扫描 (Secret Scan)：严禁源码与配置文件中包含明文 Token、私钥或未加密凭据。
   - 依赖文件清单 (requirements.txt / pyproject.toml / package.json) 完整性。

2. **BUILD (构建与编译态)**:
   - 语言运行时与基础环境检查 (Python >= 3.10 / Node.js 等)。
   - 构建元数据必须固化 (Build Metadata Generation)：生成并持久化 `version`、`git_commit`、`build_time`。
   - 单元测试 (Unit Tests) 必须 100% 通过。

3. **PACKAGE (制品打包态)**:
   - 制品包 (Tarball / Wheel / Zip) 格式及归档结构验证。
   - 制品校验和生成：必须计算并记录 `PACKAGE_SHA256`。
   - 制品清单验证与版本对齐。

4. **DEPLOY (部署与端口绑定态)**:
   - 目标服务监听端口绑定确认 (TCP Socket Probe)。
   - 进程与基础存储挂载就绪 (SQLite / 配置文件等)。
   - 必须通过技术中立的套接字探测，**MUST NOT** 依赖容器守护进程状态。

5. **RUNTIME_VERIFY (运行时探针态)**:
   - 存活探针 (Liveness Probe)：校验 `/health` 或 `/healthz` HTTP 状态码为 200。
   - 就绪探针 (Readiness Probe)：校验关键子系统（数据库、存储、内存路由）就绪。
   - 运行时身份三元组一致性校验 (`SOURCE_COMMIT`, `BUILD_COMMIT`, `LIVE_COMMIT`)。

6. **SMOKE_TEST (业务冒烟测试态)**:
   - 核心业务链路真实只读冒烟验证。
   - AI-Hub：模型路由决策与调用流水通道验证。
   - AI-KB：RAG 检索只读问答与向量可用性验证（严禁修改或删除 Dataset）。
   - Sidecar：端到端日报润色 / 语义对齐与事实防腐 (Fact Guard) 校验。
   - VTIP：每日例会只读预览与组织架构协同探针。

7. **PRODUCTION_READY (生产就绪终态)**:
   - 汇总并判定所有前置阶段结果：`checks_fail == 0`。
   - `runtime_acceptance` 判定为 `true`。
   - 生成权威验收报告与证据凭证。

---

## 3. 技术中立性约束 (Technology-Agnostic Invariants)

### 3.1 严禁强绑定 Docker (Strict Prohibition of Docker Daemon Binding)
1. 验收契约执行器 **MUST NOT** 强依赖 Docker 守护进程 (`/var/run/docker.sock`, `\\.\pipe\docker_engine`)。
2. 验收契约探针 **MUST NOT** 使用 `docker ps`、`docker inspect`、`docker exec` 作为服务存活或就绪的唯一判据。
3. 存活性与就绪性验证 **MUST** 采用标准 TCP Socket 探测 (`socket.create_connection`) 与 HTTP REST 接口探测 (`urllib.request` / `requests`)。
4. 保证在 Windows 原生命令行、WSL2 子系统、Linux 裸金属服务器与 Docker/K8s 容器中均可无缝执行。

---

## 4. 跨项目支持契约 (Cross-Project Support Matrix)

本契约强制支持并覆盖以下四大核心工程组件：

| 组件标识 | 服务名称 | 默认标准端口 | 存活性端点 | 核心冒烟职责 |
|---|---|---|---|---|
| `Hub` / `AI-Hub` | AI-Engineering-Hub | 80 / 8080 | `/health` / `/api/runtime/health` | 任务路由匹配、全量模型调度、多模态治理 |
| `AI-KB` | AI-KB (aikb-control-center) | 18090 | `/api/health` | RAGFlow 连通性、向量检索引擎只读冒烟 |
| `Sidecar` | vtip-ai-sidecar | 8799 | `/health` | 日报润色建议、Fact Guard 事实核验 |
| `VTIP` | vtip-platform-catalog | 8787 | `/healthz` | 例会规划计算、Confluence 只读协同 |

---

## 5. 统一验收返回报文规范 (Unified Return Payload Schema)

所有组件的运行时验收接口与执行器 **MUST** 输出符合以下 JSON 契约的统一数据结构：

```json
{
  "runtime_acceptance": true,
  "service": "AI-Hub",
  "version": "v0.20.0",
  "commit": "a45b0fa",
  "build_commit": "a45b0fa",
  "stage": "PRODUCTION_READY",
  "checks_total": 12,
  "checks_pass": 12,
  "checks_fail": 0,
  "failed_components": [],
  "runtime_identity": {
    "source_commit": "a45b0fa",
    "build_commit": "a45b0fa",
    "live_commit": "a45b0fa",
    "platform": "Windows-11",
    "python_version": "3.10.11",
    "technology_stack": "TECHNOLOGY_AGNOSTIC",
    "docker_bound": false
  },
  "checks": [
    {
      "name": "hub_python_runtime",
      "stage": "BUILD",
      "passed": true,
      "detail": "Python version: 3.10.11"
    }
  ],
  "timestamp": "2026-10-12T06:00:00Z"
}
```

### 5.1 必填根级字段 (Mandatory Root Fields)
- `runtime_acceptance` (boolean): 总体验收判定，必须为 `true` 或 `false`。
- `service` (string): 被验收服务名称 (`AI-Hub` | `AI-KB` | `Sidecar` | `VTIP`)。
- `version` (string): 规范版本号。
- `commit` (string): 当前运行态或源码 Git Commit Hash (前 7 位或完整 40 位)。
- `build_commit` (string): 构建制品固化的 Git Commit Hash。
- `checks_total` (integer): 检查项总数 (>= 0)。
- `checks_pass` (integer): 通过检查项数量 (>= 0)。
- `checks_fail` (integer): 失败检查项数量 (>= 0)。
- `failed_components` (array of string): 发生失败的组件名称列表，无失败时必须为空数组 `[]`。
