# AI Engineering Standards

Canonical engineering standards shared across local AI / Vibe Coding projects.

本项目是开发机跨工程共享的架构标准规范库（Source of Truth），定义网络通信、推理资源共享、智能体接入、上下文管理与工程协作标准。

---

## 1. 网络规范与接入标准 (Network Standard)

当前规范版本：

```text
NETWORK_SPEC_VERSION=V0.2
NETWORK_SPEC_STATUS=PRE_RELEASE
V0_2_COLD_START_ACCEPTANCE=PASS
FINAL_RELEASE_PENDING=true
```

### 核心文档 (Source of Truth)

- **网络架构规范（中文主文件）**：[`network/AI-工程统一网络架构与智能体接入规范.md`](./network/AI-工程统一网络架构与智能体接入规范.md) — 宿主/WSL/Docker 机器统一网络基线、Network Gate 门禁、Docker Egress Gateway 出站通道与 Thin Reference 治理。
- **网络验证上下文交接（中文主文件）**：[`network/AI-工程网络验证上下文交接.md`](./network/AI-工程网络验证上下文交接.md) — 跨会话/跨工程上下文交接与运行态基线。

兼容指针（Compatibility Alias）：
- `network/AI-NETWORK-STANDARD.md` -> 兼容指针
- `network/AI-NETWORK-HANDOFF.md` -> 兼容指针

---

## 2. 共享推理资源规范 (Shared Inference Resources Standard)

当前规范版本：

```text
RESOURCE_SPEC_VERSION=V0.1
RESOURCE_SPEC_STATUS=PRE_RELEASE
FINAL_RELEASE_PENDING=true
```

### 核心文档 (Source of Truth)

- **共享推理资源规范**：[`resources/AI-工程共享推理资源规范.md`](./resources/AI-工程共享推理资源规范.md) — 机器级共享推理资源抽象、三层拓扑（Canonical Model → Model Offering → Provider Instance）、通用资源类型（`ollama`, `cli_proxy_api`, `direct_api`）、健康语义严格区分与受控降级退避守卫。
- **共享推理资源目录**：[`resources/AI-工程共享推理资源目录.md`](./resources/AI-工程共享推理资源目录.md) — 稳定登记开发机公用推理物理节点（`ollama-local` on 11434, `cpa-local` on 8317, `cpa-cloud` on 18317），凭据引用契约化，动态模型运行时发现，零明文密钥。
- **本机共享推理资源运行画像**：[`resources/本机共享推理资源运行画像.md`](./resources/本机共享推理资源运行画像.md) — 本机已就绪的 3 大推理节点运行基线、动态发现接口、容器与宿主访问模式及运维责任划分（Cloud CPA 隧道工具归 AI-KB 持有）。
- **共享推理资源接入交接**：[`resources/AI-工程共享推理资源接入交接.md`](./resources/AI-工程共享推理资源接入交接.md) — 面向新项目与新智能体的接入实战指南（探测发现、健康检查、凭证引用契约、动态模型拉取与受控退避）。
- **项目资源画像模板**：[`resources/PROJECT-AI-RESOURCE-PROFILE.template.md`](./resources/PROJECT-AI-RESOURCE-PROFILE.template.md) — 各业务项目派生自身专属画像的基准模板。

---

## 3. 工程治理与智能体协作规范 (Engineering Governance & Context)

当前规范版本：

```text
GOVERNANCE_SPEC_VERSION=V0.1
GOVERNANCE_SPEC_STATUS=PRE_RELEASE
FINAL_RELEASE_PENDING=true
```

### 核心文档 (Source of Truth)

