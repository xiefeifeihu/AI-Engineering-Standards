---
document_id: "DOC-STANDARDS-API-CONTRACT"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "API_CONTRACT"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "9687f961b22df612c4311961e06fc1c1fd508c37"
applies_to_release: "v3.0.0"
last_updated: "2026-11-16"
supersedes: null
change_summary: "扩展消费端 impact 输出契约，明确 Standards 与消费工程 Git 身份字段及 NOT_VERIFIABLE 状态。"
history_reference: "CHANGELOG.md"
primary_entrypoint: true
content_sha256: null
---


# 接口契约规范 (API & Schema Contract)

## 1. 权威 JSON Schema 契约入口 (`schemas/`)

- [`schemas/documentation-metadata.schema.json`](../schemas/documentation-metadata.schema.json)：12 类正式工程文档 YAML Frontmatter 契约。
- [`schemas/documentation-approval.schema.json`](../schemas/documentation-approval.schema.json)：ChatGPT 独立审核 (`chatgpt_review`) 与所有者批准 (`owner_approval`) 证据契约。
- [`schemas/standards-lock.schema.json`](../schemas/standards-lock.schema.json)：工程根目录 `standards.lock.json` 四元组锁定与 `previous_locks` 历史契约。
- [`schemas/engineering-baseline.schema.json`](../schemas/engineering-baseline.schema.json)：`ENGINEERING_BASELINE` 18 项内容与 6 项动态溯源字段契约。
- [`schemas/cross-session-handoff.schema.json`](../schemas/cross-session-handoff.schema.json)：`STD-020` 跨会话自动采集交接 11 项字段契约。
- [`schemas/engineering-manifest.schema.json`](../schemas/engineering-manifest.schema.json)：`STD-001` 工程清单唯一权威 Schema（与 [`governance/engineering-manifest-schema.json`](../governance/engineering-manifest-schema.json) 保持兼容镜像一致）。

## 2. 官方 CLI 工具调用契约（Tools）

| 命令入口 | 子命令 / 参数 | 返回码与输出契约 |
| :--- | :--- | :--- |
| `python tools/standards_sync/cli.py` | `discover` / `verify-lock` / `compare` / `impact` / `prepare-upgrade` / `validate-upgrade` / `promote` / `rollback` | 标准输出结构化 JSON；成功返回 `0`，阻断或校验失败返回 `1`（远端不可达时 `discover` 返回 `status: NOT_VERIFIABLE`） |
| `python tools/validate-documentation-collection.py` | `--project-root <DIR> [--schema <PATH>] [--check-templates]` | 执行 17 项文档集合、链接与锚点校验；全部通过返回 `0`，任一违例返回 `1` |
| `python tools/generate_engineering_baseline.py` | `--project-root <DIR> [--scope {consumer,standards-release}] [--verify-only] [--observed-at <ISO>]` | 确定性生成或校验 `docs/当前权威基线.md` 与 `.artifacts/baseline/engineering_baseline.json`；默认 `consumer` 作用域解耦 Standards 自身发布证据，`standards-release` 校验三作用域发布证据；源冲突时返回 `1` |
| `python tools/generate_handoff.py` | `--project-root <DIR> --task-id <ID> [--version <VER>]` | 自动采集 11 项工程事实并生成 `docs/CROSS-SESSION-HANDOFF.md` 与 `handoff/<TASK-ID>-<VERSION>-handoff.md` |
| `python tools/validate_approval_contract.py` | `--approval-file <JSON> [--document-file <MD>] [--expected-commit <SHA>]` | 校验双层审批契约、反自批及 SHA-256/Commit 一致性；通过返回 `0`，违例返回 `1` |


## 2.1 消费端影响分析输出契约（`impact`）

`python tools/standards_sync/cli.py impact --project-root <PROJECT_ROOT> --to-ref <TAG>` 返回结构化 JSON。以下字段用于区分规范仓库与消费工程身份：

| 字段 | 含义 | 允许状态/值 |
| :--- | :--- | :--- |
| `INPUT_STANDARDS_COMMIT` | 输入端正式 Standards Tag 对应的 Peeled Commit；无 Lock 时仅在显式 `--from-ref` 且可解析时填入 | 完整 40 位 SHA 或 `UNKNOWN` |
| `TARGET_STANDARDS_COMMIT` | 目标正式 Tag 的 Peeled Commit；目标为 `WORKTREE` 时保留 `WORKTREE`，不得伪装成 Commit SHA | 完整 40 位 SHA 或 `WORKTREE` / `NOT_VERIFIABLE` |
| `CONSUMER_COMMIT` | 被评估消费工程自身的 Git HEAD，不是 Standards Commit | 完整 40 位 SHA 或 `NOT_VERIFIABLE` |
| `CONSUMER_WORKTREE_STATUS` | 消费工程工作区状态 | `CLEAN` / `DIRTY` / `NOT_VERIFIABLE` |
| `CONSUMER_VERIFICATION_STATUS` | 消费工程身份是否可绑定到当前评估内容 | 仅当 HEAD 可读且工作区为 `CLEAN` 时为 `PASS`；否则为 `NOT_VERIFIABLE` |
| `GUIDANCE_FINDINGS` | `AGENTS.md`、`CLAUDE.md`、`README.md` 中的静态扫描发现 | 数组元素包含 `file`、`line`、`code`、`excerpt` |

