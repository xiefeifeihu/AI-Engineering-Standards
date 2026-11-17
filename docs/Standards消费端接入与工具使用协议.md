---
document_id: "DOC-STANDARDS-CONSUMER-INTEGRATION-PROTOCOL"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "TECHNICAL_DESIGN"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "9687f961b22df612c4311961e06fc1c1fd508c37"
applies_to_release: "v3.0.0"
last_updated: "2026-11-16"
supersedes: null
change_summary: "补充历史 Lock 首次建锁、工具发现来源、消费端身份和历史快照验证协议。"
history_reference: "docs/API-CONTRACT.md"
primary_entrypoint: false
content_sha256: null
---

# Standards 消费端接入与工具使用协议（Consumer Integration & Tool Usage Protocol）

## 1. 目的与强制边界

本协议定义其他工程如何消费 AI-Engineering-Standards 提供的规范正文、JSON Schema、模板和官方共享工具。

1. Standards 是公共规范与共享工具的唯一维护仓库。
2. 消费工程 **MUST** 引用官方实现，**MUST NOT** 将 `tools/`、`schemas/` 或规范正文复制到工程后分叉维护。
3. 消费工程 **MUST** 保留自己的产品基线、架构、接口、测试、发布和交接资料；Standards 模板只提供结构与契约，不替代工程 Owner 的业务决策。
4. 官方 `main` 用于发现最新正式 Release。官方正式版本的唯一权威来源是 Canonical 规范仓库上的 **Git Annotated Tag**（`refs/tags/vX.Y.Z`），严禁依赖 GitHub Web UI 的 `/releases/latest` REST API（该 API 仅反映 Web Release 对象，可能滞后或脱节）。工程实际执行 **MUST** 锁定正式 Tag 的精确四元组（`repository`、`version`、`tag`、`tag_object_sha`、`peeled_commit`）。`standards_sync discover` 是只读探测操作，严禁在未经过 `prepare-upgrade`、`validate-upgrade` 与 Owner 批准前自动修改消费工程的锁定版本。
5. 候选分支、Draft PR、未发布的 main Commit 不得作为“最新正式版本”晋升。

## 2. 共享工具引用方式

### 2.1 推荐方式：Git 子模块（Git Submodule）

在消费工程根目录执行：

```powershell
git submodule add https://github.com/xiefeifeihu/AI-Engineering-Standards.git .standards
git -C .standards fetch --tags
```

随后由 `standards_sync discover` 查询官方最新正式 Release。兼容性验证和审批通过后，将子模块检出到锁文件指定的 Peeled Commit，并提交 Gitlink 与 `standards.lock.json`。

CI 应使用：

```yaml
- uses: actions/checkout@v4
  with:
    submodules: recursive
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
- name: Install Standards tool dependencies
  run: python -m pip install -r .standards/requirements-standards.txt
- name: Verify exact Standards lock
  run: python .standards/tools/standards_sync/cli.py --standards-root .standards verify-lock --project-root .
```

子模块的实际 HEAD **MUST** 与 `standards.lock.json.peeled_commit` 一致。子模块路径建议统一为 `.standards/`；如工程已有受控路径，可在 Manifest 中明确记录，不得因此复制工具实现。

### 2.2 过渡方式：受控共享检出目录

已有本地共享 Standards Clone 的工程可以暂时直接引用，不必立即增加子模块：

```powershell
$env:AI_ENGINEERING_STANDARDS_ROOT = 'D:\Projects\AI-Engineering-Standards'
$standards = $env:AI_ENGINEERING_STANDARDS_ROOT
python "$standards\tools\standards_sync\cli.py" --standards-root "$standards" discover
python "$standards\tools\standards_sync\cli.py" --standards-root "$standards" verify-lock --project-root .
```

Linux/macOS 示例：

```bash
export AI_ENGINEERING_STANDARDS_ROOT=/workspace/AI-Engineering-Standards
python "$AI_ENGINEERING_STANDARDS_ROOT/tools/standards_sync/cli.py" \
  --standards-root "$AI_ENGINEERING_STANDARDS_ROOT" discover
python "$AI_ENGINEERING_STANDARDS_ROOT/tools/standards_sync/cli.py" \
  --standards-root "$AI_ENGINEERING_STANDARDS_ROOT" verify-lock --project-root .
```

