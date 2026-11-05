---
document_id: "DOC-STANDARDS-PROTOTYPE-UX"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "PROTOTYPE_UX"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "AI_APPROVABLE"
approval_evidence_ref: null
source_commit: "5e17c0ef560ab8abafe880b988d70f85f380a104"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "CLI UX and STD-018 Chinese Diagnostics Presentation Contract for AI-Engineering-Standards."
history_reference: "standards/14-ui-diagnostics/STD-018-ui-diagnostics-enum-presentation.md"
primary_entrypoint: true
content_sha256: "sha256:d6d9b2d39bd7deb494ec94648b76f26746b841432234a1176419763296186455"
---


# 原型与交互体验规范 (Prototype & UX Specification)

## 1. 适用性说明 (`NON_RUNTIME_ARTIFACT`)

`AI-Engineering-Standards` 仓库属于非运行时规范与工具制品库（`deployment_kind: NON_RUNTIME_ARTIFACT`），自身不包含 Web 浏览器前端服务。本规范文档定义：
1. 本仓库官方 CLI 工具（`tools/standards_sync`、`tools/validate-documentation-collection.py`、`tools/generate_engineering_baseline.py`）的结构化诊断交互体验；
2. 面向全平台受管工程 UI 的 [`STD-018`](../standards/14-ui-diagnostics/STD-018-ui-diagnostics-enum-presentation.md) 内部枚举与简体中文界面展示映射标准。

## 2. 状态枚举与界面/报告展示规范 (`STD-018` / `STD-035`)

| 内部机器枚举 | 中文标准展示名称 | 语义定义与视觉规范 |
| :--- | :--- | :--- |
| `PASS` / `IN_SYNC` | 已核验通过 / 已同步 | 具备真实命令执行证据（`exit_code=0`）或精确四元组匹配 |
| `FAIL` / `UPGRADE_BLOCKED` | 校验失败 / 升级阻断 | 存在 Schema、文档集合、测试或兼容性断裂，禁止自动晋升 |
| `BLOCK` | 门禁阻断 | 前置条件不满足或违反安全/分支/审批铁律 |
| `NOT_RUN` | 未执行 | 尚未运行测试或属于非运行时仓库不适用的在线探针 |
| `NOT_VERIFIABLE` | 暂不可核验 | 远端网络离线或外部 API 不可达，禁止伪造为 `PASS` |
| `STALE` | 证据已过期 | 文档正文或 Git Commit 已变更，原审批或验证证据失效 |
