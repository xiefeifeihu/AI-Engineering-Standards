# AI 工程共享推理资源接入交接 (Shared Inference Resource Integration Guide)

> **适用对象**：
> 本交接面向新进入本开发机的新工程项目（如 VTIP、Agent 自动化流水线等）以及新接入的 AI 智能体（ChatGPT / Codex / Antigravity）。
> **目的**：指导新工程如何标准化接入宿主机已有的共享推理资源（Ollama、CPA Local、CPA Cloud），避免端口冲突、密钥泄露、架构重复造轮子与模型硬编码。

---

## 1. 快速接入全景检查表 (Quick Start Checklist)

新项目接入共享推理资源时，必须遵循以下步骤：

```text
Step 1: 阅读共享标准与目录 ──> resources/AI-工程共享推理资源规范.md & AI-工程共享推理资源目录.md
Step 2: 端口与传输探测 ──────> 探测 127.0.0.1:11434, 8317, 18317 连通性
Step 3: 获取外部凭据引用 ────> 遵循 Credential Reference Contract，从隔离受保护配置读取（绝不上屏入 Git）
Step 4: 动态拉取模型列表 ────> GET /api/tags 或 GET /v1/models（严禁硬编码）
Step 5: 建立项目专属画像 ────> 复制 PROJECT-AI-RESOURCE-PROFILE.template.md 并定制
Step 6: 实现降级与熔断 ──────> 依据项目安全策略与能力集设定受控退避（严禁无条件本地 Fallback）
```

---

## 2. 如何发现与探测资源 (Resource Discovery & Health Check)

物理资源在宿主机以标准固定端口提供服务，新项目不得擅自修改端口。

### 2.1 端点探测矩阵

```bash
# 1. 探测 Ollama 节点
curl -s http://127.0.0.1:11434/api/tags

# 2. 探测 CPA Local 节点 (带 API Key / Token)
curl -s -H "Authorization: Bearer <TOKEN>" http://127.0.0.1:8317/v1/models

# 3. 探测 CPA Cloud 节点 (需 SSH 隧道已启动，带 API Key / Token)
curl -s -H "Authorization: Bearer <TOKEN>" http://127.0.0.1:18317/v1/models
```

### 2.2 健康语义三层检查流程
智能体在进行健康自检时，必须严格执行三层校验：
1. **Resource Health (网络端口层)**：
   - 检查 TCP 端口是否监听、HTTP GET 是否在 3 秒内响应。如果超时或 Connection Refused，标记该资源实例为 `offline`。
2. **Offering Health (模型与认证层)**：
   - 检查 HTTP 返回状态码。若返回 `401 Unauthorized` 或 `Missing API key`，说明网络和节点通畅，但缺少有效凭据；若返回 200 但模型列表中不存在目标模型，说明节点未挂载该 Offering。
3. **Network Health (底层网络层)**：
   - 如果是从 Docker 容器内部调用，容器需通过宿主网关（如 `host.docker.internal:host-gateway`）或项目自建的网络路由访问宿主机端点，**严禁硬编码动态 bridge IP**。

---

## 3. 如何安全获取凭证引用 (Credential Reference)

为贯彻**绝对零密钥入库 (Zero Secrets in Git)** 原则，新项目严禁在 `.env`、配置文件、文档或代码中硬编码任何 API Key。

### 3.1 凭证引用契约 (Credential Reference Contract)
各项目应在自身画像或配置中声明凭证引用，而非直接存储凭据内容：
- `credential_ref_id`: 项目内凭据逻辑标识（如 `local_cpa_key`）
- `credential_type`: `api_key` | `bearer_token` | `basic_auth` | `none`
- `injection_contract`: `header` | `env` | `query` | `none`
- `secret_owner`: `project_local_config` | `secret_store` | `env_var`

### 3.2 规范凭证存储与注入路径
1. **宿主机安全存储**：
   - 各项目在自身的受保护目录中（如项目根目录下的 `LocalConfig/` 或机器级受保护密钥库）存储私有凭据文件；
