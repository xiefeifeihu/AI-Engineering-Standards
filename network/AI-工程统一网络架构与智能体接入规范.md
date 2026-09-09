# AI 工程统一网络架构与智能体接入规范

> 适用范围：Windows 11 + WSL2 + Docker Engine/BuildKit + Clash Party/Mihomo 的本地 AI / Vibe Coding 工程。
>
> 本文面向两类读者：
>
> 1. **AI 聊天会话**：ChatGPT 等长期会话，用于理解本机统一网络架构、排障边界和不可变约束。
> 2. **编程智能体 / Vibe Coding Agent**：Antigravity、Codex 类智能体以及不同代码工程，用于实现一致的 Build / Runtime 网络行为。
>
> 目标：把“网络架构”从单个会话里的隐含知识变成**跨会话、跨项目、跨智能体的显式工程规范**。
>
> **文档版本：V0.2（PRE-RELEASE，2026-09-08）**  
> **状态：PRE-RELEASE；Warm / Cold 实机 Gate 已通过，但尚未由用户正式定版**  
> **Canonical Repository：`git@github.com:xiefeifeihu/AI-Engineering-Standards.git`**  
> **当前参考工程：AI-KB、VTIP Platform Catalog；各 Project 独立 Network Self-Test**  
> **本次整合重点：完整 Network Gate、Docker Egress Gateway、Project Network Module、统一 cmd/sh 与日志、Web Network Center、STALE、Cloud CPA Tunnel Tool、Git Source of Truth 与 Agent 治理。**

---


## 0A. 版本治理与定版规则

本规范在正式落地、完成完整 Network Conformance Gate 并进入稳定使用前，只允许使用 `V0.x`。

- `V0.x`：设计、试运行、实机验证、修正阶段；
- `V1.0`：第一次完成机器级完整 Gate、参考工程回归并正式投入日常使用后定版；
- `V1.x`：V1.0 后向后兼容增强；
- `V2.0`：只有发生明确不兼容的网络架构升级时才使用。

此前未正式落地即使用 `v2.0` 命名的草案不作为正式版本。版本线按：

```text
原始规范草案       -> V0.1
本次完整修订       -> V0.2
完整 Gate 正式通过 -> V1.0
```

预发布阶段不要因文字修订频繁升级版本；小修订使用日期、Git Commit 和变更记录。

### V1.0 定版条件

必须同时满足：

1. Canonical Network Baseline 已按本文落地；
2. 完整 Network Conformance Gate 所有 Required 项 PASS；
3. Windows、WSL、Docker Runtime、Docker Build、Public-Egress Runtime 必需链路均通过实机验证；
4. 至少 AI-KB 与 VTIP Platform Catalog 两个参考工程回归 PASS；
5. 网络修复后的完整复验机制已有稳定脚本或固定入口；
6. Agent 安装/系统级变更权限边界已落地；
7. 文档、脚本、运行状态一致；
8. 用户明确批准正式发布。

当前预发布状态固定为：

```text
NETWORK_SPEC_VERSION=V0.2
NETWORK_SPEC_STATUS=PRE_RELEASE
V0_2_COLD_START_ACCEPTANCE=PASS
FINAL_RELEASE_PENDING=true
```

即使技术验收已经通过，在用户明确宣布正式定版前，也不得在代码、文档、Web、日志或 Agent 报告中写 `V1.0_READY=true` 或将规范标为 `V1.x`。

---

## 0. 结论先行

本机统一网络采用以下原则：

```text
Windows 11
├─ Clash Party / Mihomo
│  ├─ 正常模式：规则（Rule）
│  ├─ TUN / 虚拟网卡：开启
│  ├─ Windows 系统代理：127.0.0.1:<动态代理端口>
│  └─ 常见 Mihomo listener：7890 / 7891 / 7892
│
├─ WSL2
│  ├─ networkingMode=mirrored
│  ├─ dnsTunneling=true
│  ├─ autoProxy=false
│  ├─ WSL Shell 可显式使用 Windows loopback 代理
│  ├─ 不把 Windows TUN 可见性假定为 WSL / Docker 的事实
│  └─ 内网域名 / 私网地址保持 DIRECT
│
└─ Docker
   ├─ Runtime 容器：默认不注入 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY
   ├─ 普通 Runtime：内部服务与私网 DIRECT
   ├─ 公网出站 Runtime：由业务显式声明 egress 策略，不继承宿主开发代理
   │  ├─ DNS 必须从该 Runtime 实际网络命名空间验证
   │  ├─ 若 Fake-IP 无对应 TUN 路由，必须改用可达的真实 IP 解析路径
   │  └─ 代理、DNS、路由均不得靠“浏览器能访问”推断
   ├─ BuildKit：构建前执行网络 Preflight
   │  ├─ 动态发现 Windows Proxy Candidate
   │  ├─ 从 Docker bridge 真实验证 Proxy -> 目标站点
   │  ├─ Proxy 不可用时再验证 Docker Direct
   │  └─ Proxy、Direct 都失败时 FAIL FAST，不进入正式 build
   └─ 内部服务：DIRECT，不经公共 Proxy
```

核心思想不是“所有流量都走代理”，而是：

> **按网络层、流量方向、DNS 解析路径和服务类型分治。Build 流量按需使用动态代理；普通 Runtime 保持纯净；确需公网出站的 Runtime 必须有显式 egress 设计；公司内网和私网永远优先直连。**

本规范新增一个重要边界：

> **“Runtime 默认无代理”不等于“Runtime 不允许公网访问”。** 需要公网出站的长期 Runtime（例如 AI-KB 的 `cpa-local`）可以被明确批准访问公网，但必须通过项目级 Runtime Egress 规范确定 DNS、路由、Provider 分工和降级策略，且不得把宿主机开发代理环境变量无差别注入容器。

---


# 第零部分：Network Conformance Gate

## G1. 规范必须可执行，而不是只描述配置

任何依赖 Docker、BuildKit、外网 Provider、RAG/AI Runtime 的正式工程任务，在进入实质执行前必须证明当前网络基线有效。

```text
Load Canonical Standard
        ↓
Run Full Network Gate
        ↓
All Required PASS?
  ├─ YES -> NETWORK_READY=true -> Continue Engineering
  └─ NO  -> NETWORK_READY=false -> STOP -> Network Repair
                                      ↓
                               Minimal Repair
                                      ↓
                               Re-run FULL Gate
```

**单点恢复不等于网络恢复。** 例如 `CPA -> Bailian PASS` 不能推出 Docker Build、Google、内部 DIRECT 或其它 Runtime 也正常。

## G2. Gate 分层

### G2.1 L1 Windows

Required：

- Clash/Mihomo 进程存在；
- Rule 模式；
- TUN enabled；
- Windows System Proxy enabled；
- 动态读取 System Proxy 成功；
- 国内公网 HTTPS 快速到达；
- 海外公网 HTTPS 经 Clash 快速到达；
- 公司内网/私网未被公共代理破坏。

HTTP `400/401/403/404/405` 等只要快速返回，均可作为“网络到达”的证据。

### G2.2 L2 WSL

Required：

- `networkingMode=mirrored`；
- `dnsTunneling=true`；
- `autoProxy=false`；
- WSL Shell 到 Windows loopback proxy 可达；
- WSL 经 canonical proxy 访问国内/海外公网 PASS；
- 内部域名和私网 DIRECT。

Direct Probe 单独记录。Direct FAIL 不自动判整个 WSL FAIL，只要当前规范要求的 canonical proxy path PASS。

### G2.3 L3 Docker Runtime / bridge

Required：

- Docker DNS/bridge 基本正常；
- 普通 Runtime 无 Proxy Env；
- Docker Egress Gateway（如启用）必须从 Docker bridge 真实可达；
- 国内公网路径按设计可用；
- 海外公网路径按设计可用；
- 内部域名/RFC1918 DIRECT；
- Public-Egress Runtime 必须从目标容器自身 network namespace 验证。

### G2.4 L4 Docker Build / BuildKit

Required：

```text
Proxy Probe PASS -> PROXY BUILD
Proxy FAIL -> Direct Probe
Direct PASS -> DIRECT BUILD
Proxy FAIL + Direct FAIL -> FAIL FAST
```

`Docker Direct FAIL` 不等于 `Docker Network FAIL`。合法状态是：

```text
Docker Proxy PASS
Docker Direct FAIL
Docker Build Network PASS proxy
```

### G2.5 L5 Application Runtime

按实际应用验证：

- CPA Local -> Bailian；
- CPA Local -> Google/Gemini（若本地 Gemini 是当前设计能力）；
- CPA Local -> NVIDIA（若启用）；
- Control Center；
- RAGFlow；
- Ollama；
- 其它声明公网 Egress 的 Runtime。

必须验证到应用层，不能只用 host `curl` 代替。

### G2.6 L6 Project Network Gates

