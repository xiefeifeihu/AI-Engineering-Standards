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
4. **准入边界越权**：一个项目评测通过的模型被盲目套用到另一个安全或业务边界完全不同的项目。

本规范确立机器级（Machine-wide）的**共享推理资源架构（Shared Inference Resources）**，明确物理计算资源与业务项目治理边界的解耦标准。

---

## 2. 核心对象与三层拓扑定义 (Core Abstractions)

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. Canonical Model (逻辑规范模型)                            │
│    例: qwen3.6-plus, gemini-3-flash, ai-kb-chat:4b          │
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

### 2.2 Provider (提供方类型)
- **定义**：模型服务的通信协议与底层系统类型抽象。
- **标准枚举**：
  - `ollama`：本地 Ollama 模型服务协议（`/api/tags`, `/api/chat` 等）。
  - `cpa`：Channel Proxy Agent (CPA) 代理协议（OpenAI 兼容 `/v1/models`, `/v1/chat/completions`）。
  - `openai-compatible`：通用 OpenAI 兼容服务端点。

### 2.3 Provider Instance (物理节点实例)
- **定义**：具体的部署实体、物理接入端点与网络通道组合。
- **示例**：
  - `ollama-local`：宿主机端口 `127.0.0.1:11434`，本地直接通信。
  - `cpa-local`：宿主机端口 `127.0.0.1:8317`，本地直连或通过宿主代理。
  - `cpa-cloud`：宿主机端口 `127.0.0.1:18317`，通过本地 SSH 隧道转发至海外 VPS `127.0.0.1:8317`。

### 2.4 Model Offering (提供方能力包)
- **定义**：提供方在具体节点上提供的特定模型能力抽象，包含提供方家族标识（Family）与特定能力集（Capabilities: `text`, `vision`, `structured_json`）。
- **格式**：`<provider_family>:<model_identifier>`（如 `bailian:qwen3.6-plus`, `gemini:gemini-3-flash`）。

### 2.5 Canonical Model (逻辑规范模型标识)
- **定义**：系统内部统一认知的标准模型名称，屏蔽底层物理部署与渠道映射差异。
- **职责**：在各业务项目的路由引擎与评测记录中充当主键。

---

## 3. 健康语义严格区分 (Three-Tier Health Semantics)

智能体与监控系统必须严格区分以下三种健康维度，**严禁混为一谈**：

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. Resource Health (资源传输健康度)                           │
│    - 物理端口是否监听 (TCP 11434/8317/18317)                 │
│    - HTTP 端点是否返回 (HTTP 200)                            │
│    - 传输平均时延 EMA 与熔断保护状态                         │
└──────────────────────────────┬──────────────────────────────┘
                               │ contains
┌──────────────────────────────▼──────────────────────────────┐
│ 2. Offering Health (能力包与模型健康度)                       │
│    - 该节点当前是否广播该模型 (Advertised in catalog)        │
│    - API Key / Bearer Token 认证是否 PASS                    │
│    - 模型是否存在、是否具备任务所需能力 (Text/Vision/JSON)   │
└──────────────────────────────┬──────────────────────────────┘
                               │ relies on
┌──────────────────────────────▼──────────────────────────────┐
│ 3. Network Health (底层网络健康度)                           │
│    - 宿主机 / WSL / Docker 网桥互通性                       │
│    - Docker Egress Gateway 出站连通性                       │
│    - 外部 DNS 解析与公网传输路由                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 语义区别与处置原则
1. **Resource Healthy ≠ All Offerings Available**：
   - 节点的 HTTP ping 返回 200 仅代表该物理网关正常；若调用某特定模型返回 `Missing API key` 或 `Model not found`，属于 **Offering Health** 故障，不得将节点置为网络离线。
2. **Network Healthy ≠ Cloud Tunnel Active**：
   - 本地 Docker Egress Gateway 出站正常仅代表底层网络连通；若 SSH 端口 18317 未启动，属于 **Resource Offline**（隧道按需未启动），不得误判为网络基础设施故障。
3. **Offering Failure ≠ Network Collapse**：
   - 某海外模型因上游欠费或 API 限制返回 429/401，属于 **Offering Health** 异常；路由引擎应触发该任务的模型退避降级，严禁盲目重启网络或重建容器。

---

## 4. 资源共享与项目独立准入边界 (Project Isolation & Governance)

```text
[ 共享物理计算层 (Machine-Wide Shared Tier) ]
  ├── 共享物理节点: ollama-local (11434), cpa-local (8317), cpa-cloud (18317)
  ├── 共享通信通道: 本地 Loopback, SSH 隧道, Docker Egress Gateway
  └── 共享凭据存储: 本地受保护存储 (D:\AI-KB\LocalConfig 等)
                           │
       ┌───────────────────┴───────────────────┐
       ▼                                       ▼
[ AI-KB 业务空间 ]                       [ VTIP / 其他工程空间 ]
  ├── 独立 Project Resource Profile        ├── 独立 Project Resource Profile
  ├── 独立 production_approved 准入        ├── 独立 production_approved 准入
  ├── 独立 Task Profile Champions          ├── 独立 Task Profile Champions
  ├── 独立 数据敏感分级与降级策略          ├── 独立 数据敏感分级与降级策略
  └── 独立 评测历史与配额控制              └── 独立 评测历史与配额控制
```

### 4.1 共享范围
- **物理端口与端点地址**：所有项目统一复用已分配好的本地端口（11434、8317、18317 等），严禁随意拉起冲突实例。
- **底层管理脚本与通道工具**：如 `cloud-cpa-tunnel.cmd` 等运维脚本全机共享。

### 4.2 项目隔离硬约束 (Strict Project Isolation)
1. **`production_approved` 严禁跨项目继承**：
   - 一个模型在 AI-KB 获得生产准入（如 `ai-kb-chat:4b`），**绝不代表**其自动在 VTIP 或其他工程获得准入。每个工程必须基于自身的数据安全等级和任务评测独立裁定。
2. **Task Profile Champions 必须专属化**：
   - 各工程的业务目标不同（如知识沉淀 vs 代码生成 vs 工业视觉），每个工程必须维护自身的 `PROJECT-AI-RESOURCE-PROFILE.md`，定义专属的任务冠军模型与退避链。
3. **敏感度与配额策略隔离**：
   - 数据脱敏要求、公网 API 允许策略（`allow`/`disallow`）与单次调用 Token 上限由各工程独立实施。

---

## 5. 动态模型发现与生命周期规范 (Dynamic Lifecycle Specification)

1. **禁止静态硬编码**：
   - 各项目的逻辑配置与代码中严禁将节点上的模型列表写死为 Canonical 事实。
2. **动态探测与同步 (Discovery Contract)**：
   - 通过端点开放接口（Ollama: `GET /api/tags`，CPA: `GET /v1/models`）进行有界超时探测（<= 5s）。
3. **消失模型历史保留 (History Preservation)**：
   - 节点失联或模型下线时，系统应置该模型在该节点的状态为 `available_now=false` 并记录 `retired_at`，**严禁物理删除该模型的历史评测指标、基准分数与准入审计记录**。
4. **重新上线平滑恢复 (Restoration)**：
   - 节点恢复广播该模型时，置 `available_now=true`，清空退休时间，无缝恢复路由候选资格。