该模式适合本机多工程共享同一份 Standards Clone。CI 环境必须显式检出锁文件指定的精确 Tag/Commit，不能依赖某台开发机的绝对路径。

## 3. Python 环境与依赖

- Python：3.10 或更高版本；CI 当前使用 Python 3.12。
- 官方工具依赖统一声明在 `requirements-standards.txt`。
- 消费端安装：

```powershell
python -m pip install -r .standards/requirements-standards.txt
```

- 消费端不得各自维护不同版本的 `jsonschema` / `PyYAML` 组合来掩盖 Standards 校验差异。
- 升级依赖范围属于 Standards 工具兼容性变更，需由 Standards 仓库维护并通过 Windows/Linux CI。

## 4. 消费工程初始化模板

所有正式文档模板均为未审批的起始材料：必须保持 `status: CANDIDATE`、`approval_status: NOT_SUBMITTED`，且 `source_commit`、`content_sha256`、`approval_evidence_ref` 为 `null`。模板不代表工程事实、独立审核或 Owner 批准；实际项目文档须由消费工程根据真实证据生成并重新审核。

| 消费工程目标文件 | Standards 权威模板或生成器 | 使用规则 |
|---|---|---|
| `engineering-manifest.yaml` | `governance/templates/engineering-manifest.template.yaml` | 复制后填写真实工程身份、资源属主和适用性 |
| `standards.lock.json` | `templates/standards.lock.template.json` | 仅作为字段结构示例；必须用 `discover` 结果替换所有占位符 |
| `docs/DOCUMENT-INDEX.md` | `templates/documentation/DOCUMENT-INDEX.template.md` | 填写本工程实际适用的文档主入口 |
| `docs/当前权威基线.md` | `tools/generate_engineering_baseline.py` | 由工程正式文档与实时证据生成，不得把空模板当成事实 |
| `docs/CROSS-SESSION-HANDOFF.md` | `tools/generate_handoff.py` | 由真实 Git、Lock、测试和 CI 事实生成 |
| 其他正式文档 | `templates/documentation/*.template.md` | 按 Manifest 的 `document_type_applicability` 选择，不适用类型必须有理由 |

模板使用 `0.0.0`、`v0.0.0` 和全零 SHA 作为 Schema 合法的哨兵值（TEMPLATE_ONLY），不是正式版本锁。未用 `discover` 输出替换全部哨兵值前，Lock **MUST NOT** 通过 `verify-lock`，也不得提交为正式锁定。

更完整的模板清单见 `templates/consumer-project/README.md`。

### 4.1 历史版本首次建锁（受控初始化，不是普通升级）

本节仍属 IN_REVIEW / OWNER_MANDATORY 候选协议，不能作为自动批准。v3.0.0 CLI 没有 init-lock；verify-lock 和 prepare-upgrade 在缺少锁时 BLOCK 属于预期行为。禁止浮动 main 或模板哨兵值绕过。

1. 先确认消费端当前实际使用的旧版正式 Standards，检查 Manifest、历史兼容矩阵、本工程 HEAD、历史测试。版本不确定时 NOT_VERIFIABLE，严禁猜测。
2. 核验旧版官方 Annotated Tag、Tag Object SHA、Peeled Commit、VERSION、main 祖先关系及真实 CI。签名未核验不得宣称已签名。
3. 使用 templates/standards.lock.template.json 在独立候选分支建立历史 Lock，填入经核实的 repository/version/tag/tag_object_sha/peeled_commit、真实 locked_at 和 lock_reason；首次 previous_locks 为空，不伪造历史锁。
4. Owner 必须对历史基线和首次锁定明确批准，记录真实候选 Commit、内容摘要和审批引用。缺少可信审批验证适配器时保留 NOT_VERIFIABLE，严禁凭本地 JSON 自行晋升。
5. 使工程 Manifest 与历史 Lock 对齐；兼容矩阵仅描述兼容范围，不成为第二份锁，也不得要求其他工程跟随。
6. 完成 schema 与 verify-lock 后，才允许从该历史 Lock 开始 compare/impact/prepare-upgrade；H4 必需测试和 CI 全绿、独立审核和 Owner 批准后，才执行 promote；旧锁必须写入 previous_locks 并校验 rollback。

