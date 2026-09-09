# AI 工程共享推理资源规范 (Shared Inference Resource Specification)

```text
RESOURCE_SPEC_VERSION=V0.1
RESOURCE_SPEC_STATUS=PRE_RELEASE
FINAL_RELEASE_PENDING=true
```

## 1. 背景与核心价值

在本地多项目并行研发（如 AI-KB、VTIP、以及各类 Vibe Coding 智能体应用）中，大模型推理后端往往面临以下典型困境：
1. **端口与资源冲突**：多个项目重复拉起多个本地 Ollama 或 CPA 代理实例，相互争抢显存与固定端口；
2. **凭据与代理混乱**：各项目在代码库中各自存放 API Key、硬编码私有模型名，缺乏统一的物理节点与凭据治理；
3. **健康语义混淆**：把“网络不通”、“节点离线”、“模型鉴权失败”、“模型不存在”混为一谈，导致错误的故障处置与级联崩溃；
4. **准入边界越权**：一个项目评测通过的模型被盲目套用到另一个安全或业务边界完全不同的项目；
5. **无条件降级失控**：云端或远端模型故障时盲目回退到本地小模型，破坏多模态契约或违反数据安全策略。

本规范确立机器级（Machine-wide）的**共享推理资源架构（Shared Inference Resources）**，明确物理计算资源与业务项目治理边界的解耦标准。

---

## 2. 核心对象与三层拓扑定义 (Core Abstractions)

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. Canonical Model (逻辑规范模型)                            │
│    例: qwen3.6-plus, gemini-3-flash, custom-model:latest    │
└──────────────────────────────┬──────────────────────────────┘
                               │ maps to
┌──────────────────────────────▼──────────────────────────────┐
│ 2. Model Offering (提供方能力包)                             │
│    例: bailian:qwen3.6-plus, gemini:gemini-3-flash          │
└──────────────────────────────┬──────────────────────────────┘
                               │ deployed on
┌──────────────────────────────▼──────────────────────────────┐
│ 3. Provider Instance / Shared Resource (物理节点实例)        │
│    例: cpa-local (8317), cpa-cloud (18317), ollama-local     │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 Shared Resource (共享物理资源)
- **定义**：在宿主机级别长期运行或按需调度的物理/逻辑计算实体，提供大模型推理计算或中继网关能力。
- **特征**：单台开发机上唯一绑定特定的监听端口与通信协议，可被本地所有工程以 Client 身份并发共享访问。

### 2.2 Provider Type (提供方类型标准枚举)
- **定义**：模型服务的通信协议与底层系统类型抽象。
- **通用资源类型枚举**：
  - `ollama`：本地 Ollama 模型服务协议（原生 `/api/tags`, `/api/chat` 等）。
  - `cli_proxy_api`：CPA / CLIProxyAPI 代理网关协议（OpenAI 兼容 `/v1/models`, `/v1/chat/completions` 等）。
  - `direct_api`：服务商官方或公开 API 直连端点（OpenAI, DashScope, Anthropic 等）。
  - `openai-compatible`：其他通用 OpenAI 兼容服务端点。

### 2.3 Provider Instance (物理节点实例)
- **定义**：具体的部署实体、物理接入端点与网络通道组合。
- **开发机标准共享实例示例**：
  - `ollama-local`：宿主机端口 `127.0.0.1:11434`，类型 `ollama`，本地直接通信。
  - `cpa-local`：宿主机端口 `127.0.0.1:8317`，类型 `cli_proxy_api`，本地直连或通过宿主网关转发境内服务。
  - `cpa-cloud`：宿主机端口 `127.0.0.1:18317`，类型 `cli_proxy_api`，通过加密 SSH 隧道映射至海外云端回环 `127.0.0.1:8317`。

### 2.4 Model Offering (提供方能力包)
- **定义**：提供方在具体节点上提供的特定模型能力抽象，包含提供方家族标识（Family）与特定能力集（Capabilities: `text`, `vision`, `structured_json` 等）。
- **格式**：`<provider_family>:<model_identifier>`（如 `bailian:qwen3.6-plus`, `gemini:gemini-3-flash`）。

### 2.5 Canonical Model (逻辑规范模型标识)
- **定义**：系统内部统一认知的标准模型名称，屏蔽底层物理部署与渠道映射差异。
- **职责**：在各业务项目的路由引擎与评测记录中充当逻辑主键。

---

## 3. 端点分层与网络访问拓扑 (Endpoint Tiers & Container Access)

标准清晰划分两层访问端点，严禁将特定项目的容器网络拓扑当作通用事实：

