# STD-016: Acceptance Evidence ZIP Standard (验收证据包规范)

```text
STANDARD_ID=STD-016
VERSION=1.1.0
STATUS=ACTIVE
SCOPE=工程阶段里程碑发布与交付物打包
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-23
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
2. **标准命名与唯一存储路径契约**：
   - 标准命名：`Acceptance-<TASK-ID>-v<VERSION>.zip`（或 `Acceptance-<PROJECT-ID>-<VERSION/TAG>.zip`）。
   - **唯一合法输出路径**：所有正式交付 Acceptance ZIP **MUST** 仅存放在 `.artifacts/packages/` 目录下，并在同目录生成外部 `.sha256` 校验文件。
   - **严禁违规存放**：**MUST NOT** 在 `.artifacts/acceptance/` 目录、项目根目录或 `docs/` 下生成或存放正式交付 ZIP 包。
3. **唯一打包器与 Manifest 校验 (`STD-034`)**：
   - 每个工程仓库 **MUST** 仅通过唯一打包器 `scripts/package_acceptance.py` 基于 `.artifacts/acceptance/<TASK-ID>/v<VERSION>/manifest.json` 驱动打包。
   - `manifest.json` **MUST NOT** 包含最终 ZIP 自身的 SHA256（避免循环自引用）；打包完成后必须独立计算外部 `.sha256` 并执行真实解压与全文件哈希复核。
4. **必需包含的内容**：
   - `manifest.json`（含文件列表 `path`、`size > 0`、`sha256`）
   - `acceptance_report.md` 及可选的 PDF 报告
   - 自动化测试原始日志 (`test_results.txt`)
   - 验收截图目录 (`screenshots/`)
   - 验证输出数据快照与 Git 状态审计记录