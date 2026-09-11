# AI 工程项目清单规范 (Engineering Project Manifest Specification)

```text
MANIFEST_SPEC_VERSION=V1.0
MANIFEST_SPEC_STATUS=ACTIVE
SCHEMA_REF=AI-Engineering-Standards/governance/engineering-manifest-schema.json
```

## 1. 背景与目标

在 Windows + WSL2 + Docker 混合环境下，多个工程并行演进（AI-KB、VTIP、VTIP AI Sidecar 等），各项目往往有不同的本地监听端口、容器内部端点、依赖的共享推理资源、凭据存放位置和网络门禁。

以往这些事实散落在各项目的 README、compose.yaml 和交接文档中，容易导致：
1. **认知漂移**：不知道某个项目真实的 Web 访问入口在哪里，只能靠猜测或翻看历史对话；
2. **凭据混淆**：不知道某个服务的凭据配置在哪里，或者在调试时将密钥意外打印上屏；
3. **状态盲区**：不知道某个依赖的基础设施是否健康，或者一个可选云端离线却把整个开发面板标红；
4. **端口冲突**：各项目私自声明固定宿主端口，缺乏机器级端口治理。

本规范确立**单一项目持有自身 Manifest、机器级 Hub 汇聚呈现**的标准化架构：
- 各项目在根目录下维护 `engineering-manifest.yaml`；
- `AI-Engineering-Standards` 定义机器可读的 JSON Schema 与规范模板；
- 机器级 `AI Engineering Hub` 挂载各项目 Manifest 与实时 Runtime 状态，提供首屏 10 秒统一概览与导航。

---

## 2. 核心治理契约

1. **项目自声明原则 (Self-Declaration)**：
   各项目自己维护自己的服务、端点、健康检查契约与生命周期命令，Hub 不复制项目内部事实。
2. **零密钥红线 (Zero Secret)**：
   Manifest 与 Hub 仅回答“凭据在哪里（Reference / Environment）”以及“当前是否已配置（CONFIGURED / MISSING）”，严禁记录任何真实 API Key、Token 或密码。
3. **两级导航体系 (Two-Level Navigation)**：
   - Level 1：`http://127.0.0.1/` (AI Engineering Hub)，负责全局概览、跨项目导航与共享基础设施健康监测；
   - Level 2：各业务项目原生 Web UI（如 `127.0.0.1:18090`、`127.0.0.1:8787` 等），负责项目内部业务操作；
   - 禁止做 URL Path Reverse Proxy（不搞 `/aikb`、`/vtip` 二次代理），保留原生 loopback 体验。
4. **廉价探测原则 (Low-Cost Probing)**：
   页面加载时只执行快速的 TCP 连通性、HTTP Health 与 Docker Inspect 探测；严禁自动执行 LLM 推理、Embedding 或重跑完整 Network Gate。
5. **可选资源语义 (Optional Semantics)**：
   可选资源（如 Cloud CPA 隧道）离线时应标定为 `OPTIONAL_OFFLINE` 或 `STOPPED`，不得使 Hub 首页整体告警。
