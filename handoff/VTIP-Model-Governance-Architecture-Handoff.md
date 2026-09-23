# VTIP 模型治理架构交接指南 (VTIP Model Governance Architecture Handoff)

```text
TARGET_PROJECT=VTIP Platform (vtip-platform-catalog)
TARGET_AUDIENCE=VTIP 架构与系统会话
GOVERNANCE_BASELINE=AI Engineering Standards V1.0 / AI-Hub v0.5.4
STATUS=OFFICIAL_HANDOFF
```

---

## 1. 核心架构建议与职责划分

**强烈警示：不要默认 VTIP 平台直接调用 AI-Hub！**

VTIP 架构会话首先应当判断：**所有业务 AI 推理能力是否应该统一经过 Sidecar (`VTIP-AI-SIDECAR`)？**

### 推荐的优先架构：
```text
┌─────────────────────────┐
│   VTIP 业务系统         │ (关注情报分析、目录协同与业务模型)
└────────────┬────────────┘
             │ 专用业务协议 / Fact Guard
             ▼
┌─────────────────────────┐
│   VTIP-AI-SIDECAR       │ (专职业务中继、安全护栏、Prompt 编排与模型接入)
└────────────┬────────────┘
             │ Candidate Plan & 反馈聚合
             ▼
┌─────────────────────────┐
│   AI-Engineering-Hub    │ (机器级治理：模型发现、配额、熔断、动态路由与审计)
└─────────────────────────┘
```

### 架构考量与红线：
1. **避免双重实现**：
   若 VTIP 平台与 Sidecar 同时维护一套直连 AI-Hub 的路由逻辑，将导致重复的模型适配代码、双倍的鉴权维护与配置漂移。
2. **纯粹业务边界**：
   VTIP 应将模型调用复杂性下沉至 Sidecar，由 Sidecar 统一对接 AI-Hub 的 Candidate Plan 与反馈闭环。
