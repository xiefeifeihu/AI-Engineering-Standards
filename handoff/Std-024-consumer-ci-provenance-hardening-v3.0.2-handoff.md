---
document_id: "DOC-AI-ENGINEERING-STANDARDS-STD024-HANDOFF-001"
document_version: "3.0.2"
project_id: "ai-engineering-standards"
document_type: "CROSS_SESSION_HANDOFF"
status: "IN_REVIEW"
applies_to_release: "v3.0.2"
last_updated: "2026-11-25"
supersedes: null
change_summary: "Std-024 消费端 CI 可信来源修复、Std-023/Std-024 PR 集成复核及 v3.0.2 候选交接"
history_reference: ".artifacts/packages/Acceptance-Std-024-consumer-ci-provenance-hardening-v3.0.2.zip"
primary_entrypoint: false
source_commit: "40920aa12cd2efff3f955ccb8267115e0e22fe89"
content_sha256: null
approval_scope: "AI_APPROVABLE"
approval_status: "IN_REVIEW"
approval_evidence_ref: null
---

# 跨会话任务交接：Std-024 Consumer CI Provenance Hardening

> 本文件是 Std-024 的任务级交接快照，由 Std-025-v3-0-2-release-approval 收口。它记录截至源快照 Commit 40920aa12cd2efff3f955ccb8267115e0e22fe89 的事实；本次新增交接和 PR15 测试夹具修正会形成新的 PR #16 HEAD，其最新双平台 CI 结果须以 GitHub Checks 为准。本文不构成合并或发布授权。

## 0. 任务与交接身份

- TASK_ID：Std-024-consumer-ci-provenance-hardening
- CLOSEOUT_TASK_ID：Std-025-v3-0-2-release-approval
- TASK_CLASS：INCIDENT_REPAIR
- REPOSITORY：xiefeifeihu/AI-Engineering-Standards
- BRANCH：fix/std-024-consumer-ci-provenance-hardening
- SOURCE_SNAPSHOT_HEAD：40920aa12cd2efff3f955ccb8267115e0e22fe89
- IMPLEMENTATION_COMMIT：7651c5f2407f9f581a8950078176e556e5660758
- CANDIDATE_CODE_COMMIT：d2ce0ba3d1e85b5a74cef12177ad445a97e3188b
- PR16：OPEN / DRAFT / base=main
- PR15：OPEN / DRAFT / unmerged
- HANDOFF_CAPTURED_AT：2026-11-25T05:25:00Z
- HANDOFF_STATUS_AT_CAPTURE：READY_FOR_FINAL_CI

## 1. 正式版本与候选版本边界

### 1.1 当前正式发布事实

- VERSION on candidate branch：3.0.2
- CURRENT_OFFICIAL_RELEASE：v3.0.1
- v3.0.1 Tag Object：a712e1689dbd62dc87ecb166e60cc17b6c7fa1c4
- v3.0.1 Peeled Commit：4facfdcd17a3003f04e7deaa3dbdcb320ff82afa
- v3.0.1 发布 Main CI：45099701154，Windows / Ubuntu PASS
- v3.0.0 Tag Object：8256bb384e62894219db0992a2cb57e16d4fa8cd
- v3.0.0 Peeled Commit：8b223019c254e0edeb94576b94af46c1e48b0316
- v3.0.2 Tag：不存在（NOT_RELEASED）
- standards.lock.json 与 engineering-manifest.yaml 仍锁定 v3.0.1
- RELEASE_STATUS=NOT_RELEASED
- OWNER_APPROVAL_REQUIRED=YES

禁止将 PR #16 Draft CI PASS 解释为正式发布。不得手工创建 v3.0.2 Tag，不得覆盖 v3.0.0 / v3.0.1。

## 2. Std-024 已完成的修复范围

### 2.1 F20 / F21：消费端 CI 证据真实性

目标文件：
- tools/standards_sync/core.py
- tests/test_consumer_integration_contract.py

完成内容：
- 区分 Runner Image Provisioner、action 下载 SHA、子模块 SHA 与消费者源码 Commit。
- 将实际主仓库 git log / rev-parse HEAD / detached HEAD 输出与预期 Consumer Commit 分离核验。
- 对 GitHub Run、Job、checkout、source identity steps 和执行结论执行 fail-closed 校验。
- 严格解析 test_execution、scan_execution、release_execution。
- 阻止无关 pytest 摘要冒充扫描证据、裸 OVERALL=PASS 冒充发布门禁，以及不一致的 PASS / NOT_APPLICABLE 计数。
- 保留原始日志不变；私有 Hub 日志不进入公开 Git 或 Acceptance ZIP。

### 2.2 六项真实 Hub CI 重放

来源：
- Repository：xiefeifeihu/AI-Engineering-Hub
- PR：#35
- Run：45310932802
- Event：pull_request
- head_sha：a7acc7967f2ea84d1711bf137428b594893e47fd
- Run conclusion：success