Machine Core Gate 到此为止，不直接验证任何业务 Project 的私有 Endpoint。

每个 Project 必须通过自己的标准入口完成业务网络验收：

```text
Machine Core Gate
    PASS
      ↓
Current Project Gate
    PASS
      ↓
PROJECT_NETWORK_READY=true
```

要求：

- Project Gate 从本项目真实 `config/env/compose/registry` 读取 Endpoint；
- Project Gate 负责自己的 Runtime、Build、Provider、internal DIRECT、auth-safe smoke；
- Machine Core Gate 不得硬编码另一个 Project 的域名、端口、Jira/Confluence、数据库或 Provider；
- 跨项目总验收只能通过“调用各 Project 稳定 Gate 入口并聚合结果”实现，不能由某一个 Project 替其它 Project 做业务验收；
- 当前参考工程 AI-KB 与 VTIP 均已经按该模型完成 Cold-Start 实机验证。

## G3. Gate 失效条件

以下事件发生后，之前的 `NETWORK_READY` 自动失效：

- Windows/WSL 重启；
- `wsl --shutdown`；
- Docker daemon restart；
- Clash/Mihomo 重启或配置切换；
- Windows System Proxy 端口变化；
- `.wslconfig` 网络字段变化；
- DNS 策略变化；
- Docker daemon network/DNS/proxy 变化；
- Docker Egress Gateway 变化；
- 防火墙/路由/VPN/TUN 变化；
- 新出现跨层网络异常。

任何已保存 PASS 在启动周期变化后必须失效为 `STALE`。至少检查：

- Windows `LastBootUpTime`；
- WSL `/proc/sys/kernel/random/boot_id`；
- Gate 结果生成时间是否早于当前启动周期；
- boot metadata 是否缺失。

`STALE` 不得继续显示绿色 PASS，也不得自动运行 Gate；必须明确提示“需要重新验证”。

建议生成 `network-readiness.json`，记录时间、规范版本、分层结果、参考工程和 `overall=PASS|FAIL`，不得记录 Secret。

## G4. 网络失败即阻断

任一 Required path FAIL：

```text
NETWORK_READY=false
ENGINEERING_TASK=BLOCKED
```

先进入本文 Network Repair Decision Tree。修复后必须执行**完整 Gate**，只有全部 Required PASS 才允许恢复原任务。

---

# 第一部分：统一网络分层

## 1. Windows 主机层

### 1.1 标准运行状态

本机正常开发状态：

- Clash Party：**规则模式（Rule）**
- Clash Party / Mihomo TUN / 虚拟网卡：**开启**
- Windows 系统代理：开启
- 系统代理常见形式：

```text
127.0.0.1:7890
```

注意：端口不是永久常量。不同 Clash/Mihomo 配置可能使用不同 listener。

### 1.2 不将固定端口当作架构事实

历史上真实出现过：

```text
7890
7891
7892
```

因此：

- 可以保留 7892 作为兼容候选；
- 可以保留 7890 作为常见兼容候选；
- **不能把 7890 或 7892 写死为唯一事实**；
- 优先动态读取 Windows System Proxy；
- 必要时只读查询 Mihomo/Clash listener。

### 1.3 Windows 内网与外网职责

Windows 浏览器和桌面应用可以使用 Windows 系统代理/TUN。

但必须牢记：

> Windows 浏览器能访问外网，不等于 WSL 能访问；WSL 能访问，不等于 Docker bridge / BuildKit 能访问。

任何工程不得用“浏览器正常”作为 Docker build 网络健康证明。

---

## 2. WSL2 网络层

### 2.1 Canonical `.wslconfig`

统一基线：

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=false
```

其他资源参数可按设备配置，但网络原则保持：

- mirrored networking
- dns tunneling
- **不依赖 WSL 自动代理注入**

### 2.2 为什么 `autoProxy=false`

原因是工程要掌握代理使用边界，而不是让 WSL 把 Windows 代理无差别传播给所有进程、构建和 Runtime。

我们希望：

```text
WSL Shell 外网工具
    可以显式使用代理

Docker Build
    按 Preflight 决策是否使用代理

Runtime 容器
    默认无代理

公司内网 / 私网
    DIRECT
```

### 2.3 WSL Shell Proxy

标准 Shell 环境可存在：

```bash
HTTP_PROXY=http://127.0.0.1:<dynamic-port>
HTTPS_PROXY=http://127.0.0.1:<dynamic-port>
http_proxy=http://127.0.0.1:<dynamic-port>
https_proxy=http://127.0.0.1:<dynamic-port>
```

但 `NO_PROXY` 至少应覆盖：

```text
localhost
127.0.0.1
::1
host.docker.internal
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
sensha.top
.sensha.top
```

如公司新增内部根域，应加入 DIRECT_ONLY 列表。

### 2.4 WSL 访问 PyPI 的判断

若 `curl -I https://pypi.org/...` 输出：

```text
HTTP/1.1 200 Connection established
```

通常表示 HTTPS 连接经过 HTTP CONNECT Proxy。

因此不能把普通 `curl` 称为“直连”。

要验证真正直连，必须显式清除 proxy env 并使用：

```bash
env \
  -u HTTP_PROXY \
  -u HTTPS_PROXY \
  -u ALL_PROXY \
  -u http_proxy \
  -u https_proxy \
  -u all_proxy \
  curl --noproxy '*' ...
```

### 2.5 `dnsTunneling`、Clash Fake-IP 与 WSL Mirrored 的边界

`dnsTunneling=true` 解决的是 WSL DNS 解析入口一致性，不保证 Windows 上的所有 TUN / Wintun 路由能力都能透明出现在 Linux 网络命名空间中。

AI-KB / CPA 在本机已验证到以下真实故障模式：

```text
Windows / Mihomo DNS
    ↓
返回 198.18.x.x Fake-IP
    ↓
WSL / Docker 能“解析”域名
    ↓
Linux 路由表却没有可到达该 Fake-IP 的 TUN 路径
    ↓
TCP SYN 被送往普通默认网关
    ↓
5~15 秒超时
```

因此：

- **DNS 有结果不等于网络 PASS**；
- 公网域名解析到 `198.18.x.x` 时，必须继续验证 TCP/TLS/HTTP；
- 如果 WSL 显式代理访问 PASS，而真正 Direct 访问超时，应判定为“Direct / TUN 可见性问题”，不能把问题归咎于业务 API；
- 不允许为了规避该问题把 `autoProxy` 改成 `true`，也不允许给全部 Runtime 注入 `HTTP_PROXY/HTTPS_PROXY`；
- 需要公网出站的 Docker Runtime 可以按项目规则使用可验证的真实公网 DNS，避免不可路由 Fake-IP；
- 该结论是**当前机器的已验证事实**，不应泛化成“所有 WSL mirrored 环境必然无法使用 TUN”。其他机器必须重新验证。

---

# 第二部分：Docker 网络架构

## 3. Docker Runtime 与 Docker Build 必须分开

这是整个统一网络架构最重要的边界。

### 3.1 Docker Runtime：默认纯净原则

运行中的业务容器默认必须没有：

```text
HTTP_PROXY
HTTPS_PROXY
http_proxy
https_proxy
ALL_PROXY
all_proxy
VTIP_HTTP_PROXY
```

目的：

1. 公司内部 Jira / Confluence / GitLab 等流量不应绕经 Clash；
2. 避免宿主代理端口变化影响长期 Runtime；
3. 避免 Secret / 代理配置写入 Compose 或镜像；
4. 避免多个项目共享宿主代理状态导致不可预测故障；
5. 保持 Runtime 与 Build 网络生命周期分离。

默认 Runtime 网络策略：

```text
内部域名 / 私网服务 -> DIRECT
localhost / host.docker.internal -> DIRECT
普通业务 Runtime     -> 不继承开发代理
公网出站需求           -> 必须由项目显式声明 Runtime Egress
```

特别禁止在 Docker daemon 或 Runtime 中长期硬编码：

```text
http://127.0.0.1:7890
http://127.0.0.1:7892
```

原因：端口不是永久架构事实，且 `127.0.0.1` 在不同网络命名空间中的含义不同。

### 3.2 公网出站 Runtime（Public-Egress Runtime）

某些长期运行服务确实需要主动访问公网 API，例如：

- LLM / AI Provider Gateway；
- Webhook / SaaS API Client；
- 公网对象存储或第三方服务；
- AI-KB 的 `cpa-local`。

这类服务不是普通“内部 Runtime”，必须显式声明：

```text
runtime_egress = enabled
required_public_domains = [...]
direct_only_domains = [...]
dns_strategy = ...
proxy_env = none
application_proxy = optional/project-specific
```

默认规则：

