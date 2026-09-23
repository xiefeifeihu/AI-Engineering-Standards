# STD-015: Playwright Acceptance Standard (Playwright 界面验收规范)

```text
STANDARD_ID=STD-015
VERSION=1.1.0
STATUS=ACTIVE
SCOPE=所有 Web UI 控制台的自动化回归与验收
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

## 1. 运行模式定义 (Execution Modes)

Playwright 验收测试 **MUST** 明确声明运行模式，三种模式各有约束：

| 模式 | 说明 | Headless | 截图 | 视频 | 触发时机 |
|------|------|----------|------|------|----------|
| **AUTOMATED_TEST** | 日常自动化回归（L2 CORE） | **MUST** Headless | 仅失败时 | 否 | 每次 PR |
| **ACCEPTANCE** | 里程碑验收（L3 DEEP） | **MUST** Headless | **MUST** 全程截图 | **MUST** 全程录制 | 里程碑前 |
| **DEMO** | 演示/展示（有界面） | **MUST NOT** Headless | **SHOULD** 截图 | **SHOULD** 录制 | 按需 |

## 2. ACCEPTANCE 模式约束

1. **Headless 强制运行**：
   ACCEPTANCE 模式 **MUST** 使用 `--headed=false` 运行，**MUST NOT** 依赖本地显示器。
2. **证据目录**：
   截图和视频 **MUST** 输出到 `.artifacts/acceptance/<TASK-ID>/<VERSION>/`（参见 STD-019）。
3. **多主题验证**：
   **MUST** 覆盖明亮模式（Light）与暗黑模式（Dark）切换，切换过程中无 FOUC 闪烁。
4. **关键业务场景验证矩阵**：
   - 验证 Local CPA 常驻服务展示与期望状态；
   - 验证 Cloud CPA 按需服务展示与待命状态；
   - 验证 0 调用次数模型成功率与延迟显示「暂无数据」；
   - 验证 Candidate Plan 模型多样性与通道容灾标记；
   - 验证纯文本任务排除视觉模型；
   - 验证所有状态枚举完全中文化呈现；
   - **验证 KPI 卡片数值与点击跳转行为（按需资源、运行中）**。

## 3. DEMO 模式约束

1. **Headed 强制运行**：
   DEMO 模式 **MUST** 使用 `--headed=true`，以可视化界面展示真实交互效果。
2. **演示录屏存储**：
   录屏 **SHOULD** 存放于 `.artifacts/demo/`，**MUST NOT** 提交到 Git。
3. **禁止自动操作**：
   DEMO 模式测试 **SHOULD NOT** 包含破坏性操作或数据写入。

## 4. 证据完整性要求

1. 每次 ACCEPTANCE 运行 **MUST** 生成 `manifest.json`，包含：运行时间、Playwright 版本、浏览器版本、测试结果摘要。
2. 证据包 **MUST** 通过 `scripts/package_acceptance.py` 打包（参见 STD-016）。