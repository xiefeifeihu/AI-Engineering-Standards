# AI-Hub 资源注册规范 (AI-Hub Resource Registry Specification)

```text
SPEC_VERSION=V1.0
SPEC_CODE=SPEC-AI-HUB-RESOURCE-REGISTRY-V1
STATUS=ACTIVE
APPLIES_TO=AI Engineering Hub 及受管 AI 推理服务、基础存储与依赖组件
```

---

## 1. 背景与资源范畴

AI-Hub 资源中心承担底层 AI 计算资源、数据存储与依赖组件的统一注册、感知与受控协调职能。资源分为三大范畴：

1. **AI 推理与代理服务 (AI Inference Services)**：
   - `cpa-cloud`: 云端模型中继隧道（按需、可选开启）；
   - `cpa-local`: 本机模型代理网关；
   - `ollama`: 本机私有大模型推理引擎。
2. **基础数据与存储基础设施 (Data & Storage Infrastructure)**：
   - `mysql`: 关系型数据存储（AI-KB / RAGFlow 元数据）；
   - `elasticsearch`: 向量与全文混合检索引擎；
   - `minio`: S3 兼容对象存储中心；
   - `redis`: 快速高频状态与会话缓存。
3. **应用依赖服务 (Application Dependencies)**：
   - `ragflow-backend`: RAGFlow 容器运行实例；
   - `vtip-sidecar-service`: 专用扩展服务守护进程；
   - Docker 运行时与宿主桥接网关。

---

## 2. Resource Entity (资源实体数据模型)

所有受管资源在注册表中表达为标准化的 `Resource Entity`：

| 字段名 | 类型 | 必填 | 说明 | 示例 |
| :--- | :--- | :---: | :--- | :--- |
| `resource_id` | `string` | 是 | 资源唯一标识符 | `cpa-cloud`, `ollama`, `minio` |
| `name` | `string` | 是 | 资源人类可读名称 | `MinIO 对象存储` |
| `type` | `string` | 是 | 资源大类 | `ai_inference`, `infrastructure`, `app_dependency` |
| `owner` | `string` | 是 | 责任主体或所属工程 | `ai-kb-infra`, `sensha-cloud`, `machine-local` |
| `endpoint` | `string` | 是 | 宿主访问端点 (Host Endpoint) | `http://127.0.0.1:8317`, `127.0.0.1:3306` |
| `container_endpoint` | `string` | 否 | 容器内网络端点 | `cpa-local:8317`, `ragflow-mysql:3306` |
| `console_url` | `string` | 否 | Web 控制台管理页面直达链接 | `http://127.0.0.1:8317/management.html` |
| `health_check` | `object` | 是 | 健康探测契约（见健康规范） | `{"type": "http", "endpoint": "..."}` |
| `capabilities` | `array` | 否 | 声明的能力特征列表 | `["chat", "code", "embedding"]`, `["blob_storage"]` |
| `actions` | `array` | 否 | 白名单运维受控动作列表 | `["start", "stop", "restart", "test", "status"]` |
| `credential_status` | `string` | 是 | 凭据检测状态 (Zero Secret) | `CONFIGURED`, `MISSING`, `NONE` |

---

## 3. 控制台入口治理原则 (Console vs. API Entrance)

不同类型的资源具备不同的交互入口形式，严禁违背客观现实伪造虚假控制台：

1. **具备 Web 管理页面的资源 (Show Web Console)**：
   - 例如 CPA Local / CPA Cloud 具备管理控制台：`management.html`；
   - MinIO 具备专用 Web UI 控制台：`http://127.0.0.1:9001`；
   - 治理行为：界面提供明晰的 **“打开控制台”** 按钮，支持一键新标签打开。
2. **纯 API 或后台数据服务 (Show API / Connection String)**：
   - 例如 Ollama 提供 HTTP API (`http://127.0.0.1:11434`)，本身不存在管理控制台；
   - MySQL / Redis 仅提供 TCP 监听端口，无原生独立 Web 界面；
   - 治理行为：**严禁假设或虚构控制台**，界面显式标定为 **“API 入口”** 或 **“复制连接串”**，提供快速连通性验证。

