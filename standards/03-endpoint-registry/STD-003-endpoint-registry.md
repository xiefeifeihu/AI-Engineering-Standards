# STD-003: Endpoint Registry Standard (端点注册与拓扑映射规范)

```text
STANDARD_ID=STD-003
VERSION=1.1.2
STATUS=ACTIVE
SCOPE=跨宿主机、WSL 与 Docker 容器网络的所有网络访问端点与拓扑解析
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-24
SCHEMA_REF=schemas/endpoint.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 端点分层与定义

系统网络端点 **MUST** 严格区分以下拓扑形态，**MUST NOT** 混为一谈：
1. **HOST_ENDPOINT (宿主管理端点)**：
   Windows 宿主机 / WSL 本地 Loopback 环境下的专用访问地址，例如 Hub 门户 `http://127.0.0.1:80`、Local CPA `http://127.0.0.1:18117`。
   - 约束：**MUST** 保持 Loopback-only，**MUST NOT** 暴露于物理 LAN。
2. **DOCKER_ENDPOINT (容器消费端点)**：
   普通 Docker Bridge 容器内部访问的专属端点，例如 Hub 容器入口 `http://host.docker.internal:18000`、CPA 容器入口 `http://cpa-local:8317`。
   - 约束：由专用 Docker Ingress 或容器内部网络提供，**MUST** 支持标准 bridge container 访问，且 **MUST NOT** 监听物理 LAN (0.0.0.0)。
3. **REMOTE_ENDPOINT (远端隧道端点)**：
   通过加密 SSH/WireGuard 隧道按需转发出站的受控端点，例如 `http://127.0.0.1:18317` 动态映射至海外推理节点。
4. **CONSOLE_URL (人类控制台链接)**：
   供人类工程师在浏览器中直接打开的 Web 管理界面地址，例如 `http://127.0.0.1:80`、`http://127.0.0.1:18117/management.html`。纯 API 资源此项必须为空。

---

## 2. 规范路径与运行时画像 (Canonical Paths & Runtime Profiles)

1. **规范路径与 Base URL 解耦**：
   规范契约定义的是资源的标准 **PATH**，而不是将 `127.0.0.1` 永久等价为规范端点。
   - **Canonical Health Path**: `/health`
   - **Canonical Model Select Path**: `/api/model/select`
   - **Canonical Feedback Path**: `/api/model/feedback`
2. **Runtime Profiles (运行时画像)**：
   Endpoint Registry 返回的对象 **MUST** 包含 `runtime_profiles`，使不同运行环境的 Consumer 自动识别专属 Base URL：
   ```json
   {
     "resource_id": "ai-engineering-hub",
     "host_endpoint": "http://127.0.0.1:80",
     "docker_endpoint": "http://host.docker.internal:18000",
     "canonical_paths": {
       "health": "/health",
       "model_select": "/api/model/select",
       "model_feedback": "/api/model/feedback"
     },
     "runtime_profiles": {
       "host": {
         "endpoint": "http://127.0.0.1:80",
         "network_type": "host",
         "dns_name": "127.0.0.1"
       },
       "docker": {
         "endpoint": "http://host.docker.internal:18000",
         "network_type": "bridge",
         "dns_name": "host.docker.internal"
       }
     }
   }
   ```

---

## 3. 核心红线约束

1. **禁止 Docker Consumer 假设 127.0.0.1 是宿主地址**：
   运行在普通 Docker Bridge 容器内的应用消费端，**MUST NOT** 尝试连接 `http://127.0.0.1:80`，否则将直接连接容器自身回环导致 Connection Refused。Docker Consumer **MUST** 优先选用 `docker_endpoint`。
2. **禁止为了容器连通而直接改写 Host 监听为 0.0.0.0**：
   严禁将宿主机回环服务无保护绑定至 `0.0.0.0`。跨环境连通必须通过 Docker Gateway 独立 Ingress 或受控网络转发实现。
3. **禁止假设 Host Port == Container Port**：
   自动化工具与消费代码 **MUST** 依据调用者运行时身份精确选用对应端点，绝不能盲目假定端口相同。