1. **仍然不继承宿主 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`**；
2. 先从该容器自己的 network namespace 验证 DNS/TCP/TLS/HTTP；
3. 国内公共 API 能 Direct 时优先 Direct；
4. 海外公网如需要 Clash，应使用受治理的 Docker Egress Gateway，而不是把 Windows IP/Clash 动态端口写进容器；
5. 如 DNS 返回 Fake-IP 且该 namespace 无可达 TUN 路由，必须切换到可达的真实 IP 解析路径或按项目策略经 Gateway；
6. Application-level proxy 只能指向稳定的 Docker Egress Gateway 接口，不直接依赖 Windows 动态快照；
7. 内部域名与 RFC1918 仍必须 DIRECT；
8. 任何 DNS 覆盖都必须验证不会破坏内部域名解析。

DNS 与路由必须分开判断：

```text
DNS PASS
≠
TCP PASS
≠
TLS PASS
≠
HTTP PASS
```

只有目标服务在实际 Runtime namespace 中完成至少 TCP/TLS/HTTP 到达，才可称为 egress PASS。


### 3.2A 必须区分四种代理

排障和设计时必须明确区分：

1. **Windows System Proxy**：Windows 应用和 WSL 显式代理入口；
2. **Docker Daemon Proxy**：`docker info` 中的 HTTP/HTTPS Proxy，主要影响 dockerd 自己的 Registry/Pull 等出站；
3. **Docker Runtime Proxy Env**：容器内 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`，普通 Runtime 默认禁止；
4. **Application-level Proxy**：例如 CPA 的 `proxy-url`，属于应用自身 Egress。

必须牢记：

```text
Docker Daemon Proxy != Runtime Proxy Env != Application Proxy
```

因此 `docker info` 显示 Proxy 不能证明 Runtime 继承了 Proxy；反过来，Runtime Env 纯净也不能证明 dockerd 没有代理配置。

### 3.2B Docker Egress Gateway

本机需要一个受治理的 Docker Egress Gateway，用于把 Docker bridge / Public-Egress Runtime 的**明确海外公网需求**转交给 Windows Clash，而不打开 Clash LAN exposure，也不向所有 Runtime 注入代理环境变量。

逻辑：

```text
Windows Clash/Mihomo
127.0.0.1:<dynamic-port>
        ▲
        │ dynamic discovery
WSL Docker Egress Gateway
<stable internal interface>
        ▲
        │ host.docker.internal / host-gateway
        ├─ Docker Build
        └─ Public-Egress Runtime
```

约束：

- 上游 Clash port 动态发现，不写死 7890；
- 下游允许定义稳定机器级接口，如 `AI_DOCKER_PROXY_HOST` / `AI_DOCKER_PROXY_PORT`；
- 稳定端口是 Gateway 接口，不是 Clash port；
- Gateway 只允许本机 WSL/Docker 使用，不得向物理 LAN 暴露；
- 不允许为此开启 Clash `allow-lan`；
- 普通 Runtime 仍无 Proxy Env；
- Build 可把 Gateway 作为最高优先级 Proxy Candidate；
- Public-Egress Runtime 可把 Gateway 作为 application-level proxy；
- 内部域名/RFC1918 必须 Direct。

实现优先：已有 OS/标准组件 -> Python 标准库等最小可审计实现 -> 经用户批准的第三方组件。Agent 不得为了省事静默安装新的代理 daemon。

### 3.3 Docker Build

BuildKit 是另一套网络上下文。

它不应假设：

```text
Windows 系统代理
=
WSL Shell 代理
=
Docker bridge 代理
=
BuildKit 代理
```

正确方式：

> **在正式 build 之前，执行 Docker-side Network Preflight。**

### 3.4 AI-KB `cpa-local` 的目标 Runtime Egress Profile

AI-KB 是当前本机 Public-Egress Runtime 的参考工程。V0.2 规定其**目标架构**如下，只有完整 Gate PASS 后才能称为已验证事实：

```text
CPA Local
- WSL2 Docker
- Runtime Proxy Env = none
- Host publish = 127.0.0.1:8317 only
- Bailian/国内 Provider -> DIRECT 优先
- Gemini/Google/NVIDIA -> Docker Egress Gateway -> Clash
- 不直接写 Windows IP/Clash 动态端口

CPA Cloud
- 海外 VPS
- SSH Local Forward on demand
- 可作为海外 Provider 加速/备用节点
- 不替代本地网络基线
```

DNS 原则：

- 避免目标 namespace 使用无可达路由的 `198.18.x.x` Fake-IP；
- per-service DNS 优先于 daemon 级全局覆盖；
- `223.5.5.5`、`119.29.29.29` 只作为 AI-KB 当前已验证实现候选，不升格为所有工程的永久机器级常量；
- daemon 级 DNS 若需要变更，必须人工批准并执行完整 Gate 回归。

对 Provider：

- 国内 Provider 能 Direct 则 Direct；
- 海外 Provider 本地调用应经 Docker Egress Gateway；
- 若 CPA 当前版本支持 provider/credential 级 direct override，可给 Bailian 设置 Direct；字段名必须从 pinned 版本 schema/help/官方配置确认，禁止猜。

对 OAuth：

```text
Google endpoint timeout -> network_unavailable
Google HTTP reachable + refresh fail -> credential_refresh_error
```

只有第二种才重新授权。

---

# 第三部分：Docker Build Network Preflight

## 4. Build Preflight 的标准状态机

```text
Candidate Discovery
      ↓
Docker-side Proxy Probe
      ↓
 ┌───────────────┐
 │ Proxy 可用？   │
 └───────┬───────┘
         │ YES
         ▼
    PROXY BUILD
         │
         └─────────────┐
                       │
         NO            │
         ▼             │
Docker-side Direct Probe
         │             │
 ┌───────▼───────┐     │
 │ Direct 可用？ │     │
 └───────┬───────┘     │
         │ YES          │
         ▼              │
    DIRECT BUILD        │
                        │
         NO             │
         ▼              │
      FAIL FAST ◄───────┘
```

禁止：

```text
Proxy Probe FAIL
→ 不验证 Direct
→ 直接启动无代理 Docker build
→ pip 等 100 秒后才报错
```

---

## 5. Proxy Candidate Discovery

### 5.1 Candidate Host 来源

按动态发现处理：

1. WSL 默认网关；
2. `/etc/resolv.conf` nameserver；
3. Windows PowerShell 返回的 IPv4；
4. `host.docker.internal`；
5. TUN 地址作为低优先级候选。

Windows IPv4 必须：

- 排除 loopback；
- 排除 unspecified；
- 排除 link-local `169.254.*`；
- 普通 RFC1918 私网地址优先；
- TUN 类 `198.18.*` 后置。

### 5.2 Candidate Port 来源

优先级：

1. `VTIP_PROXY_PORT` 显式 override；
2. Windows System Proxy 动态端口；
3. 兼容默认 `7892`；
4. 常见兼容 `7890`。

候选端口必须有限，不允许扫描整个端口范围。

### 5.3 Windows System Proxy 动态解析

可只读：

```powershell
(Get-ItemProperty `
  -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
).ProxyServer
```

支持解析：

```text
127.0.0.1:7890
http://127.0.0.1:7890
http=127.0.0.1:7890;https=127.0.0.1:7890
```

---

## 6. Docker-side Proxy Probe

只在 Docker 网络视角验证才有意义。

前提：基础镜像已缓存。

例如：

```text
python:3.12.11-slim-bookworm
```

测试至少包含：

1. `socket.create_connection(host, port)`；
2. TCP timeout 约 1.5s；
3. Docker bridge 内经该 proxy 请求：
   `https://pypi.org/simple/requests/`
4. HTTP 必须返回 200；
5. 单 candidate 有界短重试；
6. 推荐最多 2 次，间隔约 0.5s。

如果 base image 不存在：

- 不允许为了“代理检测”触发隐式无限 pull；
- 降级到 host-level probe；
- 输出 degraded diagnostic。

---

## 7. Docker-side Direct Probe

所有 Proxy candidate 失败后才能检查 Direct。

必须在 Docker 网络视角：

- 清空/禁用 Proxy；
- 请求 PyPI；
- HTTP 200 才 PASS。

如果：

```text
Proxy FAIL
Direct FAIL
```

则：

```text
Docker Build Network FAIL
Docker Build SKIPPED
exit 1
```

不得进入正式 Dockerfile build。

---

## 8. Build Strategy

### Proxy 模式

```text
Docker Build Network   PASS proxy
Docker Build Proxy     http://<dynamic-ip>:<dynamic-port>
Proxy Probe            PASS pypi=200
```

仅构建期注入：

```text
HTTP_PROXY
HTTPS_PROXY
http_proxy
https_proxy
```

### Direct 模式

```text
Docker Build Network   PASS direct
Docker Direct PyPI     PASS 200
Docker Build Proxy     none
```

不得注入 proxy build args。

### Fail Fast

```text
Docker Build Network   FAIL
Proxy Probe            FAIL
Docker Direct PyPI     FAIL
Docker Build           SKIPPED
```