AI-HUB H1 的只读实例（仅供核验，不是其他工程默认值）：v2.11.0 历史 Tag Object = 2f4b4b54348a5ac8891e5a0b33c04635a27213a0；Peeled Commit = 5e17c0ef560ab8abafe880b988d70f85f380a104。目标 v3.0.0 Tag Object = 8256bb384e62894219db0992a2cb57e16d4fa8cd；Peeled Commit = 8b223019c254e0edeb94576b94af46c1e48b0316。可核实对象事实不等于审批通过。

### 4.2 只读工具的来源和身份语义

- REMOTE_OFFICIAL_DISCOVERY 只用于已查询官方远端 refs 的模式；LOCAL_CLONE_DISCOVERY 只能证明本地 Clone 中的 refs，不得将本地 main 冒充远端实时 main，远端未核实时返回 NOT_VERIFIABLE。
- 祖先检查退出码 1 表示确证非祖先；退出码非 0/1 表示对象缺失或命令异常，返回 NOT_VERIFIABLE，不可作为 NOT_ON_MAIN_BRANCH 事实失败。
- INPUT_STANDARDS_COMMIT/TARGET_STANDARDS_COMMIT 是规范仓库的 Commit；CONSUMER_COMMIT 是消费端 Git HEAD，CONSUMER_WORKTREE_STATUS 表示其工作区。消费端身份不可验证时兼容评估不能完整 PASS。
- impact 的 AGENTS/CLAUDE 文本扫描是辅助静态检查；Tests、Security、Release、Business API、Runtime 未执行时不得标记 COMPATIBLE。
- 消费端工作区必须为 CLEAN 才能将 `CONSUMER_VERIFICATION_STATUS` 标记为 PASS；DIRTY 或 HEAD 不可读时返回 NOT_VERIFIABLE，并使影响分析保持 PARTIAL。静态扫描必须正确跳过多行 HTML 注释，只忽略以明确历史标签开头的历史说明，并报告 Windows 盘符路径与 UNC 绝对路径的文件/行号。
- verify-lock 负责 Lock、Manifest 和官方 Tag 的精确绑定，不将 compatibility_matrix.yaml 变成第二个锁；矩阵中消费工程自己的兼容范围由工程级适配检查核对。

### 4.3 历史锁定安全回滚契约（F11）

- 历史 Lock（如初始引导态）`approval_evidence_ref: null` 属于合规历史事实，Schema 与工具均允许直接回滚，不得因此报错阻断。
- 执行回滚必须提供当前 Owner 回滚授权：`python tools/standards_sync/cli.py rollback --project-root . --rollback-authorization-ref <PATH>`。该参数在官方 CLI 中为强制必选（默认 `require_authorization=True`），杜绝智能体无授权直接修改锁文件。
- 回滚前必须调用 `verify_official_historical_tag` 核验目标 Tag 在官方规范仓远端存在、Tag 对象与剥离提交匹配、且位于官方 main 祖先链上；远端不可达或网络超时返回 `NOT_VERIFIABLE`，不匹配返回 `FAIL`。
- 历史 Lock 若缺少 CI 状态记录，回滚后严格标记为 `NOT_VERIFIABLE`，严禁假定或自动回退为 PASS；`promote_upgrade` 保存历史 Lock 至 `previous_locks` 时同样严格继承或默认 `NOT_VERIFIABLE`。
- 回滚过程原子更新 `standards.lock.json` 与 `engineering-manifest.yaml`；任一失败完全还原，保留 `previous_locks` 完整历史审计栈。

### 4.4 方案 C 单 Owner 双 Commit PR Merge 审批集成（F12）