2. **环境变量动态注入**：
   - 优先通过运行期环境变量（如 `CPA_API_KEY`）或容器启动参数动态注入，容器内部可挂载为只读目录；
3. **Git 忽略与防泄密约定**：
   - 项目 `.gitignore` 中必须包含：`LocalConfig/`, `*.key`, `*.token`, `.env`, `*secret*`；
   - 任何上屏日志、交互界面与诊断输出必须强制脱敏（如 `sk-***`）。

---

## 4. 如何动态发现 Model Catalog 并避免硬编码

> [!WARNING]
> **严禁静态硬编码模型列表**：
> 外部提供方的模型经常更新、废弃或由于上游状态变化而调整。新项目严禁在代码中直接写死模型列表作为唯一定义。

### 4.1 动态同步标准模式
项目应当实现周期性或带界的探测同步逻辑：
```python
# 动态同步逻辑示意
def sync_project_catalog(session, instance_endpoint, provider_type):
    # 1. 有界超时拉取 (<= 5s)
    raw_models = probe_endpoint_models(instance_endpoint, timeout=5)
    
    # 2. 状态转移与登记
    for m in raw_models:
        if exists_in_catalog(m):
            mark_available(m, available_now=True)
        else:
            register_new_model(m, status="advertised", production_approved=False)
            
    # 3. 下线与历史保留
    for m in get_all_catalog_items():
        if m not in raw_models:
            # 关键：只置为离线，严格保留评测历史与准入标记！
            mark_unavailable(m, available_now=False, retired_at=now())
```

---

## 5. 如何处理 Local 与 Cloud 节点及离线降级

### 5.1 Local vs Cloud 拓扑定位与工具归属
- **Local CPA (`8317`)**：常驻运行，优先承载国内服务（阿里百炼 CodingPlan、NVIDIA），传输延迟低于 100ms。
- **Cloud CPA (`18317`)**：海外直连，通过 SSH 隧道按需连接，承载 Gemini 等海外模型。
- **隧道工具归属**：Cloud CPA 隧道管理脚本（`cloud-cpa-tunnel.cmd` 等）由 **AI-KB** 统一持有和维护。其他工程作为消费者直接访问 `127.0.0.1:18317`，无需重复实现隧道管理脚本。

### 5.2 严禁无条件本地 Fallback 与降级守卫
新项目必须将 Cloud 资源定义为**可选能力 (Optional/On-demand)**，但降级必须受控：
1. **主动检测可用性**：
   - 探测 `127.0.0.1:18317` 是否连通；若离线，触发任务级退避评估。
2. **严禁无条件本地 Fallback**：
   - 当云端/远端模型不可用时，系统严禁未经校验直接回退到本地小模型。
   - 降级必须同时满足：
     * **项目策略允许**（当前任务明确支持 fallback）；
     * **数据敏感度合规**（数据分级允许使用降级目标）；
     * **生产准入有效**（目标模型 `production_approved=true`）；
     * **能力集匹配**（必须具备任务所需的 Capability）。
3. **能力不匹配硬阻断**：
   - 若任务为多模态图表/文档解析（必须依赖 Vision 能力），且备选本地模型不具备 Vision 能力，系统必须**返回 `capability_unavailable` 阻断执行**，严禁静默退回到纯文本模型造成数据截断与丢失。

---

## 6. 如何建立项目自身的 Resource Profile

每个工程项目必须建立并维护自身的专属画像：

1. **复制模板**：
   - 将 `resources/PROJECT-AI-RESOURCE-PROFILE.template.md` 复制到自身工程目录（如 `docs/<PROJECT>-共享推理资源画像.md`）。
2. **独立定义 Champions 与审批**：
   - 依据自身业务的数据敏感分级（公开级/内部级/绝密级），评选并记录属于自己工程的 Champion 模型。
   - 独立管理 `production_approved` 状态，明确哪些模型可以进入本工程的生产链路。
3. **配置专属降级链与配额**：
   - 针对自身业务负载设定 Token 限流与单任务最大超时。
