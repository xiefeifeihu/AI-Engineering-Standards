# [PROJECT_NAME] 共享推理资源画像模板 (Project Shared AI Resource Profile Template)

> **使用说明**：
> 1. 新项目接入共享推理资源时，请将本文件复制到项目 `docs/` 目录下（如 `docs/<PROJECT>-共享推理资源画像.md`）。
> 2. 根据本工程实际的业务任务档案、数据敏感度要求与生产审批制度填充内容。
> 3. **安全红线**：严禁在本画像中写入任何明文 API Key、Token 或密码。

---

## 1. 项目基础信息 (Project Metadata)

- **项目标识 (Project ID)**：`[PROJECT_NAME]` (如 `AI-KB`, `VTIP`)
- **仓库根路径**：`[ABSOLUTE_OR_RELATIVE_PATH]`
- **遵循的标准规范版本**：`RESOURCE_SPEC_VERSION=V0.1` (`RESOURCE_SPEC_STATUS=PRE_RELEASE`)
- **规范标准 Commit 引用**：`[CANONICAL_RESOURCE_SPEC_COMMIT_SHA]`
- **核心调度服务 / 模块**：`[ROUTER_OR_SERVICE_NAME]` (如 `app/services/router.py`)

---

## 2. 允许调度的共享资源列表 (Allowed Resources)

声明本工程获准调度的物理推理资源端点（详见共享资源目录）：

| 资源标识 (Resource ID) | 类型 | 部署端点 (Endpoint) | 本工程准入状态 (Status) | 接入通道与方式 |
| :--- | :--- | :--- | :--- | :--- |
| `ollama-local` | `ollama` | `127.0.0.1:11434` | `ENABLED` | 本地宿主 / 容器直连 (全离线安全) |
| `cpa-local` | `cpa` | `127.0.0.1:8317` | `ENABLED` | 本地 CPA 代理 (国内低时延直连) |
| `cpa-cloud` | `cpa` | `127.0.0.1:18317` | `OPTIONAL` | SSH 本地端口映射 (按需海外直连) |

---

## 3. 调度优先级与网络拓扑策略 (Resource Priority & Topology)

根据本工程的业务特性定义节点调度优先级：
1. **默认主选规则**：`[例如：优先使用 cpa-local 直连，离线或高密任务使用 ollama-local]`
2. **海外服务免代理通道**：`[例如：海外模型如 Gemini 优先经由 cpa-cloud (18317) 访问]`
3. **熔断与降级机制**：`[例如：单节点连续失败 3 次触发熔断隔离，自动退避降级]`

---

## 4. 任务档案与模型映射矩阵 (Task Mapping & Champions)

定义本工程内各个任务的推荐 Champion 模型与多级降级策略：

| 任务档案标识 (Task Profile) | 业务任务名称 | 首选规范模型 (Preferred Canonical) | 首选 Offering 与节点 | 备选退避降级 (Fallback) | 本地离线安全兜底 (Local Safe Fallback) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `[task_key_1]` | `[任务名称 1]` | `[model_1]` | `[offering_1] @ [node_1]` | `[fallback_model_1]` | `[local_fallback_1]` |
| `[task_key_2]` | `[任务名称 2]` | `[model_2]` | `[offering_2] @ [node_2]` | `[fallback_model_2]` | `[local_fallback_2]` |
| `[multimodal_task]` | `[多模态任务]`| `[vision_model]`| `[vision_offering]` | `[vision_fallback]` | `capability_unavailable (阻断纯文本降级)` |

---

## 5. 数据敏感度策略 (Sensitivity Policy)

- **公开级 (Public)**：允许分派至任意经评测的外部商业 API 与云端节点。
- **内部级 (Internal)**：仅允许调度至已签署企业协议的受控服务（如百炼 CodingPlan 或本地模型）。
- **绝密/离线级 (Secret/Offline)**：**严格禁止任何外网调用**，强制锁定 `ollama-local` 本地离线节点执行。

---

## 6. 模型生产准入制度 (Model Approval Governance)

> [!IMPORTANT]
> **独立准入硬约束**：
> 物理节点的模型列表通过动态发现拉取。外部模型评测出的 Champion 仅为推荐，**除本项目显式审批通过的模型外，其余候选模型的 `production_approved` 状态必须保持 `false`**。严禁未经人工评审直接接入生产链路。

- **当前正式准入模型列表 (`production_approved=true`)**：
  - `[approved_model_1]`
- **候选推荐待审批模型 (`production_approved=false`)**：
  - `[candidate_champion_1]`
  - `[candidate_champion_2]`

---

## 7. 能力约束与降级阻断 (Capability Requirements & Fallback Guardrails)

针对不同输入类型的任务设置硬性能力屏障：
1. **多模态图表/文档解析**：
   - 必须具备 `vision` / `multimodal` 能力。
   - **阻断策略**：若无可用多模态模型，返回 `capability_unavailable`，**严禁静默降级为文本模型导致图表数据被忽略**。
2. **严格结构化输出**：
   - 必须具备 `structured_json` 能力与 100% 契约合规率。

---

## 8. 预算与配额控制 (Budget & Quota Policy)

- **单请求最大 Token 上限**：`[例如：max_tokens=800]`
- **请求超时阈值**：`[例如：常规任务 <= 25s，深度分析任务 <= 60s]`
- **最大并发请求数**：`[例如：本地 GPU 推理并发限制 1~2，云端并发限制 5]`

---

## 9. 健康探测与可观测契约 (Health Contract)

- **资源传输探测**：`[例如：每 30 秒执行一次 TCP/HTTP 端点存活探测]`
- **动态模型发现**：`[例如：调用 GET /api/tags 与 GET /v1/models，下线模型保留评测历史]`
- **审计日志要求**：每次路由决策记录 `RouteDecisionRecord`（包含 Canonical Model、选定 Instance、决策理由、是否命中熔断降级）。

---

## 10. 凭据引用规范 (Credential Reference)

- **严禁记录明文凭证**。
- **凭证外部路径规范**：
  - 本地 CPA 凭证：`[例如：引用宿主机 D:\AI-KB\LocalConfig\cpa-client-api.key 或环境变量 CPA_API_KEY]`
  - 其他第三方凭据：`[例如：从系统级安全钥匙串或隔离配置目录读取]`
