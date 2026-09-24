# Sidecar 全量治理接入交接指南 (SIDECAR-FULL-ADOPTION-HANDOFF.md)

```text
DOCUMENT_ID=SIDECAR-FULL-ADOPTION-HANDOFF
VERSION=1.0.0
GOVERNANCE_BASELINE=AI Engineering Standards v1.1.2 / AI-Hub v0.5.9
TARGET_PROJECT=VTIP-AI-SIDECAR (vtip-ai-sidecar)
TARGET_AUDIENCE=Sidecar 专属开发会话 / 平台架构师
STATUS=OFFICIAL_DURABLE_HANDOFF
LAST_UPDATED=2026-09-24
```

---

## 1. 核心端点与运行时拓扑 (Endpoint & Runtime Topology)

为彻底解决 Docker 容器访问 Hub 回环地址引发的 `Connection Refused` 缺陷，平台已正式升级端点架构与 Runtime Profiles。**严禁在 Docker Sidecar 内部直接使用 127.0.0.1 作为 Hub Base URL**。

### 1.1 平台端点标准配置

| 运行时画像 (Runtime Profile) | 端点变量名 | 标准 Base URL | 用途与约束 |
| :--- | :--- | :--- | :--- |
| **Host Runtime** | `HUB_HOST_ENDPOINT` | `http://127.0.0.1:80` | Windows/WSL 宿主环境、CLI 工具、用户浏览器访问（LOOPBACK ONLY） |
| **Docker Runtime** | `HUB_DOCKER_ENDPOINT` | `http://host.docker.internal:18000` | **Sidecar 及所有 Docker Bridge 容器消费端必须使用**（专属 Ingress 隔离网关） |

### 1.2 规范路由路径 (Canonical Paths)

下游消费代码必须基于对应的 Base URL 拼接以下标准路径，严禁使用已弃用的历史别名：
- **模型候选方案选择 (Candidate Plan)**:
  `POST /api/model/select`
- **业务调用质量反馈 (Model Feedback)**:
  `POST /api/model/feedback`
- **平台健康探测 (Health Check)**:
  `GET /health`

---

## 2. Docker 容器网络配置要求 (Sidecar Container Network Contract)

1. **DNS 与 Host-Gateway 映射**：
   Sidecar 运行于 Docker Bridge 网络中，需确保具备 `host.docker.internal` 解析能力：
   ```yaml
   extra_hosts:
     - "host.docker.internal:host-gateway"
   ```
2. **无需添加共享外部网络**：
   Hub Docker Ingress 动态监听所有 Docker bridge 网关 IP（如 `172.17.0.1:18000`），Sidecar 无需加入 Hub 的 host 网络，也无需为 Hub 创建额外的 external docker network。
3. **零代码修改说明**：
   本次修复为平台层 Ingress 与 Standards 规范对齐，Sidecar 既有代码与 Compose 架构保持完全只读。后续 Sidecar 会话仅需在消费配置中注入 `HUB_BASE_URL=http://host.docker.internal:18000` 即可无缝切换至 Hub 全量治理。

---

## 3. Sidecar 治理协同核心机制

1. **Candidate Plan 消费与候选仲裁**：
   - Sidecar 调用 `POST /api/model/select` 获取平台多通道推荐链（Local CPA > Cloud CPA > Ollama）。
   - Sidecar 将自身业务 Champion 模型与 Hub Candidate 进行优先级权衡。
2. **Fact Guard 事实护栏与反馈上报**：
   - Sidecar 执行业务推理后，独立运行 Fact Guard 校验。
   - 校验结果指标（`fact_guard_pass`, `quality_score`, `latency_ms`, 7-class 错误分类）通过 `POST /api/model/feedback` 上报给 Hub，驱动平台动态评分与熔断策略。
3. **Legacy Safe Fallback 兜底保障**：
   - Hub 始终定位为协调中枢，非业务强依赖单点（HUB_IS_SPOF=false）。
   - 若 Hub 不可用或候选链耗尽，Sidecar 必须保持平滑回退至 Legacy 本地直连链路。
