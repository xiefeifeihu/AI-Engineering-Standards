---
document_id: "DOC-ENGINEERING-BASELINE-001"
document_version: "1.0.0"
project_id: "example-project"
document_type: "ENGINEERING_BASELINE"
status: "ACTIVE"
applies_to_release: "v1.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "当前权威基线自动生成综合视图初始模板"
history_reference: null
primary_entrypoint: true
source_commit: "0000000000000000000000000000000000000000"
approval_scope: "AI_APPROVABLE"
approval_status: "AI_APPROVED"
approval_evidence_ref: "docs/approvals/DOC-ENGINEERING-BASELINE-001.approval.json"
---

# 当前权威基线 (Engineering Baseline)

> **定位声明**：本文件（`docs/当前权威基线.md`）是由 `tools/generate_engineering_baseline.py` 自动生成的工程正式资料和实时核验事实综合视图。本文件不是第二套产品规格、不是第二套架构文档、不是第二套接口定义，也不是人工随意编辑的汇总报告；所有内容均引用原始权威资料与实时工程取证。

## 1. 工程身份与定位 (`project_identity`)
- **项目 ID**：`example-project`
- **仓库标识**：`owner/example-project`
- **部署类型**：`SERVICE`
- **发布 Profile**：`PERSONAL_LOCAL`
- **权威蓝图引用**：[`docs/PROJECT-BLUEPRINT.md`](./PROJECT-BLUEPRINT.md)

## 2. 当前产品版本 (`product_version`)
- **当前版本 (`VERSION`)**：`1.0.0`
- **发布标签 (`TAG`)**：`v1.0.0`

## 3. 正式产品功能及职责 (`product_capabilities`)
- **权威产品基线引用**：[`docs/PRODUCT-BASELINE.md`](./PRODUCT-BASELINE.md)

## 4. 当前架构边界 (`architecture_boundaries`)
- **权威系统架构引用**：[`docs/SYSTEM-ARCHITECTURE.md`](./SYSTEM-ARCHITECTURE.md)
- **权威技术方案引用**：[`docs/TECHNICAL-DESIGN.md`](./TECHNICAL-DESIGN.md)

## 5. 接口契约入口 (`api_contract_entrypoints`)
- **权威接口契约引用**：[`docs/API-CONTRACT.md`](./API-CONTRACT.md)

## 6. 已批准 ADR (`approved_adrs`)
- **权威决策记录引用**：[`docs/DECISION-RECORD.md`](./DECISION-RECORD.md)

## 7. 当前 Standards 锁定 (`standards_lock`)
- **锁文件引用**：`standards.lock.json`
- **锁定版本与 Tag**：`3.0.0` (`v3.0.0`)

## 8. Git 分支及 Commit 身份 (`git_identity`)
- **当前分支**：`main`
- **LOCAL_HEAD**：`0000000000000000000000000000000000000000`

## 9. 最近 CI 事实 (`recent_ci_facts`)
- **状态**：`NOT_RUN`

## 10. 最近 Build 事实 (`recent_build_facts`)
- **状态**：`NOT_RUN`

## 11. Runtime 核验事实 (`runtime_verification_facts`)
- **状态**：`NOT_RUN`

## 12. 测试和验收事实 (`test_and_acceptance_facts`)
- **权威测试基线引用**：[`docs/TEST-ACCEPTANCE.md`](./TEST-ACCEPTANCE.md)
- **权威运维手册引用**：[`docs/RELEASE-OPERATIONS.md`](./RELEASE-OPERATIONS.md)

## 13. 未决问题 (`open_issues`)
- 无未决阻塞问题（以实时生成结果为准）。

## 14. 待审批事项 (`pending_approvals`)
- 无待审批事项（以实时生成结果为准）。

## 15. 证据来源 (`evidence_sources`)
| 事实类别 | 仓库 (`repository`) | 来源路径 (`source_path`) | 来源 Commit (`source_commit`) | 证据引用 (`evidence_ref`) | 观测时间 (`observed_at`) | 核验状态 (`verification_status`) |
|:---|:---|:---|:---|:---|:---|:---|
| `CI` | `owner/example-project` | `.github/workflows/ci.yml` | `0000000000000000000000000000000000000000` | `.artifacts/ci/latest.json` | `2026-11-05T00:00:00Z` | `NOT_RUN` |

## 16. 来源 Commit (`source_commit`)
- `0000000000000000000000000000000000000000`

## 17. 核验时间 (`verified_at`)
- `2026-11-05T00:00:00Z`

## 18. 内容摘要 (`content_sha256`)
- `sha256:0000000000000000000000000000000000000000000000000000000000000000`
