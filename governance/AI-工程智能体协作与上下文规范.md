# AI 工程智能体协作与上下文规范 (AI Agent Collaboration & Context Specification)

```text
GOVERNANCE_SPEC_VERSION=V0.1
GOVERNANCE_SPEC_STATUS=PRE_RELEASE
FINAL_RELEASE_PENDING=true
```

## 1. 背景与目标

在多工程并行开发（如 AI-KB、VTIP）与多大模型智能体（ChatGPT、Codex、Antigravity、Claude 等）协作时，常出现以下协作失范：
1. **上下文臃肿与污染**：会话重启时将包含大量历史操作细节、失效分支甚至死代码的日志全量塞入，导致模型注意力漂移；
2. **职责边界混乱**：将面向工程师调试的“现场日志”与面向大模型启动的“会话交接”混淆，甚至在交接中记录过时或错误的运行事实；
3. **真源撕裂与重复拷贝**：各项目私自拷贝全量规范并各自修改，失去与标准库的同步；
4. **Git 操作失控**：智能体在未完全掌握多远程源（Multi-Remote）现状时，盲目执行 `git reset --hard`、`clean` 或自动 push 到未经验证的远程。

本规范确立统一的**文档职责分工、标准引用规范与智能体 Git 操作安全底线**。

---

## 2. 文档职责分层：Chat Handoff vs Engineering Live Handoff

各工程在维护交接文档时，必须严格区分两类交接，不得混为一谈：

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. Chat / Human Handoff (会话级极简交接)                     │
│    - 面向大模型会话重启与人类快速对齐                        │
│    - 极度精炼 (<= 150 行)                                   │
│    - 仅包含: 当前阶段目标、核心事实基线、禁止事项、必读指针 │
│    - 严禁堆砌长篇代码片段、过时调试步骤与大段历史输出       │
└──────────────────────────────┬──────────────────────────────┘
                               │ 引用与分工
┌──────────────────────────────▼──────────────────────────────┐
│ 2. Engineering Live Handoff (工程现场详尽记录)               │
│    - 面向具体工位、现场研发与深层调试                       │
│    - 详尽完整: 命令执行序列、异常排查记录、诊断与配置差异   │
│    - 包含: 环境依赖版本、端口占用明细、验证日志路径         │
└─────────────────────────────────────────────────────────────┘
```

### 2.1 会话交接 (Chat Handoff) 准则
- 每次任务结束或会话切换时更新；
- 必须明确当前任务编号、分支、已完成目标与下一步待办；
- 列出不可违背的禁止事项清单（如严禁修改网络、严禁重启某些进程）；
- 提供必读文件指针，引导新会话智能体主动读取最新代码与配置，而非在交接中硬编码静态复制。

### 2.2 现场交接 (Engineering Live Handoff) 准则
- 用于开发机工位现场的上下文恢复与异常排障；
- 记录详细的操作指令与环境细节；
- 当涉及多个历史交接文件时，已被替代的旧交接必须标记 `SUPERSEDED` 并移入归档目录（如 `docs/archive/handoffs/`），严禁留在活动文档区误导智能体。

---

## 3. Canonical Standards 与 Project Profile 关系

```text
AI-Engineering-Standards (本机唯一 Canonical Source of Truth)
  ├── network/AI-工程统一网络架构与智能体接入规范.md
  ├── resources/AI-工程共享推理资源规范.md & AI-工程共享推理资源目录.md
  └── governance/ (协作、上下文、安全与打包规范)
           │
           │ 声明式 Thin Reference (仅记录版本、Commit SHA、指针)
           ▼
各业务项目 (AI-KB, VTIP, 等)
  ├── docs/AI-NETWORK-STANDARD.md        # Thin Reference
  ├── docs/<PROJECT>-网络配置画像.md     # Project Profile (专属拓扑/网关/Gate)
  ├── docs/<PROJECT>-共享推理资源画像.md # Project Profile (专属 Champions/审批)
  └── scripts/network/network-gate.*     # Project Gate 实现
```

### 3.1 核心治理原则
1. **单一真源 (Single Canonical Source)**：
   - 跨工程通用的网络架构、共享资源协议与治理准则仅在 `AI-Engineering-Standards` 仓库维护；
2. **瘦引用 (Thin Markdown Reference)**：
   - 下游项目严禁将标准库数十 KB 的长文全量复制进自身代码库；
   - 仅在项目内维护瘦引用文件，标明当前遵循的规范版本、同步时的 `STANDARDS_COMMIT` 哈希与相对/绝对引用指引；
3. **严禁跨项目文件系统硬链接/软链接**：
   - 禁止创建跨盘/跨目录的 Windows Symlink 或 Directory Junction。跨系统、压缩包打包与解压、CI/CD 构建均会发生链接破坏与路径失真。项目必须使用常规 Markdown 瘦引用文档；
4. **Project Profile 聚焦专属边界**：
   - 各项目仅记录本项目的实际网络网关映射、允许调度的资源范围、经过项目独立人工审批（`production_approved=true`）的模型、专属任务 Champions 与本地离线降级守卫。

---

## 4. 智能体 Git 操作边界与安全红线 (Git Safety Boundaries)

任何执行工程任务的 AI 智能体（Codex、Antigravity、ChatGPT 等）必须严格遵守以下 Git 操作规范：

### 4.1 绝对禁止操作 (Strictly Prohibited)
1. **严禁对未授权的远程仓库执行写入**：
   - 特别在多远程（Multi-Remote）仓库中（如包含 `github`、`http-dev`、`origin`），未经明确指令，严禁自动 `git push`；
   - 若某些远程（如企业内网/第三方开发源）落后于主分支，严禁擅自执行强制覆盖或自动同步；
2. **严禁破坏性重置与清理**：
   - 严禁执行 `git reset --hard`、`git clean -fd`；
   - 严禁执行 `git push --force`；
   - 严禁在未获明确指令前执行 `git merge`、`git tag`；
3. **严禁触碰未归属于当前任务的 Stash**：
   - 若仓库中存在其他任务的保存现场（如 `stash@{0}`），未经用户明确许可严禁 drop、pop 或覆盖。

### 4.2 审查与提交准则
1. **提交前自检 (Pre-commit Audit)**：
   - 必须执行 `git status` 与 `git diff`，仔细核对每一个修改文件；
   - 严禁误带无关文件（如 `desktop.ini`、临时日志、编辑器缓存）；
2. **绝对零凭据泄漏 (Zero Secrets)**：
   - 任何提交前必须扫描是否包含 API Key、Token、私钥、包含真实账号密码的配置；
   - 敏感文件必须严格列入 `.gitignore` 并存放在 `LocalConfig/` 或环境变量中。
