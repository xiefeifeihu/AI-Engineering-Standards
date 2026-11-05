---
document_id: "DOC-STANDARDS-PROJECT-BLUEPRINT"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "PROJECT_BLUEPRINT"
status: "ACTIVE"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "5e17c0ef560ab8abafe880b988d70f85f380a104"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "Project Blueprint for AI-Engineering-Standards independent governance repository."
history_reference: "CHANGELOG.md"
primary_entrypoint: true
---

# 项目总体蓝图 (Project Blueprint)

## 1. 工程定位与核心使命

- **唯一规范权威源 (Single Source of Truth)**：`xiefeifeihu/AI-Engineering-Standards` 是跨工程架构、研发、测试、文档、发布、证据和运行契约的唯一规范权威源。
- **独立自治维护 (`D4=APPROVED`)**：`AI-Engineering-Standards` 作为独立工程维护全部官方规范正文（`standards/`）、机器可读契约（`schemas/`）、标准模板（`templates/`）和官方共享工具（`tools/`），不依附于 `AI-Engineering-Hub` 或 `AI-KB`。
- **受控版本锁定与自动同步 (`D3`/`D5=APPROVED`)**：所有下游工程（`AI-Engineering-Hub`、`AI-KB`、`vtip-platform-catalog`、`vtip-ai-sidecar`）通过 `standards.lock.json` 四元组精确锁定经过 `main` CI 验证的正式发布 Tag，禁止使用浮动 `main` 或手工硬编码版本号。

## 2. 跨工程边界与职责划分

| 仓库名称 | 角色定位 | 针对 Standards 的权限边界 |
| :--- | :--- | :--- |
| `xiefeifeihu/AI-Engineering-Standards` | 唯一规范与官方共享工具属主 | 唯一允许编写、维护和发布 `STD-001`~`STD-035`、JSON Schemas 与 `tools/standards_sync` 的仓库 |
| `AI-Engineering-Hub` | 控制平面与模型路由中枢 | 只读消费端：通过 `standards.lock.json` 锁定版本，不得复制规范正文或充当 Standards 修改入口 |
| `AI-KB` (`ai-kb-infra`) | 知识引擎与推理资源属主 | 只读消费端：消费官方 `tools/standards_sync`，不再维护私有同步工具副本 |
| `vtip-platform-catalog` | VTIP 平台编目与服务治理 | 只读消费端：遵循统一 `schemas/engineering-manifest.schema.json` 与 `STD-035` 12 类文档契约 |
| `vtip-ai-sidecar` | VTIP 智能伴随服务 | 只读消费端：遵循统一 `standards.lock.json` 与 `STD-035` 12 类文档契约 |

## 3. 演进里程碑

- **v1.0.0 – v2.4.0**：建立 `STD-001` 至 `STD-033` 核心规范矩阵、模型路由契约、两阶段运行时验收与 14 阶段工程生命周期。
- **v2.5.0 – v2.11.0**：建立 `STD-034` 编码智能体执行治理、`STD-035` 全生命周期文档契约与 AI 自主测试设计闭环。
- **v3.0.0（当前基线）**：完成 12 类正式文档收敛（移除 `HISTORICAL_ARCHIVE` 枚举、新增 `ENGINEERING_BASELINE`）、ChatGPT 独立审核与 Owner 双层批准契约、`STD-020` 跨会话自动采集交接，以及 `tools/standards_sync` 官方版本发现与受控同步工具链。