### 3.1 宿主机可视化与测试端点 (Host Display Endpoint)
- **定位**：运行在 Windows 宿主机上的 CLI、浏览器、桌面工具与测试脚本直接访问的本地回环地址。
- **标准端口**：
  - `ollama-local`: `127.0.0.1:11434`
  - `cpa-local`: `127.0.0.1:8317`
  - `cpa-cloud`: `127.0.0.1:18317`

### 3.2 容器环境访问契约 (Container Runtime Access)
- **定位**：运行在 Docker 容器内部的应用访问宿主机共享推理资源的网络契约。
- **规范原则**：
  1. 容器访问宿主机服务必须经由项目配置的宿主网关，推荐使用 Docker 标准的 `host.docker.internal`（需配置 `extra_hosts: ["host.docker.internal:host-gateway"]`）或项目自定义的内部反向代理；
  2. **严禁在通用规范中固化特定容器别名**（如假定所有项目都能解析 `http://ollama:11434` 或 `http://cpa-local:8317`，这些仅是特定 Compose 内部的私有服务名）；
  3. **严禁硬编码动态网桥 IP**（如 `172.17.x.x` 或 `172.18.x.x`），网桥 IP 会随 WSL/Docker 网络重构动态改变，不是稳定契约。

---

## 4. 凭证抽象与安全解耦规范 (Credential Reference Contract)

为贯彻**绝对零密钥入库 (Zero Secrets in Git)** 原则，通用规范完全解耦具体项目的文件路径与凭据文件名。

### 4.1 通用凭据引用契约字段
任何项目声明对共享资源的接入凭据时，必须使用以下标准化引用格式：

```yaml
credential_ref_id: "<logical_reference_id>"   # 逻辑引用标识，如 "local_cpa_key"
credential_type: "api_key"                    # 枚举: api_key | bearer_token | basic_auth | none
injection_contract: "header"                  # 枚举: header (Authorization: Bearer) | env | query | none
secret_owner: "project_local_config"          # 枚举: project_local_config | secret_store | env_var
```

### 4.2 凭据安全红线
1. **禁止项目真实路径入库**：标准规范中严禁保留任何项目的私有绝对路径（如机器本地配置目录或特定 `.key` 文件名）；
2. **凭据所有权归项目自身**：各项目负责在自身宿主受保护目录（`LocalConfig/`、`.env.local` 等并列入 `.gitignore`）中存放真实凭据，或通过运行时环境变量注入；
3. **安全上屏规范**：任何日志、诊断输出或报告中，凭证内容必须强制脱敏（如 `sk-***`），绝不上屏。

---

## 5. 健康语义严格区分 (Three-Tier Health Semantics)

智能体与监控系统必须严格区分以下三种健康维度，**严禁混为一谈**：

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. Resource Health (资源传输健康度)                           │
│    - 物理端口是否监听 (TCP 11434/8317/18317)                 │
│    - HTTP 端点是否响应 (HTTP 200)                            │
│    - 传输平均时延与熔断保护状态                              │
└──────────────────────────────┬──────────────────────────────┘
                               │ contains
┌──────────────────────────────▼──────────────────────────────┐
│ 2. Offering Health (能力包与模型健康度)                       │
│    - 该节点当前是否广播该模型 (GET /api/tags 或 /v1/models)  │
│    - 凭据认证是否通过 (Auth PASS)                            │
│    - 模型是否存在、是否具备任务所需能力 (Text/Vision/JSON)   │
└──────────────────────────────┬──────────────────────────────┘
                               │ relies on
┌──────────────────────────────▼──────────────────────────────┐
│ 3. Network Health (底层网络健康度)                           │
│    - 宿主机 / WSL / Docker 网络通道与网关互通性              │
│    - Docker Egress Gateway 出站连通性                        │
│    - 外部 DNS 解析与公网传输路由                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.1 语义区别与处置原则
1. **Resource Healthy ≠ All Offerings Available**：
   - 节点的 HTTP ping 返回 200 仅代表该物理网关正常；若调用某特定模型返回 `Missing API key` 或 `Model not found`，属于 **Offering Health** 故障，不得将节点置为网络离线。
2. **Network Healthy ≠ Cloud Tunnel Active**：
   - 本地 Docker Egress Gateway 出站正常仅代表底层网络连通；若 SSH 端口 18317 未启动，属于 **Resource Offline**（隧道按需未启动），不得误判为网络基础设施故障。
3. **Offering Failure ≠ Network Collapse**：
   - 某海外模型因上游欠费或 API 限制返回 429/401，属于 **Offering Health** 异常；路由引擎应触发该任务的模型退避，严禁盲目重启网络或重建容器。

