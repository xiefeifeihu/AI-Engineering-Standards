# STD-002: Resource Ownership Standard (资源所有权与职责边界规范)

```text
STANDARD_ID=STD-002
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=开发机所有 AI 基础设施、推理代理、数据存储与中继资源
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
SCHEMA_REF=schemas/resource.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 资源所有权核心原则

在多工程协作环境中，所有物理计算资源、容器实例、代理网关及隧道脚本 **MUST** 归属于唯一的 **Owner Repo**。

1. **Owner 唯一持有 (Strict Ownership)**：
   每个受管资源仅由一个工程团队/仓库持有生命周期管理脚本、原始编排文件与敏感配置。
2. **禁止实现跨仓库复制 (No Implementation Duplication)**：
   其他消费方工程（如 AI-Hub、Sidecar、VTIP）**MUST NOT** 复制 Owner 脚本的实现，**MUST** 仅通过 Standard Action、Host Action Bridge 或标准化网络端口消费。
3. **准入与治理隔离**：
   某资源在 Owner 工程的生产准入状态，**MUST NOT** 自动继承给其他业务工程。各消费者工程独立维护生产准入与配额策略。

---

## 2. 关键共享资源 Ground Truth 所有权归属

| 资源标识 (`resource_id`) | 责任主体 (`owner`) | 所有者仓库 (`owner_repo`) | 标准管理入口 (`canonical_lifecycle`) |
| :--- | :--- | :--- | :--- |
| `local-cpa` | `ai-kb-infra` | `D:\AI-KB\Repo\ai-kb-infra` | `scripts/cpa/local-cpa.cmd` |
| `cpa-cloud` | `ai-kb-infra` | `D:\AI-KB\Repo\ai-kb-infra` | `scripts/cpa/cloud-cpa-tunnel.cmd` |
| `ollama` | `machine-local` | 本机全局基础设施服务 | Windows 服务 / 本机进程 |
| `ai-kb-control` | `ai-kb-infra` | `D:\AI-KB\Repo\ai-kb-infra` | `apps/aikb-control-center/docker-compose.yml` |
| `ai-kb-ragflow` | `ai-kb-infra` | `D:\AI-KB\Repo\ai-kb-infra` | `config/ragflow/v0.26.4/docker-compose.aikb.yml`|
| `ai-engineering-hub` | `ai-engineering-hub` | `D:\Projects\AI-Engineering-Hub` | `compose.yaml` (Port 80) |
