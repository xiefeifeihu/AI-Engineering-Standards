---
document_id: "DOC-STANDARDS-SYSTEM-ARCHITECTURE"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "SYSTEM_ARCHITECTURE"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "cdc3a7babe50fff69c52da406a0a2745b442ac14"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "System Architecture for AI-Engineering-Standards v3.0.0 defining single source of truth topology, baseline synthesis, approval pipeline, and version sync boundaries."
history_reference: "docs/architecture/STANDARDS-V1-ARCHITECTURE.md"
primary_entrypoint: true
content_sha256: null
---


# 系统架构设计 (System Architecture)

## 1. 核心架构组件与边界

- **规范定义层 (`standards/` + `templates/`)**：承载人类可读与智能体可读的权威条文及 12 类标准文档模板，是所有下游工程架构与研发契约的上游源头。
- **契约模式层 (`schemas/` + `governance/`)**：以 `schemas/*.schema.json` 为唯一权威机器契约，`governance/engineering-manifest-schema.json` 作为受控只读兼容镜像，消除双轨 Schema 漂移。
- **自动化治理工具层 (`tools/`)**：
  - `tools/standards_sync/`：负责远端/本地正式 Tag 发现、四元组校验、版本/条款/Schema 差异对比、10 维度兼容性影响评估、升级候选生成、回归验证、受控晋升与历史回滚。
  - `tools/generate_engineering_baseline.py`：负责汇聚 10 类正式文档与 9 类实时事实，确定性产出 `docs/当前权威基线.md`。
  - `tools/generate_handoff.py`：负责自动采集 Git/CI/测试/决策状态并生成 `docs/CROSS-SESSION-HANDOFF.md` 及 `handoff/` 快照。
  - `tools/validate-documentation-collection.py` & `tools/validate_approval_contract.py`：负责 17 项文档集合校验与双层审批真实性门禁。
- **只读下游消费边界**：`AI-Engineering-Hub`、`AI-KB`、`vtip-platform-catalog`、`vtip-ai-sidecar` 单向依赖本仓库发布的已验证 Tag，本仓库严禁反向依赖下游工程代码或运行时服务。

## 2. 文档晋升与版本同步数据流

```mermaid
flowchart TD
    A["Coding Agent 维护正式文档 / 生成候选"] --> B["工具自动校验 (Schema + 17项集合校验 + 基线一致性)"]
    B --> C["ChatGPT 独立跨文档及事实审核 (chatgpt_review)"]
    C --> D{"是否属于 Owner 必批范围 (D2)?"}
    D -- "否 (AI可批范围)" --> E["记录 AI_APPROVED (绑定 Commit + SHA256)"]
    D -- "是 / 不确定 (默认要求Owner)" --> F["Owner 在聊天或受控介质批准 -> 记录 OWNER_APPROVED"]
    E --> G["Git 固化 & 远端 main CI 全绿"]
    F --> G
    G --> H["签发 Annotated Tag & Project Sources / 下游工程受控同步"]
```
