# AI Engineering Standards

Canonical engineering standards shared across local AI / Vibe Coding projects.

## 网络规范与接入标准（Network Standard）

当前规范版本：

```text
NETWORK_SPEC_VERSION=V0.2
NETWORK_SPEC_STATUS=PRE_RELEASE
V0_2_COLD_START_ACCEPTANCE=PASS
FINAL_RELEASE_PENDING=true
```

### 核心文档（Source of Truth）

- **网络规范（中文主文件）**：[`network/AI-工程统一网络架构与智能体接入规范.md`](./network/AI-工程统一网络架构与智能体接入规范.md) — 机器统一网络基线、Network Gate、修复决策树、Project Network Module、标准日志与 Web 网络中心规范。
- **网络交接（中文主文件）**：[`network/AI-工程网络验证上下文交接.md`](./network/AI-工程网络验证上下文交接.md) — 跨会话/跨工程上下文交接与运行态基线。

注：原英文路径仅作为向后兼容重定向入口（Compatibility Alias）：
- `network/AI-NETWORK-STANDARD.md` -> 兼容指针
- `network/AI-NETWORK-HANDOFF.md` -> 兼容指针

## 项目接入（Project Integration）

各工程按约定同步本地快照并维护项目自身专属 Profile 与门禁脚本：

```text
docs/AI-工程统一网络架构与智能体接入规范.md   (快照)
docs/AI-工程网络验证上下文交接.md           (快照)
docs/AI-KB-网络配置画像.md                 (项目画像)
scripts/network/network-gate.cmd
scripts/network/network-gate.sh
```

Canonical Repo 仅定义共享契约与基线，各 Project 自行管理实际 Endpoint、运行时/构建依赖以及业务网络自测。

## 版本治理（Version Governance）

在用户明确批准正式定版前，任何环境严禁使用 `V1.0` 或输出 `V1.0_READY=true`。预发布修订统一采用 `V0.2` 并以 Git Commit 与日期追踪。
