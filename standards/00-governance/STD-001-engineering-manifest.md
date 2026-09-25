# STD-001: Engineering Manifest Standard (工程清单规范)

```text
STANDARD_ID=STD-001
VERSION=1.1.3
STATUS=ACTIVE
SCOPE=所有参与跨工程协作与 AI-Hub 汇聚的本地工程仓库
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-25
SCHEMA_REF=schemas/engineering-manifest.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 核心目标与原则

每个独立的 AI 工程仓库（如 AI-KB、VTIP、VTIP-AI-SIDECAR、AI-Engineering-Hub）**MUST** 在项目根目录维护单一自包含的 `engineering-manifest.yaml`。

1. **项目自声明原则 (Self-Declaration)**：
   各工程自己维护本工程的服务定义、端点映射、健康检查契约与受控生命周期命令。AI-Engineering-Hub **MUST NOT** 深度硬编码或复制 Owner 内部事实。
2. **单一可信源原则 (Single Source of Truth)**：
   工程清单是跨项目协作时工程对外暴露能力的唯一声明。
3. **机器可验证性**：
   清单 **MUST** 通过 `schemas/engineering-manifest.schema.json` 自动化校验。

---

## 2. 清单结构规范

清单根节点 **MUST** 包含三大必填部分：
- `schema_version`: 当前固定为 `"1.0"` 或 `"1.0.0"`。
- `project`: 项目元数据，包括 `id`, `name`, `purpose`, `repo_path_hints`, `consumer_contract`。
- `services`: 本项目持有的服务实体列表。

每个服务实体 **MUST** 定义：
- `id`: 小写连字符唯一标识符（例如 `local-cpa`, `ai-kb-control`）。
- `name`: 人类可读名称。
- `owner`: 责任仓库标识符（例如 `ai-kb-infra`）。
- `category`: `project_app`, `shared_ai_resource`, `knowledge_data_infra`, `machine_infra`。
- `exposure`: `loopback`, `docker_internal`, `optional_tunnel`, `none`。
- `endpoints`: `windows_host`, `wsl_host`, `docker_internal`, `docker_consumer`。
  - `docker_internal`: 同 Docker 网络/容器 DNS 内直连端点（如 `http://cpa-local:8317`）。
  - `docker_consumer`: 外部 Docker bridge 容器经由宿主网关/中继消费端点（如 `http://host.docker.internal:18318`）。
  - 端点字段均为可选，无强行共存约束；旧版本清单不含 `docker_consumer` 完全保持合法兼容。
- `health_contract`: 声明探测类型与超时。
- `lifecycle_policy`: `ALWAYS_ON`, `ON_DEMAND`, `MANUAL`, `EXTERNAL`。
- `desired_state`: `RUNNING`, `STOPPED`。
