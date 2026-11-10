---
document_id: "DOC-MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-V300"
document_version: "3.0.0"
project_id: "ai-engineering-standards"
document_type: "TECHNICAL_DESIGN"
status: "IN_REVIEW"
approval_status: "IN_REVIEW"
approval_scope: "OWNER_MANDATORY"
approval_evidence_ref: null
source_commit: "9687f961b22df612c4311961e06fc1c1fd508c37"
applies_to_release: "v3.0.0"
last_updated: "2026-11-05"
supersedes: null
change_summary: "AI-Engineering-Hub first consumer pilot plan for Standards v3.0.0 candidate; other consumers excluded."
history_reference: null
primary_entrypoint: false
content_sha256: null
---

# Standards v3.0.0 候选迁移指南：AI-Hub 首个消费端试点

> **状态**：PROPOSED / NOT_APPROVED（本指南是候选迁移计划，不代表下游工程已批准升级）。
> **唯一首个试点**：`xiefeifeihu/AI-Engineering-Hub`。
> **本 PR 边界**：只修改 AI-Engineering-Standards；不修改 AI-Hub、AI-KB、VTIP 或 SideCar。

## 1. 试点选择与工程边界

首个消费端选择 AI-Engineering-Hub，原因是它目前最接近 Standards 的执行模式：工程规则明确引用 Standards，具有启动前置检查（Preflight），并在 Manifest 与兼容性矩阵中声明 Standards 精确版本和 Commit。它适合验证新版本的发现、锁定、文档生成、兼容性分析及受控升级能力。

其他工程不纳入本轮试点：

| 工程 | 本轮状态 | 后续处理 |
|---|---|---|
| AI-KB | OUT_OF_SCOPE | 当前仍在补齐标准要求（包括自动化测试治理）；完成自身基线后再单独评估 |
| VTIP | OUT_OF_SCOPE | 是否按新标准接入，留待后续 Owner 决策 |
| SideCar | OUT_OF_SCOPE | 是否按新标准接入，留待后续 Owner 决策 |

本指南不对上述工程的当前兼容性作出结论，不创建升级承诺，也不要求重分类其历史文档。

## 2. AI-Hub 当前观测基线（只读 GitHub 事实）

| 项目 | 已核实值 | 证据与适用范围 |
|---|---|---|
| 仓库 | `xiefeifeihu/AI-Engineering-Hub` | GitHub 公共仓库 |
| 默认分支 | `main` | GitHub 仓库元数据 |
| 观测 Commit | `7ebf695d0998faf68539f1412aab8fbd41672fd5` | 2026-11-05 查询到的 main HEAD |
| 产品版本 | `v0.22.9` | `compatibility_matrix.yaml` 的 `platform_release_version` |
| Manifest Schema 版本 | `1.1.3` | `engineering-manifest.yaml` |
| Standards 版本 | `2.11.0` | Manifest 与兼容性矩阵 |
| Standards Tag | `v2.11.0` | Manifest |
| Standards Peeled Commit | `5e17c0ef560ab8abafe880b988d70f85f380a104` | Manifest 与兼容性矩阵 |
| 根目录 `standards.lock.json` | NOT_FOUND | 对该 main Commit 的 GitHub 文件查询返回 404 |
| `AGENTS.md` | 存在固定版本/Commit 文本 | 当前 main 的文件正文 |
| Standards Preflight | 存在 | `scripts/agent/preflight.py` |

**解释与限制：**

1. 上表是指定 GitHub main Commit 的只读观测，不代表用户本机工作树、其他分支、运行时或生产部署状态。
2. AI-Hub 目前通过 `engineering-manifest.yaml` 和 `compatibility_matrix.yaml` 声明 Standards 2.11.0；尚未采用 v3.0.0 的四元组 `standards.lock.json` 契约。
3. `AGENTS.md` 当前仍包含 2.11.0 与 Commit 的固定文字；试点需评估如何改为引用 Manifest/Lock，而不是将浮动版本写死在规则正文。
4. 以上差异是试点输入，不是 AI-Hub 当前不合规或生产故障的结论。

## 3. 试点目标与禁止范围

### 3.1 目标

- 验证 AI-Hub 能否通过官方共享仓库引用 Standards 工具、Schema 与模板，不复制分叉公共实现。
- 验证 `standards.lock.json` 与 AI-Hub Manifest、兼容性矩阵的字段关系。
- 验证官方最新正式 Tag 发现、Tag Object SHA、Peeled Commit、VERSION 与 main 祖先链核验。
- 验证从 2.11.0 到 v3.0.0 的 Schema/规范差异和 AI-Hub 专属兼容性分析。
- 验证 AI-Hub 的文档模板、`docs/当前权威基线.md`、交接文档及文档集合校验。
- 验证 Windows/Linux CI、AI-Hub 自有测试、发布门禁及必要的业务回归。
- 验证失败时保持旧锁定，不产生半升级；回滚必须恢复原四元组。

### 3.2 禁止范围

