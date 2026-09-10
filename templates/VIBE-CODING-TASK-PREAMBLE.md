# Vibe Coding / AI Agent 任务前置提示词模板 (Task Preamble Template)

> **使用说明**：
> 本模板为跨工程智能体（ChatGPT / Codex / Antigravity / Claude 等）执行代码研发、重构或架构运维任务时的**必选前置声明（Preamble）**。在开启新任务或会话前，将本声明填充并附加至 Prompt 开头。

---

```markdown
================================================================================
【AI-ENGINEERING 智能体任务前置安全与规范约束】
================================================================================

1. 规范标准与 Canonical 引用：
- 本机通用网络规范与共享推理资源唯一真源：D:\Projects\AI-Engineering-Standards
- 当前遵循规范版本：NETWORK_SPEC=V0.2 (PRE_RELEASE), RESOURCE_SPEC=V0.1 (PRE_RELEASE)
- 本工程遵循 Thin Markdown Reference + Project Profile 架构，严禁将标准长文复制入库，严禁创建跨工程 symlink/junction。

2. 当前任务上下文与项目边界：
- 目标工程路径：[填入当前工程绝对路径，例如 D:\AI-KB\Repo\ai-kb-infra 或 D:\Projects\vtip-platform-catalog]
- 当前工作分支：[填入当前分支，例如 feat/aikb-v0.4 或 main]
- 任务输入真源：严格以 LIVE Repo 真实工作区现状为准，任何外部压缩包或聊天粘贴仅用于审计比对，绝不作为盲目覆盖来源。

3. 绝对禁止事项 (Guardrails & Redlines)：
- 严禁越权修改本机网络配置（Windows 代理、WSL 路由、Docker Egress Gateway、Clash 配置）；
- 严禁非必要重启宿主机操作系统、wsl --shutdown 或重启 Docker Daemon；
- 严禁触碰任何未指派的 Git stash；
- 严禁无授权的 git reset --hard、git clean -fd、git merge、git tag 或 force push；
- 在多 Remote 仓库中，未经用户明确授权严禁自动向任何远程执行 push 操作。

4. 推理资源与服务调用守卫：
- 共享推理资源（ollama: 11434, cpa-local: 8317, cpa-cloud: 18317）只读消费，严禁冲突抢占端口；
- 严禁未经策略检查的无条件本地 fallback；云端模型离线且备选模型无相应 capability（如视觉 Vision）时必须明确阻断（capability_unavailable）；
- 容器消费契约守卫：修改容器配置前必须查验项目的消费声明（shared_inference_consumption）。严禁向声明为 NONE 的项目（如 vtip-platform-catalog 核心容器）随意注入 host.docker.internal 或强制绑定共享推理资源；仅对声明为 REQUIRED 或 OPTIONAL 的项目/组件（如 vtip-ai-sidecar、ai-kb）按需注入契约。

5. 凭据隔离与绝不上屏原则 (Zero Secrets)：
- 严禁在代码、注释、提交历史、交接文档或模型提示词中记录任何明文 API Key、Token 或密码；
- 所有日志、调试输出与上屏回复中的凭据必须脱敏（如 sk-***）。
================================================================================
```
