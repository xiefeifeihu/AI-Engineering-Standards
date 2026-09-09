# AI 工程共享推理资源目录 (Shared Inference Resource Catalog)

> **标准约束**：
> 本目录登记当前开发机上经过工程验收、稳定可复用的推理资源物理端点与契约。
> **安全红线**：严禁在此登记任何明文 API Key、OAuth Token、Management Key、Refresh Token 或密码。仅记录物理网络端点、协议类型与动态发现契约。具体可用模型列表由各项目运行时动态探测获取，严禁硬编码。

---

## 1. 资源登记概览

| 资源标识 (resource_id) | 资源类型 | 作用域 (Scope) | 宿主端点 (Endpoint) | 鉴权模式 | 动态发现契约 | 运行定位 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`ollama-local`** | `ollama` | `machine-local` | `127.0.0.1:11434` | 无需凭据 (`none`) | `GET /api/tags` | 本地自建、离线私密、零外部网络依赖 |
| **`cpa-local`** | `cpa` | `machine-local` | `127.0.0.1:8317` | CPA Client API Key | `GET /v1/models` | 本地代理网关、国内模型直连低时延 |
| **`cpa-cloud`** | `cpa` | `hybrid-cloud` | `127.0.0.1:18317` | CPA Client API Key | `GET /v1/models` | 按需海外隧道、海外模型直连免代理损耗 |

---

## 2. 资源详细契约与配置规范

### 2.1 资源 A：`ollama-local`

```yaml
resource_id: ollama-local
type: ollama
scope: machine-local
host_display_endpoint: "127.0.0.1:11434"
container_internal_endpoint: "http://ollama:11434"
credential: none
model_discovery: "GET /api/tags"
health_check: "GET /api/tags"
```

- **架构与部署**：
  - 作为常驻本地容器或系统服务运行，挂载本地权重目录（如 `D:\AI-KB\Models\ollama`）。
- **运行特征**：
  - **Local & Offline Capable**：支持全离线运行，断网环境下依然稳定可用。
  - **Privacy Friendly**：高敏感度数据（代码、私密文档、密钥审计）无需出站。
  - **硬件相关性**：推理性能直接依赖本机硬件（如 RTX 5060 Laptop GPU 与本机 CPU）。
- **动态模型治理约定**：
  - 本地微调模型、通用小模型与视觉模型均由运行时从 `/api/tags` 实时拉取。
  - 不得在静态标准文档中硬编码具体模型版本为 Canonical 事实。

---

### 2.2 资源 B：`cpa-local`

```yaml
resource_id: cpa-local
type: cpa
scope: machine-local
host_display_endpoint: "127.0.0.1:8317"
container_internal_endpoint: "http://cpa-local:8317"
management_url: "http://127.0.0.1:8317/management.html"
credential_mode: "cpa_client_api_key"
credential_reference: "LocalConfig/cpa-client-api.key 或环境变量 CPA_API_KEY"
model_discovery: "GET /v1/models"
health_check: "GET /v1/models"
```

- **架构与部署**：
  - 本地 Channel Proxy Agent 容器实例，负责境内上游 API（如阿里百炼 CodingPlan）的直连中继与分发。
- **运行特征**：
  - **极低传输时延**：境内服务通过宿主机直连，无跨洋网络跳点与代理开销。
  - **多提供方聚合**：支持配置聚合阿里云百炼 (Bailian)、NVIDIA Offering 等国内或低延迟通道。
- **安全与凭证红线**：
  - 访问必须携带 `Authorization: Bearer <CPA_CLIENT_KEY>` 请求头。
  - 真实密钥仅从宿主机安全目录（`D:\AI-KB\LocalConfig`）或环境变量注入，**严禁提交入 Git**。
- **动态模型治理约定**：
  - 动态 Offering 列表通过 `GET /v1/models` 实时拉取，模型状态由上游通道健康度决定。

---

### 2.3 资源 C：`cpa-cloud`

```yaml
resource_id: cpa-cloud
type: cpa
scope: hybrid-cloud
host_display_endpoint: "127.0.0.1:18317"
transport: "SSH Local Port Forward (127.0.0.1:18317 -> VPS 127.0.0.1:8317 loopback)"
remote_cpa_security: "VPS 127.0.0.1 loopback only (严禁 VPS 公网暴露 8317)"
credential_mode: "cpa_client_api_key"
credential_reference: "LocalConfig/cpa-client-api.key 或环境变量 CPA_API_KEY"
model_discovery: "GET /v1/models"
health_check: "GET /v1/models"
cloud_tunnel_policy: "Optional / On-demand (按需开启)"
```

- **架构与部署**：
  - 云端部署：在海外 VPS 宿主机仅监听本地回环 `127.0.0.1:8317`，**严禁在公网防火墙开放 8317 端口**。
  - 本地传输：本地通过 Windows OpenSSH 后台进程创建加密隧道（`-L 127.0.0.1:18317:127.0.0.1:8317`）。
- **运行特征**：
  - **海外服务免代理直连**：用于调度 Google Gemini 等海外大模型，避免经过本地代理层产生二次抖动与证书截断。
  - **按需可选机制 (Optional)**：默认无需常驻，离线时本地业务平滑降级至 `ollama-local` 或 `cpa-local`。
- **标准 CLI 操作契约 (CLI Contract)**：
  - 所有支持该资源的工程统一通过标准命令进行生命周期管理：
    ```text
    cloud-cpa-tunnel.cmd start   # 启动 SSH 后台守护进程并进行有界自检
    cloud-cpa-tunnel.cmd stop    # 安全关闭 SSH 映射进程
    cloud-cpa-tunnel.cmd status  # 探测 TCP 端口与 HTTP 模型接口并输出状态
    cloud-cpa-tunnel.cmd test    # 执行 GET /v1/models 连通性测试
    cloud-cpa-tunnel.cmd open    # 浏览器打开管理端点
    ```
  - 隧道状态同步文件：`cloud_tunnel_status.json`，供容器化或跨进程服务读取快照。

---

## 3. 资源接入安全规范

1. **零密钥入库原则**：
   - 任何接入本目录资源的工程，代码与文档中只允许记录 `resource_id` 与 Endpoint 地址，凭证必须遵循外部安全注入规范。
2. **端口冲突禁止**：
   - 全机严禁任何第三方服务占用 `11434`, `8317`, `18317` 端口。
3. **动态发现强制**：
   - 所有调用端必须实现模型目录动态同步机制，并支持节点下线时保留本地评测历史。
