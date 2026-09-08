# AI 工程网络验证上下文交接（Canonical Handoff）

> 日期：2026-09-08  
> 当前规范：**V0.2 PRE-RELEASE**  
> Canonical Git：`git@github.com:xiefeifeihu/AI-Engineering-Standards.git`  
> 用途：交给新的 ChatGPT / Antigravity / Codex / 其它工程会话，快速恢复本机网络架构、验证机制、当前事实与禁止事项。  
> Source of Truth：Canonical Standards Git 中的网络规范；Project 内 `docs/AI-NETWORK-STANDARD.md` 是同步快照。

---

# 1. 当前状态

```text
NETWORK_SPEC_VERSION=V0.2
NETWORK_SPEC_STATUS=PRE_RELEASE

WARM_ACCEPTANCE=PASS
WINDOWS_PHYSICAL_RESTART=DONE
V0_2_COLD_START_ACCEPTANCE=PASS

AIKB_PROJECT_NETWORK_READY=true
VTIP_PROJECT_NETWORK_READY=true

FINAL_RELEASE_PENDING=true
```

重要：即使 Warm / Cold / Project Gate 都已经 PASS，**在用户明确批准正式定版前，禁止称 V1.0、V1.0_READY 或 V1.x**。

---

# 2. 当前机器 Canonical Network Baseline

```text
Windows 11
├─ Clash Party / Mihomo
│  ├─ Rule Mode
│  ├─ TUN enabled
│  ├─ Windows System Proxy = 127.0.0.1:<dynamic-port>
│  └─ 不把 7890/7891/7892 当永久事实
│
├─ WSL2 / Ubuntu 24.04
│  ├─ networkingMode=mirrored
│  ├─ dnsTunneling=true
│  ├─ autoProxy=false
│  └─ 内网 / 私网优先 DIRECT
│
└─ Docker
   ├─ 普通 Runtime：默认无 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY
   ├─ Docker Egress Gateway：host.docker.internal:17890
   ├─ Public-Egress Runtime：显式声明 Egress
   └─ Build：Proxy Probe -> Direct Probe -> Fail Fast
```

Tailscale / SD-WAN 已退出本机默认架构，不得重新引入作为常规路径。

---

# 3. 四类代理不要混淆

```text
Windows System Proxy
!= Docker Daemon Proxy
!= Docker Runtime Proxy Env
!= Application-level Proxy
```

典型错误：`docker info` 看到 Proxy，不代表业务容器继承了 Proxy；业务容器 `env` 纯净，也不能证明 dockerd 没有代理配置。

---

# 4. Docker Egress Gateway 当前事实

当前路径：

```text
Docker Container / Build
        ↓
host.docker.internal:17890
        ↓
WSL docker-proxy-relay.service
        ↓
Windows Clash 127.0.0.1:<dynamic-port>
```

当前资产：

```text
AI-KB Repo:
ops/network/docker-proxy-relay.py
ops/network/docker-proxy-relay.service
ops/network/docker-proxy-relay.sh
```

机器实际 systemd：

```text
docker-proxy-relay.service
```

关键事实：

- Python 标准库实现；
- 上游 Clash 端口动态发现；
- 稳定内部端口 17890；
- 绑定 loopback / Docker bridge gateway；
- 不向物理 LAN 暴露；
- 不要求 Clash `allow-lan`；
- Windows/WSL/Docker 分层实测已 PASS；
- 物理 Windows 重启后已自动恢复并通过 Cold Gate。

---

# 5. 网络治理的最重要结论：Machine / Project 解耦

此前发生过：AI 会话不知道另一个 Project 的真实业务域名，却直接猜 Endpoint 做验证，导致错误诊断。

因此从 V0.2 起强制：

> **Machine Core 只验证跨项目共享底座；每个 Project 自己读取真实配置、验证自己的实际网络通路。其它 Project 和 AI 不需要知道，也不允许猜。**

结构：

```text
Layer A: Machine Core Gate
    Windows / Clash
    WSL
    Docker bridge
    Docker Egress Gateway
    安全边界
          ↓
Layer B: Project Network Contract
    Project 自己的依赖 / Runtime / Build / Provider / DIRECT
          ↓
Layer C: Project Network Self-Test
    读取真实配置
    在真实 Runtime 验证
    输出统一 PASS/FAIL
```

---

# 6. 每个 Project 的强制标准入口

所有 Project 必须提供：

```text
scripts/network/network-gate.cmd
scripts/network/network-gate.sh
```

Windows：

```text
scripts\network\network-gate.cmd
```

WSL/Linux：

