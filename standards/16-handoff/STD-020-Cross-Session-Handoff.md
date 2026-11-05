# STD-020: Cross-Session Handoff Standard (跨会话交接与自动化续接规范)

```text
STANDARD_ID=STD-020
VERSION=2.0.0
STATUS=ACTIVE
SCOPE=所有 AI 工程任务的跨会话交接协议、自动化事实采集与机器可验证交接契约
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-11-05
SCHEMA_REF=schemas/cross-session-handoff.schema.json, schemas/documentation-metadata.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 交接类型与唯一入口定义 (Handoff Types & Canonical Entrypoints)

本规范保留并严格区分两种交接类型（`DURABLE` 与 `TEMPORARY`），同时确立工程级唯一当前交接主入口：

| 交接类别 | 交接类型 (`handoff_type`) | 标准路径 | Git 追踪策略 | 核心职责 |
|:---|:---|:---|:---|:---|
| **工程当前交接主入口** | `DURABLE` | `docs/CROSS-SESSION-HANDOFF.md` | **必须提交 Git** | 工程内唯一活跃的 `CROSS_SESSION_HANDOFF` 主入口（`status: ACTIVE`, `primary_entrypoint: true`），反映工程最新会话交接状态。 |
| **任务级正式交接快照** | `DURABLE` | `handoff/<TASK-ID>-<VERSION>-handoff.md` | **必须提交 Git** | 每个独立工程任务完成或阶段封版时的不可变历史交接证据（`primary_entrypoint: false`）。 |
| **会话间临时交接** | `TEMPORARY` | `.artifacts/handoff/temporary/` | **严禁提交 Git** | 跨终端/跨会话临时上下文传递（如 `<TASK-ID>-RETURN.md`），被 `.gitignore` 严格排除，目标会话接收后清理。 |

1. **唯一当前交接入口原则**：每个受管工程 **MUST** 在 `docs/CROSS-SESSION-HANDOFF.md` 维护当前唯一活跃的跨会话交接文档（`document_type: CROSS_SESSION_HANDOFF`，`status: ACTIVE`，`primary_entrypoint: true`）。
2. **历史交接证据保护铁律**：新生成的任务级正式交接（`handoff/<TASK-ID>-<VERSION>-handoff.md`）或当前交接主入口更新 **MUST NOT** 覆盖、篡改或删除 `handoff/` 目录下已有的其他历史任务交接文件。

---

## 2. 跨会话交接十项加一自动化采集要求 (Automated Handoff Collection Requirements)

跨会话交接生成器（`tools/generate_handoff.py`）与机器校验契约（`schemas/cross-session-handoff.schema.json`）**MUST** 自动采集、结构化记录并验证以下 11 项核心工程事实：

1. **自动采集 Git 状态 (`git_state.status_summary`)**：实时执行 `git status -sb`，如实记录工作区是否干净（`worktree_clean`）及未提交变更摘要。
2. **自动采集分支及 Commit (`git_state.branch`, `local_head`, `remote_head`)**：实时采集当前分支名、本地 `HEAD` 精确 Commit SHA 及远端跟踪分支 Commit（若网络不可达则标记 `NOT_VERIFIABLE`）。
3. **自动采集 Standards 锁定 (`standards_lock`)**：自动读取 `standards.lock.json`（及 `engineering-manifest.yaml`），记录当前锁定的 `repository`、`version`、`tag`、`tag_object_sha` 与 `peeled_commit`。
4. **自动汇总实际测试结果 (`test_results`)**：从真实测试执行产物读取测试命令、退出码、通过数、失败数与证据路径（`evidence_ref`）。未执行测试时 **MUST** 标记 `verification_status: NOT_RUN`，严禁伪造 `PASS`。
5. **自动关联 CI Run ID (`ci_run`)**：关联目标 Commit 的远端 CI `run_id`、`workflow` 与核验状态（`PASS` / `FAIL` / `BLOCK` / `NOT_RUN` / `NOT_VERIFIABLE`）。
6. **自动汇总已完成事项 (`completed_items`)**：结构化列出本任务/本会话已闭环完成的工程事项。
7. **自动汇总未完成事项 (`pending_items`)**：结构化列出尚未完成的待续工作项。
8. **自动汇总 `BLOCK` 阻断项 (`blockers`)**：显式列出当前所有阻塞项（`blocker_id`、`description`、`severity`、`remediation`）。
9. **自动记录已批准决策 (`approved_decisions`)**：记录已获批准的决策 ID、摘要、审批状态（`AI_APPROVED` 或 `OWNER_APPROVED`）及真实审批引用（`approval_reference`）。
10. **自动记录 `PROPOSED` 待审事项 (`proposed_items`)**：将尚未获得批准的设计建议或待决策事项显式标记为 `status: PROPOSED` 并指明 `requires_owner_approval`，**MUST NOT** 将 `PROPOSED` 事项混入 `approved_decisions`。
11. **自动生成下一会话启动指引 (`next_session_guide`)**：包含新会话强制读取顺序（`mandatory_read_order`）、必跑实时核验命令（`verification_commands`）与下一步操作清单（`immediate_next_steps`）。

---

## 3. 新会话启动实时重核验铁律 (Mandatory Real-Time Re-Verification on Session Start)

1. **严禁依赖旧聊天摘要推断工程状态**：任何新启动的会话或编码智能体 **MUST NOT** 仅凭上一轮聊天记录摘要或历史交接文本直接假定当前 Git 分支、Commit、CI 状态或 Runtime 状态。
2. **启动强制重核验流程**：新会话接手任务时，**MUST** 首先按 `STD-035` §8 顺序读取 `docs/DOCUMENT-INDEX.md`、`docs/当前权威基线.md` 与 `docs/CROSS-SESSION-HANDOFF.md`，随后立即在终端执行实时核验命令（核查 `git status -sb`、`git rev-parse HEAD`、`standards.lock.json` 与 `tools/standards_sync` 锁定校验），确认实时工程事实与交接记录一致后方可开始编码。
3. **交接漂移阻断**：若新会话发现实际工作区 Commit 或文件状态与 `docs/CROSS-SESSION-HANDOFF.md` 记录不一致，**MUST** 先重新运行 `tools/generate_handoff.py` 和 `tools/generate_engineering_baseline.py` 刷新实时事实，严禁在基线漂移状态下盲目修改代码。

---

## 4. 验收交接包与跨仓库隔离约束 (Acceptance Package & Cross-Repo Isolation)

1. **验收 ZIP 包隔离**：正式验收 ZIP 包 **MUST** 遵循 `STD-016` 唯一存放于 `.artifacts/packages/`，包含 `manifest.json`（含 `task_id`、`version`、`run_id`、`created_at`、`files`），从不提交 Git。
2. **跨仓库交接严格隔离**：不同仓库的交接文档 **MUST** 独立存放在各自所属仓库内，**MUST NOT** 跨仓库混合提交或越权修改只读参考仓库（`AI-Engineering-Hub`、`AI-KB`、`vtip-platform-catalog`、`vtip-ai-sidecar`）。