- 不修改 AI-Hub 业务代码、运行时配置或生产部署。
- 不改变 Hub 已批准的产品/架构/API 决策。
- 不修改 AI-KB、VTIP、SideCar。
- 不把 AI-Hub 的试点通过解释为其他工程兼容。
- 不因 Standards 测试失败而修改 Hub 断言或放宽 Standards 规范。
- 不在 v3.0.0 正式发布前将候选版本写入 Hub 正式锁定。

## 4. AI-Hub 试点执行阶段

### H1：只读基线复核

由 AI-Hub Owner/编码智能体在实际工作区重新核验：

- Git 仓库、分支、完整 HEAD、工作区状态；
- Manifest、compatibility matrix、AGENTS/CLAUDE 与 Preflight；
- 当前 Standards 本地引用目录、Tag 对象与 Peeled Commit；
- Hub 自有测试、CI、Build/Runtime 证据。

GitHub main 的历史快照不得替代执行时的本机事实。结果缺失时标记 `NOT_VERIFIABLE`。

### H2：共享工具接入候选

推荐优先使用固定 Commit 的 Git 子模块（路径建议 `.standards/`），也允许现有受控共享检出目录通过 `AI_ENGINEERING_STANDARDS_ROOT` 引用。两种方式都必须满足：

- 只引用官方仓库；
- 执行时检出 `standards.lock.json` 指定的精确 Tag/Commit；
- 不复制公共脚本、Schema 或 Standards 正文；
- CI 中显式检出相同的精确版本；
- 子模块 Gitlink/实际 HEAD 与锁定 `peeled_commit` 一致。

### H3：文档与 Preflight 适配候选

- 新增/补齐 AI-Hub 的 `standards.lock.json`；
- 评估 Manifest 的 Standards 字段与锁文件如何保持单一事实源；
- 更新 Preflight，使其验证四元组和本地共享工具实际 Commit；
- 将 AGENTS/CLAUDE 中固定版本说明改为引用正式 Lock/Manifest；
- 从 Standards 模板创建缺失文档；基线和交接文件由官方生成器生成；
- 不删除或重写 Hub 历史文档，任何类型映射必须按真实内容判断。

以上均是待 AI-Hub 任务批准的候选实施项，不在本 PR 中执行。

### H4：兼容性与真实回归

按以下维度分别执行并保存原始证据：

1. Manifest 与 Schema；
2. Standards Lock/Tag/VERSION；
3. AGENTS.md / CLAUDE.md / Preflight；
4. 12 类文档元数据及文档集合；
5. 基线生成与摘要；
6. 跨会话交接与历史快照不可覆盖；
7. Hub 单元/契约/集成测试；
8. Hub Windows/Linux CI；
9. 发布与安全门禁；
10. Hub API、浏览器和运行时业务回归（仅在任务明确要求且具备环境时）。

每个维度记录 Source Commit、Target Commit、执行命令、时间、退出码、原始证据和状态。测试门禁必须包含真实测试执行证据（`tests_collected >= 1`、`tests_passed >= 1`、`tests_failed == 0`、`tests_skipped >= 0`），分离 Job 绿色与测试真实执行两个概念，严禁空测试或全部跳过被认定为有效通过。未执行为 `NOT_RUN`；无法核验为 `NOT_VERIFIABLE`；任一必需维度未知时不得汇总为 `COMPATIBLE`。

### H5：受控晋升与回滚

只有在 v3.0.0 正式 Tag 已存在、官方 main CI 通过、AI-Hub 全部必需兼容性门禁通过、审批证据有效且 AI-Hub Owner 批准后，才允许更新 AI-Hub 的精确锁定。

升级前保存当前 2.11.0 四元组及工程 Manifest；升级与回滚采用应用级协同双文件写入与恢复机制（`execute_transactional_two_file_update`），在第二步写入或磁盘异常时自动执行一致性回滚，恢复失败时严格保留备份文件，支持中断检测与恢复，明确其非断电级硬件原子事务保证。升级失败时不得静默降级或覆盖历史证据，按 AI-Hub 的正式发布策略恢复旧锁定并重新验证。

## 5. Standards 侧验收标准

- 官方共享工具在独立消费端目录可调用，不依赖 AI-KB 或 Hub 的代码。
- 没有 Lock 时不回退固定历史版本；网络不可用时返回 `NOT_VERIFIABLE`。
- Fork/非官方 Remote、轻量 Tag、Tag Object/Peeled Commit/VERSION 不一致均阻断。
- 未执行的兼容性维度不标记 `COMPATIBLE`。
- 模板不包含固定的“最新版本”；必须由 `discover` 取得正式版本并填入。
- 基线/交接生成器不伪造 PASS 或审批状态。
- Ubuntu 与 Windows CI 均通过。
- 试点通过不自动授权修改或升级其他工程。

## 6. 后续决策

AI-Hub 试点完成后，由 Owner 根据独立验收报告评估该接入模式是否可复用；任何其他工程仍须由其 Owner 独立决定是否接入，不存在默认推广或自动加入。AI-KB、VTIP、SideCar 的接入时间、版本和迁移范围均保持未决；Standards 不得预先替这些工程作出批准。
