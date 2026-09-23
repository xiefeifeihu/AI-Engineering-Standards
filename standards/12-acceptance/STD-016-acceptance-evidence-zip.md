# STD-016: Acceptance Evidence ZIP Standard (验收证据包规范)

```text
STANDARD_ID=STD-016
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=工程阶段里程碑发布与交付物打包
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

## 1. 验收证据包打包规范

1. **独立打包原则**：
   不同工程仓库的验收成果 **MUST** 分别打包为独立的 ZIP 文件，严禁跨仓库混合打包。
2. **标准命名契约**：
   - `Acceptance-<PROJECT-ID>-<VERSION/TAG>.zip`
3. **必需包含的内容**：
   - `acceptance_report.md` 及可选的 PDF 报告
   - 自动化测试日志 (`test_results.txt`)
   - 验收截图目录 (`screenshots/`)
   - 验证输出数据快照