必须在正式 build 前退出。

## 8A. Runtime Egress Preflight（长期公网出站容器）

Build Preflight 与 Runtime Egress Preflight 必须分开。

Runtime Egress 标准诊断层级：

```text
L1 Windows
  ↓
L2 WSL
  ↓
L3 Docker bridge / target container namespace
  ↓
L4 DNS -> TCP -> TLS -> HTTP
  ↓
L5 Application Runtime client
```

### 8A.1 Windows

验证：

- System Proxy；
- Clash/Mihomo 进程；
- TUN 状态；
- 动态 listener；
- 目标公网服务从 Windows 是否可达。

### 8A.2 WSL

必须分别验证：

```text
WSL Proxy
WSL True Direct
```

True Direct 要清除所有 proxy env 并使用 `--noproxy '*'`。

如果：

```text
WSL Proxy PASS
WSL Direct FAIL
```

说明透明 TUN / Direct 路径不能被假定为 WSL 可用，继续进入 Docker namespace 诊断。

### 8A.3 Docker bridge 与目标容器 namespace

至少测试：

1. 普通 Docker bridge；
2. 实际目标容器 network namespace。

推荐：

```bash
docker run --rm   --network container:<target-container>   <cached-diagnostic-image>   ...
```

不要只在 WSL host 上 `curl` 就判 Docker Runtime PASS。

### 8A.4 Fake-IP 黑洞判定

如果公共域名在容器中解析为 `198.18.x.x`，但 TCP 连接超时：

1. 记录当前 resolver；
2. 用一个已验证的公共 DNS 进行**诊断性**解析；
3. 如果得到真实公网 IP 并快速 TCP/TLS 成功，则根因属于 DNS/Fake-IP 与路由路径不一致；
4. 采用项目级 DNS 策略修复，而不是修改业务 Provider、TLS 或依赖版本。

### 8A.5 Fail Fast

公网 Runtime 诊断必须有界：

- Connect timeout 推荐 `<= 5s`；
- 单目标 total timeout 推荐 `<= 10s`；
- 一次失败后进入下一层，不连续重复同一请求；
- DNS、TCP、TLS、HTTP 分别记录；
- 所有测试日志脱敏。

标准输出建议：

```text
Runtime Egress Layer     L3 container:cpa-local
DNS                      PASS real-ip=<redacted>
TCP 443                  PASS 9ms
TLS                      PASS
HTTP                     PASS status=200
Runtime Proxy Env        none
Runtime Egress           PASS direct
```

---

# 第四部分：内部网络和安全边界

## 9. DIRECT_ONLY

以下原则默认适用于所有本机工程：

### 公司内部域名

```text
sensha.top
*.sensha.top
```

必须直接连接。

如新增：

```text
corp.example
*.corp.example
```

应加入统一 DIRECT_ONLY。

### 私网

```text
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
localhost
127.0.0.1
::1
host.docker.internal
```

默认 DIRECT。

### DNS 与 DIRECT_ONLY 的关系

`DIRECT` 不只意味着“不经过 HTTP Proxy”，还意味着：

- 域名解析路径不能把内部域名发送到不受控的公共 DNS；
- 内部域名得到的地址必须走内部路由；
- 公共 Runtime 为解决 Fake-IP 使用公共 DNS 时，不得破坏 `sensha.top` / 私网等内部解析需求。

因此：

> **公共 DNS Override 只应该应用到确实需要它的 Runtime，或经过整机回归证明可作为 Docker 默认 DNS。**

若某个容器同时需要公司内网与公网，应使用可验证的 split DNS / 项目级 resolver 设计，不允许简单“全部改成 223.5.5.5”后把内部域名解析问题留给运行期。

### 禁止事项

禁止把内部 Jira / Confluence / GitLab Token、Cookie 或 Authorization 流量为了“方便联网”绕经公共 Proxy。

禁止在诊断日志输出：

```text
Authorization
Bearer
Jira Token
Confluence Secret
PAT
secrets.env
```

---

# 第五部分：AI 聊天会话必须知道的网络架构

## 10. AI Chat 的职责

新的 ChatGPT 长期会话、项目会话或任何 AI 助手，开始参与工程前必须知道：

### 10.1 不允许重新设计已定版网络

以下作为 Canonical Fact：

```text
Windows 11
+
WSL2 mirrored networking
+
dnsTunneling=true
+
autoProxy=false
+
Clash Party / Mihomo
+
规则模式
+
TUN 开启
```

除非用户明确要求重新设计，否则 AI 不应建议：

- 把 `.wslconfig` 改回 NAT；
- 全局打开 WSL autoProxy；
- 给所有 Docker Runtime 注入代理；
- 把公司内网流量送入 Clash；
- 硬编码当前 Windows IP；
- 硬编码唯一 Clash 端口。

### 10.2 网络问题的诊断顺序

AI 不得因为“浏览器能联网”就说 Docker 网络正常。

统一按以下层次判断：

```text
L1 Windows
L2 WSL
L3 Docker Runtime / bridge
L4 BuildKit
L5 Application Runtime
```

一个层 PASS 不能替代下一层验证。

### 10.3 AI 应区分网络错误与业务错误

典型：

```text
pip:
No matching distribution found
```

如果前面连续出现：

```text
Connection to pypi.org timed out
```

首先判定为网络问题，而不是 Python package 不存在。

### 10.4 AI 不得先重复耗时操作

若一次正式 build 已因网络 timeout 等待约 100 秒失败：

- 不应立即重复第二次相同 build；
- 应先运行网络 preflight；
- 确认 strategy 后再 build。

### 10.5 遇到长期公网出站 Runtime 时的职责

当某个 Docker Runtime 明确需要访问公网时，AI 不得直接套用 Build Proxy 方案，也不得简单建议“给 Compose 加 HTTP_PROXY”。

必须先回答：

```text
它是不是长期公网出站 Runtime？
它访问哪些外部域？
哪些域必须 DIRECT？
DNS 在目标容器 namespace 中返回什么？
返回的是 Real IP 还是 Fake-IP？
TCP/TLS/HTTP 哪一层失败？
应用自身是否还配置 proxy-url？
```

AI-KB 的已验证经验：

```text
Windows PASS
WSL Proxy PASS
WSL Direct FAIL
Docker Fake-IP timeout
Docker 指定公共 DNS -> Real IP -> Direct PASS
```

这种情况应在 Runtime DNS / 路由层解决，不应去修改模型、OAuth、API Key、TLS 或 requirements。

---

# 第六部分：Vibe Coding / 编程智能体工程规范

## 11. 每个 Project 必须显式携带网络规范与 Network Module

不能依靠智能体“记得另一个会话讨论过什么”。

### 11.1 Canonical Source of Truth

跨项目网络标准的唯一 Canonical Git Source 为：

```text
git@github.com:xiefeifeihu/AI-Engineering-Standards.git
```

建议仓库结构：

```text
AI-Engineering-Standards/
├─ README.md
└─ network/
   ├─ AI-NETWORK-STANDARD.md
   └─ AI-NETWORK-HANDOFF.md
```

OneDrive、ChatGPT 下载件、聊天粘贴文本只能作为副本，不是 Source of Truth。

### 11.2 每个 Project 的必需结构与 Canonical 引用规范

AI-Engineering-Standards 仓库是本机唯一的 **Canonical Source of Truth**。
为防止跨项目文档冗余、版本漂移与事实割裂，**正式废弃向各项目完整复制 61KB/15KB 全量规范正文的旧做法**，全面采用 **“Thin Markdown Reference（瘦引用）+ Project Profile（项目画像）”** 的分层治理架构：

```text
<project-root>/
├─ docs/
│  ├─ AI-NETWORK-STANDARD.md   # Thin Canonical Reference（记录规范版本、Commit SHA、引用路径）
│  └─ AI-NETWORK-PROFILE.md    # 仅描述本 Project 的差异、配置来源与 Gate
├─ scripts/
│  └─ network/
│     ├─ network-gate.cmd
│     └─ network-gate.sh
└─ logs/
   └─ network/                 # 运行生成，必须 gitignore
```

**关键约束**：
1. **Thin Markdown Reference**：项目内 `docs/AI-NETWORK-STANDARD.md`（或其软链接名称对应文件）只需记录标准库地址、规范版本、同步 Commit SHA 与核心原则摘要，指向 Canonical Source，严禁全量拷贝正文；
2. **严禁跨项目文件系统链接**：**严禁使用 Windows symlink、directory junction 或 hard link 跨工程跨盘引用文档**，避免在跨盘、跨系统、压缩包打包/解压或 CI 构建时失效；
3. **Project Profile 专注自身事实**：项目特有网络拓扑、出站网关映射、差异化 Gate 检查记录在 `docs/AI-NETWORK-PROFILE.md`。

### 11.3 Project Network Module 职责

Project 自己负责：