六项 Job：
| Gate | Job ID | 证据类型 | 修复后提交结果 |
|---|---:|---|---|
| unit_tests | 138166184154 | test_execution | VERIFIED |
| integration_tests | 138166184471 | test_execution | VERIFIED |
| security_scan | 138166184081 | scan_execution | VERIFIED |
| business_api | 138166184067 | test_execution | VERIFIED |
| runtime_acceptance | 138166183598 | test_execution | VERIFIED |
| release_gates | 138166184132 | release_execution | VERIFIED |

release_gates 对应 G01–G12：10 PASS、2 NOT_APPLICABLE（G05、G12，均有理由）、0 FAIL。

六份完整原始日志仅保存在受控本地目录：
.artifacts/acceptance/Std-024-consumer-ci-provenance-hardening/v3.0.2/hub_ci_replay/

原始日志 SHA-256 清单位于 Acceptance ZIP 的 hub_raw_logs_sha256.json。独立复审已从 GitHub 重新获取六份日志并计算哈希，6/6 与清单一致。

### 2.3 F22：验收 ZIP 覆盖事务保护

目标文件：
- scripts/package_acceptance.py

完成内容：
- 默认禁止覆盖历史 ZIP / sidecar / checksum 身份。
- --allow-overwrite 必须配合真实非占位 --overwrite-reason。
- overwrite_audit.jsonl 纳入可恢复多文件事务。
- 增加审计写入与替换失败注入、回滚和恢复校验。

历史包保持不变：
- Acceptance-Std-024-consumer-ci-provenance-hardening-v3.0.1.zip
  SHA-256：220297aeed096ced97b7a29ab43ba02a6254468924a01a7b53d07457acfb9c89
- Acceptance-Std-023-POST-RELEASE-EVIDENCE-CLOSEOUT-v3.0.1.zip
  SHA-256：e3a6af44c6ada36c7905fcc78514e3e95caf283f9b111ed23bcf243cad197e0b

## 3. Std-023 PR #15 与 Std-024 PR #16 集成复核

### 3.1 Git 祖先关系（已核实）

PR #15：
- HEAD：a0b2de23d007754c5551c17de4c77872e1d8212a
- Branch：docs/std-023-v3-0-1-post-release-closeout
- 4 个 PR commits：
  - c44c462ada8e8edda81b4b73ec7e4c0bd64b4050
  - b23c7ce8c881818cc6481859b97828ef67b9c2d7
  - a5106764b4736c220b20a89348e239cc4b132326
  - a0b2de23d007754c5551c17de4c77872e1d8212a

PR #16：
- 源快照 HEAD：40920aa12cd2efff3f955ccb8267115e0e22fe89
- Branch：fix/std-024-consumer-ci-provenance-hardening
- 与 PR #15 比较：status=diverged、ahead_by=7、behind_by=4、merge_base=4facfdcd17a3003f04e7deaa3dbdcb320ff82afa。

因此：PR #15 的 4 个提交并非 PR #16 的 Git 祖先。不能声称两个分支具有提交祖先关系，也不能仅以文件路径覆盖证明所有语义已集成。

### 3.2 文件与语义集成

- PR #15 的 13 个变更路径全部包含在 PR #16 的 16 个变更路径中。
- 下列 6 个文件在两个 PR HEAD 的 Git blob 完全一致：
  - README.md
  - docs/DOCUMENT-INDEX.md
  - docs/release-evidence/v3.0.1.json
  - engineering-manifest.yaml
  - handoff/Std-023-POST-RELEASE-EVIDENCE-CLOSEOUT-v3.0.1-handoff.md
  - standards.lock.json
- 下列文件在 PR #16 中经过候选版本刷新或功能扩展，需以 PR #16 内容为准：
  - CHANGELOG.md
  - docs/CROSS-SESSION-HANDOFF.md
  - docs/当前权威基线.md
  - tests/test_baseline_sync_and_approval_governance.py
  - tests/test_consumer_integration_contract.py
  - tools/generate_engineering_baseline.py
  - tools/generate_handoff.py
- PR #16 保留 v3.0.1 正式发布凭证、Standards 自身 v3.0.1 lock、Std-023 任务交接、Std-020_FINAL_RELEASE 与 CURRENT_CANDIDATE_PR 两个独立事实作用域。
- PR #16 的历史 PR #13/#14 测试保留 version_override=3.0.1，避免 VERSION=3.0.2 时改变历史合同测试语义。

### 3.3 本次发现并修复的 PR15 独有测试差异

