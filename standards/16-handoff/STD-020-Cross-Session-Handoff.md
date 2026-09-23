# STD-020: Cross-Session Handoff Standard (跨会话交接规范)

```text
STANDARD_ID=STD-020
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=所有 AI 工程任务的会话间交接协议
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

## 1. 交接类型定义 (Handoff Types)

| 类型 | 说明 | 持久性 | 格式 |
|------|------|--------|------|
| **DURABLE** | 正式交接文档，提交入 Git，长期有效 | 永久 | Markdown，存于 `handoff/` |
| **TEMPORARY** | 临时上下文传递，不提交 | 单次使用后删除 | Markdown，存于 `.artifacts/handoff/temporary/` |

## 2. Durable 交接文档规范

1. **强制字段**：
   - `TASK_ID`：任务标识符（例：`AI-ENGINEERING-PLATFORM-V1-002`）
   - `VERSION`：目标版本
   - `STATUS`：`COMPLETED` | `IN_PROGRESS` | `BLOCKED`
   - `COMPLETED_ITEMS`：已完成项列表
   - `PENDING_ITEMS`：待续项列表
   - `COMMIT_HASH`：最后提交哈希
   - `TEST_RESULTS`：测试结果摘要
2. **提交要求**：Durable 交接文档 **MUST** 在任务完成后单独提交到目标仓库的 `handoff/` 目录。
3. **命名规范**：`<TASK-ID>-<VERSION>-handoff.md`

## 3. Temporary 交接规范

1. **存储位置**：**MUST** 存放于 `.artifacts/handoff/temporary/`，且被 `.gitignore` 排除。
2. **生命周期**：临时交接文档 **MUST** 在目标会话确认接收后删除。
3. **格式**：自由格式 Markdown，但 **SHOULD** 包含：当前工作状态、未完成步骤、关键变量/配置。

## 4. 验收交接包 (Acceptance Handoff Package)

验收 ZIP 包视为 ARCHIVE 类型 Durable 交接物：
1. **MUST** 遵循 STD-016 命名规范。
2. **MUST** 存放于 `.artifacts/packages/`，从不提交 Git。
3. **MUST** 包含 `manifest.json` 元数据文件，字段包括 `task_id`、`version`、`run_id`、`created_at`、`files`。

## 5. 跨仓库交接约束

1. 不同仓库的交接文档 **MUST** 独立存放，**MUST NOT** 跨仓库混合内容。
2. 对只读仓库（AI-KB、VTIP Platform）的交接 **MUST** 以外部文档形式存放，严禁修改目标仓库。