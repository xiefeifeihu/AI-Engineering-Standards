# STD-010: Model Feedback Contract (模型调用反馈契约)

```text
STANDARD_ID=STD-010
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=所有向 AI-Hub 上报实际调用结果的业务消费者
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
SCHEMA_REF=schemas/model-feedback.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 接口与上报规范

业务系统在实际完成模型调用后，**SHOULD** 异步将执行结果上报至 `POST /api/model/feedback`。

```json
{
  "decision_id": "route-1774316000-a1b2c3",
  "consumer": "ai-kb",
  "task": "knowledge_distillation",
  "model": "qwen2.5-72b-instruct",
  "channel": "local-cpa",
  "success": true,
  "latency_ms": 1420.5,
  "prompt_tokens": 850,
  "completion_tokens": 320,
  "total_tokens": 1170,
  "quality_metrics": {
    "knowledge_quality": 0.95,
    "citation_validity": 1.0,
    "answer_completeness": 0.9
  }
}
```

---

## 2. 职责分界红线

1. **通用契约承载，不侵入业务评测算法**：
   AI-Hub **MUST NOT** 深度实现 AI-KB 的知识切片相关性评分、事实校验算法或 Sidecar 的 Fact Guard 逻辑。
2. **指标聚合与熔断驱动**：
   Hub 仅接收并统计业务方回传的通用分数（0.0 ~ 1.0），用于驱动滑动窗口指标更新、熔断状态机流转与动态降权。
