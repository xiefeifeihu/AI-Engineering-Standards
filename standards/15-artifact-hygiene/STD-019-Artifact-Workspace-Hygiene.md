# STD-019: Artifact & Workspace Hygiene Standard (工程制品与工作区卫生规范)

```text
STANDARD_ID=STD-019
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=所有 AI 工程仓库的制品分类、存储与清理
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

## 1. 制品分类 (Artifact Classification)

所有工程制品 **MUST** 按以下六类分类处理：

| 类别 | 描述 | Git 状态 | 存储位置 |
|------|------|----------|----------|
| **SOURCE** | 源代码、配置、Schema、文档 | 必须提交 | 仓库源树 |
| **GENERATED** | 自动生成文件（报告、PDF、临时输出） | MUST NOT 提交 | `.artifacts/` |
| **ACCEPTANCE** | 验收证据（截图、视频、日志、报告） | MUST NOT 提交 | `.artifacts/acceptance/<TASK>/<VERSION>/` |
| **DEMO** | 演示录屏与截图 | MUST NOT 提交 | `.artifacts/demo/` |
| **TEMPORARY** | 临时工作文件（草稿、调试输出） | MUST NOT 提交 | `.artifacts/handoff/temporary/` |
| **ARCHIVE** | 历史交付 ZIP 包 | MUST NOT 提交 | `.artifacts/packages/` |

## 2. .artifacts/ 目录规范

1. **根目录隔离**：每个仓库根目录下 **MUST** 维护 `.artifacts/` 目录。
2. **Git 排除**：`.artifacts/` **MUST** 出现在 `.gitignore` 中，任何子目录或文件 **MUST NOT** 被提交。
3. **标准子目录结构**：
   ```
   .artifacts/
     acceptance/<TASK-ID>/<VERSION>/
       reports/          # 验收报告 Markdown/PDF
       screenshots/      # 关键截图
       videos/           # 录屏视频
       logs/             # 测试日志
       manifest.json     # 本次验收元数据
     packages/           # 最终 ZIP 交付包
     demo/               # 演示资产
     handoff/
       temporary/        # 跨会话临时交接文件
   ```

## 3. 验收子目录命名规范

- TASK-ID：全大写，格式为 `<PROJECT>-<TYPE>-<NNN>`（例：`AI-HUB-DEV-009`）
- VERSION：语义化版本，格式为 `v<MAJOR>.<MINOR>.<PATCH>`（例：`v0.5.6`）

## 4. 工作区清理策略 (Workspace Hygiene Policy)

1. **定期审计**：每次里程碑发布后 **SHOULD** 运行 `tools/cleanup_audit.py` 生成清理审计报告。
2. **禁止手动删除**：**MUST NOT** 直接删除任何文件，必须先生成 `workspace_cleanup_plan.md` 并经人工审核。
3. **分类保留策略**：
   - `KEEP`：当前活跃制品，保留不动。
   - `ARCHIVE`：历史 ZIP 交付包，保留在 `.artifacts/packages/`。
   - `GENERATED`：自动生成文件，可安全删除后重新生成。
   - `TEMP`：临时文件，确认后删除。
   - `OBSOLETE`：过期废弃制品，确认后删除。

## 5. 旧版打包脚本清理

1. 每个仓库 **MUST** 只保留一个 `scripts/package_acceptance.py` 统一打包脚本。
2. 历史版本化脚本（如 `package_acceptance_v05*.py`）**MUST** 在版本升级后删除。
3. 统一脚本 **MUST** 通过 manifest JSON 驱动，支持 `task_id`、`version`、`run_id` 参数化。