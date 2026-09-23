# AI Engineering Standards 现状全面审计报告 (Standards V1.0 Audit)

```text
AUDIT_ID=AUDIT-STANDARDS-V1-001
DATE=2026-09-23
SCOPE=D:\Projects\AI-Engineering-Standards
STATUS=COMPLETED
AUTHOR=AI Platform Governance Agent
```

---

## 1. 审计背景与事实优先级法则

在建立 **AI Engineering Standards V1.0** 基线之前，对 `D:\Projects\AI-Engineering-Standards` 仓库现存文件、跨项目引用及运行态一致性进行端到端静态与动态审计。

本规范库确立开发机跨工程事实的不可逆优先级序列：
1. **当前 Runtime（运行态真实状态）**
2. **Owner Repo 当前代码（所有者仓库源码实现）**
3. **Owner Manifest（所有者声明清单 `engineering-manifest.yaml`）**
4. **Hub Runtime Registry（AI-Hub 运行时动态注册表）**
5. **Git 历史提交记录**
6. **Standards（跨工程规范库）**
7. **旧聊天与历史会话记录**

> **治理核心底线**：Standards 库是跨工程契约与 Schema 标准的定义者，负责提供 Contract 与边界约束，但**绝不能反向强迫真实正确的 Runtime 倒退适配过期的静态文档**。

---

## 2. 现有资产与规范清单盘点

经实际文件系统扫描，仓库现有文件及目录共计 30 项实体，分类盘点如下：

| 序号 | 文件 / 目录路径 | 类型 | 规范代号 / 声明版本 | 职责概述 |
| :---: | :--- | :--- | :--- | :--- |
| 1 | `README.md` | 导航文档 | V0.2 / PRE_RELEASE | 规范库总览、网络规范 V0.2 及资源规范 V0.1 说明 |
| 2 | `governance/AI-工程会话上下文包规范.md` | 规范文档 | V0.1 / PRE_RELEASE | 会话级上下文导出规则与防泄密检查 |
| 3 | `governance/AI-工程智能体协作与上下文规范.md` | 规范文档 | V0.1 / PRE_RELEASE | 智能体协作、Git 安全边界与交接职责分界 |
| 4 | `governance/AI-工程项目清单规范.md` | 规范文档 | V1.0 / ACTIVE | 项目 Manifest 规范（单一持有、Hub 汇聚） |
| 5 | `governance/engineering-manifest-schema.json` | JSON Schema | 1.0 (Draft 2020-12) | Manifest 机器可读 JSON Schema |
| 6 | `governance/templates/engineering-manifest.template.yaml`| 模板配置 | 1.0 | 各工程初始化 Manifest 的标准模板 |
| 7 | `hub/AI-Hub健康检查规范.md` | 规范文档 | V1.0 / ACTIVE | 三层健康检查模型（PRESENT, AVAILABLE, READY） |
| 8 | `hub/AI-Hub应用接入规范.md` | 规范文档 | V1.0 / ACTIVE | 统一门户应用实体与两级导航体验 |
| 9 | `hub/AI-Hub资源注册规范.md` | 规范文档 | V1.0 / ACTIVE | 机器级 AI 推理服务与存储基础设施注册模型 |
| 10 | `network/AI-工程统一网络架构与智能体接入规范.md` | 规范文档 | V0.2 / PRE_RELEASE | 宿主/WSL/Docker 机器统一网络基线与 Network Gate |
| 11 | `network/AI-工程网络验证上下文交接.md` | 交接文档 | V0.2 / PRE_RELEASE | 跨会话网络验证现场基线 |
| 12 | `network/AI-NETWORK-STANDARD.md` | 兼容指针 | - | 指向统一网络架构规范的别名文件 |
| 13 | `network/AI-NETWORK-HANDOFF.md` | 兼容指针 | - | 指向网络验证上下文交接的别名文件 |
| 14 | `resources/AI-工程共享推理资源规范.md` | 规范文档 | V0.1 / PRE_RELEASE | 三层推理拓扑模型、资源类型与退避原则 |
| 15 | `resources/AI-工程共享推理资源目录.md` | 目录文档 | V0.1 / PRE_RELEASE | 开发机公用推理节点登记目录与连接串定义 |
| 16 | `resources/本机共享推理资源运行画像.md` | 画像文档 | V0.1 / PRE_RELEASE | 本机推理资源运行态指标与参数基线 |
| 17 | `resources/AI-工程共享推理资源接入交接.md` | 交接文档 | V0.1 / PRE_RELEASE | 新工程与智能体接入推理资源实战手册 |
| 18 | `resources/PROJECT-AI-RESOURCE-PROFILE.template.md` | 模板文档 | - | 业务项目专属推理资源画像派生模板 |
| 19 | `templates/VIBE-CODING-TASK-PREAMBLE.md` | 模板文档 | - | 智能体编程任务前置安全与规范约束声明 |
| 20 | `tools/check-shared-inference.py` | 诊断工具 | 1.0 | 共享推理资源三层探测脚本（Python 独立版） |
| 21 | `tools/check-shared-inference.sh` | 诊断脚本 | - | 探测工具的 Bash 执行包装 |
| 22 | `tools/export-project-context.ps1` | 工具脚本 | - | Windows 原生上下文安全导出 PowerShell 脚本 |
| 23 | `tools/export-project-context.sh` | 工具脚本 | - | WSL/Linux 原生上下文导出 Shell 脚本 |

