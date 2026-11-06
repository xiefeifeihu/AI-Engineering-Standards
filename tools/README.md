# 官方共享工具（Official Shared Tools）

本目录提供跨工程复用的工具实现。消费工程应通过固定版本的 Standards 仓库引用调用，不得复制后分叉。

## 工具清单

| 工具入口 | 中文职责 | 读写范围 |
|---|---|---|
| `standards_sync/cli.py` | 官方版本发现、精确锁核验、差异与兼容性分析、候选升级、晋升和回滚 | 诊断命令只读；候选写入 `.artifacts/standards_upgrade/`；promote/rollback 写 Lock 与 Manifest |
| `validate-documentation-collection.py` | 正式文档集合、Frontmatter、主入口、链接、锚点和审批引用校验 | 只读 |
| `validate-schemas.py` | JSON Schema 与样例验证 | 只读 |
| `generate_engineering_baseline.py` | 生成工程当前权威基线综合视图 | 写入指定工程的 `docs/当前权威基线.md` 和机器报告 |
| `generate_handoff.py` | 生成当前交接、任务快照和可选临时交接 | 写入指定工程交接路径；不得覆盖历史快照 |
| `validate_approval_contract.py` | 校验审批范围、候选 Commit、内容摘要及外部审批事件 | 只读 |
| `consumer-validation-evidence.schema.json` | 消费端 CI 证据契约；绑定仓库、项目、Commit、目标 Standards 四元组与六类验证维度 | 只读 Schema |
| `engineering-manifest.yaml → standards_validation.required_ci_jobs` | Owner 审核的消费端 CI Workflow/Job/命令白名单；证据不得自行选择任意绿色 Job | 只读核验 |
| `verify_consumer_ci_gate()` | 通过 GitHub Actions API 核验消费端 Workflow Run 与指定 Job 的真实状态 | 只读网络核验 |
| `validate_test_coverage.py` | 测试覆盖与证据契约校验 | 只读 |
| `validate_two_stage_release.py` | 两阶段发布证据契约校验 | 只读 |
| `cleanup_audit.py` | 工作区与制品清理审计 | 只读审计；不得绕过人工授权删除数据 |

## 安装依赖

在 Standards 仓库根目录或消费端引用目录执行：

```powershell
python -m pip install -r requirements-standards.txt
```

依赖：Python 3.10+、`jsonschema`、`PyYAML`。CI 当前使用 Python 3.12。

## 调用方式

从 Standards 仓库根目录：

```powershell
python tools/standards_sync/cli.py discover
python tools/standards_sync/cli.py verify-lock --project-root .
python tools/validate-documentation-collection.py --project-root . --check-templates
python tools/validate-schemas.py
python tools/generate_engineering_baseline.py --project-root .
python tools/generate_handoff.py --project-root . --task-id <TASK_ID> --version <PROJECT_VERSION>
```

从消费工程引用的 `.standards/` 子模块：

```powershell
python .standards/tools/standards_sync/cli.py --standards-root .standards verify-lock --project-root .
python .standards/tools/validate-documentation-collection.py --project-root . --check-templates
python .standards/tools/generate_engineering_baseline.py --project-root . --standards-root .standards
python .standards/tools/generate_handoff.py --project-root . --standards-root .standards --task-id <TASK_ID> --version <PROJECT_VERSION>
```

完整流程、Windows/Linux CI 示例、版本锁定和审批边界见 [Standards 消费端接入与工具使用协议](../docs/Standards消费端接入与工具使用协议.md)。