```text
./scripts/network/network-gate.sh
```

外部 AI、用户、CI 只依赖这两个入口，不依赖内部 Python 文件名。

Exit Code：

```text
0 = 所有 Required PASS
非 0 = Required FAIL 或 Gate 自身异常
```

Optional SKIP 不阻断 Project Ready。

---

# 7. 每个 Project 应有本地规范快照与 Profile

推荐 Project 结构：

```text
<project>/
├─ docs/
│  ├─ AI-NETWORK-STANDARD.md
│  └─ AI-NETWORK-PROFILE.md
├─ scripts/
│  └─ network/
│     ├─ network-gate.cmd
│     └─ network-gate.sh
└─ logs/
   └─ network/
```

其中：

- `docs/AI-NETWORK-STANDARD.md`：Canonical 网络规范的项目本地同步快照；
- `docs/AI-NETWORK-PROFILE.md`：只描述本 Project 的差异、配置来源、Runtime/Build/Provider、Gate 入口；
- Project Profile 尽量引用配置键，而不是复制真实 Endpoint；
- Project Snapshot 应记录 Canonical Repo / Version / Commit，便于发现漂移。

---

# 8. 标准日志 / JSON / Footer

目录：

```text
logs/network/
```

每次生成：

```text
network-gate-YYYYMMDD-HHMMSS.log
network-gate-YYYYMMDD-HHMMSS.json
network-gate-latest.log
network-gate-latest.json
```

日志目录必须 `.gitignore`。

统一 Footer：

```text
NETWORK_GATE_RESULT
project=<project-name>
overall=PASS|FAIL
required=<n>
passed=<n>
failed=<n>
optional_skipped=<n>
cold_start_verified=true|false
duration_ms=<n>

PROJECT_NETWORK_READY=true|false
```

JSON 至少记录：

```text
schema_version
project
started_at / finished_at / duration_ms
standard_version
boot_metadata.windows_last_boot
boot_metadata.wsl_boot_id
checks[]
summary.required/passed/failed/optional_skipped
project_network_ready
cold_start_verified
```

所有 stdout / log / JSON / SSE 必须先脱敏。

---

# 9. STALE 机制

旧 PASS 不是永久凭证。

以下变化后必须判 `STALE`：

- Windows LastBootUpTime 改变；
- WSL boot_id 改变；
- boot metadata 缺失；
- latest result 早于当前启动周期；
- 网络基础设施发生明显变化。

STALE：

```text
不得继续显示 NETWORK READY
不得自动跑 Gate
必须提示“需要重新验证”
```

---

# 10. Web Project / Module 的统一规则

只要 Project 或 Module 有 Web UI：

- Web 首页必须直接显示 Network Status；
- 首页必须能进入正式 Network 页面；
- 状态至少：`UNKNOWN / RUNNING / PASS / FAIL / STALE`；
- 显示最后验证时间；
- 显示 Cold Start；
- PASS 明确 `NETWORK READY`；
- FAIL 明确 `NETWORK BLOCKED`；
- STALE 明确“需要重新验证”；
- 首页加载不得自动运行 Gate。

如果一个 Project 有多个 Web Module，每个主要 Module 首页都必须链接 Project Network Status 或正式 Sub-Gate；不能为每个页面复制一套网络检测。

Web 与 CLI 必须执行同一个正式 Project Gate。

---

# 11. AI-KB 当前 Project Network Module

统一入口：

```text
scripts/network/network-gate.cmd
scripts/network/network-gate.sh
```

内部实现：

```text
ops/network/run_machine_network_gate.py
ops/network/run_project_network_gate.py
ops/network/run_network_gate.py   # compatibility wrapper
```

AI-KB Project Gate 当前验证：

```text
Machine Core
CPA Local root
CPA Management UI/API
CPA 127.0.0.1 bind
CPA Runtime Proxy Env isolation
Bailian real inference
Google OAuth transport
Gemini real inference
Gemini credential/quota
NVIDIA real inference
Control Center
RAGFlow
Ollama
Cloud CPA optional node
```

最近实测：

```text
Total=25
Required=24
Passed=24
Failed=0
Skipped=1 (Cloud Optional offline)
PROJECT_NETWORK_READY=true
```

---

# 12. AI-KB Web Network Center

Control Center：

```text
http://127.0.0.1:18090/
http://127.0.0.1:18090/network
```

AG-015 实机部署后已验证：

```text
GET /health             PASS
GET /                   PASS
首页 Network Status      PASS
GET /network            PASS
POST /network/run       PASS
SSE realtime log        PASS
Run -> RUNNING -> PASS  PASS
历史网络记录             PASS
```