---

## 3. 问题细分审计（过时、冲突、重复与缺陷）

### 3.1 明确过时规范 (Stale Specifications)
1. **Cloud CPA 隧道旧脚本路径过时**：
   - 发现位置：
     - `resources/AI-工程共享推理资源目录.md` (Line 107)：`scripts/tunnel/cloud-cpa-tunnel.cmd`
     - `resources/本机共享推理资源运行画像.md` (Line 72)：`scripts/tunnel/cloud-cpa-tunnel.cmd`
   - 事实分析：
     AI-KB 仓库早前已对目录结构进行规范重构，旧路径 `scripts/tunnel/cloud-cpa-tunnel.cmd` 已正式废弃并移除，当前 Canonical 真实路径为 `scripts/cpa/cloud-cpa-tunnel.cmd`。虽然在 `network/AI-工程统一网络架构与智能体接入规范.md` (Line 1589) 中已更新为正确路径，但 resources 目录下多处文档未同步，造成跨文档失实。
2. **README 预发布版本冻结标识过时**：
   - 发现位置：`README.md` (Line 14-17, 36-39, 56-59, 105)
   - 事实分析：
     文档仍强制标明 `V0.1` / `V0.2` `PRE_RELEASE` 并声明“严禁使用 V1.0”。本次任务正式要求建设 V1.0 基线，该冻结状态已完成使命，需正式升级至 `V1.0.0`。

### 3.2 冲突规范 (Conflicting Specifications)
1. **Local CPA 宿主端口冲突 (Port Conflict: 8317 vs 18117)**：
   - 发现位置：
     - `resources/本机共享推理资源运行画像.md` (Line 53, 82)
     - `tools/check-shared-inference.py` (Line 37)
     - `hub/AI-Hub资源注册规范.md` (Line 92)
   - 事实分析：
     上述文档将 Local CPA 宿主监听端点记录为 `http://127.0.0.1:8317`。但在 AI-KB Ground Truth 与 AI-Hub v0.5.3 生产运行时中：
     - **Host Endpoint 为 `http://127.0.0.1:18117`**；
     - **Docker Internal Endpoint 为 `http://cpa-local:8317`**；
     旧文档混淆了 Host 端点与 Container 端点，违反了“严禁假定 Host Port == Container Port”的核心原则。
2. **Local CPA 所有权与动作集冲突 (Ownership & Actions Conflict)**：
   - 发现位置：`hub/AI-Hub资源注册规范.md` (Line 91, 99)
   - 事实分析：
     文档将 Local CPA 所有者错误登记为 `sensha-cloud`，动作集标记为仅 `status, test`。
     **实际 Ground Truth**：
     - Owner 为 `ai-kb-infra`（仓库：`D:\AI-KB\Repo\ai-kb-infra`）；
     - Canonical Lifecycle 为 `scripts/cpa/local-cpa.cmd`；
     - 动作集完备支持 `start`, `stop`, `restart`, `status`, `test`；
     - Hub 不得复制 Owner 实现。

