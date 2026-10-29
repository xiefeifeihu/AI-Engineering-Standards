# STD-017: Git Release & Versioning Standard (Git 发布与版本治理规范)

```text
STANDARD_ID=STD-017
VERSION=2.10.0
STATUS=ACTIVE
SCOPE=AI Engineering 平台下所有独立 Git 代码仓库
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-29
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 独立仓库与提交隔离

1. **严禁跨 Repo 混合 Commit**：
   `AI-Engineering-Standards` 与 `AI-Engineering-Hub` 是两个独立的 Git 仓库，拥有完全独立的 commit 历史、分支与远程 origin。
2. **干净工作区交付**：
   阶段验收结束时，每个仓库的工作区 **MUST** 保持 clean 状态。

---

## 2. 语义化版本控制 (Semantic Versioning)

版本号严格采用 `MAJOR.MINOR.PATCH` 规范：
- `MAJOR`: 重大架构突破或破坏性变更
- `MINOR`: 新增兼容功能、规范扩展或功能升级
- `PATCH`: 向后兼容的缺陷修复与 Conformance Patch

---

## 3. 正式发布 Tag 独立核验闭环 (Post-Tag Verification)

正式 Release Tag 必须在生产验收完全确认 PASS 后创建并推送至远端仓库。Tag 创建后，流水线必须执行独立的 `git rev-parse` 与远端标签核验，确保：
```text
TAG_COMMIT == LIVE_COMMIT == REMOTE_HEAD
```
在 PERSONAL_LOCAL 启用 AUTO_AFTER_GREEN 自动化发布模式时，正式 Release Tag 亦由受控执行器在 Stage 10 冒烟验证与 Stage 11 验收完全确认 PASS 后自动创建并推送，并执行独立的五态一致性核验闭环；严禁在冒烟未通过或任一前置门禁未满足时提前打标或推送 Tag。
严禁在仅完成本地标签创建而未推送到远端或未完成独立核验时宣布发布完成。


---

## 4. 无强制 PR 的 main 发布策略

1. 正式 Standards **不再要求先创建或合并 PR**。项目可在受控工作区直接向 main 提交；已配置的 GitHub 分支保护与人员权限仍必须遵守，严禁强推或绕过。
2. 远端 main 最新精确 Commit 与目标 Commit 一致，且绑定该 Commit 的远端 GitHub Actions CI **实际成功**，方可进入发布审批与生产部署。功能分支测试不能冒充 main CI。
3. 发布前 Stage 1 全绿仅代表候选可部署；部署后 Stage 2 在当前 LIVE_COMMIT 上的真实用户旅程自动化验收 PASS 才能形成最终生产裁决；然后打 Tag 并远端核验。
4. NON_RUNTIME_ARTIFACT 工程（如规范仓库）必须声明其不具有线上服务，使用真实主分支版本制品与 Schema/消费端契约验收，不得伪造生产服务测试。
