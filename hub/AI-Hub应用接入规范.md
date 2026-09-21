# AI-Hub 应用接入规范 (AI-Hub Application Onboarding Specification)

```text
SPEC_VERSION=V1.0
SPEC_CODE=SPEC-AI-HUB-APP-REGISTRY-V1
STATUS=ACTIVE
APPLIES_TO=AI Engineering Hub 及所有接入机器级门户的业务应用
```

---

## 1. 背景与核心原则

AI Engineering Hub (`http://127.0.0.1:80`) 作为本机所有 AI 业务应用与工程服务的**唯一机器级统一入口与能力协调平台**，必须保持以下核心架构原则：

1. **统一入口 + 能力协调 (Hub定位)**：
   - AI-Hub 不是业务系统，不替代业务逻辑，不提供任何复杂 IAM 或远程 Shell。
   - 各业务应用（AI-KB、VTIP、VTIP-AI-SIDECAR、RAGFlow 等）保持独立自治运行与业务闭环。
2. **两级导航体验 (Two-Level Navigation)**：
   - **Level 1** (`http://127.0.0.1/`): Hub 门户，负责全局应用发现、实时健康感知与直达跳转；
   - **Level 2** (如 `127.0.0.1:18090`, `127.0.0.1:8787`): 业务应用的原生 Web UI，用户直接交互；
   - 严禁做二次反向代理（如 `/aikb`, `/vtip` 路径重写），严格保持原生 loopback 体验。
3. **禁止全端口盲探扫描 (No Blind Port Scanning)**：
   - 严禁在局域网或 Loopback 进行全端口扫射（端口扫描无法判断服务真实身份与所有权）；
   - 应用入口来源遵循声明式准入：
     1. 优先读取 AI-Hub 本身注册表 (`config/app-registry.yaml`)；
     2. 结合各项目根目录 `engineering-manifest.yaml`；
     3. 结合精确 Docker 容器名或已知 Metadata 发现。

---

## 2. Application Entity (应用实体数据模型)

所有接入 AI-Hub 的应用必须具备规范化的 `Application Entity` 元数据：

| 字段名 | 类型 | 必填 | 说明 | 示例 |
| :--- | :--- | :---: | :--- | :--- |
| `id` | `string` | 是 | 全局唯一小写应用标识符 | `aikb`, `vtip`, `vtip-sidecar`, `ragflow` |
| `name` | `string` | 是 | 应用展示全称 | `AI-KB (企业级智能知识库)` |
| `description`| `string` | 是 | 业务职能与定位描述 | `企业级知识沉淀、文档切片与 RAG 问答中枢` |
| `owner` | `string` | 是 | 负责工程仓库或责任主体 | `ai-kb-infra`, `vtip-team` |
| `category` | `string` | 是 | 应用分类维度 | `knowledge_base`, `analysis`, `sidecar`, `rag_engine` |
| `url` | `string` | 是 | 原生浏览器直达 Loopback URL | `http://127.0.0.1:18090` |
| `health_check`| `object`| 是 | 健康探测契约（见健康规范） | `{"type": "http", "path": "/health"}` |
| `icon` | `string` | 否 | 语义化 Emoji 图标 | `📘`, `📊`, `🧩`, `⚡` |
| `tags` | `array` | 否 | 业务与能力特征标签 | `["知识库", "RAG", "对话"]` |
| `enabled` | `boolean`| 是 | 是否启用入口展示 (默认 true) | `true` |
| `order` | `integer`| 否 | 排序权重（数值越小排序越靠前） | `10` |

---

## 3. 应用接入配置文件示例 (`config/app-registry.yaml`)

```yaml
version: "1.0"
applications:
  - id: "aikb"
    name: "AI-KB"
    description: "企业级智能知识库管理与 RAG 问答中枢"
    owner: "ai-kb-infra"
    category: "knowledge_base"
    url: "http://127.0.0.1:18090"
    health_check:
      type: "http"
      path: "/health"
      timeout_seconds: 1.0
    icon: "📘"
    tags: ["知识库", "RAG", "问答", "数据沉淀"]
    enabled: true
    order: 1

  - id: "vtip"
    name: "VTIP Platform Catalog"
    description: "基于大模型的情报分析、研判与报告平台"
    owner: "vtip-team"
    category: "analysis"
    url: "http://127.0.0.1:8787"
    health_check:
      type: "http"
      path: "/health"
      timeout_seconds: 1.0
    icon: "📊"
    tags: ["情报分析", "研判", "报告", "专项协同"]
    enabled: true
    order: 2

  - id: "vtip-sidecar"
    name: "VTIP-AI-SIDECAR"
    description: "业务系统专用模型接入中继与插件扩展"
    owner: "vtip-team"
    category: "sidecar"
    url: "http://127.0.0.1:8799"
    health_check:
      type: "http"
      path: "/health"
      timeout_seconds: 1.0
    icon: "🧩"
    tags: ["模型接入", "Sidecar", "API中继", "扩展"]
    enabled: true
    order: 3

  - id: "ragflow"
    name: "RAGFlow"
    description: "专业级知识库构建与深度文档解析检索引擎"
    owner: "ai-kb-infra"
    category: "rag_engine"
    url: "http://127.0.0.1:18080"
    health_check:
      type: "http"
      path: "/"
      timeout_seconds: 1.0
    icon: "⚡"
    tags: ["RAG引擎", "深度解析", "混合检索"]
    enabled: true
    order: 4
```

---

## 4. 准入与生命周期契约

1. **服务启动与就绪**：
   应用必须在原生端口监听并暴露非阻塞健康端点（推荐 `/health`），返回 HTTP 200 标识业务就绪。
2. **免密与回环原则**：
   严格限制监听于 `127.0.0.1`，内部通信免密互信，严禁向局域网或公网直接裸露应用界面。
3. **零密钥红线**：
   应用的凭据信息（如数据库连接串、API 密钥）必须隔离在受管目录或本地环境变量中，严禁在注册表中记录任何明文 Secret。