### 3.3 重复与冗余规范 (Duplicate & Redundant Content)
1. `network/AI-NETWORK-STANDARD.md` 与 `network/AI-NETWORK-HANDOFF.md` 为早期英文向中文规范迁移时建立的软兼容指针，内容极少，应保留作为别名兼容，但不应视为主规范。
2. 推理资源目录、规范与画像三份文档之间存在较多关于 CPA 认证头、模型拉取命令的逐字重复，V1.0 应将通用契约沉淀入独立 STD，避免到处复制代码块导致版本漂移。

### 3.4 缺失的核心规范 (Missing Standards)
在现有仓库中，以下关键治理维度完全缺失：
1. **端口治理标准 (Port Governance Standard)**：
   缺少针对 Windows 动态端口排除范围 (`netsh int ipv4 show dynamicport tcp`)、排除端口段 (`netsh int ipv4 show excludedportrange tcp`) 及本机 18000-19999 机器级工程约定的正式规范。
2. **资源生命周期分类规范 (Lifecycle Policy Standard)**：
   缺少 `ALWAYS_ON`（常驻服务）、`ON_DEMAND`（按需服务）、`MANUAL`（手动管理）、`EXTERNAL`（外部管理）以及 `desired_state` 与 `actual_state` 状态模型的正式契约。
3. **模型治理三层契约 (Model Governance Contracts)**：
   缺少 STD-008（模型注册表规范）、STD-009（候选路由方案契约）、STD-010（模型反馈契约）、STD-011（应用消费契约）。
4. **冷启动与样本置信度标准**：
   缺少对 0 调用次数、无延迟样本时的明确语义规范，导致旧实现误标“100% 成功率”与“0ms 延迟”。
5. **多环境运行时边界规范 (Runtime Boundary Standard)**：
   缺少 Windows 宿主、WSL2 子系统与 Docker 桥接网络的端点映射与跨环境通信边界定义（STD-012）。
6. **工程验证与发布标准**：
   缺少跨项目测试分层标准（STD-014）、Playwright 验收标准（STD-015）、验收证据包标准（STD-016）、独立 Git 发布规范（STD-017）与 UI 诊断/枚举本地化规范（STD-018）。
7. **机器可读 Schema 缺失**：
   仓库先前仅包含 `engineering-manifest-schema.json`，缺少资源、端点、动作、模型注册、路由请求/响应、模型反馈与审计日志等 8 个 JSON Schema。

---

## 4. 规范处理矩阵与处置方案

| 规范类别 | 处理策略 | 具体清单与动作 |
| :--- | :--- | :--- |
| **可保留并演进** | 原样保留并纳管入 V1.0 架构 | `AI-工程会话上下文包规范.md`, `AI-工程智能体协作与上下文规范.md`, `AI-工程统一网络架构与智能体接入规范.md`, `AI-工程项目清单规范.md` |
| **需要更新校准** | 更新 Ground Truth，消除冲突 | `resources/AI-工程共享推理资源目录.md`（修正路径与端口）, `resources/本机共享推理资源运行画像.md`（更正端口至 18117）, `tools/check-shared-inference.py`（默认端口更正为 18117） |
| **废弃候选标记** | 保留历史并在头部明确标明 DEPRECATED | 旧隧道脚本路径引用 `scripts/tunnel/cloud-cpa-tunnel.cmd` -> 归档至 `deprecated/CLOUD-CPA-TUNNEL-DEPRECATED.md` |
| **新增正式标准** | 形成 STD-001 ~ STD-018 正式标准文档 | 建立 `standards/` 分类目录并输出 18 份标准化文档 |
| **新增 Schema** | 编写 9 个标准 JSON Schema 并配自检测试 | `schemas/*.schema.json` + `tools/validate-schemas.py` |
| **新增会话交接** | 产出 3 份面向具体项目长期会话的指南 | `handoff/AI-KB-...md`, `handoff/Sidecar-...md`, `handoff/VTIP-...md` |

---

## 5. 结论

本审计证实：
1. 现有 Standards 规范库骨架扎实，但存在多处因项目演进（特别是 Local CPA 端口变更与 Cloud CPA 脚本路径调整）导致的局部陈旧与冲突；
2. 缺乏模型治理、端口治理、资源生命周期及机器可读 Schema 等关键拼图；
3. 本次建立 Standards V1.0 基线将严格以 Ground Truth 为准绳，彻底修复 Stale 内容，补充完整规范矩阵与 Schema，实现跨项目自动化对齐。
