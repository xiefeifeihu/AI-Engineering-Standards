# AI 工程会话上下文包规范 (AI Context Pack Export Specification)

```text
CONTEXT_PACK_SPEC_VERSION=V0.1
CONTEXT_PACK_SPEC_STATUS=PRE_RELEASE
FINAL_RELEASE_PENDING=true
```

## 1. 目标与定位

当工程师需要将当前开发机工位的项目工程现场提供给外部大模型（如 ChatGPT Web / Claude）进行离线评审、架构分析或在新智能体会话中快速恢复上下文时，必须遵循标准化的**上下文包导出规则 (Context Pack Export)**。

### 核心安全与质量原则
1. **严格基于 LIVE Repo 构建**：上下文包必须直接从工作区（Live Working Tree）抽取真实文件，严禁层层转手二次打包造成事实失真；
2. **绝对安全零泄漏 (Zero Secrets)**：严禁打包任何凭据目录（`LocalConfig/`）、环境变量（`.env`）、私钥密钥、内部令牌；
3. **拒绝噪音与垃圾文件**：排除版本控制底层（`.git/`）、虚拟环境（`.venv/`）、依赖包（`node_modules/`）、构建缓存与运行时日志；
4. **排除失效过期交接**：已标记 `SUPERSEDED` 或已被新文件替代的旧交接严禁纳入活动上下文。

---

## 2. 上下文包标准构成契约

一个标准导出的 Context Pack 必须满足以下构成结构：

### 2.1 必选核心文件 (Required Inclusions)
1. **项目入口与架构说明**：`README.md`，以及项目内的核心规范架构图；
2. **活跃交接文档 (Active Handoffs)**：当前项目唯一生效的活跃 Chat Handoff 或现场交接（如 `docs/3、当前交接.md` 或最新命名的活动交接）；
3. **项目特征画像 (Project Profiles)**：
   - 项目网络画像（如 `docs/*-网络配置画像.md` 或 `docs/AI-NETWORK-PROFILE.md`）
   - 项目推理资源画像（如 `docs/*-共享推理资源画像.md`）
4. **Thin Canonical References**：指向 Canonical Standards 的瘦引用文件（如 `docs/AI-NETWORK-STANDARD.md`）；
5. **Git 运行态快照 (Git State Snapshot)**：由导出脚本动态生成的 `GIT-STATE-SNAPSHOT.txt`，包含：
   - 当前 Commit Hash（`git rev-parse HEAD`）
   - 当前分支名称（`git branch --show-current`）
   - 当前工作区修改状态（`git status --short`）
   - 远程仓库列表与地址（`git remote -v`）
   - 最近 5 次提交日志（`git log -n 5 --oneline`）

### 2.2 严禁包含项 (Strict Exclusions)
- `.git/`、`.svn/` 目录
- `LocalConfig/`、`secrets/`、`credentials/` 目录
- `*.key`、`*.token`、`*.pem`、`*.crt`、`*.pfx`、`*.p12`、`id_rsa*`
- `.env`、`.env.local`、`.env.*.local`
- `.venv/`、`venv/`、`node_modules/`、`target/`、`dist/`、`build/`、`__pycache__/`
- `logs/`、`*.log`、`tmp/`、`temp/`
- 数据卷与本地数据库（`*.db`、`*.sqlite3`、`ragflow-volumes/` 等）
- 归档的失效交接：`docs/archive/**`、包含 `SUPERSEDED` 标记的旧文件

---

## 3. 标准打包工具实现

本规范在标准库的 `tools/` 目录中提供跨平台导出脚本：
- PowerShell 版本（Windows 宿主原生）：[`tools/export-project-context.ps1`](../tools/export-project-context.ps1)
- Bash 版本（WSL / Linux / macOS 原生）：[`tools/export-project-context.sh`](../tools/export-project-context.sh)

### 3.1 命令行调用语法
```powershell
# Windows PowerShell
pwsh D:\Projects\AI-Engineering-Standards\tools\export-project-context.ps1 -ProjectDir "D:\AI-KB\Repo\ai-kb-infra" -OutputDir "D:\AI-KB\ContextPacks"
```

```bash
# Bash / WSL
bash /mnt/d/Projects/AI-Engineering-Standards/tools/export-project-context.sh /mnt/d/AI-KB/Repo/ai-kb-infra /mnt/d/AI-KB/ContextPacks
```
