# STD-014: Testing Standard (跨项目分层测试规范)

```text
STANDARD_ID=STD-014
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=AI-Engineering-Standards、AI-Engineering-Hub 及跨工程自动化测试
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

## 1. 分层测试体系要求

1. **非破坏性原则 (Non-Destructive Testing)**：
   测试用例 **MUST NOT** 调用破坏性清空命令，**MUST NOT** 删除真实数据集或清空历史有效审计日志。
2. **Standards 仓库测试**：
   必须包含自动化 Schema 校验脚本（`tools/validate-schemas.py`），对所有 9 个 Schema 进行有效性与边界样例回归测试。
3. **Hub 仓库测试**：
   包含针对性单元测试、API 集成测试与端到端 Playwright UI 验收测试。
