# STD-032 v2.10.0 迁移指南：无强制 PR 与生产双阶段验收

正式版本的发布和工程过程不再要求 PR；不允许使用功能分支测试代替远端 main Commit 对应的真实 GitHub Actions CI。若当前仓库已有 GitHub 分支保护禁止直推，应遵守现有规则，不得暴力覆盖、关闭强制检查或代替仓库管理员修改保护策略。

## 开发及发布

1. 先核实 Git 状态、产品基线、规范版本，必要时使用独立开发分支进行候选测试，保留回退空间。
2. 在确认 GitHub main 推送权限与无未保存工作区变更后，可直接更新 main，取消强制创建/合并 PR。
3. 远端 main 上的完整 40 位 Commit 和绑定该 Commit 的远端 CI 必须取证成功。
4. AUTO_AFTER_GREEN 的十项机器门禁完整保留，只将 PR_MERGED 更名为 MAIN_COMMIT_VERIFIED。
5. 受控本地部署必须执行备份、隔离恢复、旧版回滚核验、运行时身份核验。只有双阶段最终通过才能创建和核验 Tag。
6. HIGH_ASSURANCE 仍要求其真实独立审批与受保护密钥/Environment 验证，取消 PR 不意味着取消独立授权或审计。

## 两阶段验收

- PRE_RELEASE_QUALIFICATION（发布前）：单元、契约、集成、候选 UI/Playwright、安全及可回滚性，目标只是允许部署，不证明生产业务可用。
- POST_DEPLOY_REAL_ACCEPTANCE（部署后）：针对当前 LIVE_COMMIT 的真实生产入口，执行真实浏览器、API、依赖与核心业务任务，断言实际输出和数据效果。必须覆盖正式产品基线中的关键用户旅程，记录真实 Run ID、时间、版本身份及原始证据。
- 第二阶段失败/未知即禁止声明整体 PASS，且禁止正式 Tag；应有安全回滚或问题修复闭环。第一阶段不通过也禁止部署。
- 测试仅等同覆盖过的真实用户交互；未覆盖的业务验收、主观人工采纳和高风险写入仍须标明未验证。
- NON_RUNTIME_ARTIFACT（Standards/文档规范）以发布制品身份和实际 Schema/消费契约测试为验收依据，不得假造线上服务 E2E。

## 关键 Schema

- release-approval-policy.schema.json：新策略 schema_version 1.2.0；采用 MAIN_COMMIT_VERIFIED。
- release-authorization-evidence.schema.json：新自动发布证据 schema_version 1.1.0；保留十项真实门禁。
- two-stage-release-acceptance.schema.json：双阶段原始结果结构。
- tools/validate_two_stage_release.py：校验 Commit/Tag/Live 一致性、后置测试时序和关键旅程覆盖。

## 四工程真实验收最低要求

- AI-Hub：真实 CPA/Ollama、模型调用与限流/额度、免费资源查询、三视角拓扑真实点击、资源入库与状态。
- AI-KB：RAGFlow 实际非空检索、文档证据、知识提炼效果、网络/额度异常（只读、无明文凭据）。
- SideCar：真实日报润色、事实防腐、业务结构，Confluence 的真实只读链路，不能仅通过 HTTP 200 认定质量。
- VTIP：真实 Jira/Confluence 只读、计划日期和工时、工作日历与实际页面；无授权不执行写入。

历史 PR、Tag、分支、ZIP 和证据保留，当前任务只升级后续规范与验证逻辑，不得因清理 PR 机制而丢失历史代码或证据。
