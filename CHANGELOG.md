# AI Engineering Standards - Changelog

All notable changes to the AI Engineering Standards baseline are documented in this file.

## [Unreleased]

> RELEASE_STATUS=CANDIDATE | PROPOSED_VERSION=3.0.0 | MAIN_MERGED=true | RELEASE_TAG_NOT_CREATED=true | REISSUE_IN_PROGRESS=true
>
> **v3.0.0 一次性重发处理中 (PR #9 已合并，修复分支 PR #10 处理中)**：
> - PR #9 已由 Owner 正式合入官方 main（Merge Commit: `3cd42b69049b148bceea1324d4f8212393cb96df`），状态：`PR9=MERGED`。
> - main CI 历史运行失败（Run 42933692363: `Run 42835611644 has no associated pull requests`），原因为 PR 合并后 GitHub Actions API 历史 Run 的 `pull_requests` 字段返回空列表。
> - Std-016 已完成：OUTPUT_COMMIT=`fd9dd6e0de9e5e1b00c5bfa1d0e213401fa90eb7`，Push Run `42938147072` (Windows/Ubuntu PASS)，PR Run `42938186969` (Windows/Ubuntu PASS)，TEST_COUNT=220，STATUS=COMPLETED。
> - Std-017 已完成：OUTPUT_COMMIT=`d00821e251bfe3c1495163b6af8af6c01210d5f4`，Push Run `42942640853` (Windows/Ubuntu PASS)，PR Run `42942649996` (Windows/Ubuntu PASS)，TEST_COUNT=220，STATUS=COMPLETED，交付包 SHA256: `97d90be32a5dad6a5fa415eaea8c941248c2cecdae45491263f433cc6d40a0bd`。
> - Std-018 最终收口：已验证输入快照 Commit `21939da5e13eb39dedd0557561e88e1342be694c`，Push Run `42983601133` (Windows/Ubuntu PASS)，PR Run `42983609802` (Windows/Ubuntu PASS)，TEST_COUNT=221，STD018=COMPLETED。前序快照 Commit `09940874a1bf539f53c22426add0757667c040a0`。实现 PR9 历史发布证据与 Std-018 当前工程快照双证据双作用域独立核验，消除重复作用域与重复字段首匹配绕过缺陷，权威基线与跨会话交接严格分界。
> - PR #10 关联分支 `fix/std-016-merged-pr-run-evidence`，状态：`PR10=OPEN/DRAFT`；当前处于 OPEN/DRAFT 状态，待 ChatGPT 独立复核及 Owner 批准；合入 main 后仍须执行 main CI，main CI 全绿后才允许重建 Annotated Tag `v3.0.0`。
> - 远端旧 `v3.0.0` Annotated Tag 已按 Owner 授权在本地完整备份后清理（`OLD_TAG_DELETED=true`），正式 Tag 尚未重建。
> - 整体发布流程继续保持 `IN_PROGRESS`，严禁提前标记 RELEASED 或将 PR #10 标记为 MERGED，严禁把 main CI 标记为 PASS。

### Added
- **基线与交接作用域/字段唯一性校验与防绕过门禁强化 (STD-020 / STD-034 / STD-035 / Std-018)**:
  - 彻底消除 `generate_engineering_baseline.py` 与 `generate_handoff.py` 的首匹配绕过隐患：实现作用域标题唯一性提取器 (`extract_scope_content`)，规范作用域标题出现 0 次报错 `SCOPE_SECTION_MISSING`，>1 次报错 `DUPLICATE_SCOPE_SECTION`。
  - 实现基于行匹配集合的字段唯一性校验器 (`extract_line_field_matches` / `verify_scoped_field`)：规范字段出现 0 次报错 `MISSING_FIELD`，>1 次（无论是相同值还是冲突值）报错 `DUPLICATE_FIELD`，恰好 1 次时执行值校验。
  - 同行多次出现同一字段时逐个扫描捕获值，并仅对字段别名的重叠捕获去重；所有独立期望字段必须有显式校验规则，未配置时 fail-closed。
  - 整理 `docs/当前权威基线.md` 与 `docs/CROSS-SESSION-HANDOFF.md` 结构，确保机器校验标记 `(PR9_HISTORICAL_RELEASE_EVIDENCE)` 与 `(STD018_CURRENT_SNAPSHOT)` 全文各仅出现一次。
  - 新增双生成器 12 类负向测试用例 `test_b17`，严格覆盖重复作用域、重复字段、冲突字段、后置追加字段、字段缺失及文件篡改等拦截场景。
- **权威基线与交接事实对齐及核心 Commit 边界明确 (STD-020 / STD-034 / STD-035 / Std-018)**:
  - 记录 Std-018 源快照验证点：`STD018_SOURCE_COMMIT=94faab425899f7b3ade85112c8405679df46dfe3`，Push Run `42953706511` (Windows/Ubuntu PASS)，PR Run `42953714846` (Windows/Ubuntu PASS)，TEST_COUNT=220。
  - 标记任务最终完成：`Std018=COMPLETED`，记录最终文档输出 `STD018_FINAL_OUTPUT_COMMIT=f4cee41306cff68be2743036d64bb37d5b8c1b25`，Push Run `42969139490` (Windows/Ubuntu PASS)，PR Run `42969143389` (Windows/Ubuntu PASS)，全量测试 `TEST_COUNT=220` (PASS 220, FAILED 0, SKIPPED 0)，`PR9=MERGED`，`PR10=OPEN/DRAFT`。
  - 保持整体发布状态：`RELEASE_STATUS=CANDIDATE`，`MAIN_MERGED=true`，`RELEASE_TAG_NOT_CREATED=true`，`REISSUE_IN_PROGRESS=true`，未合入 main 并经 main CI 成功前严禁标记 RELEASED。
  - 纠正 `handoff/Std-016-V3-0-0-REISSUE-MERGED-PR-RUN-FALLBACK-v3.0.0-handoff.md` 历史交接快照 Commit 归属，准确记录 `OUTPUT_COMMIT=fd9dd6e0de9e5e1b00c5bfa1d0e213401fa90eb7` 与 220 项测试事实，消除将 PR9 候选 Commit `3361148` 误作为 Std-016 输出的矛盾。
  - 归档 Std-017 验收证据历史快照 `handoff/Std-017-V3-0-0-REISSUE-ACCEPTANCE-EVIDENCE-CLOSEOUT-v3.0.0-handoff.md`。
  - 修正 Std-018 跨会话交接快照 `handoff/Std-018-V3-0-0-REISSUE-CURRENT-BASELINE-HANDOFF-ALIGNMENT-v3.0.0-handoff.md`，准确记录 `OUTPUT_COMMIT=94faab425899f7b3ade85112c8405679df46dfe3`、`FINAL_OUTPUT_COMMIT=f4cee41306cff68be2743036d64bb37d5b8c1b25`、Push Run `42953706511` / `42969139490`、PR Run `42953714846` / `42969143389` 与 220 项测试事实，清除 PLACEHOLDER。
  - 更新权威基线 `docs/当前权威基线.md`，严格区分核心 Commit 事实边界（PR9 候选 `3361148`、Std-016 输出 `fd9dd6e`、Std-017 输出 `d00821e`、Std-018 输入 `d00821e`、Std-018 源快照 `94faab4`、Std-018 最终输出 `f4cee41`、当前 main HEAD `3cd42b6`、当前功能分支 HEAD `f4cee41`），并记录 `MAIN_CI_STATUS=WAITING_FOR_PR10_MERGE`。
  - 严格保护 `docs/release-evidence/v3.0.0-reissue.json` 中的 PR9 历史发布凭证，刷新活跃交接入口 `docs/CROSS-SESSION-HANDOFF.md` 为 Std-018 最新状态。
- **验收证据收口与纯净测试日志归档 (STD-016 / STD-020 / STD-034 / Std-017)**:
  - 纠正过程测试日志与独立诊断分离，提供 clean git status 与 220 项全量真实测试日志 `test_results.txt`。
  - 提交快照 `d00821e251bfe3c1495163b6af8af6c01210d5f4`，触发并通过 GitHub Actions 双平台真实 CI：Push Run `42942640853` (Windows/Ubuntu PASS, 220 tests PASS)，PR Run `42942649996` (Windows/Ubuntu PASS, 220 tests PASS)。
  - 生成 Std-017 验收交付包 `Acceptance-Std-017-V3-0-0-REISSUE-ACCEPTANCE-EVIDENCE-CLOSEOUT-v3.0.0.zip` (SHA256: `97d90be32a5dad6a5fa415eaea8c941248c2cecdae45491263f433cc6d40a0bd`) 并标记 `STATUS=COMPLETED`。
- **合并后历史 PR Run 关联信息丢失修复与 PR API Fallback 真实性核验 (STD-016 / STD-034 / STD-035 / Std-016)**:
  - 修复 `tools/release_evidence.py` 中的 `verify_single_github_run()`：当 PR 合并后 GitHub Actions 历史 Run 的 `pull_requests` 返回空列表时，使用独立发布证据中的 `pr_number`，通过 GitHub REST API 查询 `GET /repos/{owner}/{repo}/pulls/{pr_number}` 触发严格身份回退核验 (P1-A)。
  - 严格校验 6 大契约项：PR number 与 `expected_pr_number` 一致、PR `base.ref=main`、PR `head.ref` 与历史 Run `head_branch` 一致、PR `head.sha` 与历史 Run `head_sha` 一致、当 `pr_status=MERGED` 时 `merged=true` 且 `merged_at` 非空；网络异常或不可达时记录 `NOT_VERIFIABLE`，身份不一致判定 `FAIL`，严禁伪造 PASS (P1-B)。
  - 在 `.github/workflows/standards-ci.yml` 的 `validate-standards` Job 中补充最小必要只读权限 `pull-requests: read`，保留 `actions: read` 与 `contents: read`，保持零密钥安全与最小权限原则 (P1-C)。
  - 刷新独立发布证据、权威基线与跨会话交接中的历史 CI 事实至已验证 Commit `336114861b2c720106a6076956eef08c9cd6ded7`（Push Run 42843755347，PR Run 42843964061，全量 219 项测试双平台全绿），记录 PR #9 已合并事实与 Merge Commit `3cd42b69` 并保留 Std-015 历史快照 (P1-D)。
  - 新增单元与集成测试 `test_b15`，覆盖 9 大正负向场景，并在 `GITHUB_REF_NAME=main` 模拟环境中真实直连核验已合并 PR #9 历史 Run 通过 (P1-E)。
- **主干 CI 分支误判修复与发布证据分支严格绑定 (STD-015 / STD-034 / STD-035 / Std-015)**:
  - 在 `schemas/release-evidence.schema.json` 中新增必填字段 `push_head_branch`（类型 `string`，`minLength=1`），严格绑定历史 Push Run 真实所属分支，从契约层面防止环境分支覆盖 (P1-A)。
  - 修复 `tools/release_evidence.py` 中的 `verify_github_ci_runs()`：Push Run 的 `expected_head_branch` 必须且直接取自 `evidence["push_head_branch"]`，彻底消除 `effective_target_branch` 从 `GITHUB_REF_NAME` 错误推断导致 main Push CI 误判功能分支的历史缺陷；禁止缺少字段时回退默认分支；禁止模拟绕过生产验证 (P1-B)。
  - 补充关键回归测试用例 `test_b14`，在 `GITHUB_REF_NAME=main` 模拟环境中验证历史功能分支 Push Run（`head_branch=feat/standards-baseline-sync-governance`）验证通过，并覆盖 11 类分支缺失、分支不一致、PR 错误、base 非 main、workflow path 错误、repo 不匹配、未完成、Job 失败及 API 不可达等负向拦截与离线降级场景 (P1-C)。
  - 刷新独立发布证据、权威基线与跨会话交接中的历史 CI 事实至已验证 Commit `18a71b920c0dc162ae4f4c1ce35aad901bdba9d2`（Push Run 42835602231，PR Run 42835611644，全量 218 项测试双平台全绿），保留 Std-014 历史快照并生成 Std-015 新快照 (P1-D)。
- **GitHub Actions 实时 CI 真实性门禁接入与身份绑定强化 (STD-014 / STD-034 / STD-035 / Std-014)**:
  - 将实时 GitHub CI 真实性验证正式接入 `.github/workflows/standards-ci.yml` 核心门禁（`python tools/release_evidence.py --project-root . --check-ci`），执行于 Schema 校验之后、Baseline/Handoff verify-only 之前 (P1-A)。
  - 在 CI 中配置最小只读权限 (`actions: read`、`contents: read`) 并通过 `GITHUB_TOKEN` 鉴权，严禁泄露 Token，在网络不可达时返回 `NOT_VERIFIABLE` 并阻断发布门禁。
  - 完善 `tools/release_evidence.py` 中的 `verify_single_github_run()`，实现 9 大核心项严格核验：Repository full_name、Run ID、Event 类型、Workflow path (`.github/workflows/standards-ci.yml`)、被测 Commit head_sha、status=completed、conclusion=success、Ubuntu Job completed/success、Windows Job completed/success；Push Run 额外核验目标功能分支 `head_branch`；PR Run 额外核验 PR number=9、`base.ref=main` 与 `event=pull_request` (P1-B)。
  - 消除 `tools/validate-schemas.py` 内部重复执行完整 unittest 的性能瓶颈，严格遵循职责分离原则，仅验证 JSON Schema 结构与样本有效性，由 `standards-ci.yml` 保留一次完整 unittest discover (P2)。
  - 新增 12 项真实性负向测试用例（覆盖 Repository 不匹配、Run ID 不匹配、Workflow path 不匹配、Event 不匹配、head_sha 不匹配、PR number 不匹配、base branch 不匹配、Run 未完成、Run conclusion 失败、Ubuntu Job 缺失/失败、Windows Job 缺失/失败、API 不可达），严格证明所有身份不匹配与故障场景均不能返回 PASS。
  - 对齐发布证据、权威基线与跨会话交接中的历史 CI 事实至已通过 Commit `70f7554`（Push Run 42800374434，PR Run 42800383714，全量 217 项测试双平台全绿）。
- **单一发布证据源与 verify-only 真实性强化 (STD-020 / STD-034 / STD-035 / Std-013)**:
  - 确立 `docs/release-evidence/v3.0.0-reissue.json` 为单一发布证据源，定义 `schemas/release-evidence.schema.json` 契约，收敛 20 项关键发布、Tag 与 CI 事实。
  - 实现通用发布证据加载与 GitHub CI 真实性校验器（`tools/release_evidence.py`），支持 gh CLI 与 API 只读鉴权双通道，严禁泄露 Token，在网络离线或无权限时客观标记 `NOT_VERIFIABLE`，严禁伪造 PASS。
  - 彻底重构 `tools/generate_engineering_baseline.py` 与 `tools/generate_handoff.py` 的 `--verify-only` 门禁机制：所有期望语义事实直接且仅来自独立发布证据文件，彻底废除从待验证 Markdown 文件内容正则回填的“自证循环”（彻底解决 P1-B 漏洞）。
  - 对齐权威基线与交接文档中的最新 CI 事实至已验证 Commit `4538b8ba`（Push Run 42783497089，PR Run 42783504258，全量 216 项测试在 Windows 与 Ubuntu 双平台全绿），解决交接与基线事实过期（解决 P1-A）。
  - 修复 FINAL_RETURN Commit SHA 逻辑，区分输入快照 Commit（`4538b8ba`）与输出提交 Commit，严禁制造自引用或虚构提交（解决 P1-C）。
  - 增加 12 类真实 CLI 负向门禁测试，并严格证明：仅修改待验证 Markdown 中的 Commit 或 Run ID，即使重新计算 Frontmatter `content_sha256`，`verify-only` 仍然失败。
- **交接与基线生成器事实对齐与语义门禁强化 (STD-020 / STD-035 / Std-012)**:
  - 修复 `tools/generate_engineering_baseline.py` 与 `tools/generate_handoff.py`，清晰分离并准确呈现四类关键 Commit：`source_commit`（基线源）、`code_candidate_commit`（代码候选）、`snapshot_commit`（文档快照）与 `last_verified_ci_commit`（CI 验证）。
  - 支持 CLI 传入真实 CI 状态、Run ID（包含 Push Run 42772211734 与 PR Run 42772217074）、CI Commit 与摘要，不再将 NOT_VERIFIABLE 固定作为默认事实。
  - 大幅增强 `--verify-only` 门禁真实性：除 Frontmatter 与摘要哈希外，增加 11 项关键事实语义一致性核查（TASK_ID、candidate_commit、snapshot_commit、last_verified_ci_commit、CI Run ID、CI Commit、CI verification_status、TEST_COUNT、PR 状态、release_flow_status、OLD_TAG_DELETED）。
  - 补充 6 类负向拦截测试覆盖（旧 CI Run ID 失败、错误 CI Commit 失败、PASS 改 NOT_VERIFIABLE 失败、216 tests 改 215 tests 失败、旧候选 Commit 失败、旧 Tag 未删除失败）。
  - 规范时间戳字段继承与防抖，避免无意义的时间抖动导致无限提交循环。
- **个人工程单人 Owner 治理机制与 PR 合并审批契约 (STD-034 §16.5 / D2=APPROVED / Std-009)**:
  - 确立个人工程单一 Owner 治理模式（实际仓库所有者 `xiefeifeihu`），无需第二名 Reviewer、第二 GitHub 账号或团队审批。
  - 明确职责边界与权限分离：ChatGPT 负责独立技术审查并提出建议结论（`READY_FOR_OWNER_MERGE`、`CHANGES_REQUESTED` 或 `BLOCK`），不得代替 Owner 批准发布；编程智能体（VibeCoding）负责工程代码与门禁执行，严禁自行批准；Owner 作为最终审批者。
  - 确立 PR 合并审批模式 (`GITHUB_PR_MERGE_EVENT`)：候选阶段审批状态保持为 `OWNER_APPROVAL_REQUIRED`；PR 作者与仓库 Owner 为同一人时允许 Owner 直接合并，以 GitHub 界面合并候选 PR 入 `main` 作为最终批准动作。
  - 建立 PR 合并溯源机器校验（`tools/validate_approval_contract.py`）：调用 GitHub PR API 校验 `merged=true`、`merged_by.login == Owner`、`base.ref == "main"`、`head.sha == candidate_commit` 且 `merged_at` 存在有效时间戳。未真实合入前严禁标记 `OWNER_APPROVED`。
  - 更新 `schemas/documentation-approval.schema.json` 与 `schemas/documentation-metadata.schema.json` 支持 PR 合并审批模型。
- **事务日志路径安全与符号链接阻断 (STD-034 §4 / Std-010)**:
  - `tools/standards_sync/core.py` 中的 Journal 目标路径校验严格拒绝所有符号链接（包括工程内部指向 `README.md` 等普通文件的符号链接），防止利用事务回滚机制覆盖篡改工程核心文件。
- **12 类正式文档分类与 ENGINEERING_BASELINE 规范 (STD-035 v3.0.0 / D1=APPROVED)**:
  - 正式 document_type 调整为 12 类：PROJECT_BLUEPRINT、PRODUCT_BASELINE、SYSTEM_ARCHITECTURE、TECHNICAL_DESIGN、API_CONTRACT、PROTOTYPE_UX、TEST_ACCEPTANCE、RELEASE_OPERATIONS、DECISION_RECORD、CROSS_SESSION_HANDOFF、DOCUMENT_INDEX、ENGINEERING_BASELINE。
  - 新增 docs/当前权威基线.md (ENGINEERING_BASELINE) 确定性综合视图，汇聚 11 类正式文档与 10 类实时工程事实，强制记录 18 项核心内容与 6 项动态溯源字段 (repository, source_path, source_commit, evidence_ref, observed_at, verification_status)。
  - 新增 schemas/engineering-baseline.schema.json、templates/documentation/ENGINEERING-BASELINE.template.md 与 tools/generate_engineering_baseline.py。
- **文档审核与晋升双层审批契约 (STD-035 §4 / STD-034 §16 / D2=APPROVED)**:
  - 解耦文档生命周期状态 (CANDIDATE, IN_REVIEW, ACTIVE, SUPERSEDED, ARCHIVED) 与审批状态 (NOT_SUBMITTED, IN_REVIEW, AI_APPROVED, OWNER_APPROVAL_REQUIRED, OWNER_APPROVED, REJECTED, BLOCKED)。
  - 新增 schemas/documentation-approval.schema.json 与 tools/validate_approval_contract.py，严格分离 ChatGPT 独立审核记录与 Owner 批准记录，严禁编程智能体伪造 AI_APPROVED、OWNER_APPROVED、HUMAN_ACCEPTED。
- **跨会话交接自动化 (STD-020 v2.0.0)**:
  - 确立唯一当前入口 docs/CROSS-SESSION-HANDOFF.md、任务级不可变快照 handoff/<TASK-ID>-<VERSION>-handoff.md 与临时交接 .artifacts/handoff/temporary/。
  - 新增 schemas/cross-session-handoff.schema.json 与 tools/generate_handoff.py，自动采集 11 项实时工程事实并强制新会话启动重验。
- **Standards 官方同步工具与四元组锁定契约 (STD-034 §4 / D3-D5=APPROVED)**:
  - 新增 schemas/standards-lock.schema.json 与 templates/standards.lock.template.json，强制锁定 version、tag、tag_object_sha、peeled_commit 并保留 previous_locks 历史栈。
  - 新增 schemas/consumer-validation-evidence.schema.json，绑定消费工程 Commit、目标 Standards 四元组与 GitHub Actions 六类 CI Job；`validate-upgrade` 通过 GitHub Actions API 核验真实 Run/Job。
  - 新增 tools/standards_sync/ 官方共享工具 (discover, verify-lock, compare, impact, prepare-upgrade, validate-upgrade, promote, rollback)。
- **跨工程迁移指南 (docs/migration/MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md)**:
  - 提供以 AI-Engineering-Hub 为首个消费端试点的接入与验证方案；其他工程不在本次迁移范围内。

### Changed (BREAKING)
- **移除 HISTORICAL_ARCHIVE 正式文档类型枚举 (D1=APPROVED)**:
  - HISTORICAL_ARCHIVE 不再作为 schemas/documentation-metadata.schema.json 的 document_type 枚举值；历史归档回归文档生命周期 (status=ARCHIVED 或 SUPERSEDED, primary_entrypoint=false) 及目录存储分类，保留文档原始语义类型。
- **统一 Engineering Manifest Schema (STD-001)**:
  - 确立 schemas/engineering-manifest.schema.json 为唯一权威 Schema，同步 governance/engineering-manifest-schema.json 为精确兼容镜像。
- **升级 tools/validate-documentation-collection.py 至 v3.0.0**:
  - 移除硬编码本地绝对路径，完整实现 17 项跨平台文档集合校验（含 Markdown 相对链接与标题锚点校验、source_commit 真实性与跨文档一致性校验）。

## [2.11.0] - 2026-10-30

### Added
- **AI 智能体自主测试设计契约与闭环流程 (STD-014 / STD-034)**:
  - 编码前自动读取 8 项核心事实源（蓝图、产品基线、架构、接口契约、测试基线、Diff、缺陷历史、上次验收报告）。
  - 自主执行 13 阶段测试闭环，从需求影响分析到自动化测试、缺陷修复、回归与测试基线同步演进。
  - 建立强断言严格度准则：正向业务强制验证真实业务成功终态，严禁将 BLOCK/CONFIGURED/MOCK_ONLY/HTTP 200 视为 PASS；负向用例强制验证预期阻断与降级。
- **持续测试用例基线规范 (STD-035 / docs/TEST-ACCEPTANCE.md)**:
  - 统一测试基线模板 (	emplates/documentation/TEST-ACCEPTANCE.template.md)，覆盖分层策略、产品需求映射、稳定 Case ID、断言严格度与历史缺陷复现回归矩阵。
- **十项反造假机器门禁与覆盖验证契约**:
  - 提供 schemas/test-coverage-verification.schema.json 覆盖报告机器契约。
  - 提供校验器 	ools/validate_test_coverage.py，并在 	ests/test_ai_driven_test_governance.py 中完整覆盖 10 项反向欺诈场景校验。
  - 模板与迁移指南：	emplates/test-coverage-verification.template.json 与 docs/migration/MIGRATION-GUIDE-AI-DRIVEN-TEST-GOVERNANCE-v2.11.0.md。

### Changed
- **STD-014**: 修正历史 9 个 Schema 旧文案为动态扫描所有在册 Schema；补充自主测试设计方法论与持续用例门禁。
- **STD-015**: 消除 L2 CORE 混用冲突，锁定 Playwright 归属于 L3 DEEP 及两阶段验收；将 PR 触发变更为 UI/端到端变更或候选验证；增加前端操作五步闭环强断言。
- **STD-031**: 运行时验收 PRODUCTION_READY 终态对齐 P0 关键用例与覆盖契约，严禁 Mock 或开发端口冒充生产。
- **STD-032**: 完善 10 项全绿门禁中 Gate 3 (AUTOMATED_TESTS_PASS) 与 Gate 4 (PLAYWRIGHT_PASS) 的持续覆盖要求；SMOKE_TEST 阶段对齐 POST_DEPLOY P0 用例执行。
- **STD-033**: 平台统一验证大盘纳管持续测试用例覆盖与业务强断言验证。
- **STD-034**: 更新 Rule G、H、K、O 治理铁律，纳入 AI 自主测试职责与 10 项反向测试门禁。
- **STD-035**: 完善 TEST_ACCEPTANCE 文档生命周期演进机制。

## [2.10.0] - 2026-10-29

### Added
- **无强制 PR 与两阶段真实发布工程架构 (STD-014 / STD-032 / STD-034)**:
  - 在 PERSONAL_LOCAL 声明下遵循 STD-034 Rule C，免除强制 PR 要求，以目标 main Commit 的 GitHub Actions 真实远端 CI 为准。
  - 确立 Stage 1 (PRE_RELEASE_QUALIFICATION) 与 Stage 2 (POST_DEPLOY_REAL_ACCEPTANCE) 严格发布前后因果律。
  - 提供 schemas/two-stage-release-acceptance.schema.json 与 	ools/validate_two_stage_release.py。
  - AUTO_AFTER_GREEN 第 1 门禁更名为 MAIN_COMMIT_VERIFIED。

## [2.9.0] - 2026-10-27

### Added
- **STD-035: Documentation Lifecycle & Project Baseline Contract (全生命周期工程文档与产品基线契约规范)**:
  - 规范 11 种正式工程文档类型（蓝图、产品基线、架构、技术方案、API契约、原型UX、测试验收、发布运维、决策记录、跨会话交接、历史归档）。
  - 确立最新全量与历史演进双重保证：每个项目始终保持一份最新全量文档集合，同时保留不可篡改的历史演进。
  - 单一权威入口规则 (`PRIMARY_ENTRYPOINT=true`)，杜绝多份互相矛盾的最新版本。
  - 提供 `schemas/documentation-metadata.schema.json` 结构化元数据契约与校验器。
  - 提供 11 种正式文档模板 (`templates/documentation/`) 与受管工程迁移指南 (`docs/migration/MIGRATION-GUIDE-STD-035.md`)。
- **Coding Gateway 统一自动上下文与治理契约 (`STD-021` / `schemas/coding-gateway.schema.json`)**:
  - 新增统一上下文字段：`consumer_id`, `target_project`, `task_family`, `task_type`, `task_id`, `run_id`, `session_id`, `turn_id`, `attempt_id`, `decision_id`, `route_id`, `trace_id`, `context_origin`。
  - 严格分离 `consumer_id` (调用客户端如 Claude Code) 与 `target_project` (被操作工程如 Sidecar)。
  - 自动分配 TaskId / RunId 与会话保持规则（`EXPLICIT`, `CLIENT_SESSION`, `GATEWAY_GENERATED`, `CLIENT_ADAPTER`），禁止从自然语言 Prompt 文本推测或虚构 TaskId。

### Changed
- **STD-020 Cross-Session Handoff**: 增加与 STD-035 协同契约，规定新启动会话必须按序优先读取主索引、蓝图、产品基线、架构与接口契约。
- **Tools & Tests**: `validate-schemas.py` 扩充 STD-035 元数据与 Coding Gateway 自动上下文样本校验，新增 `tests/test_std035_and_coding_context.py` 单元测试套件。

## [2.6.0] - 2026-10-25

### Added
- STD-032 explicit, mutually exclusive GitHub Environment and protected local-key approval profiles; no automatic fallback.
- Strict signed-envelope and approval-policy schemas; identity separation, human interaction, revocation, expiry and durable one-time consumption requirements.
- Schema contract tests and CI execution. Structural validation never establishes a human approval.

### Changed
- Resolve unconditional Required Reviewers wording while retaining the strict GitHub profile.
- Candidate workflows cannot claim approval merely because an environment job ran.
- Correct README release metadata; published v2.5.0/v2.5.1 tags remain immutable.

## [2.5.0] - 2026-10-23

### Added
- **STD-034: Coding Agent Execution Governance & Machine Gate Contract (跨工程编程智能体执行治理与强制机器门禁规范)**:
  - 确立 15 项跨工程智能体执行治理标准：`AGENTS.md` 项目级规则契约（Rules A–O）、`CLAUDE.md` 客户端适配规则、Thin Reference 薄引用模式、Standards 版本与 Commit 锁定（不可读取时阻断，禁止静默降级）、Agent 任务启动 Preflight（`scripts/agent/preflight.py`）、结构化任务 Context 与 Git 分支关联、修改文件授权范围、测试与证据真实性、唯一 Acceptance 打包器（`scripts/package_acceptance.py`）、CI/CD 12 项强制门禁、五态 Commit 身份、`STD-023` 编码交付 8 阶段状态、未通过门禁禁止 `OVERALL_STATUS=PASS`、跨 Windows/WSL Git 安全规则、非法制品路径与 `docs/` 污染自动检测。

### Changed
- **STD-016 v1.1.0 / STD-019 v1.2.0 / STD-032 / STD-033**:
  - 消除规范间冲突：明确正式架构图与正式项目设计图片（`.png`, `.jpg`, `.jpeg`, `.svg`）允许在 `docs/01-架构设计/` 与 `docs/**/assets/` 中由 Git 追踪，而测试截图、录像、日志仍必须严格归档至 `.artifacts/`。
  - 锁定正式 Acceptance ZIP 的唯一合法输出路径为 `.artifacts/packages/`，严禁在 `.artifacts/acceptance/` 或仓库根目录存放正式 ZIP，严禁项目复制 Standards 全文。

---
## [2.4.0] - 2026-10-13

### Added
- **STD-033: Platform Verification Governance (平台统一验证治理规范)**:
  - 确立三大标准递进协同体系：STD-031 原子探针基底、STD-032 交付流水线门禁、STD-033 全域验证治理中枢。
  - 建立 **统一 14 阶段工程生命周期契约 (Unified Engineering Lifecycle Contract)**：PLAN -> DESIGN -> CODE -> DEV_TEST -> SECURITY_SCAN -> BUILD -> PACKAGE -> PUBLISH -> DEPLOY -> RUNTIME_VERIFY -> SMOKE_TEST -> PRODUCTION_READY -> OPERATE -> FEEDBACK。
  - 确立 **五维运行时验收矩阵 (5-Dimension Runtime Acceptance Matrix)**：Identity Check、Runtime Check、Dependency Check、Network Topology Check、Business Smoke Check。
  - 确立 schemas/platform-verification.schema.json 机器可读证据模式，支持 20/20 规范模式全量校验。
  - 统一四大项目 scripts/release/ 模板规范（补齐 
ollback_check.py，统一输出 
untime_acceptance.json、
elease_report.json、rtifact_manifest.json）。
  - 制定 Git 发布治理六大铁律与 .artifacts/ 四目录（cceptance/, packages/, screenshots/, 
eports/）治理规范。

---

## [2.3.0] - 2026-10-13

### Added
- **STD-032: AI Platform Release Engineering Contract (AI 平台发布工程契约规范)**:
  - 定义 12 阶段标准发布生命周期：`PLAN -> CODE -> DEV_TEST -> SECURITY_SCAN -> BUILD -> PACKAGE -> PUBLISH -> DEPLOY -> RUNTIME_VERIFY -> SMOKE_TEST -> PRODUCTION_RELEASE -> TAG`。
  - 定义六大强制自动化门禁：`SOURCE` (`git clean` + `secret scan`)、`DEV_TEST` (`unit`/`contract`/`integration`/`e2e`)、`BUILD` (`build_metadata`)、`PACKAGE` (`artifact sha256`)、`DEPLOY` (`runtime probe`)、`SMOKE` (`minimal business verification`)。
  - 统一四项目 `scripts/release/` 目录模板：`release_pipeline.py`、`build_metadata.py`、`runtime_acceptance.py`、`artifact_manifest.py`。
  - 制定 Git 发布四步铁律 (`commit -> push remote -> create tag -> push tag`) 与五态 Commit 一致性校验 (`LOCAL_HEAD == REMOTE_HEAD == TAG_COMMIT == BUILD_COMMIT == LIVE_COMMIT`)。
  - 制定 `.artifacts/{acceptance,packages,screenshots,evidence}` 目录规范、`docs/` 6 分类治理与技术中立回滚契约。
- **schemas/release-engineering.schema.json**: 发布工程契约 JSON Schema 校验规范及合规样例。

---

## [2.2.0] - 2026-10-12

### Added
- **STD-031: Runtime Acceptance Contract (运行时验收契约规范)**:
  - 确立统一多阶段验收生命周期：SOURCE -> BUILD -> PACKAGE -> DEPLOY -> RUNTIME_VERIFY -> SMOKE_TEST -> PRODUCTION_READY。
  - 强制技术中立性要求（Technology-Agnostic）：严禁强绑定 Docker 守护进程或容器特异性探针，全面支持原生 Windows、WSL2、Linux 裸金属与容器化运行环境。
  - 覆盖四大核心工程系统：AI-Hub、AI-KB、vtip-ai-sidecar、vtip-platform-catalog。
  - 制定统一运行时验收返回报文规范 (
untime_acceptance, service, ersion, commit, uild_commit, checks_total, checks_pass, checks_fail, ailed_components)。
- **schemas/runtime-acceptance.schema.json**: 运行时验收契约 JSON Schema 校验规范及合规样例。

---

## [2.1.1] - 2026-10-10

### Added
- **STD-009 v2.1.1**: 通用任务契约（Generic Task Contract）落地，正式引入 consumer_id, 	ask_family, 	ask_type, capability_profile, output_contract 字段。
- **STD-009 v2.1.1**: 同义字段冲突硬检验契约（HTTP 422 SYNONYMOUS_FIELD_CONFLICT）与未注册消费端鉴权拒绝（HTTP 403）。
- **STD-010 v1.3.1**: 多阶段反馈契约支持通用任务字段，明确 BULLET_LIMIT_EXCEEDED 软告警隔离与 HTTP200_EMPTY_STRUCTURE 真实归因。
- **STD-030 v2.1.1**: 明确 Sidecar 标准语义 (consumer_id=sidecar, 	ask_family=document_transformation, 	ask_type=report_polishing, capability_profile=faithful_summarization, output_contract=markdown_structured_bullets)，锁定 capability_profile 为命名字符串。

### Changed
- schemas/model-routing-request.schema.json: 支持 nyOf 兼容旧 	ask 与规范 	ask_type，新增通用契约可选字段。
- schemas/model-feedback.schema.json: 新增通用契约可选字段，继续保持 dditionalProperties: false。
- schemas/model-routing-response.schema.json: 增补候选执行方案增量元数据定义。
- schemas/unified-ai-capability-platform.schema.json: 升级 contract_version 至 2.1.1，补齐消费端契约字段。

---

## [2.1.0] - 2026-10-09

### Added
- **STD-030: Unified AI Capability Platform Contract**: 四库分离架构、模型部署智能、推理引擎能力目录、只读硬件画像、多模态调度与多消费端隔离治理。
- schemas/unified-ai-capability-platform.schema.json: 统一平台契约元数据 Schema。

---

## [2.0.0] - 2026-10-08

### Added
- **STD-028 Model Supply Autopilot and Champion Management Contract**: Canonical standard for external model supply discovery, free/trial pricing classification, zero-secret availability probing, CPA transactional onboarding, quota health backoff, cost-aware multi-objective routing with Free Capacity Lane, and 5-stage autonomous Champion management.
- **model-supply-autopilot.schema.json**: JSON Schema validating Model Supply Sources, Discovered Items, Probe Results, Quota Events, CPA Onboarding Events, and Champion Rollout Events.
- **STD-025 Extension**: Added `CPA_REGISTER_MODEL_ROUTE`, `CPA_DISABLE_MODEL_ROUTE`, and `CPA_REFRESH_MODEL_CATALOG` canonical action types, alongside `POLICY_PREAUTHORIZED` execution mode for approved low-risk non-destructive route registrations.

---

## [1.9.0] - 2026-10-08

### Added
- **STD-027: Safe Autonomous Promotion and Canary Routing Contract** (`standards/08-model-governance/STD-027-safe-autonomous-promotion-contract.md`)
  - Canonical contract for Model Ops Autopilot R4 bounded production routing autonomy:
    - Scoped `SAFE_AUTONOMOUS` mode while retaining global `SHADOW_ONLY` default.
    - Orthogonal rollout state machine (`NOT_ELIGIBLE`, `ELIGIBLE`, `CANARY_PENDING`, `CANARY_ACTIVE`, `CANARY_HOLD`, `ROLLBACK_PENDING`, `ROLLED_BACK`, `PROMOTION_READY`, `FULL_PROMOTION_BLOCKED`).
    - 19 mandatory hard evidence gates (sample_count >= 10, confidence >= 0.90, agent compatible, health, circuit breaker, etc.).
    - Strict bounded canary stages (0% -> 5% -> 10% maximum).
    - Deterministic non-sensitive hash bucketing and frozen plan preservation.
    - Dual-condition observation windows (dwell time + eligible samples).
    - Autonomous rollback with relative Champion degradation budgets.
    - Anti-flapping hysteresis cooldown (>= 60 minutes).
    - Champion preservation snapshot and versioned Compare-and-Swap (CAS) routing policy update.
    - Operator override precedence and restart-persistent global Autonomy Kill Switch.
    - Explainable governance audit and zero metrics double-counting invariants.
- **Canonical Schema**: `schemas/safe-autonomous-promotion.schema.json` supporting all 9 canonical R4 autonomy record types.

## [1.8.0] - 2026-10-07

### Added
- **STD-026: Model Scout and Challenger Contract (AI-Hub-014-R3-MODEL-SCOUT-AND-CHALLENGER-AUTOMATION)**:
  - Established canonical Model Scout Source Registry supporting 4 classes (`ACTIVE_RUNTIME_CATALOG`, `OWNER_CANDIDATE_CATALOG`, `PROVIDER_DECLARED_CATALOG`, `OPTIONAL_PUBLIC_METADATA_CATALOG`).
  - Defined 3 candidate physical availability classes (`AVAILABLE_NOW`, `OWNER_ACTION_REQUIRED`, `METADATA_ONLY`).
  - Enforced zero-trust model provenance (no provider inference from model names).
  - Defined Scoped Scout Campaign with frozen Champion semantics (`PRODUCTION_ROUTE_WINNER`, `HISTORICAL_LEADER`, `PLATFORM_PINNED_BASELINE`) and hard eligibility gates (`AGENT_COMPATIBLE` required for coding agent challenges).
  - Codified separation of production routing preferences from challenge fairness (`RAW_CHALLENGE_CAPABILITY` vs `PLATFORM_PRODUCTION_POLICY`).
  - Defined Frozen Fairness Specification with `fairness_spec_hash`.
  - Defined Challenge Suite Registry (`TECHNICAL_MICROBENCH`, `AGENT_MICROBENCH`, `CONSUMER_BUSINESS_EVALUATION`) with isolated coding sandboxes and zero prompt/code leakage.
  - Defined Dedicated Challenge Result Memory, exponential time decay (`ALL_TIME` vs `EFFECTIVE` views), memory epochs, and conservative exploration budget governance.
  - Defined multi-dimensional Pareto comparison conclusions and explainable promotion recommendations (`PROMOTION_RECOMMENDED != PRODUCTION_PROMOTED`).
  - Integrated STD-025 Owner Action requests in `APPROVAL_REQUIRED` and Ollama resource preflight; strictly disabled automatic model removal (`OLLAMA_REMOVE_MODEL`).
  - Codified four-layer zero double-counting invariants (`SCOUT_L1_DOUBLE_COUNT=false`, `SCOUT_CODING_OUTCOME_DOUBLE_COUNT=false`, `SCOUT_AIKB_QUALITY_DOUBLE_COUNT=false`, `SCOUT_SIDECAR_BUSINESS_DOUBLE_COUNT=false`).
  - Published machine-readable `schemas/model-scout-challenger.schema.json`.

## [1.7.0] - 2026-10-07

### Added
- **STD-025: Owner Action Execution Contract (AI-Hub-014-R2-OWNER-ACTION-EXECUTOR)**:
  - Formally established the execution plane boundary: Hub = Control Plane (decision, approval, lease, verification, close-loop), AI-KB = Resource Owner (local validation, exclusive lock, canonical lifecycle execution, non-sensitive fact results).
  - Defined canonical end-to-end flow: OBSERVE -> RECOMMEND -> OWNER_ACTION_REQUEST -> APPROVAL -> OWNER_ACK -> EXECUTION_LEASE -> OWNER_EXECUTION -> OWNER_RESULT -> HUB_REDISCOVERY -> HUB_CAPABILITY_PROBE -> VERIFY -> ACTION_COMPLETED | ACTION_FAILED -> LIFECYCLE_REEVALUATION.
  - Defined 14 canonical execution states (`REQUESTED`, `APPROVAL_REQUIRED`, `APPROVED`, `ACKNOWLEDGED`, `LEASED`, `EXECUTING`, `EXECUTION_SUCCEEDED`, `EXECUTION_FAILED`, `VERIFYING`, `VERIFIED`, `COMPLETED`, `REJECTED`, `EXPIRED`, `CANCELLED`).
  - Codified the non-equivalence invariant: `OWNER_EXECUTION_SUCCEEDED != ACTION_COMPLETED` (execution exit code 0 requires independent Hub verification).
  - Codified `ONE_REQUEST_ID_ONE_EFFECT=true`, exclusive execution leases, and resource concurrency guards.
  - Published machine-readable `schemas/owner-action-execution.schema.json`.

## [1.6.1] - 2026-10-06

### Changed
- Hardened STD-024 Model Ops Autopilot parameter allowlists and recursive zero-secret scanning.
- Normalized dual-layer capability states: Aggregate Capability State vs Per-Dimension Capability Verification State.

## [1.6.0] - 2026-10-06

### Added
- **STD-024: Model Ops Autopilot Governance Contract (AI-Hub-014-R1-MODEL-OPS-AUTOPILOT-FOUNDATION)**:
  - Background asynchronous discovery across Local CPA, Cloud CPA, and Ollama.
  - Tiered capability probes (L0-L3) with critical-path routing isolation (P95 <= 50ms).
  - Deterministic lifecycle state machine (DISCOVERED, PROBE_VERIFIED, CHALLENGER, SHADOW, PRODUCTION_ELIGIBLE, TEMP_UNAVAILABLE, QUARANTINED, REJECTED).
  - Shadow-only governance mode and explainable recommendations.

## [1.5.0] - 2026-09-30

### Added
- **STD-023: Coding Agent Outcome Contract & Persistent Coding Task Memory (AI-Hub-013-R1-CODING-OUTCOME-CONTRACT)**:
  - Strictly separated Layer 1 Model Invocation Feedback (`POST /api/model/feedback`) from Layer 2 Coding Agent Outcome (`POST /api/coding/outcome`).
  - Defined canonical two-stage outcome lifecycle (`ATTEMPT_COMPLETED`, `INTEGRATION_DECISION`) and the core invariant: one `coding_attempt_id` equals exactly one Coding Memory sample.
  - Defined Frozen Coding Candidate Plan contract (`POST /api/coding/candidate-plan`, `GET /api/coding/candidate-plan/{decision_id}`) and First Bake-Off fairness mode (`CODING_OUTCOME_RANKING_MODE=SHADOW_ONLY`).
  - Enforced single-primary-model attribution (`SINGLE_PRIMARY_MODEL`) per independent coding attempt, authentic provenance (prohibiting fake strings such as `unknown`/`未验证`/`N/A`/`not_verified`), and zero raw source/patch/diff storage (`additionalProperties: false` in `schemas/coding-agent-outcome.schema.json`).
  - Codified non-penalizing integration semantics (`task_outcome=COMPLETED` with `integration_selected=false` is valid and never penalizes completion capability or L1 health).
  - Guaranteed strict isolation between Coding Outcome failures (`FAILED`/`PARTIAL`/`BLOCKED`), L1 technical health/circuit breakers, and non-coding L2 domain quality memories (`ai-kb`, `vtip-ai-sidecar`).
  - Published durable handoff `handoff/SIDECAR-CODING-BAKEOFF-INTEGRATION-HANDOFF.md` for `SIDECAR-DEV-022`.

## [1.4.0] - 2026-09-30

### Added
- **STD-022: Model Runtime Memory & Decay Governance (AI-Hub-012-R2-LONG-TERM-MODEL-MEMORY)**:
  - Defined separation of **Raw Historical Facts (All-Time Memory)** and **Recent Effective Routing Memory**.
  - Specified `observed_at` canonical exponential time decay ($w = 0.5^{\text{age}/\text{half\_life}}$) with configurable defaults (`technical_half_life_days = 7`, `business_quality_half_life_days = 30`) and out-of-order arrival safety.
  - Defined strict 5-tuple L2 business quality isolation (`consumer`, `task`, `metric_namespace`, `logical_model_id`, `channel`) and namespace-internal aggregation (`namespace_specific_weighted` vs `neutral_mean_normalized`).
  - Defined `effective_sample_weight` and effective governance confidence (`历史样本数`, `当前有效样本权重`, `当前治理置信度`).
  - Defined `model_fingerprint`, `fingerprint_status` (`VERIFIED`/`已确认`, `PARTIAL`/`部分可识别`, `UNKNOWN`/`未知`), and `memory_epoch` with false-epoch prevention and cold-start neutral priors.
  - Defined idempotent historical L2 memory rebuild from persisted L3 `model_invocations` without downstream consumer replay or L1 counter mutation.

## [1.3.0] - 2026-09-29

### Added
- **STD-010: Model Feedback Contract v1.3.0 (AI-Hub-012-R1-FEEDBACK-CONTRACT-FREEZE)**:
  - Codified multi-stage feedback lifecycle: `execution`, `business_evaluation`, and `human_review` stages.
  - Formally established domain judgment ownership: consumers own business evaluation, Hub owns technical health memory and multi-tenant persistence.
  - Added canonical `review_decision` enum (`approved`, `approved_with_note`, `rejected`, `revise`, `discard`, `execution_failed`, `not_reviewed`) and structured `review_reason_code`.
  - Added `evaluation_method` enum (`deterministic`, `llm_judge`, `human`, `combined`, `unknown`).
  - Added `metric_namespace` specification to isolate cross-consumer metric comparability.
  - Decoupled `evaluation_confidence` (consumer single-event confidence) from Hub-computed `sample_confidence_level`.
  - Aligned Hub and STD-009 sample confidence thresholds: 0=NONE, 1-9=LOW, 10-49=MEDIUM, 50+=HIGH.
  - Added `source_unit_id`, `source_unit_hash` (content only), and `execution_spec_hash` (params only).
  - Clarified model identities: `logical_model_id`, `selected_model_id`, `upstream_model_id`, `resource_id`.
  - Fixed multi-stage idempotency collisions with stage-aware deduplication identity.
  - Added `observed_at` (ISO-8601 UTC) for asynchronous evaluation and out-of-order tolerance.
  - Enforced zero raw business content guardrail via `additionalProperties: false` in `schemas/model-feedback.schema.json`.
  - Guaranteed business rejections never mutate technical failure counters or trigger circuit breakers.

## [1.2.0] - 2026-09-28

### Added
- **STD-021: Coding Agent Gateway Contract (AI-Hub-010-CODING-GATEWAY)**:
  - Formally established AI-Hub execution plane capabilities for professional coding agents.
  - Defined 4 canonical virtual models: `hub-code-auto`, `hub-code-fast`, `hub-code-deep`, and `hub-code-local`.
  - Standardized dual-protocol support: Anthropic Messages API (`/v1/messages`) for Claude Code, and OpenAI Chat Completions API (`/v1/chat/completions`) for OpenCode, Cline, Continue, Aider, and generic agents.
  - Codified failover semantics: transparent candidate-plan failover strictly before first streamed token; strictly prohibited cross-model output concatenation after stream start.
  - Established soft session stickiness based on `session_id` and diagnostic header metadata (`X-Hub-Decision-Id`, `X-Hub-Selected-Model`, `X-Hub-Channel`, `X-Hub-Attempts`).
  - Standardized coding-specific feedback metrics (`ttft_ms`, `tool_call_success`, `retry_count`, `fallback_count`, and reserved quality fields in `schemas/model-feedback.schema.json`).
  - Added `schemas/coding-gateway.schema.json` with full automated validation in `tools/validate-schemas.py`.

## [1.1.3] - 2026-09-25

### Added
- **Engineering Manifest Docker Consumer Endpoint & SOT Convergence (AI-HUB-V1-008)**:
  - Extended `schemas/engineering-manifest.schema.json` and `governance/engineering-manifest-schema.json` with `endpoints.docker_consumer`.
  - Added support for `schema_version` `"1.1"`, `"1.1.0"`, and `"1.1.3"` while maintaining 100% backward compatibility with `"1.0"` / `"1.0.0"`.
  - Defined explicit semantics: `docker_internal` for in-network container communication vs `docker_consumer` for bridge container access via host gateway relay.
  - Aligned STD-001 (v1.1.3), STD-003 (v1.1.3), and STD-012 (v1.1.3) with single source of truth resolution.

## [1.1.2] - 2026-09-24

### Added
- **Docker / Host Dual-Profile Runtime Topology (AI-ENGINEERING-PLATFORM-V1-005)**:
  - Formally established `HUB_HOST_ENDPOINT` (`http://127.0.0.1:80`, loopback only) and `HUB_DOCKER_ENDPOINT` (`http://host.docker.internal:18000`, dedicated bridge ingress).
  - Extended `schemas/endpoint.schema.json` with `runtime_profiles` (host, docker) and `canonical_paths` (`health`, `model_select`, `model_feedback`).
  - Allocated Port `18000` in `STD-006` Port Governance for Hub Docker Consumer Ingress.
  - Published official durable handoff `handoff/SIDECAR-FULL-ADOPTION-HANDOFF.md`.

### Changed
- **STD-003 v1.1.2**: Decoupled Canonical Paths from Base URL; defined Runtime Profiles to drive dynamic endpoint resolution.
- **STD-011 v1.1.2**: Explicitly prohibited Docker consumers from assuming `127.0.0.1` represents host; required consumers to prioritize `docker_endpoint`.
- **STD-012 v1.1.2**: Codified 3-tier boundary isolation rules, requiring Hub to bind dedicated listeners strictly on Docker bridge gateways while keeping loopback intact and physical LAN completely unexposed.

## [1.1.1] - 2026-09-23

### Changed
- **Contract Freeze (AI-ENGINEERING-PLATFORM-V1-004)**:
  - Unified Canonical Model Router API (POST /api/model/select) and Model Feedback API (POST /api/model/feedback).
  - Formally deprecated /api/router/* as compatibility aliases (/api/router/candidate-plan, /api/router/feedback, /api/router/match).
  - Fixed request enum typo across documentation and templates (quality strictly [high, medium, low]; latency strictly [low, normal, batch]; eliminated quality=normal).
  - Eliminated dual error taxonomies: unified on the 7 canonical classes in model-feedback.schema.json (QUOTA_EXHAUSTED, RATE_LIMITED, AUTH_FAILED, MODEL_UNAVAILABLE, NETWORK_ERROR, TIMEOUT, PROVIDER_ERROR).
  - Standardized Candidate Plan response schema conformance (rank, logical_model_id, endpoint_reference, governance_state, metrics, reason).
  - Aligned Durable Handoff baselines in handoff/ to Standards v1.1.1 and Hub v0.5.8.
  - Added contract regression assertions to tools/validate-schemas.py.

## [1.1.0] - 2026-09-23

### Added
- **STD-019: Artifact & Workspace Hygiene Standard** – Six-category artifact taxonomy (SOURCE, GENERATED, ACCEPTANCE, DEMO, TEMPORARY, ARCHIVE), `.artifacts/` directory layout, and workspace cleanup policy.
- **STD-020: Cross-Session Handoff Standard** – DURABLE vs TEMPORARY handoff types, mandatory fields, lifecycle constraints, and cross-repo isolation rules.
- **ARTIFACT-GOVERNANCE-V1.1.md** – Architecture overview of artifact governance model, KPI semantic correctness fix rationale, and Playwright mode governance.
- **tools/cleanup_audit.py** – Automated workspace audit tool implementing STD-019 classification.

### Changed
- **STD-014 v1.1**: Extended to four-level testing matrix (L1-SMOKE, L2-CORE, L3-DEEP, L4-DIAGNOSTIC) with explicit per-level constraints on scope, duration, tooling and output location.
- **STD-015 v1.1**: Added three explicit Playwright execution modes (AUTOMATED_TEST, ACCEPTANCE, DEMO) with mandatory headless/headed rules and KPI card verification requirement.
- **`.gitignore`**: Added `.artifacts/`, `playwright-report/`, `test-results/`.

## [1.0.0] - 2026-09-23

### Added
- **Formal Standards Framework (STD-001 to STD-018)**:
  - STD-001: Engineering Manifest Standard
  - STD-002: Resource Ownership Standard
  - STD-003: Endpoint Registry Standard
  - STD-004: Canonical Action Standard
  - STD-005: Health Status & Lifecycle Model Standard
  - STD-006: Port Governance Standard (18000-19999 Convention & Windows Dynamic Port Range)
  - STD-007: Credential Reference & Zero Secret Standard
  - STD-008: Model Registry Standard
  - STD-009: Model Routing Contract
  - STD-010: Model Feedback Contract
  - STD-011: Application Consumer Contract
  - STD-012: Windows / WSL / Docker Runtime Boundary
  - STD-013: Logging & Observability Standard
  - STD-014: Testing Standard
  - STD-015: Playwright Acceptance Standard
  - STD-016: Acceptance Evidence ZIP Standard
  - STD-017: Git Release & Versioning Standard
  - STD-018: UI Diagnostics & Enum Presentation Standard
- **Machine-readable JSON Schemas (`schemas/`)**:
  - `engineering-manifest.schema.json`
  - `resource.schema.json`
  - `endpoint.schema.json`
  - `canonical-action.schema.json`
  - `model-registry.schema.json`
  - `model-routing-request.schema.json`
  - `model-routing-response.schema.json`
  - `model-feedback.schema.json`
  - `audit-event.schema.json`
- **Resource Lifecycle Classification Model**:
  - `ALWAYS_ON` (常驻服务), `ON_DEMAND` (按需服务), `MANUAL` (手动管理), `EXTERNAL` (外部管理)
  - Explicit `desired_state` and `actual_state` contracts.
- **Cross-Session Integration Handoffs (`handoff/`)**:
  - `AI-KB-Model-Governance-Integration-Handoff.md`
  - `Sidecar-Model-Governance-Integration-Handoff.md`
  - `VTIP-Model-Governance-Architecture-Handoff.md`
- **Audit & Architecture Baseline**:
  - `docs/audit/STANDARDS-V1-AUDIT.md`
  - `docs/architecture/STANDARDS-V1-ARCHITECTURE.md`
  - `deprecated/CLOUD-CPA-TUNNEL-DEPRECATED.md`
- **Automated Schema Validator**:
  - `tools/validate-schemas.py`

### Changed
- **Local CPA Ground Truth Alignment**:
  - Aligned Host Endpoint to `http://127.0.0.1:18117` and Docker Internal Endpoint to `http://cpa-local:8317`.
  - Affirmed Owner as `ai-kb-infra` (`D:\AI-KB\Repo\ai-kb-infra`).
  - Standardized canonical lifecycle commands to `scripts/cpa/local-cpa.cmd` (`start`, `stop`, `restart`, `status`, `test`).
- **Cloud CPA Alignment**:
  - Standardized script path to `scripts/cpa/cloud-cpa-tunnel.cmd`.
  - Host Endpoint `http://127.0.0.1:18317` with fallback range `18318-18320`.
  - Classified as `ON_DEMAND` with `desired_state: STOPPED`.
- **Cold Start Semantics**:
  - Established contract: 0 invocations must return `success_rate: null` and `latency_p50/p95: null`. UI must display "暂无数据" and never "100%" or "0ms".
  - Introduced `sample_count` and `metric_confidence` (`NONE`, `LOW`, `MEDIUM`, `HIGH`).

### Deprecated
- `scripts/tunnel/cloud-cpa-tunnel.cmd` permanently marked as DEPRECATED in favor of `scripts/cpa/cloud-cpa-tunnel.cmd`.
- Direct Host port `8317` marked as DEPRECATED in favor of governed Host port `18117`.
