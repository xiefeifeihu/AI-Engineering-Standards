# STD-015: Playwright Acceptance Standard (Playwright 界面验收规范)

```text
STANDARD_ID=STD-015
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=所有 Web UI 控制台的自动化回归与验收
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 自动化验收约束

1. **Headless 运行与证据捕获**：
   Playwright 验收用例 **MUST** 支持 Headless 模式运行，并在 `acceptance_output/` 下自动捕获关键屏幕截图与全流程录屏视频。
2. **多主题验证 (Light / Dark Themes)**：
   验收用例 **MUST** 覆盖明亮模式（Light）与暗黑模式（Dark）切换，且切换过程中无明显 FOUC 样式闪烁。
3. **关键业务场景验证矩阵**：
   - 验证 Local CPA 常驻服务展示与期望状态；
   - 验证 Cloud CPA 按需服务展示与平时待命；
   - 验证 0 调用次数模型成功率与延迟显示“暂无数据”；
   - 验证 Candidate Plan 模型多样性与通道容灾标记；
   - 验证纯文本任务排除视觉模型；
   - 验证所有状态枚举完全中文化呈现。