- 在消费端 PR 审批与晋升中，通过 `commit_bindings` 显式解耦消费端候选 HEAD 与 Standards Peeled Commit（包含 repository、target_tag、tag_object_sha、peeled_commit 4 项完整字段），并通过 `content_bindings` 绑定门禁映射与清单摘要，杜绝概念混淆。
- 审批记录与 `approval_event` 内的 `commit_bindings` 和 `content_bindings` 必须逐字段严格相等；`event_timestamp` 必须精确等于 GitHub PR API 返回的 `merged_at`。
- 审批凭证通过 GitHub API 读取 PR Merge 事件，强制核验 `merged=true`、`merged_by=Owner`、`base.ref=main`、`head.sha=consumer.candidate_commit`。
- 编程智能体严禁参与或自批审批（`CODING_AGENT` 角色强阻断）；严禁智能体执行 PR 合并；废除未实现的 `SIGNED_OWNER_EVENT` 伪枚举。
- 针对 `STANDARDS_LOCK_PROMOTION` 和 `LOCK_ROLLBACK`，强制要求双向绑定，严禁使用单 Commit 遗留旁路绕过。

## 5. 每次任务启动与工具调用顺序

在消费工程根目录运行：

```powershell
# 1. 查询官方最新正式 Release（不改变当前锁定）
python .standards/tools/standards_sync/cli.py --standards-root .standards discover

# 2. 核验当前工程精确锁定
python .standards/tools/standards_sync/cli.py --standards-root .standards verify-lock --project-root .

# 3. 比较当前锁定与候选目标（未提供 Lock 时，只允许显式 --from-ref 做只读引导分析）
python .standards/tools/standards_sync/cli.py --standards-root .standards compare --project-root . --to-ref vX.Y.Z

# 4. 生成工程级兼容性影响报告
python .standards/tools/standards_sync/cli.py --standards-root .standards impact --project-root . --to-ref vX.Y.Z
```

命令输出的 `NOT_VERIFIABLE` 不得解释为 PASS。网络不可用时，工程可以继续使用已经锁定且本地可验证的版本执行已有工作，但不得推断“最新版本已确认”，不得静默升级或降级。

## 6. 受控升级流程

1. `discover` 获取官方最新正式 Tag、Tag Object SHA、Peeled Commit、VERSION 和 main CI 状态。
2. `compare` 分析标准正文、Schema 和规范性条款差异。
3. `impact` 按消费工程实际 Lock 评估影响；未执行维度必须标记 `NOT_RUN` / `NOT_VERIFIABLE`。
4. `prepare-upgrade` 只生成候选 Lock 和影响报告，输出到 `.artifacts/standards_upgrade/`；不修改正式 Lock。
5. 消费工程先在 Owner 审核的 `engineering-manifest.yaml` → `standards_validation.required_ci_jobs` 中登记每个门禁的真实 Workflow 路径、Job 名称和命令，并提供 `approval_evidence_ref` 追溯 Owner 审核批准；再在自身 CI 中执行单元、集成、发布、安全、业务 API 与 Runtime 回归，所有必需 Job 必须运行在同一个消费工程 Commit 上。
6. 从 `templates/consumer-project/consumer-validation-evidence.template.json` 生成 `.artifacts/standards_upgrade/<TAG>/consumer-validation-evidence.json`，填写真实仓库、项目标识、消费 Commit、目标 Standards 四元组，以及每个 CI Job 的 Workflow 路径、Run ID、Job 名称、命令、Head SHA、GitHub Actions 证据链接及结构化测试执行证据（`test_execution` 包含 `tests_collected >= 1`、`tests_passed >= 1`、`tests_failed == 0`、`tests_skipped >= 0`）；严禁通过空测试、全跳过测试或未真实执行测试的绿色 Job 蒙混晋升。这些字段必须与 Owner 审核的 Manifest 门禁映射完全一致。
7. 执行以下只读验证；工具先核对证据与 Owner 审核的 Manifest 门禁映射，再通过 GitHub Actions API 核验每个 Run 和 Job 的仓库、Workflow、Commit、完成状态及成功结论：

```powershell
python .standards/tools/standards_sync/cli.py --standards-root .standards validate-upgrade --project-root . --target-tag vX.Y.Z
```