当前 Web 可以显示：

```text
PASS / FAIL / RUNNING / UNKNOWN / STALE
Required / Passed / Failed / Skip
实时运行日志
子系统检测明细
Cloud CPA tunnel 只读状态
历史网络验收记录
```

---

# 13. AI-KB Web -> Host Gate Runner

AI-KB Control Center 本身在 Docker 中，无法安全直接运行 Windows PowerShell、宿主 Docker/WSL 网络诊断。

AG-015 引入 Project Adapter：

```text
aikb-network-gate-runner.service
/data/gate_run.trigger
```

行为：

```text
Web POST /network/run
  ↓
创建 Control Center Run
  ↓
触发 host runner
  ↓
host 调用 scripts/network/network-gate.sh --run-id <id>
  ↓
Run / RunEvent
  ↓
SSE 实时显示
```

关键边界：

- Web 与 CLI 使用同一个 Gate；
- Web 不直接获得通用 host shell；
- 同一时间最多一个 Gate；
- 有硬 timeout；
- 日志脱敏；
- 该 Runner 是 AI-KB Project Adapter，不是其它 Project 必须复制的 Machine Component；
- 其它 Project 若需要类似桥接，应自行设计最小、可审计 Adapter，并遵守系统服务人工批准规则。

---

# 14. AI-KB Cold Start 验收

Windows 已完成真实物理重启。

重启后未在 Gate 前进行手工网络修复。

自动恢复并验证：

```text
docker-proxy-relay.service
Docker Egress Gateway
cpa-local
Control Center
RAGFlow
Ollama
```

Cold Gate：PASS。

因此：

```text
V0_2_COLD_START_ACCEPTANCE=PASS
```

---

# 15. CPA Local 当前事实

```text
CPA Version = v7.2.149
Container = cpa-local
Host bind = 127.0.0.1:8317 only
Runtime HTTP(S)/ALL Proxy Env = none
Application Egress Gateway = host.docker.internal:17890
```

Provider：

```text
Bailian -> DIRECT
Gemini / Google -> Docker Egress Gateway -> Clash
NVIDIA -> Docker Egress Gateway -> Clash
```

当前已验证：

```text
Management PASS
Bailian PASS
Google OAuth PASS
Gemini PASS
Gemini Quota/Token PASS
NVIDIA PASS
```

曾经出现 NVIDIA Function 404；clean recreate `cpa-local` 后用户手工确认 Local / Cloud NVIDIA 均正常。因此不要再把该历史 404 当现行网络故障。

---

# 16. Cloud CPA 与标准 Tunnel Tool

Cloud CPA 不公开 VPS 8317，按需使用 SSH Local Forward。

逻辑：

```text
127.0.0.1:18317
→ SSH Local Forward
→ VPS 127.0.0.1:8317
```

SSH alias：

```text
aikb-vps-public
```

统一入口：

```text
scripts/cpa/cloud-cpa-tunnel.cmd
scripts/cpa/cloud-cpa-tunnel.sh
```

支持：

```text
start
stop
status
test
open
```

重要：

- `ssh -N` 是长生命周期进程；
- 成功不是等待进程退出；
- 成功 = process alive + local 18317 listening + Cloud CPA transport PASS；
- 已健康时 REUSE；
- 未知进程占 18317 时 FAIL，不杀；
- stop 只停止工具自己托管的 tunnel；
- 手工 tunnel 标 `EXTERNAL/MANUAL`，不得杀；
- Web 只读显示状态和 CLI 提示，Docker 内 Control Center 不启动 Windows `ssh.exe`；
- Cloud 默认 Optional，tunnel 未开启时 Project Gate SKIP，不阻断本地 READY。

---

# 17. VTIP / 其它 Project 的边界

AI-KB 与 Machine Core 不再保存或验证 VTIP 的具体业务 Endpoint。

当前事实只保留：

```text
VTIP 已建立自己的 Project Network Gate
Windows 冷重启后 VTIP 自己验证 PASS
VTIP_PROJECT_NETWORK_READY=true
```

任何新会话涉及 VTIP：

```text
进入 VTIP Repo
→ 读取 VTIP config / docs/AI-NETWORK-PROFILE.md
→ 运行 VTIP scripts/network/network-gate.cmd/.sh
```

不要从 AI-KB 文档猜 VTIP 的 Jira / Confluence / Runtime Endpoint。

---

# 18. Project Gate 失败时的工作流

