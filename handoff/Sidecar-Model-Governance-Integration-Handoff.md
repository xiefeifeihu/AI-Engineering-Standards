# Sidecar 模型治理接入交接指南 (Sidecar Model Governance Integration Handoff)

```text
TARGET_PROJECT=VTIP-AI-SIDECAR (vtip-ai-sidecar)
TARGET_AUDIENCE=Sidecar ChatGPT / Claude 长期架构会话
GOVERNANCE_BASELINE=AI Engineering Standards V1.0 / AI-Hub v0.5.4
STATUS=OFFICIAL_HANDOFF
```

---

## 1. 架构定位与交接前言

本交接文档专供 **VTIP-AI-SIDECAR 项目专属会话** 阅读与系统设计，**Hub 严禁直接侵入或修改 Sidecar 代码库**。

AI-Engineering-Hub 已提供：
- 规范的 Candidate Plan 接口（`POST /api/model/select`）
- 零密钥端点注册表
- 业务反馈接口（`POST /api/model/feedback`）

---

## 2. Sidecar 会话需要自主决策的核心事项

1. **Fact Guard 事实护栏与反馈契约**：
   - Sidecar 拥有专属的 Fact Guard 校验逻辑；
   - 校验结果指标（如 `fact_guard_pass` (0 或 1)、`confidence` (0.0~1.0)、`structure_validity` (0.0~1.0)）由 Sidecar 独立计算并打包在 `quality_metrics` 中上报给 Hub；
   - Hub 仅记录与聚合，绝不复制 Fact Guard 的内部规则与 Prompt 实现。
2. **Sidecar Champion 机制与 Hub Candidate 的协作**：
   - Sidecar 在调用 Hub 路由接口获取候选方案链后，如何与自身预置的 Champion 模型进行优先级仲裁或退避校验。
3. **Safe Fallback 策略**：
   - Sidecar 作为业务中继，必须在所有 Hub 候选失活时具备本地或直接直连通道的优雅回退能力，确保调用方不发生挂死。
