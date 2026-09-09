# AI 工程共享推理资源目录 (Shared Inference Resource Catalog)

> **标准约束**：
> 本目录登记当前开发机上经过工程验收、稳定可复用的推理资源物理端点与契约。
> **安全红线**：严禁在此登记任何明文 API Key、OAuth Token、Management Key、Refresh Token 或密码。仅记录物理网络端点、协议类型与动态发现契约。具体可用模型列表由各项目运行时动态探测获取，严禁硬编码。

---

## 1. 资源登记概览

| 资源标识 (resource_id) | 资源类型 | 作用域 (Scope) | 宿主端点 (Endpoint) | 鉴权模式 | 动态发现契约 | 运行定位 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`ollama-local`** | `ollama` | `machine-local` | `127.0.0.1:11434` | 无需凭据 (`none`) | `GET /api/tags` | 本地自建、离线私密、零外部网络依赖 |
| **`cpa-local`** | `cli_proxy_api` | `machine-local` | `127.0.0.1:8317` | Bearer Token / API Key | `GET /v1/models` | 本地代理网关、国内模型直连低时延 |
| **`cpa-cloud`** | `cli_proxy_api` | `hybrid-cloud` | `127.0.0.1:18317` | Bearer Token / API Key | `GET /v1/models` | 按需海外隧道、海外模型直连免代理损耗 |

---

## 2. 资源详细契约与配置规范

### 2.1 资源 A：`ollama-local`

```yaml
resource_id: ollama-local
type: ollama
scope: machine-local
host_display_endpoint: "127.0.0.1:11434"
container_access_mode: "host_gateway (例如 host.docker.internal:11434)"
credential_contract:
  credential_type: none
  injection_contract: none
model_discovery: "GET /api/tags"
health_check: "GET /api/tags"
```

- **架构与部署**：
  - 作为常驻本地容器或系统服务运行，挂载本地权重目录（由宿主机或管理服务统一部署维护）。
- **运行特征**：
  - **Local & Offline Capable**：支持全离线运行，断网环境下依然稳定可用。
  - **Privacy Friendly**：高敏感度数据（代码、私密文档、密钥审计）无需出站。
  - **硬件相关性**：推理性能直接依赖本机硬件算力。
- **动态模型治理约定**：
  - 本地微调模型、通用小模型与视觉模型均由运行时从 `/api/tags` 实时拉取。
  - 不得在静态标准文档中硬编码具体模型版本为 Canonical 事实。

---

### 2.2 资源 B：`cpa-local`

```yaml
resource_id: cpa-local
type: cli_proxy_api
scope: machine-local
host_display_endpoint: "127.0.0.1:8317"
container_access_mode: "host_gateway (例如 host.docker.internal:8317)"
management_url: "http://127.0.0.1:8317/management.html"
credential_contract:
  credential_ref_id: "local_cpa_key"
  credential_type: "api_key"
  injection_contract: "header"
  secret_owner: "project_local_config"
model_discovery: "GET /v1/models"
health_check: "GET /v1/models"
```

- **架构与部署**：
  - 本地 CPA / CLIProxyAPI 容器实例，负责境内上游 API（如阿里百炼 CodingPlan）的直连中继与分发。
- **运行特征**：
  - **极低传输时延**：境内服务通过宿主机直连，无跨洋网络跳点与代理开销。
  - **多提供方聚合**：支持配置聚合阿里云百炼 (Bailian)、NVIDIA Offering 等国内或低延迟通道。
- **安全与凭证红线**：
  - 访问必须携带 `Authorization: Bearer <TOKEN>` 请求头。
  - 真实密钥由各项目从自身宿主受保护目录（如各项目的 `LocalConfig/`、`.env.local`）或环境变量注入，**严禁提交入 Git**。
- **动态模型治理约定**：
  - 动态 Offering 列表通过 `GET /v1/models` 实时拉取，模型状态由上游通道健康度决定。

---

### 2.3 资源 C：`cpa-cloud`

```yaml
resource_id: cpa-cloud
type: cli_proxy_api
scope: hybrid-cloud
host_display_endpoint: "127.0.0.1:18317"
container_access_mode: "host_gateway (例如 host.docker.internal:18317)"
transport: "SSH Local Port Forward (127.0.0.1:18317 -> VPS 127.0.0.1:8317 loopback)"
remote_cpa_security: "VPS 127.0.0.1 loopback only (严禁 VPS 公网暴露 8317)"
credential_contract:
  credential_ref_id: "cloud_cpa_key"
  credential_type: "api_key"
  injection_contract: "header"
  secret_owner: "project_local_config"
model_discovery: "GET /v1/models"
health_check: "GET /v1/models"
cloud_tunnel_policy: "Optional / On-demand (按需开启)"
tool_owner: "ai-kb-infra (AI-KB 统一持有与维护隧道生命周期脚本)"
```

- **架构与部署**：
  - 云端部署：在海外 VPS 宿主机仅监听本地回环 `127.0.0.1:8317`，**严禁在公网防火墙开放 8317 端口**。
  - 本地传输：本地通过 Windows OpenSSH 后台进程创建加密隧道（`-L 127.0.0.1:18317:127.0.0.1:8317`）。
- **运行特征**：
  - **海外服务免代理直连**：用于调度 Google Gemini 等海外大模型，避免经过本地代理层产生二次抖动与证书截断。
  - **按需可选机制 (Optional)**：默认无需常驻，离线时本地业务依据自身安全策略平滑退避或阻断。
- **生命周期管理与协作边界**：
  - 隧道管理脚本由 **AI-KB** 项目持有维护（`scripts/tunnel/cloud-cpa-tunnel.cmd` 等）。
  - 其他项目（如 VTIP 等）仅作为消费者接入 `127.0.0.1:18317`（宿主）或宿主网关（容器），**无需重复实现隧道管理脚本**。

---

## 3. 资源接入安全规范

1. **零密钥入库原则**：
   - 任何接入本目录资源的工程，代码与文档中只允许记录 `resource_id` 与 Endpoint 地址，凭据必须遵循凭据引用契约由外部注入。
2. **端口冲突禁止**：
   - 全机严禁任何第三方服务占用 `11434`, `8317`, `18317` 端口。
3. **动态发现强制**：
   - 所有调用端必须实现模型目录动态同步机制，并支持节点下线时保留本地评测历史。

