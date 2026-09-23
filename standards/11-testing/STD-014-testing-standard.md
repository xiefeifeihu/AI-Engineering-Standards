# STD-014: Testing Standard (跨项目分层测试规范)

```text
STANDARD_ID=STD-014
VERSION=1.1.0
STATUS=ACTIVE
SCOPE=AI-Engineering-Standards、AI-Engineering-Hub 及跨工程自动化测试
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

## 1. 分层测试体系要求

1. **非破坏性原则 (Non-Destructive Testing)**：
   测试用例 **MUST NOT** 调用破坏性清空命令，**MUST NOT** 删除真实数据集或清空历史有效审计日志。
2. **Standards 仓库测试**：
   必须包含自动化 Schema 校验脚本（`tools/validate-schemas.py`），对所有 9 个 Schema 进行有效性与边界样例回归测试。
3. **Hub 仓库测试**：
   包含针对性单元测试、API 集成测试与端到端 Playwright UI 验收测试。

---

## 2. 四层测试矩阵 (Four-Level Testing Matrix)

所有 AI 工程仓库 **MUST** 实现以下四层测试，并按顺序执行：

| 层级 | 名称 | 触发时机 | 工具 | 目标 |
|------|------|----------|------|------|
| **L1 - SMOKE** | 冒烟测试 | 每次提交 | pytest / shell | 核心路径可用性验证（< 30s）|
| **L2 - CORE** | 核心回归 | 每次 PR / 里程碑 | pytest | 所有单元 + API 集成（< 5min）|
| **L3 - DEEP** | 深度验收 | 里程碑发布前 | pytest + Playwright | 端到端 UI 验收、主题、截图（< 15min）|
| **L4 - DIAGNOSTIC** | 诊断探针 | 按需/生产巡检 | 自定义脚本 | 健康探针、性能基线、Schema 合规 |

### L1 - SMOKE 冒烟测试约束
- **MUST** 在 < 30 秒内完成。
- **MUST** 只测试应用启动、核心路由可达性和关键配置加载。
- **MUST NOT** 依赖外部网络或真实 AI 服务。

### L2 - CORE 核心回归约束
- **MUST** 覆盖所有业务逻辑单元（模型路由、资源注册、健康判定等）。
- **MUST** 包含 API 契约合规测试（按 STD-009、STD-010 等）。
- **MUST NOT** 运行 Playwright 浏览器用例（保留给 L3）。

### L3 - DEEP 深度验收约束
- **MUST** 使用 Playwright Headless 模式运行（参见 STD-015）。
- **MUST** 生成截图和视频证据，输出到 `.artifacts/acceptance/<TASK>/<VERSION>/`。
- **MUST** 覆盖明亮/暗黑双主题。
- **MUST NOT** 在日常 CI 中自动触发，仅在里程碑发布前手动或定时触发。

### L4 - DIAGNOSTIC 诊断探针约束
- **MUST** 包含 Schema 合规校验（`tools/validate-schemas.py`）。
- **MUST** 报告模型健康状态与 KPI 指标基线。
- **MAY** 包含性能回归测试。

---

## 3. 测试输出与证据规范

1. 所有测试输出 **MUST** 输出到 `.artifacts/acceptance/<TASK>/<VERSION>/logs/`。
2. Playwright 截图 **MUST** 存放于 `.artifacts/acceptance/<TASK>/<VERSION>/screenshots/`。
3. Playwright 视频 **MUST** 存放于 `.artifacts/acceptance/<TASK>/<VERSION>/videos/`。
4. 测试日志 **MUST NOT** 提交到 Git（受 `.gitignore` 排除）。

---

## 4. 失败处理规范

1. 任何层级测试失败 **MUST** 阻断发布流程。
2. 失败报告 **MUST** 包含：失败测试名称、错误信息、复现步骤。
3. **MUST NOT** 跳过或注释失败测试来强制通过，必须修复根本原因。