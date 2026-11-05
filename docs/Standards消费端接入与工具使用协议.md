---
document_id: "DOC-STANDARDS-CONSUMER-INTEGRATION-PROTOCOL"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "TECHNICAL_DESIGN"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "5e17c0ef560ab8abafe880b988d70f85f380a104"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "Consumer integration, shared tool invocation, templates, exact Standards locking, CI, upgrade and rollback protocol."
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
4. 官方 `main` 用于发现最新正式 Release；工程实际执行 **MUST** 锁定正式 Tag 的精确四元组（`version`、`tag`、`tag_object_sha`、`peeled_commit`）。
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

| 消费工程目标文件 | Standards 权威模板或生成器 | 使用规则 |
|---|---|---|
| `engineering-manifest.yaml` | `governance/templates/engineering-manifest.template.yaml` | 复制后填写真实工程身份、资源属主和适用性 |
| `standards.lock.json` | `templates/standards.lock.template.json` | 仅作为字段结构示例；必须用 `discover` 结果替换所有占位符 |
| `docs/DOCUMENT-INDEX.md` | `templates/documentation/DOCUMENT-INDEX.template.md` | 填写本工程实际适用的文档主入口 |
| `docs/当前权威基线.md` | `tools/generate_engineering_baseline.py` | 由工程正式文档与实时证据生成，不得把空模板当成事实 |
| `docs/CROSS-SESSION-HANDOFF.md` | `tools/generate_handoff.py` | 由真实 Git、Lock、测试和 CI 事实生成 |
| 其他正式文档 | `templates/documentation/*.template.md` | 按 Manifest 的 `document_type_applicability` 选择，不适用类型必须有理由 |

模板中的 `{{...}}` 是未填充占位符，不是有效版本锁。占位符未替换前，Lock **MUST NOT** 通过 Schema 或 `verify-lock`，也不得提交为正式锁定。

更完整的模板清单见 `templates/consumer-project/README.md`。

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
5. 消费工程执行自身 Schema、单元、集成、业务、发布、安全及 Runtime 回归，保存绑定消费工程 Commit 与目标 Standards Peeled Commit 的原始证据。
6. `validate-upgrade` 只有在全部必需验证证据可核验后才能给出可晋升结论；当前工具尚未完成消费端多类证据的统一导入适配，缺证据时必须返回 `NOT_VERIFIABLE`。
7. ChatGPT 独立审核候选差异；属于 Owner 必批范围的变更，必须取得 Owner 明确批准。
8. 所有必需门禁通过后，才可执行 `promote` 更新 Lock/Manifest；随后重新运行 `verify-lock` 并记录远端 CI/Commit。
9. 任一门禁失败，保持旧 Lock 不变；不得通过修改测试断言或降低 Standards 要求使升级“变绿”。

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

本次候选版本只选择 AI-Engineering-Hub 作为首个消费端试点。试点当前观测基线、阶段和验收标准见迁移指南。AI-KB、VTIP、SideCar 不属于本轮试点，不得从 AI-Hub 试点结果推导其兼容性或升级批准。

## 10. 路径与显示名称

为保证 Windows/Linux、Python 导入、Git 子模块和跨工程链接稳定，当前机器路径与文件路径保持英文技术标识。README、目录导航、规范标题和用户界面采用“中文名称（English Name）”展示。路径重命名必须作为单独迁移任务处理，检查全部引用和消费者，不与本次治理升级混合。