PR #15 对 test_a6_promote_and_rollback_parity_against_candidate_commit 增加了历史 v2.11.0 fixture 绑定：
- standards.version=2.11.0
- standards.tag=v2.11.0
- standards.tag_object_sha=2f4b4b54348a5ac8891e5a0b33c04635a27213a0
- standards.peeled_commit=5e17c0ef560ab8abafe880b988d70f85f380a104
- 并增加断言，确保失败原因不是 DOWNGRADE_FORBIDDEN。

复核发现，PR #16 在扩展同一测试文件时遗漏了这 4 个字段与 1 个断言。Std-025 已在本次交接提交中将其恢复。最新 Commit 的 CI 必须再次验证该测试与全量测试。

结论：
- PR15/PR16 为内容级协调集成，不是 Git ancestry 集成。
- PR15 保持 OPEN / DRAFT；PR16 未合并前不得关闭 PR15。
- PR16 合并后，重新核对 PR15 剩余 Diff，确认被完整替代后再由 Owner 决定关闭为 superseded。
- 不对 PR15 做独立合并，不强推，不重写历史。

## 4. 文档治理与历史资产

- 14 份受控文档继续保持 status=IN_REVIEW、approval_status=IN_REVIEW。
- 不自动晋升 ACTIVE。
- 分类勘误：
  - docs/PROTOTYPE-UX.md = AI_APPROVABLE
  - docs/Standards消费端接入与工具使用协议.md = OWNER_MANDATORY
- 历史 Std-023 Acceptance ZIP 不修改。
- v3.0.1 release-evidence 不修改。
- v3.0.0 / v3.0.1 Annotated Tag 不修改。

## 5. 已有本地测试与门禁证据（源快照 40920aa）

- 全量单元测试：359 tests，OK，退出码 0。
- STD024_REQUIRE_VERBATIM_REPLAY=1：六项真实 Hub Job replay 均 VERIFIED。
- Live GitHub API：六项 Job VERIFIED；六项 bypass probes fail-closed。
- Schema：32/32 PASS。
- 文档集合、Baseline/Handoff verify-only、verify-lock、compare、release_evidence --check-ci、test coverage、git diff --check、Secret Scan：全部 PASS。
- Secret Scan：196 个跟踪文件，0 命中。

## 6. 源快照远端 CI（40920aa）

- Push Run 45534472714：Windows Job 138937566193 PASS；Ubuntu Job 138937566473 PASS。
- PR Run 45534477548：Windows Job 138937581409 PASS；Ubuntu Job 138937581587 PASS。
- 两个 Tag Publish Job 均 skipped，符合 feature branch / pull_request 候选阶段行为。
- 这些 CI 绑定的是源快照 40920aa，不是本次新增交接与测试修复后的最终 HEAD。

## 7. Acceptance ZIP

文件：
Acceptance-Std-024-consumer-ci-provenance-hardening-v3.0.2.zip

SHA-256：
57b5a32b06662178197d433c4471414ed51b33c607d9f9b59470d6eaaa5c6b8e

ZIP 内容：
manifest.json + 11 项证据文件；CRC 与 11 项载荷 SHA-256 均通过；不包含私有原始 .log。

## 8. 当前待完成事项与严格停止点

1. 本次提交后，重新读取 PR #16 最新 HEAD。
2. 等待最新 Push CI 与 PR CI 的 Windows / Ubuntu 作业全部完成。
3. 核对两次 CI 的 head_sha 都等于 PR #16 最新 HEAD。
4. 核对修复后的 test_a6 与全量 359 项测试结果。
5. 将最终 HEAD、Commit、Push Run、PR Run、四个双平台 Job ID 和结论记录在 PR #16 审计评论。
6. 保持 PR #16 OPEN / DRAFT。
7. 保持 PR #15 OPEN / DRAFT。
8. 不合并 PR #16，不关闭 PR #15，不创建或签发 v3.0.2。

必须等待 Owner 对 PR #16 最新精确 HEAD 的明确批准，方可进入 Merge Commit 合并与 main CI 自动签标阶段。

## 9. 下一会话启动指引

先实时核验：
- PR #16 的最新 head SHA、draft、base 与 mergeable 状态。
- PR #15 的最新 head SHA 与剩余 Diff。
- main HEAD 与 v3.0.1 Tag Object / Peeled Commit。
- 本次新提交的 Push CI 与 PR CI 双平台状态。
- v3.0.2 Tag 仍不存在。

最终返回字段：
TASK_ID=Std-025-v3-0-2-release-approval
STD024_HANDOFF_STATUS=
PR15_PR16_CONTENT_INTEGRATION=
PR16_FINAL_HEAD=
PR16_PUSH_CI=
PR16_PR_CI=
WINDOWS_CI=
UBUNTU_CI=
PR16_STATE=OPEN_DRAFT
PR15_STATE=OPEN_DRAFT
OWNER_APPROVAL_REQUIRED=YES
RELEASE_STATUS=NOT_RELEASED
OVERALL_STATUS=
