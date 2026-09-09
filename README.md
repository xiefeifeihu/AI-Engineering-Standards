# AI Engineering Standards

Canonical engineering standards shared across local AI / Vibe Coding projects.

本项目是开发机跨工程共享的架构标准规范库（Source of Truth），定义网络通信、推理资源共享、智能体接入与工程契约标准。

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

- **网络架构规范（中文主文件）**：[`network/AI-工程统一网络架构与智能体接入规范.md`](./network/AI-工程统一网络架构与智能体接入规范.md) — 宿主/WSL/Docker 机器统一网络基线、Network Gate 门禁、修复决策树、Docker Egress Gateway 出站通道与 Web 网络中心规范。
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

- **共享推理资源规范**：[`resources/AI-工程共享推理资源规范.md`](./resources/AI-工程共享推理资源规范.md) — 机器级共享推理资源抽象、三层拓扑（Canonical Model → Model Offering → Provider Instance）、健康语义严格区分（Resource vs Offering vs Network Health）与项目独立准入隔离原则。
- **共享推理资源目录**：[`resources/AI-工程共享推理资源目录.md`](./resources/AI-工程共享推理资源目录.md) — 稳定登记开发机公用推理物理节点（`ollama-local` on 11434, `cpa-local` on 8317, `cpa-cloud` on 18317），动态模型不硬编码，严禁登记任何明文密钥。
- **共享推理资源接入交接**：[`resources/AI-工程共享推理资源接入交接.md`](./resources/AI-工程共享推理资源接入交接.md) — 面向新项目与新智能体的接入实战指南（探测发现、健康检查、凭证引用、动态模型拉取与 Cloud 离线退避）。
- **项目资源画像模板**：[`resources/PROJECT-AI-RESOURCE-PROFILE.template.md`](./resources/PROJECT-AI-RESOURCE-PROFILE.template.md) — 各业务项目派生自身专属画像的基准模板。

---

## 3. 项目接入体系 (Project Integration Architecture)

各业务工程（如 AI-KB、VTIP 等）按规范在本地维护自身专属画像与工程配置，形成“标准层 - 画像层”解耦结构：

```text
AI-Engineering-Standards (共享标准定义)
  ├── network/AI-工程统一网络架构与智能体接入规范.md
  └── resources/AI-工程共享推理资源规范.md & AI-工程共享推理资源目录.md
          │
          │ 映射与派生
          ▼
各业务项目 (如 AI-KB: D:\AI-KB\Repo\ai-kb-infra)
  ├── docs/AI-KB-网络配置画像.md         (项目专属网络拓扑与网关画像)
  ├── docs/AI-KB-共享推理资源画像.md     (项目专属 14 类任务 Champion 与降级画像)
  ├── scripts/network/network-gate.cmd   (项目网络门禁执行入口)
  └── LocalConfig/                       (本地机密与凭据隔离目录，绝不进 Git)
```

---

## 4. 版本治理与安全底线 (Governance & Security)

1. **预发布严谨性**：在用户明确批准正式定版前，任何环境严禁使用 `V1.0` 或输出 `V1.0_READY=true`。网络规范统一采用 `V0.2`，资源规范统一采用 `V0.1`。
2. **绝对零密钥入库 (Zero Secrets in Git)**：标准库中严禁记录任何真实 API Key、OAuth Token、Refresh Token、密码或私有密钥。所有凭证仅记录外部安全引用规范。
3. **独立生产准入硬隔离**：共享物理资源可以跨项目复用，但模型的 `production_approved` 准入状态、任务 Champion、数据敏感分级与配额必须由各业务项目独立制定，严禁跨项目隐式继承。