```text
真实 Endpoint
Runtime / Network Namespace
Docker Build 依赖
Provider / SaaS API
Internal DIRECT
Auth-safe Smoke
Required / Optional
Web Module / Sub-Gate
```

所有 Endpoint 优先从项目真实配置读取，不得在 Gate 中复制一份地址，更不得让其它 Project 或 AI 猜测。

### 11.4 统一稳定入口

所有 Project 对人、AI、CI 暴露且只承诺以下稳定入口：

```text
Windows: scripts
etwork
etwork-gate.cmd
WSL/Linux: ./scripts/network/network-gate.sh
```

内部可以委托 `ops/network/*.py` 或其它实现，但外部不依赖实现文件名。

---

## 12. 编程智能体的强制约束

任何 Antigravity / Codex / Vibe Coding Agent 收到工程任务时，应同时得到：

```text
【统一网络架构约束】

1. Windows + WSL2 mirrored networking。
2. Clash/Mihomo 作为开发宿主外网能力。
3. 不硬编码 Windows IP。
4. 不硬编码唯一 Proxy Port。
5. Build 前动态 discovery + Docker-side probe。
6. Proxy 不可用时必须验证 Docker Direct。
7. Proxy/Direct 都失败时 FAIL FAST。
8. Build Proxy 仅以 build args 使用。
9. Runtime 容器不得继承 HTTP_PROXY/HTTPS_PROXY。
10. sensha.top / 私网必须 DIRECT。
11. 不修改 TLS 校验。
12. 不使用 --trusted-host 绕过问题。
13. 不把 Secret 输出到网络诊断日志。
14. 不因网络错误修改 requirements 版本。
15. 不因为当前某个 IP/端口可用就写死进代码。
```

---


# 第六A部分：Agent 安装与系统级变更权限

## 12A. 默认允许

Agent 可自行：

- 只读诊断；
- 有界网络 Probe；
- 修改当前 Repo 的代码、测试、文档；
- 启停已有且明确属于当前项目的服务；
- 修改任务已明确授权的项目级配置。

## 12B. 必须人工批准

以下行为必须先暂停、说明原因和回退方式，得到用户明确确认后才能执行：

- `apt/apt-get install/remove`；
- 系统/用户全局 `pip`、`pipx` 安装；
- `npm -g`、`cargo install`、机器级 `go install`；
- `winget`、`choco`、MSI/EXE 安装；
- 新 systemd service/timer/socket；
- 新 Windows Service / Scheduled Task；
- 新网络 daemon / VPN / TUN / 虚拟网卡 / 驱动；
- 持久化 route/firewall 变更；
- Docker daemon 全局 DNS/proxy/network 配置；
- `/etc/systemd/**`、`/etc/network/**` 持久修改；
- `.wslconfig` 网络字段修改。

不得把“实现 relay”“形成可安装运行方式”等宽泛要求解释为自动获准安装第三方系统软件。

## 12C. 系统变更审计

网络任务结束必须报告：

```text
packages installed/removed
systemd units
Windows services/tasks
new listeners
daemon.json changes
DNS changes
route/firewall changes
executables added
rollback method
```

若没有：

```text
SYSTEM_INSTALLS=NONE
SYSTEM_LEVEL_CHANGES=NONE
```

---

# 第七部分：跨项目工程模板

## 13. 每个 Repo 的推荐入口

建议统一：

```bash
./scripts/docker-build.sh <service>
```

而不是让不同项目各自：

```bash
docker build ...
docker compose build ...
pip install ...
```

入口职责：

```text
读取版本
→ 写 Compose version env
→ Network Preflight
→ 选择 proxy/direct/fail
→ docker compose build
```

---

## 14. 通用环境变量

建议跨项目统一命名：

```text
AI_PROXY_PORT
AI_PROXY_DEBUG
```

项目可以兼容旧变量，例如：

```text
VTIP_PROXY_PORT
VTIP_PROXY_DEBUG
```

最终建议采用：

```text
AI_PROXY_PORT
优先级高于动态发现
```

但不要在现有稳定项目中为了统一命名强行重构；可在新项目中先采用通用命名，旧项目渐进兼容。

---

## 15. 通用网络 Preflight 输出规范

所有工程尽量统一输出：

### Proxy

```text
Docker Build Network      PASS proxy
Docker Build Proxy        http://<host>:<port>
Proxy Probe               PASS target=<url> status=200
```

### Direct

```text
Docker Build Network      PASS direct
Docker Direct             PASS target=<url> status=200
Docker Build Proxy        none
```

### Failure

```text
Docker Build Network      FAIL
Proxy Probe               FAIL
Docker Direct             FAIL
Docker Build              SKIPPED
```

让人和 AI 都能快速判断，不需要读 100 行 pip traceback。

---

# 第七A部分：Project Network Module 标准协议

## 15A. Project Gate 的验证层级

每个 Project 根据实际依赖选择检查项，但必须遵循：

```text
Config Truth
  ↓
DNS
  ↓
TCP
  ↓
TLS
  ↓
HTTP
  ↓
Application/API
  ↓
Runtime / Build / Provider Smoke
```

规则：

- DNS PASS 不能替代 TCP/TLS/HTTP/Application PASS；
- 有容器 Runtime 时，优先在真实 Runtime namespace 或 `--network container:<runtime>` 中验证；
- 需要 Build 时必须有 Build Network Preflight；
- Auth Smoke 优先只读，能 GET-only 就不得写；
- 所有 Probe 必须有硬 timeout；
- Required FAIL 时 Project Gate 非 0 退出，阻断后续网络依赖任务；
- Optional SKIP 不应导致 Project Gate FAIL。

## 15B. 标准日志、JSON 与 Footer

所有 Project 必须写入：

```text
logs/network/
├─ network-gate-YYYYMMDD-HHMMSS.log
├─ network-gate-YYYYMMDD-HHMMSS.json
├─ network-gate-latest.log
└─ network-gate-latest.json
```

`logs/network/` 必须加入 `.gitignore`。

文本日志应采用稳定、可读、可机器解析的结构，例如：

```text
2026-09-08T11:51:42+08:00 | INFO | L5-MODELS | GEMINI_INFERENCE | PASS | latency_ms=1580
```

JSON 至少包含：

```json
{
  "schema_version": "1",
  "project": "example",
  "started_at": "...",
  "finished_at": "...",
  "duration_ms": 0,
  "standard_version": "V0.2 PRE-RELEASE",
  "boot_metadata": {
    "windows_last_boot": "...",
    "wsl_boot_id": "..."
  },
  "checks": [],
  "summary": {
    "required": 0,
    "passed": 0,
    "failed": 0,
    "optional_skipped": 0
  },
  "project_network_ready": true,
  "cold_start_verified": true
}
```

stdout 与 `.log` 结尾必须输出：

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

Exit Code：`0` = 所有 Required PASS；非 `0` = Required FAIL 或 Gate 自身异常。

## 15C. Secret Redaction

任何 stdout / log / JSON / Web/SSE 均禁止暴露：

```text
API Key
Management Key
OAuth Token
Refresh Token
Cookie
Authorization
Password
Credential JSON
bcrypt/hash 等认证材料
```

必须在写日志和推送 Web 事件前进行统一脱敏。

# 第七B部分：Web Network Center 标准

## 15D. 有 Web UI 的 Project / Module 必须提供网络入口

如果 Project 或 Module 存在 Web UI，其主要首页必须显式显示 Network Status，并能进入正式 Network 页面。

至少支持：

```text
UNKNOWN
RUNNING
PASS
FAIL
STALE
```

首页至少显示：

- 最后验证时间；
- Cold Start 是否已验证；
- `NETWORK READY` / `NETWORK BLOCKED` / “需要重新验证”；
- “查看网络状态”入口。

首页加载不得自动运行 Gate。

一个 Project 如果存在多个 Web Module，每个主要 Module 首页都必须能够链接到该 Project Network Status 或正式 Module Sub-Gate；不得为每个页面复制一套网络检测逻辑。

## 15E. Web 与 CLI 必须同源

Web 的“运行网络验证”必须调用同一正式：

```text
scripts/network/network-gate.sh
```

禁止 Web 自己重新写一套 curl / socket 判断。

Web 应具备：

- 单运行并发锁；
- 整体硬 timeout（参考 `<=120s`）；
- 实时日志（SSE 或已有有界轮询/RunEvent 机制）；
- RUNNING -> PASS/FAIL 最终收敛；
- 最近结果持久读取；
- 全程 Secret redaction。

### 15E.1 容器 Web 到宿主 Gate 的边界

如果 Web 本身运行在隔离 Docker 容器中，且无法直接访问 Windows PowerShell、Docker Host 或宿主 network namespace，可以使用**项目显式批准的宿主 Gate Runner/Adapter**桥接，但必须满足：

