---
document_id: "DOC-STANDARDS-PRODUCT-BASELINE"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "PRODUCT_BASELINE"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "cdc3a7babe50fff69c52da406a0a2745b442ac14"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "Product Baseline for AI-Engineering-Standards v3.0.0 covering STD-001..STD-035, 30 JSON Schemas, 12 Doc Templates, and official CLI tools."
history_reference: "CHANGELOG.md"
primary_entrypoint: true
content_sha256: null
---


# 产品功能与当前基线 (Product Baseline)

## 1. 当前正式交付能力清单

- **全平台正式工程规范矩阵 (`standards/`)**：维护 `STD-001` 至 `STD-035` 共 31 份正式规范，覆盖工程清单、资源归属、端点注册、标准动作、健康生命周期、端口治理、零密钥安全、模型治理 (`STD-008`~`STD-011`, `STD-021`~`STD-026`)、运行时边界、可观测性、分层测试、Playwright 验收、Acceptance ZIP、Git 发布、中文诊断展示、制品卫生、跨会话交接 (`STD-020`)、运行时与发布工程 (`STD-031`~`STD-033`)、智能体执行治理 (`STD-034`) 与全生命周期文档契约 (`STD-035`)。
- **30 个机器可读 JSON Schema (`schemas/`)**：提供 Draft 2020-12 标准 Schema，包含新增的 `documentation-approval.schema.json`、`standards-lock.schema.json`、`engineering-baseline.schema.json`、`cross-session-handoff.schema.json` 及更新的 12 类 `documentation-metadata.schema.json` 与统一 `engineering-manifest.schema.json`。
- **当前权威基线自动生成引擎 (`tools/generate_engineering_baseline.py`)**：从 10 类正式文档与 9 类实时工程事实确定性生成 `docs/当前权威基线.md`，强制校验 18 项核心字段与 6 项动态溯源属性。
- **跨会话交接自动采集引擎 (`tools/generate_handoff.py`)**：自动采集 11 项实时 Git、锁定、测试、CI 与任务状态，维护唯一活跃入口 `docs/CROSS-SESSION-HANDOFF.md` 与任务级不可变快照 `handoff/<TASK-ID>-<VERSION>-handoff.md`。
- **双层审批防伪造校验器 (`tools/validate_approval_contract.py`)**：强制分离 ChatGPT 独立审核记录 (`chatgpt_review`) 与所有者批准记录 (`owner_approval`)，校验 `CANDIDATE_COMMIT` 与 `CONTENT_SHA256` 绑定，拦截智能体自批。
- **Standards 官方版本发现与受控同步工具 (`tools/standards_sync/`)**：提供 `discover`、`verify-lock`、`compare`、`impact`、`prepare-upgrade`、`validate-upgrade`、`promote`、`rollback` 8 大子命令，实现精确四元组锁定与一键回滚。
- **跨平台 17 项文档集合校验器 (`tools/validate-documentation-collection.py`)**：无任何硬编码本地绝对路径，在 Windows 与 Linux 上统一校验 12 类主入口唯一性、生命周期与审批状态一致性、Markdown 相对链接及标题锚点可达性。