---

## 6. 动态模型发现与不可用处理契约 (Discovery & Degradation Contract)

### 6.1 运行时动态发现契约
1. **禁止静态硬编码**：共享资源上可用的模型列表属于动态运行时事实（通过 `GET /api/tags` 或 `GET /v1/models` 获取），标准文档与项目静态配置中严禁将特定模型列表固化为不可变事实；
2. **下线模型历史保留 (History Preservation)**：当物理节点下线或上游模型撤销时，系统应置该模型状态为 `available_now=false` 并记录退役时间，**严禁物理删除历史评测分数、基准数据与审计记录**；
3. **重新上线平滑恢复 (Restoration)**：节点恢复广播该模型时，重新置 `available_now=true`，无缝恢复候选资格。

### 6.2 状态传播与降级退避契约 (Degraded / Unavailable Propagation)
- **标准职责边界**：本标准仅定义资源与模型的 `Healthy`、`Degraded`、`Unavailable` 状态发现与事件广播协议，**绝不越权决定具体业务的降级处置**；
- **严禁无条件本地 Fallback**：
  - 当云端/远端模型不可用时，**严禁系统未经策略检查盲目回退到本地模型**；
  - 降级必须由各项目自身的调度策略与安全等级裁定，且必须同时满足以下条件：
    1. **项目策略允许**：当前业务流程明确允许 Fallback；
    2. **数据敏感度合规**：目标节点与模型的安全级别符合数据分级要求；
    3. **生产准入有效**：备选模型在当前项目中拥有有效的生产审批（`production_approved=true`）；
    4. **能力契约匹配**：备选模型必须具备任务所需的必要能力（如多模态视觉解析任务，若备选模型无 Vision 能力，必须**阻断并返回 `capability_unavailable`**，绝不允许静默回退到纯文本模型导致数据截断丢失）。

---

## 7. 资源共享与项目独立准入边界 (Project Isolation & Governance)

```text
[ 机器级共享物理计算层 (Machine-Wide Shared Tier) ]
  ├── 共享物理节点: ollama-local (11434), cpa-local (8317), cpa-cloud (18317)
  ├── 共享通信通道: 本地 Loopback, SSH 隧道, Docker Egress Gateway
  └── 隔离凭据规范: 各项目在受保护存储中独立维护凭据引用
                           │
       ┌───────────────────┴───────────────────┐
       ▼                                       ▼
[ 项目 A 业务空间 (如 AI-KB) ]           [ 项目 B 业务空间 (如 VTIP) ]
  ├── 专属 Project Resource Profile       ├── 专属 Project Resource Profile
  ├── 独立 production_approved 准入       ├── 独立 production_approved 准入
  ├── 专属 Task Champions 矩阵            ├── 专属 Task Champions 矩阵
  ├── 专属 数据敏感分级与降级策略         ├── 专属 数据敏感分级与降级策略
  └── 专属 评测记录与配额管理             └── 专属 评测记录与配额管理
```

### 7.1 项目隔离硬约束 (Strict Project Isolation)
1. **`production_approved` 严禁跨项目继承**：
   - 某模型在一个项目评测通过并获生产准入，**绝不代表**其自动在其他项目获得准入。每个工程必须基于自身的数据安全等级和任务场景独立审批；
2. **Task Champions 必须专属化**：
   - 各工程的业务目标不同（如知识沉淀 vs 代码生成 vs 工业数据目录），各项目依据自身的 `PROJECT-AI-RESOURCE-PROFILE.md` 独立维护任务冠军与退避链；
3. **数据敏感度与配额策略隔离**：
   - 数据脱敏要求、公网 API 允许范围与 Token 消耗预算由各工程独立实施。

---

## 8. Cloud CPA 隧道工具职责与协作边界 (Cloud CPA Tunnel Ownership)

1. **工具资产归属与生命周期**：
   - Cloud CPA 隧道管理脚本（`cloud_cpa_tunnel.py` / `cloud-cpa-tunnel.cmd`）作为基础设施的一部分，由 **AI-KB 仓库统一持有与维护生命周期**；
2. **共享消费边界**：
   - 隧道在宿主机建立的本地转发端口（`127.0.0.1:18317`）作为“机器级共享推理资源”开放给开发机上所有工程复用；
   - 其他项目（如 VTIP、独立 Agent）作为纯消费者接入，直接通过 `127.0.0.1:18317`（宿主）或对应网关（容器）消费 `cpa-cloud` 资源，**无需也不得重复复制或实现私有隧道脚本**。
