# STD-017: Git Release & Versioning Standard (Git 发布与版本治理规范)

```text
STANDARD_ID=STD-017
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=AI Engineering 平台下所有独立 Git 代码仓库
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
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