- **智能体协作与上下文规范**：[`governance/AI-工程智能体协作与上下文规范.md`](./governance/AI-工程智能体协作与上下文规范.md) — 会话级极简交接 (Chat Handoff) 与工程现场记录 (Engineering Live Handoff) 的职责分界、Canonical Standards 与 Project Profile 关系、智能体 Git 操作安全边界与防泄密规则。
- **项目清单规范与统一导航契约**：[`governance/AI-工程项目清单规范.md`](./governance/AI-工程项目清单规范.md) — 统一 AI 工程清单规范（Schema: `governance/engineering-manifest-schema.json`，Template: `governance/templates/engineering-manifest.template.yaml`），定义跨工程服务定位、健康探测、零密钥凭据引用与宿主 80 端口 Engineering Hub 架构。
- **上下文包导出规范**：[`governance/AI-工程会话上下文包规范.md`](./governance/AI-工程会话上下文包规范.md) — 面向外部 AI 评审与新会话恢复的上下文导出规则，严格基于 LIVE Repo，严禁密钥、依赖包与失效交接。

---

## 4. 任务模板与工程工具 (Templates & Tools)

- **Vibe Coding 任务前置模板**：[`templates/VIBE-CODING-TASK-PREAMBLE.md`](./templates/VIBE-CODING-TASK-PREAMBLE.md) — 开启任何智能体编码与重构任务时的必选前置安全与规范约束声明。
- **上下文导出工具 (PowerShell)**：[`tools/export-project-context.ps1`](./tools/export-project-context.ps1) — Windows 宿主原生的一键安全导出脚本。
- **上下文导出工具 (Bash)**：[`tools/export-project-context.sh`](./tools/export-project-context.sh) — WSL / Linux 环境原生的一键安全导出脚本。

---

## 5. 项目接入体系 (Project Integration Architecture)

各业务工程（如 AI-KB、VTIP 等）按规范在本地维护自身专属画像与工程配置，形成“标准层 - 画像层”解耦结构：

```text
AI-Engineering-Standards (共享标准定义，唯一 Canonical Source)
  ├── network/AI-工程统一网络架构与智能体接入规范.md
  ├── resources/AI-工程共享推理资源规范.md & AI-工程共享推理资源目录.md
  └── governance/ & templates/ & tools/
          │
          │ 声明式 Thin Reference + Project Profile 派生
          ▼
各业务项目 (如 AI-KB: D:\AI-KB\Repo\ai-kb-infra, VTIP: D:\Projects\vtip-platform-catalog)
  ├── docs/AI-NETWORK-STANDARD.md        (Thin Reference，指向标准库 Commit)
  ├── docs/<PROJECT>-网络配置画像.md     (项目专属网络拓扑与网关画像)
  ├── docs/<PROJECT>-共享推理资源画像.md (项目专属 Champions、审批与降级画像)
  ├── scripts/network/network-gate.cmd   (项目网络门禁执行入口)
  └── LocalConfig/                       (本地机密与凭据隔离目录，绝不进 Git)
```

**关键原则**：
- **废弃全量复制**：严禁将数十 KB 的规范全文拷贝进项目代码库；
- **禁止文件系统跨盘链接**：严禁创建跨工程跨盘的 Windows Symlink 或 Directory Junction，统一使用 Markdown 瘦引用。

---

## 6. 版本治理与安全底线 (Governance & Security)

1. **预发布严谨性**：在用户明确批准正式定版前，任何环境严禁使用 `V1.0` 或输出 `V1.0_READY=true`。网络规范统一采用 `V0.2`，资源与治理规范统一采用 `V0.1`。
2. **绝对零密钥入库 (Zero Secrets in Git)**：标准库中严禁记录任何真实 API Key、OAuth Token、Refresh Token、密码或私有密钥。所有凭据仅记录外部安全引用规范。
3. **独立生产准入硬隔离**：共享物理资源可以跨项目复用，但模型的 `production_approved` 准入状态、任务 Champion、数据敏感分级与配额必须由各业务项目独立制定，严禁跨项目隐式继承。
4. **受控降级退避**：当远端或云端模型不可用时，严禁无条件盲目回退到本地模型。必须校验项目策略允许、数据敏感度合规、生产审批有效及能力契约（如多模态 Vision 必须匹配）。