- Runner 只执行该 Project 的标准 Gate 入口；
- Web 不直接获得任意宿主 shell 能力；
- Trigger / IPC 接口最小化；
- 同一时刻最多一个 Gate；
- 有 timeout、审计、日志脱敏；
- Runner 属于 Project 适配层，不升格为所有工程必须复制的机器级组件；
- 新 systemd/Windows Service 仍遵守“需人工批准”的治理原则。

AI-KB 当前参考实现使用：

```text
aikb-network-gate-runner.service
/data/gate_run.trigger
Run / RunEvent + SSE
```

该实现用于解决 Control Center 容器无法直接执行宿主 Gate 的隔离边界，不代表其它 Project 必须使用同样机制。

# 第七C部分：Cloud CPA SSH Tunnel Tool 规范

## 15F. Cloud CPA 只通过按需 SSH Local Forward

AI-KB Cloud CPA 是 Optional Node。标准本地入口：

```text
127.0.0.1:18317
  -> SSH Local Forward
  -> VPS 127.0.0.1:8317
```

标准工具：

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

约束：

- `start` 先检查 18317；健康则 REUSE；未知进程占用则 FAIL，不杀；
- `ssh -N` 成功不是等待进程退出，而是 process alive + 18317 listening + Cloud CPA transport PASS；
- `stop` 只停止工具自己托管/记录的 tunnel；手工 tunnel 标记 EXTERNAL/MANUAL，不得杀；
- `open` 只打开 `http://127.0.0.1:18317/management.html`；
- Web 可以显示 Cloud Tunnel 状态和 CLI 提示，但 Docker 内 Control Center 禁止跨边界启动 Windows `ssh.exe`；
- Cloud 默认 Optional，未开启时 Project Gate `SKIP`，不得阻断本地 `PROJECT_NETWORK_READY=true`。

---

# 第八部分：Tailscale / SD-WAN 与其它虚拟网络

## 16. 本机基线

本机开发环境不再依赖 Tailscale / SD-WAN 作为默认网络路径。

原因不是“绝对不能安装”，而是本机同时存在：

```text
Clash TUN
WSL mirrored networking
Docker bridges
VMware virtual adapters
AI/RAG services
```

额外的 SD-WAN/Tailscale 可能改变：

- route priority；
- interface enumeration；
- DNS；
- TUN 行为；
- Docker -> Windows Proxy candidate 顺序；
- 开机恢复顺序。

因此：

> 本机 Canonical Network Baseline 不包含 Tailscale / SD-WAN。

其他机器如果必须使用，应单独做网络兼容验证，不直接套用本机已验证结论。

---


# 第八A部分：Network Repair Decision Tree 与完整复验

## 16A. 修复总原则

```text
先定位故障层
→ 最小修复
→ 不扩大影响面
→ 完整 Network Gate 复验
```

禁止“换几个 DNS/代理/路由组合直到看起来好了”。

## 16B. 分层修复

### CASE 1：Windows FAIL

先修 Clash/Mihomo、System Proxy、Windows DNS/TUN；停止 WSL/Docker 调整。

### CASE 2：Windows PASS，WSL Proxy FAIL

检查 mirrored、loopback、动态 proxy port、WSL interface/firewall；不要先改 Docker。

### CASE 3：WSL Proxy PASS，Docker Proxy FAIL

检查 Docker bridge、host-gateway、Docker Egress Gateway、Gateway bind/security、candidate discovery。这是 Docker -> Clash 的典型断点。

### CASE 4：Docker Proxy PASS，Build FAIL

进入 BuildKit、build args、Dockerfile、Registry/Package target；不要修改 Windows 网络。

### CASE 5：Docker 网络 PASS，Application Runtime FAIL

检查 target namespace DNS、application proxy、Provider endpoint、credential、quota、HTTP client。

### CASE 6：公网修复导致内部网络 FAIL

此次修复直接判失败。回滚最近网络变更，不能以“公网已通”作为成功。

## 16C. Full Revalidation

任何网络层修改后必须重新验证：

```text
1. Windows 国内公网
2. Windows 海外公网
3. WSL canonical proxy
4. WSL internal DIRECT
5. Docker Egress Gateway
6. Docker Build Preflight
7. Docker internal DIRECT
8. Public-Egress Runtime 国内
9. Public-Egress Runtime 海外
10. AI-KB services
11. VTIP Build
12. Jira/Confluence/GitLab internal path（如使用）
```

只有全部 Required PASS 才能恢复 `NETWORK_READY=true`。

---

# 第九部分：故障诊断 Runbook

## 17. Windows

```powershell
$inet = Get-ItemProperty `
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'

$inet |
  Select-Object ProxyEnable, ProxyServer, AutoConfigURL

Get-Process |
  Where-Object { $_.ProcessName -match 'clash|mihomo' }

Get-NetTCPConnection -State Listen
```

目标：

- 系统代理开启；
- Mihomo 进程存在；
- 代理 listener 存在。

---

## 18. WSL

```bash
env | grep -iE '^(http|https|all|no)_proxy='
```

验证普通外网：

```bash
curl -I https://pypi.org/simple/requests/
```

真正 Direct：

```bash
env \
  -u HTTP_PROXY \
  -u HTTPS_PROXY \
  -u ALL_PROXY \
  -u http_proxy \
  -u https_proxy \
  -u all_proxy \
  curl --noproxy '*' \
  -I https://pypi.org/simple/requests/
```

如果目标是 Runtime 公网 API，还应检查解析结果：

```bash
getent ahostsv4 <public-domain>
ip route
```

若解析到 `198.18.x.x` 且 Direct 超时，而 `curl -x http://127.0.0.1:<dynamic-port>` PASS，应进入 Fake-IP / TUN 路由诊断，不要把业务 API 判为故障。

---

## 19. Docker

真正 Docker Direct：

```bash
docker run --rm -i \
  python:3.12.11-slim-bookworm \
  python - <<'PY'
import urllib.request

opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({})
)

with opener.open(
    "https://pypi.org/simple/requests/",
    timeout=8,
) as response:
    print(response.status)
PY
```

Proxy 候选必须在 Docker bridge 里验证，而不是只在 WSL host 验证。


同时检查 Docker Engine 的网络配置：

```bash
cat /etc/docker/daemon.json
```

重点审计：

- 是否残留硬编码 `proxies`；
- 是否把 `127.0.0.1:<固定端口>` 当成 Docker daemon 永久代理；
- 当前默认 `dns`；
- 任何 daemon 级 DNS 变更是否已经验证内部域名。

对实际长期 Runtime，必须从其 network namespace 验证：

```bash
docker run --rm \
  --network container:<target-container> \
  <cached-diagnostic-image> \
  ...
```

AI-KB / CPA 的标准检查还包括：

```bash
docker inspect cpa-local
```

确认：

```text
Runtime HTTP_PROXY = none
Runtime HTTPS_PROXY = none
Runtime ALL_PROXY = none
Host publish = 127.0.0.1 only
```

对公共域名：

- 默认 resolver 下记录实际 IP；
- 若出现不可路由 Fake-IP，再以项目批准的公共 DNS 做诊断；
- 公共 DNS 得到 Real IP 且 TCP/TLS/HTTP PASS 后，才可判定 Fake-IP 黑洞。

---

# 第十部分：项目启动时给 AI / Agent 的最小 Bootstrap

## 20. 给新的 AI 聊天会话

复制：

```text
本工程使用统一开发网络规范：

Windows 11 + WSL2 mirrored networking + Clash Party/Mihomo。
Clash 标准状态为 Rule + TUN enabled。
WSL dnsTunneling=true，autoProxy=false。

公司内网 sensha.top / *.sensha.top 与 RFC1918 私网 DIRECT。

Docker Runtime 默认不得携带 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY。
需要长期公网出站的 Runtime 必须显式声明 Runtime Egress，并从目标容器 namespace 验证 DNS/TCP/TLS/HTTP；不得把宿主开发代理无差别注入容器。
若公共域名解析为 198.18.x.x Fake-IP 且 Direct 超时，应检查 Fake-IP/TUN 路由，不把 DNS 有结果视为网络正常。
Docker Build 必须通过动态 Network Preflight：
先动态发现 Windows Proxy Candidate，
再从 Docker bridge 真实测试 Proxy，
Proxy 全失败后才测试 Docker Direct，
两者都失败时必须 FAIL FAST，禁止盲目启动 build。

不得硬编码 Windows IP 或唯一 Clash 端口。
不得因为 pip 网络超时修改 requirements。
不得通过 --trusted-host 或关闭 TLS 绕过网络错误。

如本 Repo 有 docs/AI-NETWORK-STANDARD.md，
以该文档和本项目 Network Runbook 为工程事实。
```

---

## 21. 给 Antigravity / 编程智能体

复制：