```text
Read Canonical Standard
       ↓
Run Machine Core + Current Project Gate
       ↓
Required PASS ?
  ├─ YES -> continue engineering
  └─ NO  -> PROJECT_NETWORK_READY=false
            ENGINEERING_TASK=BLOCKED
                  ↓
             分层定位故障
                  ↓
             最小修复
                  ↓
        重跑完整受影响 Gate
```

禁止：

```text
浏览器能联网 -> 推断 Docker 正常
WSL 能联网 -> 推断 Runtime 正常
DNS 有结果 -> 推断 TCP/TLS/HTTP 正常
一个 Project PASS -> 推断另一个 Project PASS
```

---

# 19. Agent 权限边界

未经用户明确批准，不得自行：

```text
apt / apt-get install/remove
全局 pip/pipx/npm/cargo/go
winget/choco/MSI
新 systemd unit
新 Windows Service / Scheduled Task
新 proxy daemon / VPN / TUN / 虚拟网卡
持久 route/firewall
.wslconfig 网络修改
Docker daemon 全局 DNS/proxy/network 修改
```

所有 Agent：

- 不关闭 TLS；
- 不使用 `--trusted-host` 掩盖网络错误；
- 不因网络 timeout 改 requirements/model/provider；
- 不输出 Secret；
- 不无限等待；
- 网络修复后完整复验。

---

# 20. Canonical Git Source of Truth

用户已建立独立 GitHub Repository：

```text
git@github.com:xiefeifeihu/AI-Engineering-Standards.git
```

这个仓库应成为跨项目 AI Engineering Standard 的唯一 Canonical Source。

建议结构：

```text
AI-Engineering-Standards/
├─ README.md
└─ network/
   ├─ AI-NETWORK-STANDARD.md
   └─ AI-NETWORK-HANDOFF.md
```

AI-KB / VTIP 等 Project 各自保存同步快照，方便 Agent 在项目内直接读取。

日志不进 Git。

---

# 21. AI-KB 当前 Git / 任务状态

分支：

```text
feat/aikb-v0.4
```

网络相关关键 Commit：

```text
28c1441 fix(network): restore docker clash egress gateway and conformance gate
fe60436 fix(network): validate internal runtime transport
c16f9f0 feat(network): add project gate and web status
5a6b8f3 feat(network): standardize project gate and cloud tunnel tools
9bf745d feat(network): enable host gate runner daemon and SSE event listener for web ui
```

AG-012：

```text
stash@{0}
WIP: AG-012 dynamic model benchmarking and profiles
```

网络基线已经稳定，可以在 Canonical 文档/Git 同步完成后恢复 AG-012。

---

# 22. 给新的 AI 会话的最短 Bootstrap

```text
本机使用 AI Engineering Network Standard V0.2 PRE-RELEASE。

Canonical Git:
git@github.com:xiefeifeihu/AI-Engineering-Standards.git

开始任何 Docker / Build / Provider / 外网工作前：
1. 阅读本 Project docs/AI-NETWORK-STANDARD.md 与 AI-NETWORK-PROFILE.md；
2. 运行 scripts/network/network-gate.cmd 或 .sh；
3. Required FAIL 时停止业务任务，先修网络；
4. 不猜其它 Project Endpoint；
5. Machine Core 只验证公共底座；Project Gate 自己读取真实配置；
6. Runtime 默认无 HTTP(S)/ALL Proxy Env；
7. Docker 海外公网使用受治理的 Egress Gateway；
8. 内网 / 私网 DIRECT；
9. 修复后完整复验；
10. 不得擅自把 V0.2 发布为 V1.0。
```

---

# 23. 当前交接结论

```text
NETWORK_SPEC_VERSION=V0.2
NETWORK_SPEC_STATUS=PRE_RELEASE

MACHINE_NETWORK=PASS
AIKB_PROJECT_NETWORK_READY=true
VTIP_PROJECT_NETWORK_READY=true
V0_2_COLD_START_ACCEPTANCE=PASS

AIKB_WEB_NETWORK_CENTER=PASS
AIKB_WEB_REALTIME_GATE=PASS
CPA_LOCAL=PASS
CPA_CLOUD=OPTIONAL

FINAL_RELEASE_PENDING=true
```

后续推荐顺序：

```text
1. 将完整 Canonical V0.2 文档提交到 AI-Engineering-Standards GitHub Repo
2. AI-KB 项目内同步 Canonical Snapshot + AI-KB Profile
3. VTIP 按同一规范生成/完善自己的 Project Network Module
4. 不增加版本号，继续保持 V0.2 PRE-RELEASE
5. 用户最终确认正式发布时，再将 V0.2 -> V1.0 RELEASED
6. 恢复 AG-012 Model Benchmark
```
