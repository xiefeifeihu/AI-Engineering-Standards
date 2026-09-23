# AI-KB 模型治理接入交接指南 (AI-KB Model Governance Integration Handoff)

```text
TARGET_PROJECT=AI-KB (ai-kb-infra)
TARGET_AUDIENCE=AI-KB ChatGPT / Claude 长期架构会话
GOVERNANCE_BASELINE=AI Engineering Standards V1.0 / AI-Hub v0.5.4
STATUS=OFFICIAL_HANDOFF
```

---

## 1. 架构定位与交接前言

本交接文档专供 **AI-KB 项目专属会话** 阅读与决策，**绝非直接在代码库中盲目 Vibe Coding**。

AI Engineering Hub 当前已完成对齐并提供如下稳定核心能力：
1. **Candidate Execution Plan (`POST /api/model/select`)**：
   业务方声明任务意图（`knowledge_distillation`, `chat`, `code` 等）、质量期望（`high` / `normal`）与时延偏好，Hub 返回包含 1~5 个去重后的异构候选模型方案链（包含评分、得分拆解、治理健康度及通道容灾标记）。
2. **Endpoint Registry (`/api/endpoints/local-cpa`, `/api/endpoints/cpa-cloud`)**：
   动态感知 Local CPA（Host: `127.0.0.1:18117`，Docker: `cpa-local:8317`）及 Cloud CPA 运行端点与配置漂移。
3. **Feedback API (`POST /api/model/feedback`)**：
   接受实际调用结果回传（耗时、Token、错误分类及业务质量指标），动态驱动熔断降权。
4. **模型治理中心 (Model Governance)**：
   提供 206+ 模型的滑动窗口统计、P50/P95 追踪与 7 大标准错误分类自愈。

---

## 2. AI-KB 会话需要自主决策的核心事项

AI-KB 作为独立的 Owner 工程（`D:\AI-KB\Repo\ai-kb-infra`），其会话需在自身系统设计中独立决策：
1. **真实业务接入切入点**：
   - 是优先接入“AIKB Control Center 两层问答路由”？
   - 还是先作为 RAGFlow 召回后的“知识提炼 (Knowledge Distillation)”辅助模型？
2. **保留 Legacy 静态保底机制**：
   - Hub 绝不是 AI-KB 的生存单点。
   - 当 Hub 离线或所有候选失败时，AI-KB **MUST** 保留原有的直接访问百炼/Ollama 的静态保底逻辑。
3. **逐候选尝试与故障转移 (Candidate Chain Trial)**：
   - 按照 Hub 返回的 `candidates` 数组顺序逐个尝试；
   - 记录每次尝试的通道、时延与状态。
4. **计算业务专有质量反馈 (Quality Metrics Calculation)**：
   - AI-KB 负责计算自身专有的质量指标（例如：`knowledge_quality` 文档相关性分、`citation_validity` 引用有效率、`answer_completeness` 回答完整度）；
   - 将计算得到的数值（0.0 ~ 1.0）上报至 Hub 反馈接口。Hub 仅进行聚合，不侵入评测算法。
5. **调用反馈闭环**：
   - 在后台线程或异步任务中调用 `POST /api/model/feedback`，避免阻塞主问答流程。