```text
【工程网络约束】

开始修改 Docker、依赖下载、代理、网络相关代码前：

1. 先阅读：
   docs/AI-NETWORK-STANDARD.md
   以及本项目 network/runbook 文档。

2. 保持：
   Windows + WSL2 mirrored networking
   Clash/Mihomo Rule + TUN
   WSL autoProxy=false

3. Build Network：
   - 动态发现 Proxy；
   - 不硬编码 Windows IP；
   - 不硬编码唯一端口；
   - Docker-side 验证 Proxy；
   - Proxy 全失败后验证 Docker Direct；
   - Proxy/Direct 双失败则 FAIL FAST；
   - 不进入正式 build。

4. Runtime：
   - 默认不注入 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY；
   - 内部 sensha.top 与私网 DIRECT；
   - 若属于长期公网出站 Runtime，必须显式声明 Runtime Egress；
   - 从目标容器 namespace 验证 DNS/TCP/TLS/HTTP；
   - 遇到 198.18.x.x Fake-IP 时继续验证路由，不把“DNS 有结果”当作 PASS；
   - 公共 DNS / 应用层 proxy 只能作为项目级策略，不能无差别传播给所有 Runtime。

5. 安全：
   - 不关闭 TLS；
   - 不使用 --trusted-host 绕过；
   - 不输出 Token/Secret；
   - 不修改业务依赖版本来“修复”网络问题。

6. 任何网络改动必须提供：
   - Windows/WSL/Docker/BuildKit/Application 所处网络层；
   - 变更前后策略；
   - 单元测试；
   - 实机 Preflight；
   - Runtime Proxy=none 验证；
   - Runtime DNS 策略；
   - 内网解析与 DIRECT 回归；
   - 如为公网 Runtime，至少一个真实外部目标 E2E。
```

---

# 第十一部分：当前已验证的参考实现

## 22. VTIP Platform Catalog

当前参考实现：

```text
scripts/detect_proxy.py
scripts/detect-proxy.sh
scripts/docker-build.sh
docs/network-proxy-validation.md
docs/WSL-Docker测试.md
```

已实现的关键能力：

- WSL gateway / resolver / Windows IPv4 动态 discovery；
- Windows System Proxy 端口动态解析；
- `VTIP_PROXY_PORT` override；
- 7890 / 7892 有限兼容；
- Docker-side Proxy Probe；
- Docker-side Direct Probe；
- 有界 retry / timeout；
- Proxy / Direct / Fail 三策略；
- Fail Fast；
- Debug diagnostic；
- Build-only proxy；
- Runtime proxy none。

VTIP 是当前本机统一网络架构的**参考实现**，但跨项目复用时应提炼通用命名，不要直接复制 VTIP 业务耦合。

### 22.1 AI-KB / CPA Runtime Egress

AI-KB 是“长期公网出站 Docker Runtime”的当前参考实现。

已验证资产：

```text
config/cpa/compose.yaml
docs/AI-NETWORK-STANDARD.md
D:\AI-KB\Logs\ag011-network.log
```

当前已确认事实：

- `cpa-local` Runtime 无 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`；
- 默认 WSL/Docker DNS 曾返回 `198.18.x.x` Fake-IP，并在无对应 TUN 路由时造成 TCP timeout；
- per-service DNS / Runtime Egress 分层诊断用于规避 Fake-IP 黑洞，不能把公共 DNS 当所有 Project 的永久机器常量；
- Docker Egress Gateway 已完成落地并在 Windows 冷重启后自动恢复；
- CPA Local -> Google/Gemini/NVIDIA 已通过 Gateway -> Clash 的真实模型/传输验证；
- Bailian 使用 Direct 路径验证通过；
- CPA Local clean recreate 后 Management、配置、Auth 持久化、Gemini/NVIDIA 均通过；
- Cloud CPA 可作为海外 Provider 备用/加速，但不是本地核心 Network Gate 的 Required 项；
- Cloud CPA 通过标准 SSH Local Forward Tool 按需使用；
- 外部 Provider 全部不可用时，Router 应按能力约束回退已批准的 Local Ollama。

该案例补全了 VTIP 主要覆盖的 Build Network 经验：

```text
VTIP -> Build 网络参考实现
AI-KB -> Runtime Egress 参考实现
```

---

# 第十二部分：需要跨会话长期坚持的设计原则

## 23. 十八条不可变原则

1. **Windows 浏览器联网不等于 WSL 联网。**
2. **WSL 联网不等于 Docker 联网。**
3. **Docker bridge 联网不等于目标 Runtime 联网。**
4. **Runtime 和 Build 的 Proxy 生命周期必须分离。**
5. **Docker daemon proxy、Runtime proxy env、Application proxy 必须区分。**
6. **普通 Runtime 默认无代理；Public-Egress Runtime 必须显式声明 Egress。**
7. **内部网络与私网永远优先 DIRECT。**
8. **Proxy 地址和端口动态发现，不依赖某次运行时快照。**
9. **任何 Proxy 都必须从真正消费它的网络层验证。**
10. **Docker Direct FAIL 不等于 Docker Network FAIL；Proxy PASS 可以合法工作。**
11. **DNS PASS 不等于 TCP/TLS/HTTP PASS。**
12. **Fake-IP 必须与目标 namespace 的真实可路由性一起判断。**
13. **公共 DNS Override 不得破坏内部域名与 Docker service discovery。**
14. **Proxy/Direct 都失败必须 Fail Fast。**
15. **网络错误必须在网络层解决，不修改依赖、模型或 TLS 掩盖。**
16. **任何网络修复后必须执行完整 Network Gate，不能只复测修复点。**
17. **Network Gate FAIL 时必须阻断网络依赖型工程任务。**
18. **Agent 不得静默安装系统/网络软件；所有 AI 会话和 Agent 必须显式加载本规范。**

---

# 第十三部分：工程推广建议

## 24. Canonical Git 与跨项目落地方式

### 第一层：独立 Canonical Standards Repository

唯一 Canonical Source：

```text
git@github.com:xiefeifeihu/AI-Engineering-Standards.git
```

建议：

```text
AI-Engineering-Standards/
├─ README.md
└─ network/
   ├─ AI-NETWORK-STANDARD.md
   └─ AI-NETWORK-HANDOFF.md
```

规范和交接必须进入 Git；OneDrive 与聊天附件只作为副本。

### 第二层：每 Repo 保存 Thin Canonical Reference 与 Project Profile

每个 Project：

```text
docs/AI-NETWORK-STANDARD.md   # Thin Reference (规范版本、Commit SHA、指向标准仓指针)
docs/AI-NETWORK-PROFILE.md    # 记录本 Project 的专属网络拓扑、网关映射与 Gate
scripts/network/network-gate.cmd
scripts/network/network-gate.sh
```

项目本地 `AI-NETWORK-STANDARD.md` 作为瘦引用（Thin Canonical Reference），必须标记 Canonical Repo / Version / Commit，使 Agent 能够溯源真源与发现版本漂移，**严禁跨工程复制全量正文，严禁使用 Windows symlink / junction 跨盘链接**。

`AI-NETWORK-PROFILE.md` 只记录本 Project 的差异和配置来源，不复制可从 config 自动读取的 Endpoint。

### 第三层：Agent Bootstrap

每个项目的 `AGENTS.md`、`GEMINI.md`、`README-AI.md` 或启动提示中应加入：

```text
Before network/build/provider changes:
1. read docs/AI-NETWORK-STANDARD.md;
2. run scripts/network/network-gate.cmd or .sh;
3. if Required FAIL, stop engineering work and repair network first.
```

### 第四层：自动化与 Web

Project Gate 是唯一判断来源。CLI、CI、Web 必须调用同一 Gate，不得复制检测逻辑。

长期可以从 Canonical Standards Repo 提供模板，但模板只定义协议和脚手架；真实 Endpoint 和业务验证永远由 Project 自己生成和维护。

---

## 25. 本机当前 Canonical Network Baseline

截至 2026-09-08，本机标准网络事实为：

```text
OS:
Windows 11

WSL:
WSL2
Ubuntu 24.04
networkingMode=mirrored
dnsTunneling=true
autoProxy=false

Proxy:
Clash Party / Mihomo
Mode=Rule
TUN=enabled

Windows System Proxy:
127.0.0.1:<dynamic port>
当前常见为 7890

Mihomo compatibility ports:
7890 / 7891 / 7892

Company/Internal:
sensha.top / *.sensha.top DIRECT

Private Networks:
DIRECT

Docker Runtime:
No HTTP(S)/ALL Proxy Env by default

Docker Public-Egress Runtime:
项目显式声明
DNS / TCP / TLS / HTTP from target namespace
不继承宿主开发代理

Docker Build:
Dynamic Preflight
Proxy -> Direct -> Fail Fast

Fake-IP:
当前机器已验证 WSL/Docker 可能获得 198.18.x.x Fake-IP
Fake-IP 可解析不代表可路由