8. 只有 Manifest、文档集合、权威基线和全部必需消费端 CI Job 均通过，`validate-upgrade` 才能返回 `PASS`。缺少证据、网络不可用或 GitHub API 不可核验时返回 `NOT_VERIFIABLE`；任一证据失败、Commit 不一致或 Job 失败时返回 `UPGRADE_BLOCKED`。`NON_RUNTIME_ARTIFACT` 的 Runtime 维度必须明确标记 `NOT_APPLICABLE` 并说明原因；`SERVICE` 必须提供 Runtime CI 证据。
9. ChatGPT 独立审核候选差异；属于 Owner 必批范围的变更，必须取得 Owner 明确批准。
10. 所有必需门禁通过后，才可执行 `promote` 更新 Lock/Manifest。晋升与回滚采用应用级协同双文件写入与恢复机制（`execute_transactional_two_file_update`），先写入临时文件与备份文件（`.bak`）并维护事务日志（`.standards_sync_tx.json`），在第二步替换或磁盘写入发生故障时自动触发回滚恢复；若恢复再次失败严格保留备份文件杜绝数据丢失；进程异常中断时支持通过 `recover-tx` 检测并恢复；明确多文件协作更新基于应用级协调与单文件原子替换，非断电级硬件原子事务；随后重新运行 `verify-lock` 并记录远端 CI/Commit。
11. 任一门禁失败，保持旧 Lock 不变；不得通过修改测试断言或降低 Standards 要求使升级“变绿”。

## 7. 工具权限分级

| 工具/子命令 | 默认性质 | 允许写入的位置 |
|---|---|---|
| `discover` | 只读 | 无 |
| `verify-lock` | 只读 | 无 |
| `compare` | 只读 | 无 |
| `impact` | 只读 | 无 |
| `validate-upgrade` | 只读 | 无 |
| `prepare-upgrade` | 候选生成 | 仅 `.artifacts/standards_upgrade/` |
| `generate_engineering_baseline.py` | 文档生成 | 指定工程的基线文件及机器报告 |
| `generate_handoff.py` | 文档生成 | 当前交接、不可覆盖的任务快照及临时交接 |
| `validate-documentation-collection.py` | 只读校验 | 无 |
| `validate-schemas.py` | 只读校验 | 无 |
| `promote` | 受控写入 | `standards.lock.json`、Manifest |
| `rollback` | 受控写入 | `standards.lock.json`、Manifest |

生成器写入正式 `docs/` 前，消费工程编码智能体必须确认目标工程、分支和写入范围；生成结果仍需 ChatGPT 审核及适用的 Owner 批准。

## 8. 审批真实性与当前能力边界

- 编程智能体不得自行声明 `AI_APPROVED` 或 `OWNER_APPROVED`。
- 当前审批验证器可以查询并核验 GitHub PR Review 事件，但尚未实现可独立验证的 ChatGPT 会话证明适配器。
- 因此，ChatGPT 在聊天中完成的审核可以作为人工审核过程和决策记录；在可信会话证明适配器实现前，不能把本地 JSON 中的 `reviewer="ChatGPT"` 或任意 `chatgpt://` 字符串当作机器可验证凭证，也不能据此绕过 `promote` 门禁。
- Owner 聊天批准也必须记录精确范围、候选 Commit 和内容摘要；如需由工具自动验证，必须使用受信任的外部审批事件，不能伪造 GitHub 用户事件。

## 9. 首个消费端试点

Standards 提供可复用能力，但消费端必须由各自 Owner 显式批准接入。本次候选版本只选择 AI-Engineering-Hub 作为首个消费端试点。试点当前观测基线、阶段和验收标准见迁移指南。AI-KB、VTIP、SideCar 不属于本轮试点，不得从 AI-Hub 试点结果推导其兼容性或升级批准；不默认加入自动巡检或自动升级。

## 10. 路径与显示名称

为保证 Windows/Linux、Python 导入、Git 子模块和跨工程链接稳定，当前机器路径与文件路径保持英文技术标识。README、目录导航、规范标题和用户界面采用“中文名称（English Name）”展示。路径重命名必须作为单独迁移任务处理，检查全部引用和消费者，不与本次治理升级混合。
