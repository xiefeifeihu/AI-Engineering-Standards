# 消费工程初始化模板索引（Consumer Project Starter）

本目录不复制公共工具实现，而是把仓库内已有权威模板映射到消费工程目标路径。消费工程应先创建 Manifest 与精确 Standards Lock，再按适用性复制正式文档模板。

## 模板映射

| 消费工程目标路径 | 权威模板/生成器 | 说明 |
|---|---|---|
| `engineering-manifest.yaml` | `governance/templates/engineering-manifest.template.yaml` | 填写项目身份、部署形态、资源属主和文档适用性 |
| `standards.lock.json` | `templates/standards.lock.template.json` | 仅含占位符；必须先运行官方 `discover` 并填入真实四元组 |
| `docs/DOCUMENT-INDEX.md` | `templates/documentation/DOCUMENT-INDEX.template.md` | 每种适用文档类型只登记一个主入口 |
| `docs/PROJECT-BLUEPRINT.md` | `templates/documentation/PROJECT-BLUEPRINT.template.md` | 项目愿景、边界与演进蓝图 |
| `docs/PRODUCT-BASELINE.md` | `templates/documentation/PRODUCT-BASELINE.template.md` | 已交付产品能力、职责与冻结决策 |
| `docs/SYSTEM-ARCHITECTURE.md` | `templates/documentation/SYSTEM-ARCHITECTURE.template.md` | 架构组件、数据流和信任边界 |
| `docs/TECHNICAL-DESIGN.md` | `templates/documentation/TECHNICAL-DESIGN.template.md` | 技术方案与实现设计 |
| `docs/API-CONTRACT.md` | `templates/documentation/API-CONTRACT.template.md` | API、事件和数据契约 |
| `docs/PROTOTYPE-UX.md` | `templates/documentation/PROTOTYPE-UX.template.md` | 原型和交互规范 |
| `docs/TEST-ACCEPTANCE.md` | `templates/documentation/TEST-ACCEPTANCE.template.md` | 测试分层、Case ID 和验收证据 |
| `docs/RELEASE-OPERATIONS.md` | `templates/documentation/RELEASE-OPERATIONS.template.md` | 发布、部署、回滚与运维 |
| `docs/DECISION-RECORD.md` | `templates/documentation/DECISION-RECORD.template.md` | 已批准 ADR 与待审决策分离 |
| `docs/CROSS-SESSION-HANDOFF.md` | `tools/generate_handoff.py` | 必须从真实 Git/Lock/测试/CI 事实生成 |
| `docs/当前权威基线.md` | `tools/generate_engineering_baseline.py` | 必须从正式文档和实时事实生成，不得手工填造 |

## 初始化顺序

1. 从官方 Standards 正式 Release 检出精确版本。
2. 运行 `discover`，验证 Tag Object SHA、Peeled Commit、VERSION 和 main CI。
3. 填充 `standards.lock.json`，并确保子模块/共享检出 HEAD 与 Peeled Commit 一致。
4. 从 Manifest 模板生成并填写本工程 Manifest。
5. 根据 `document_type_applicability` 复制适用的正式文档模板；不适用类型必须记录理由。
6. 运行官方文档集合和 Schema 校验。
7. 使用官方基线生成器与交接生成器生成动态综合视图。
8. 由 ChatGPT 审核候选文档；Owner 必批的决策必须单独批准。

Lock 模板中的 `0.0.0`、`v0.0.0` 和全零 SHA 是 `TEMPLATE_ONLY` 哨兵值，不是有效正式锁定。未用 `discover` 输出替换并通过 `verify-lock` 前，不得提交为正式 Lock。所有文档模板必须保持 `status: CANDIDATE`、`approval_status: NOT_SUBMITTED`，且 `source_commit`、`content_sha256`、`approval_evidence_ref` 为 `null`；不得预置 `ACTIVE`、`AI_APPROVED` 或 `OWNER_APPROVED`。未完成填充、真实证据核验和独立审批前，不得正式生效。