`analysis_status` 与 `compatibility_status` 必须分开解释。消费端 HEAD 不可读或工作区非 CLEAN 时，影响分析为 `PARTIAL`，兼容性不得汇总为 `COMPATIBLE`。任一必需维度为 `NOT_RUN` 或 `NOT_VERIFIABLE` 时，整体状态不得为 `PASS`。静态指引扫描不替代真实测试、安全、发布、业务 API 或 Runtime 验收。
## 2.2 历史基线锁定回滚契约（`rollback`）

`python tools/standards_sync/cli.py rollback --project-root <PROJECT_ROOT> --rollback-authorization-ref <PATH>`

1. **强制 Owner 授权**：官方 CLI `rollback` 子命令强制要求 `--rollback-authorization-ref`，默认 `require_authorization=True`，严禁智能体无授权直接修改锁文件。授权记录必须满足 `schemas/documentation-approval.schema.json`、`reviewer_type == "OWNER"` 且 `approval_status == "OWNER_APPROVED"`。
2. **官方历史 Tag 远端一致性核验**：回滚时必须调用 `verify_official_historical_tag` 核验目标 Tag 在官方规范仓远端存在、Tag 对象与剥离提交匹配、以及位于官方 main 祖先链上；远端不可达或网络超时返回 `NOT_VERIFIABLE`，不匹配返回 `FAIL`。
3. **历史 Lock 真实性保持与 CI 状态**：历史 Lock 的 `approval_evidence_ref` 允许为 `null`（如初始引导态），严禁篡改或伪造历史审批事实；历史 Lock 缺失或无效 CI 记录时默认标记为 `NOT_VERIFIABLE`，严禁假定或自动回退为 `PASS`。
4. **两文件事务更新**：回滚操作原子更新 `standards.lock.json` 与 `engineering-manifest.yaml`；任一文件写入或校验失败时彻底回退，保留 `previous_locks` 完整审计链。

## 2.3 单 Owner 双 Commit PR Merge Event 审批契约（方案 C）

在消费端合入升级分支或执行 Standards Lock 变更时，审批契约通过 `commit_bindings` 显式解耦双 Commit 身份：

```json
{
  "commit_bindings": {
    "consumer": {
      "repository": "<CONSUMER_REPO>",
      "candidate_commit": "<CONSUMER_HEAD_SHA>"
    },
    "standards": {
      "repository": "xiefeifeihu/AI-Engineering-Standards",
      "target_tag": "v3.0.0",
      "tag_object_sha": "8256bb384e62894219db0992a2cb57e16d4fa8cd",
      "peeled_commit": "8b223019c254e0edeb94576b94af46c1e48b0316"
    }
  },
  "content_bindings": {
    "ci_job_mapping_sha256": "sha256:<64-HEX>",
    "lock_manifest_sha256": "sha256:<64-HEX>"
  }
}
```

- **验证规则**：GitHub PR Merge 事件必须由仓库属主独立执行（`merged=true`，`merged_by=Owner`，`base.ref=main`，`head.sha=consumer.candidate_commit`）；严禁智能体自批或合并（`CODING_AGENT` 角色严格阻断）。
- **字段双向对齐与时间戳匹配**：审批记录与 `approval_event` 内部的 `commit_bindings`（consumer 2项、standards 4项）与 `content_bindings`（2项有效摘要）必须逐字段完全一致；`event_timestamp` 必须精确匹配 GitHub PR API 返回的 `merged_at`。
- **禁止单 Commit 旁路绕过**：针对 `STANDARDS_LOCK_PROMOTION` 和 `LOCK_ROLLBACK` 作用域，必须具备上述双向 Commit 绑定与内容绑定，严禁使用旧版单 Commit 结构绕过。
- **审批范围**：明确区分 `GATE_MAPPING`（门禁配置映射）与 `STANDARDS_LOCK_PROMOTION`（基线晋升）。
- **枚举清理**：彻底废除未实现的 `SIGNED_OWNER_EVENT` 伪枚举。

## 3. 消费端调用与权限边界

完整接入步骤、共享工具引用方式、依赖安装、模板复制、Windows/Linux 命令、CI 示例及升级/回滚流程统一见 [`Standards消费端接入与工具使用协议`](./Standards消费端接入与工具使用协议.md)。消费工程 **MUST NOT** 复制并分叉 `tools/`、`schemas/` 或标准正文；应通过固定版本的官方仓库引用调用。