---

## 4. 资源注册配置文件示例 (`config/resource-registry.yaml`)

```yaml
version: "1.0"
resources:
  # AI 推理服务
  - resource_id: "cpa-cloud"
    name: "CPA Cloud (云端模型中继)"
    type: "ai_inference"
    owner: "ai-kb-infra"
    endpoint: "http://127.0.0.1:18318"
    container_endpoint: "host.docker.internal:18318"
    console_url: "http://127.0.0.1:18317/management.html"
    health_check:
      type: "file_snapshot"
      path: "D:/AI-KB/Repo/ai-kb-infra/logs/cloud_tunnel_status.json"
      optional: true
    capabilities: ["chat", "code", "reasoning", "multi_model"]
    actions: ["start", "stop", "restart", "test", "status"]
    credential_status: "CONFIGURED"

  - resource_id: "cpa-local"
    name: "Local CPA (本机模型代理)"
    type: "ai_inference"
    owner: "sensha-cloud"
    endpoint: "http://127.0.0.1:8317"
    container_endpoint: "cpa-local:8317"
    console_url: "http://127.0.0.1:8317/management.html"
    health_check:
      type: "http"
      endpoint: "http://127.0.0.1:8317/v1/models"
    capabilities: ["chat", "embedding", "code"]
    actions: ["status", "test"]
    credential_status: "NONE"

  - resource_id: "ollama"
    name: "Ollama (本地私有算力)"
    type: "ai_inference"
    owner: "machine-local"
    endpoint: "http://127.0.0.1:11434"
    container_endpoint: "ollama:11434"
    console_url: "" # 纯 API 服务，不提供控制台
    health_check:
      type: "http"
      endpoint: "http://127.0.0.1:11434/api/tags"
    capabilities: ["chat", "embedding", "offline", "qwen", "deepseek"]
    actions: ["status", "test"]
    credential_status: "NONE"

  # 基础设施服务
  - resource_id: "mysql"
    name: "MySQL 关系型数据库"
    type: "infrastructure"
    owner: "ai-kb-infra"
    endpoint: "127.0.0.1:3306"
    container_endpoint: "ai-kb-ragflow-mysql-1:3306"
    console_url: "" # 纯 TCP 数据存储
    health_check:
      type: "tcp"
      port: 3306
    capabilities: ["relational_storage", "acid", "metadata"]
    actions: []
    credential_status: "CONFIGURED"

  - resource_id: "elasticsearch"
    name: "Elasticsearch 检索引擎"
    type: "infrastructure"
    owner: "ai-kb-infra"
    endpoint: "http://127.0.0.1:1200"
    container_endpoint: "ai-kb-ragflow-es01-1:9200"
    console_url: ""
    health_check:
      type: "http"
      endpoint: "http://127.0.0.1:1200/"
    capabilities: ["vector_search", "fulltext_search", "hybrid_search"]
    actions: []
    credential_status: "CONFIGURED"

  - resource_id: "minio"
    name: "MinIO 对象存储中心"
    type: "infrastructure"
    owner: "ai-kb-infra"
    endpoint: "http://127.0.0.1:9000"
    container_endpoint: "ai-kb-ragflow-minio-1:9000"
    console_url: "http://127.0.0.1:9001" # MinIO 具备原生 Web 控制台
    health_check:
      type: "docker_status"
      container_name: "ai-kb-ragflow-minio-1"
    capabilities: ["blob_storage", "s3_compatible", "document_chunks"]
    actions: []
    credential_status: "CONFIGURED"

  - resource_id: "redis"
    name: "Redis 高速缓存"
    type: "infrastructure"
    owner: "ai-kb-infra"
    endpoint: "127.0.0.1:6379"
    container_endpoint: "ai-kb-ragflow-redis-1:6379"
    console_url: ""
    health_check:
      type: "tcp"
      port: 6379
    capabilities: ["key_value_cache", "pubsub", "session_state"]
    actions: []
    credential_status: "CONFIGURED"
```