AI-KB CPA Local:
Runtime Proxy Env = none
127.0.0.1:8317 only
国内公网 Provider -> DIRECT 优先
海外 Provider -> Docker Egress Gateway -> Clash（V0.2 Required target）
项目级 DNS 避免 Fake-IP 黑洞

AI-KB CPA Cloud:
Optional / non-core by default
海外 Provider 备用/加速
SSH Local Forward on demand

Tailscale / SD-WAN:
不属于本机默认开发网络基线
```

### 25.0A Project Gate / Web / Cloud Tool 当前已验证事实

```text
Network Spec:
V0.2 PRE-RELEASE

Warm-State Acceptance:
PASS

Windows Physical Restart:
DONE

Cold-Start Acceptance:
PASS

AI-KB Project Gate:
25 total / 24 required / 24 passed / 0 failed / 1 optional skipped
PROJECT_NETWORK_READY=true

VTIP Project Gate:
Cold-restart 后由 VTIP 自身 Gate 验证 PASS

AI-KB Web:
首页 Network Status Card PASS
/network PASS
Web Run -> RUNNING -> PASS
实时 SSE 日志 PASS
历史运行记录 PASS

AI-KB Host Adapter:
aikb-network-gate-runner.service
仅作为 AI-KB Web -> host Gate 的项目适配器

Cloud CPA:
Optional by default
scripts/cpa/cloud-cpa-tunnel.cmd/.sh
start/stop/status/test/open
```

当前状态仍是：

```text
NETWORK_SPEC_VERSION=V0.2
NETWORK_SPEC_STATUS=PRE_RELEASE
V0_2_COLD_START_ACCEPTANCE=PASS
FINAL_RELEASE_PENDING=true
```

### 25.1 关于 Docker DNS 的机器级与项目级边界

当前 AI-KB 已验证 `223.5.5.5`、`119.29.29.29` 可使 `cpa-local` 获取国内公网真实 IP 并恢复 Direct。

但必须区分：

- **机器级事实**：当前 WSL/Docker 默认解析路径可能受 Mihomo Fake-IP 影响；
- **项目级实现**：AI-KB `cpa-local` 使用已验证公共 DNS；
- **跨项目规则**：不得把某两个公共 DNS 无条件写成所有项目永久标准。

任何 daemon 级 DNS 设定都必须回归：

```text
公司内部域名解析
RFC1918 服务
Docker 内部服务发现
公网 Runtime
```

若未来内部 Runtime 需要公司 DNS，应优先采用 per-service DNS / split DNS，而不是牺牲内部解析能力。

---

# 26. 文档维护规则

发生以下变化时必须更新本文：

- `.wslconfig` 网络模式变更；
- Clash/Mihomo 替换；
- System Proxy 机制变更；
- Docker Engine / Docker Desktop 网络模式变更；
- 增加新的公司内部域；
- Build Proxy Preflight 算法升级；
- Runtime Egress / DNS 策略变更；
- Clash Fake-IP / TUN 行为变更；
- Docker daemon 级 DNS / proxy 配置变更；
- 引入必须长期存在的 SD-WAN / VPN；
- 新项目发现现有网络标准无法覆盖的真实故障。

版本变更应记录：

```text
日期
变更原因
受影响网络层
验证工程
验证结果
```

---

## 27. 当前参考事件

本规范的重要来源之一，是 VTIP Platform Catalog 的真实 Docker build 网络事故：

- Windows / WSL / Docker 网络曾因 Tailscale / SD-WAN、Clash TUN 状态切换出现瞬时不一致；
- 手工 Proxy detector 可 PASS，但正式 build 一度 detector FAIL；
- 旧逻辑在 Proxy 探测失败后直接 fallback direct；
- Docker Direct 同时不可达时，pip 等待约 100 秒后以“找不到 requests 版本”的表象失败；
- 随后将构建入口升级为：
  **动态 Discovery → Docker-side Proxy Probe → Docker-side Direct Probe → Fail Fast**。

该事件应作为以后所有 AI 工程网络设计的反例与回归场景。

### 27.1 AI-KB / CPA Runtime Egress 事故（2026-09-07）

AI-KB 在 CPA Local 真实运行中发现第二类参考事故：

```text
Windows 访问百炼 / Google PASS
WSL 显式 Proxy PASS
WSL True Direct FAIL
Docker 解析到 198.18.x.x Fake-IP
Docker TCP 443 超时
CPA Management api-call 对百炼 / Google 均超时
```

进一步取证：

- Docker / CPA Runtime 未注入 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`；
- WSL `dnsTunneling=true` 通过宿主 DNS 获得 Mihomo Fake-IP；
- 目标 namespace 无对应 Fake-IP 的可达 TUN 路由；
- 诊断时指定公共 DNS 后，百炼解析为真实公网 IP；
- TCP 握手与 HTTP 快速恢复；
- 项目级 DNS 策略只能证明国内 Direct 局部恢复，不能作为完整网络恢复结论；
- 后续又发现 Docker Build、Docker -> Clash、CPA -> Google 仍失败；
- 因此 V0.2 要求增加 Docker Egress Gateway，并用 Full Network Gate 重新验收。

由此形成新的 Runtime 规则：

> **长期公网出站容器必须把 DNS、路由与应用调用分层验证。Fake-IP 解析成功不能作为网络正常的证据。**

---

### 27.2 跨 Project Gate 耦合缺陷与修正（2026-09-07～08）

在首次 Full Gate 中，AI-KB Gate 曾直接验证 VTIP/Jira/Confluence 业务路径，并因会话错误猜测业务域名而暴露治理缺陷。

由此确定：

> **Machine Core Gate 只验证机器公共能力；每个 Project 自己读取真实配置并执行 Project Network Self-Test。其它 Project 和 AI 不得猜测其 Endpoint。**

最终形成统一入口：

```text
scripts/network/network-gate.cmd
scripts/network/network-gate.sh
```

以及标准日志、JSON、Footer、Exit Code、STALE 机制。

### 27.3 AI-KB Web Network Center 与宿主执行边界（2026-09-08）

AI-KB Control Center 运行在 Docker 容器中，无法安全直接访问 Windows PowerShell、宿主 Docker/WSL 网络命名空间。为了保证 Web 与 CLI 使用同一个正式 Project Gate，AI-KB 引入项目级宿主适配器：

```text
aikb-network-gate-runner.service
```

Web 通过最小 Trigger 触发宿主 `scripts/network/network-gate.sh`，运行事件继续复用 Control Center `Run / RunEvent` 并通过 SSE 实时展示。

实机验证：

```text
GET /health        PASS
GET /              PASS（Network Status Card）
GET /network       PASS
POST /network/run  PASS
SSE realtime log   PASS
Gate Required      24/24 PASS
Cloud Optional     SKIP when tunnel offline
```

该 Runner 是 AI-KB Project Adapter，不是所有项目的机器级强制组件。

---

## 28. 版本变更记录

### V0.1 — 原始草案

建立：

- Windows + WSL2 mirrored + Clash/Mihomo 基线；
- Docker Build Dynamic Preflight；
- Runtime 默认无 Proxy Env；
- 内部 DIRECT；
- Fail Fast。

### V0.2 — 2026-09-07～08（当前预发布）

累计新增/纠正：

- Network Conformance Gate，Required FAIL 即阻断工程任务；
- 修复后 Full Revalidation；
- Daemon Proxy / Runtime Proxy Env / Application Proxy 分层；
- Docker Egress Gateway；
- Public-Egress Runtime；
- Fake-IP 的 DNS/TCP/TLS/HTTP 分层判断；
- OAuth network vs credential 判定；
- Agent 系统软件安装与全局网络变更需人工批准；
- 预发布版本统一使用 V0.x；
- Machine Core Gate 与 Project Gate 解耦；
- 每 Project 强制 `scripts/network/network-gate.cmd/.sh`；
- 标准 text/JSON log、Footer、Exit Code；
- Cold Boot Metadata + STALE；
- 有 Web 的 Project/Module 首页 Network Status + Network Center；
- Web 与 CLI 共用同一 Project Gate；
- AI-KB `aikb-network-gate-runner.service` 项目适配；
- Cloud CPA SSH Tunnel 标准工具 `start/stop/status/test/open`；
- Canonical Git Source：`git@github.com:xiefeifeihu/AI-Engineering-Standards.git`；
- AI-KB 与 VTIP 均完成冷启动后 Project Gate 验证。

当前状态：

```text
NETWORK_SPEC_VERSION=V0.2
NETWORK_SPEC_STATUS=PRE_RELEASE
WARM_ACCEPTANCE=PASS
V0_2_COLD_START_ACCEPTANCE=PASS
AIKB_PROJECT_NETWORK_READY=true
VTIP_PROJECT_NETWORK_READY=true
FINAL_RELEASE_PENDING=true
```

**不得因为技术 Gate 已经 PASS 就自行改成 V1.0。只有用户明确批准正式定版后才能发布 V1.0。**
