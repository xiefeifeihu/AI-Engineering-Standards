# STD-003: Endpoint Registry Standard (端点注册与拓扑映射规范)

```text
STANDARD_ID=STD-003
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=跨宿主机、WSL 与 Docker 容器网络的所有网络访问端点
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
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

系统网络端点 **MUST** 严格区分以下四类概念，**MUST NOT** 混为一谈：
1. **Host Endpoint (宿主端点)**：
   Windows 宿主机 Loopback 环境下的访问地址，例如 `http://127.0.0.1:18117`。
2. **Docker Endpoint (容器端点)**：
   容器内部互联网络或 Docker 网桥内部的访问地址，例如 `http://cpa-local:8317` 或 `http://ai-kb-ragflow:80`。
3. **Remote Endpoint (远端端点)**：
   通过加密隧道转发出站或海外 VPS 的受控访问端点，例如 `127.0.0.1:18317` 转发至海外回环。
4. **Console URL (人类控制台链接)**：
   供人类工程师在浏览器中直接打开的 Web 管理界面地址，例如 `http://127.0.0.1:18117/management.html`。

---

## 2. 核心红线约束

1. **禁止假设 Host Port == Container Port**：
   例如 `local-cpa` 资源在宿主机监听端口为 `18117`，在 Docker 网络内端口为 `8317`。自动化工具与消费代码 **MUST** 依据调用者运行时身份（宿主 vs 容器）精确选用对应端点，绝不能盲目假定端口相同。
2. **纯 API 资源严禁虚构 Console URL**：
   对于 Ollama、MySQL、Redis 等纯 API/TCP 资源，`console_url` **MUST** 为空，UI 界面应呈现“复制连接串/API端点”，**MUST NOT** 伪造虚假的 Web 访问按钮。
