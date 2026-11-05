---
document_id: "DOC-STANDARDS-API-CONTRACT"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "API_CONTRACT"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "cdc3a7babe50fff69c52da406a0a2745b442ac14"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "CLI, JSON Schema, and Cross-Project Governance Data Contracts for AI-Engineering-Standards v3.0.0."
history_reference: "CHANGELOG.md"
primary_entrypoint: true
content_sha256: null
---


# 接口契约规范 (API & Schema Contract)

## 1. 权威 JSON Schema 契约入口 (`schemas/`)

- [`schemas/documentation-metadata.schema.json`](../schemas/documentation-metadata.schema.json)：12 类正式工程文档 YAML Frontmatter 契约。
- [`schemas/documentation-approval.schema.json`](../schemas/documentation-approval.schema.json)：ChatGPT 独立审核 (`chatgpt_review`) 与所有者批准 (`owner_approval`) 证据契约。
- [`schemas/standards-lock.schema.json`](../schemas/standards-lock.schema.json)：工程根目录 `standards.lock.json` 四元组锁定与 `previous_locks` 历史契约。
- [`schemas/engineering-baseline.schema.json`](../schemas/engineering-baseline.schema.json)：`ENGINEERING_BASELINE` 18 项内容与 6 项动态溯源字段契约。
- [`schemas/cross-session-handoff.schema.json`](../schemas/cross-session-handoff.schema.json)：`STD-020` 跨会话自动采集交接 11 项字段契约。
- [`schemas/engineering-manifest.schema.json`](../schemas/engineering-manifest.schema.json)：`STD-001` 工程清单唯一权威 Schema（与 [`governance/engineering-manifest-schema.json`](../governance/engineering-manifest-schema.json) 保持兼容镜像一致）。

## 2. 官方 CLI 工具调用契约（Tools）

| 命令入口 | 子命令 / 参数 | 返回码与输出契约 |
| :--- | :--- | :--- |
| `python tools/standards_sync/cli.py` | `discover` / `verify-lock` / `compare` / `impact` / `prepare-upgrade` / `validate-upgrade` / `promote` / `rollback` | 标准输出结构化 JSON；成功返回 `0`，阻断或校验失败返回 `1`（远端不可达时 `discover` 返回 `status: NOT_VERIFIABLE`） |
| `python tools/validate-documentation-collection.py` | `--project-root <DIR> [--schema <PATH>] [--check-templates]` | 执行 17 项文档集合、链接与锚点校验；全部通过返回 `0`，任一违例返回 `1` |
| `python tools/generate_engineering_baseline.py` | `--project-root <DIR> [--verify-only] [--observed-at <ISO>]` | 确定性生成或校验 `docs/当前权威基线.md` 与 `.artifacts/baseline/engineering_baseline.json`；源冲突时返回 `1` |
| `python tools/generate_handoff.py` | `--project-root <DIR> --task-id <ID> [--version <VER>]` | 自动采集 11 项工程事实并生成 `docs/CROSS-SESSION-HANDOFF.md` 与 `handoff/<TASK-ID>-<VERSION>-handoff.md` |
| `python tools/validate_approval_contract.py` | `--approval-file <JSON> [--document-file <MD>] [--expected-commit <SHA>]` | 校验双层审批契约、反自批及 SHA-256/Commit 一致性；通过返回 `0`，违例返回 `1` |


## 3. 消费端调用与权限边界

完整接入步骤、共享工具引用方式、依赖安装、模板复制、Windows/Linux 命令、CI 示例及升级/回滚流程统一见 [`Standards消费端接入与工具使用协议`](./Standards消费端接入与工具使用协议.md)。消费工程 **MUST NOT** 复制并分叉 `tools/`、`schemas/` 或标准正文；应通过固定版本的官方仓库引用调用。
