# STD-001: Engineering Manifest Standard (工程清单规范)

```text
STANDARD_ID=STD-001
VERSION=1.3.0
STATUS=ACTIVE
SCOPE=所有参与跨工程协作与 AI-Hub 汇聚的本地工程仓库
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-11-05
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

每个独立的 AI 工程仓库（如 AI-KB、VTIP、vtip-ai-sidecar、AI-Engineering-Hub、AI-Engineering-Standards）**MUST** 在项目根目录维护单一自包含的 `engineering-manifest.yaml`。

1. **项目自声明原则 (Self-Declaration)**：
   各工程自己维护本工程的服务定义、端点映射、健康检查契约、Standards 锁定与受控生命周期命令。AI-Engineering-Hub **MUST NOT** 深度硬编码或复制 Owner 内部事实。
2. **单一可信源原则 (Single Source of Truth)**：
   工程清单是跨项目协作时工程对外暴露能力与遵循规范的唯一声明。
3. **机器可验证性**：
   清单 **MUST** 通过 `schemas/engineering-manifest.schema.json` 自动化校验（镜像 `governance/engineering-manifest-schema.json` 保持字节级一致）。
4. **版本概念三维正交原则**：
   - **Standards 整体版本 (`VERSION`)**：平台规范套件的主干版本（如 `2.11.0` 或 `3.0.0`）；
   - **Engineering Manifest `schema_version`**：清单本身的数据结构版本（当前基线为 `"1.3.0"`，兼容 `"1.0"`, `"1.1"`, `"1.2"`）；
   - **Standards Lock `schema_version`**：`standards.lock.json` 的契约模式版本（当前固定为 `"1.0.0"`）。
   编码智能体与工具 **MUST NOT** 将 Standards 整体大版本（如 `3.0.0`）混淆为清单 Schema 版本。

---

## 2. 清单结构规范

清单根节点 **MUST** 包含三大必填部分，并按需包含规范锁定扩展：
- `schema_version`: 当前固定为 `"1.3.0"`（兼容 `"1.0"`, `"1.1"`, `"1.2"`, `"1.3"`）。
- `standards`: 规范版本锁定与来源绑定对象（**MUST** 与 `standards.lock.json` 精确一致）：
  - `repository`: 规范唯一官方仓库（固定为 `xiefeifeihu/AI-Engineering-Standards`）。
  - `version`: 锁定规范 SemVer 版本（如 `2.11.0` 或 `3.0.0`）。
  - `tag`: 规范正式 Annotated Tag（如 `v2.11.0`）。
  - `tag_object_sha`: 40 字符十六进制 Tag 对象 SHA。
  - `peeled_commit`: 40 字符十六进制解包 Commit SHA。
  - `lock_file`: 锁文件相对路径（固定为 `standards.lock.json`）。
- `project`: 项目元数据，包括：
  - `id`: 小写连字符唯一工程标识符。
  - `name`: 人类可读工程名称。
  - `purpose`: 工程职责与范围说明。
  - `deployment_kind`: `SERVICE` 或 `NON_RUNTIME_ARTIFACT`。
  - `release_profile`: `PERSONAL_LOCAL`, `MAINTAINER_RELEASE`, 或 `HIGH_ASSURANCE`。
  - `document_type_applicability`: 对 STD-035 规定的 12 类正式文档的显式适用性声明：
    - 每个声明文档类型指定 `applicable: true/false`；
    - 若声明 `applicable: false`，**MUST** 提供不少于 5 个字符的 `justification`；
    - `DOCUMENT_INDEX` 与 `ENGINEERING_BASELINE` 为强制类型，**MUST NOT** 声明为不适用。
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
