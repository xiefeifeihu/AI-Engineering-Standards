# STD-011: Application Consumer Contract (应用消费契约与容灾规范)

```text
STANDARD_ID=STD-011
VERSION=1.1.2
STATUS=ACTIVE
SCOPE=AI-KB、VTIP-AI-SIDECAR、VTIP Platform 等所有下游消费系统
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-24
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 业务消费核心准则

1. **运行时画像端点选用原则 (Runtime Profile Selection)**：
   - **Host Process (宿主进程)**：Windows / WSL 本机 CLI、单元测试、测试脚本 **MUST** 使用 `host_endpoint`（如 `http://127.0.0.1:80`）。
   - **Docker Consumer (容器消费端)**：运行在普通 Docker Bridge 容器内的消费端（如 `vtip-ai-sidecar`, `ai-kb-control`）**MUST** 优先使用 `docker_endpoint`（如 `http://host.docker.internal:18000`）。
   - **严禁容器端使用宿主回环**：Docker 容器内部 **MUST NOT** 将 `127.0.0.1` 视作宿主机地址。
2. **规范路径与 Base URL 分离 (Canonical Paths Contract)**：
   下游 Consumer **MUST** 使用规范路由路径，不得假设特定 IP：
   - **Model Select Path**: `POST /api/model/select`
   - **Model Feedback Path**: `POST /api/model/feedback`
   - **Health Path**: `GET /health`
3. **禁止长期硬编码模型与端口**：
   业务工程代码中 **SHOULD NOT** 长期硬编码特定的单个模型名称（如 `gpt-4o`）或固定通道端口。业务层应向 Hub 声明业务意图，按 Hub 返回的候选方案链尝试。
4. **Hub 严禁成为业务生存单点 (No Single Point of Failure)**：
   Hub 是治理与协调中枢，并非业务生死存亡的唯一单点。
5. **双重兜底原则**：
   - 业务系统优先按 Hub 返回的 `candidates` 顺序逐个尝试执行；
   - 若 Hub 所有候选全部异常，或者 Hub 本身离线无法连通，业务系统 **MUST** 自动回退到自身保留的 Local/Legacy 静态保底策略，确保核心业务持续运转。
