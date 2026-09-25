# STD-012: Windows / WSL / Docker Runtime Boundary (多环境运行时边界规范)

```text
STANDARD_ID=STD-012
VERSION=1.1.3
STATUS=ACTIVE
SCOPE=跨 Windows 宿主、WSL2 子系统与 Docker 桥接网络的开发与运行环境
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-25
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 三层环境拓扑定义

1. **Windows Host (宿主环境)**：
   负责原生 IDE、用户浏览器交互、原生 CLI 命令执行、Windows Host Action Bridge (18777)。
2. **WSL2 (Linux 子系统)**：
   运行 Docker 守护进程及 Linux 原生构建工具，为 Hub 提供 host network namespace。
3. **Docker Bridge (容器网络)**：
   运行各业务系统容器（`vtip-ai-sidecar`, `ai-kb-control`, RAGFlow, Elasticsearch, MySQL, Redis, Local CPA）。

---

## 2. 访问规则与安全边界

1. **Hub 双端点拓扑隔离**：
   - **HOST_ENDPOINT (`http://127.0.0.1:80`)**：
     仅监听本地回环接口 `127.0.0.1`。供宿主 Windows、WSL 及浏览器管理使用。**严禁直接修改为 0.0.0.0**。
   - **DOCKER_ENDPOINT (`http://host.docker.internal:18000`)**：
     由 Hub 内置 Docker Ingress 提供，**严格仅绑定 Docker 网桥网关接口**（如 `172.17.0.1`, `172.18.0.1` 等 `docker0`, `br-*`）。
2. **物理 LAN 零暴露红线**：
   - Hub Docker Ingress **MUST NOT** 监听物理 LAN 接口（如 `192.168.10.x`）。
   - Client ACL 校验：仅允许来自 Docker bridge 子网（`172.16.0.0/12`）与 loopback 的连接，阻断任何外来流量。
3. **宿主资源直通保障**：
   Hub 必须保持 host 网络模式运行，以确保持续直接访问 Windows Host Action Bridge (18777)、Local CPA (18117)、Cloud CPA (18317)、Ollama (11434) 及基础设施存储，不得降级为普通 bridge 模式。
4. **容器访问宿主服务规范**：
   普通 bridge 容器通过 `host.docker.internal:<PORT>` 访问宿主/网桥暴露的服务（需配置 `extra_hosts: host.docker.internal:host-gateway`）。
   Owner 工程若需向外部 bridge 容器暴露宿主 Loopback 资源（如 Cloud CPA 18317），**MUST** 通过 Docker Gateway 专用中继（如 18318）并于 `engineering-manifest.yaml` 显式声明 `docker_consumer: http://host.docker.internal:18318`。
