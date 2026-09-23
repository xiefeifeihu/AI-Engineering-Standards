# STD-012: Windows / WSL / Docker Runtime Boundary (多环境运行时边界规范)

```text
STANDARD_ID=STD-012
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=跨 Windows 宿主、WSL2 子系统与 Docker 桥接网络的开发与运行环境
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
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
   负责原生 IDE、用户浏览器交互、原生 CLI 命令执行，以及通过 `127.0.0.1:80` 访问 Hub。
2. **WSL2 (Linux 子系统)**：
   运行 Docker 守护进程及 Linux 原生构建工具。
3. **Docker Bridge (容器网络)**：
   运行 RAGFlow、Elasticsearch、MySQL、Redis、Local CPA 及 AI-Hub 容器。

---

## 2. 访问规则与安全边界

- 宿主访问容器服务：必须通过容器映射至宿主回环的端口（如 `18117`）；
- 容器访问宿主服务：通过 `host.docker.internal:<PORT>` 访问；
- 容器之间相互访问：通过 Docker Compose 自定义网络内部服务名与内部端口访问（如 `cpa-local:8317`）；
- 所有对外暴露的 HTTP 接口默认仅绑定 `127.0.0.1`，严禁无认证暴露于 `0.0.0.0` 公网接口。
