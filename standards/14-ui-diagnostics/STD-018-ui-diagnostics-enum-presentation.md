# STD-018: UI Diagnostics & Enum Presentation Standard (UI 诊断与枚举呈现规范)

```text
STANDARD_ID=STD-018
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=面向人类工程师的所有前端页面、看板与终端诊断输出
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

## 1. 契约与人类界面的语言解耦

1. **API / 存储层：稳定英文常量**：
   REST API、JSON Schema、数据库字段中 **MUST** 使用大写英文字符串常量枚举（例如 `ALWAYS_ON`, `ON_DEMAND`, `HEALTHY`, `QUARANTINED`, `NONE`, `LOW`, `HIGH`）。
2. **人类视图层：纯简体中文呈现**：
   所有面向人类的 Web 界面、弹窗、表格、Tooltip 与状态 Badge **MUST NOT** 直接显示未翻译的内部英文枚举，**MUST** 翻译为对应的标准简体中文。

---

## 2. 标准枚举映射基准表

| 英文常量枚举 | 规定简体中文展示 | 适用场景 |
| :--- | :--- | :--- |
| `ALWAYS_ON` | **常驻服务** | 资源生命周期策略 |
| `ON_DEMAND` | **按需服务** | 资源生命周期策略 |
| `MANUAL` | **手动管理** | 资源生命周期策略 |
| `EXTERNAL` | **外部管理** | 资源生命周期策略 |
| `RUNNING` | **运行中** | 期望 / 实际运行状态 |
| `STOPPED` | **已停止** / **待命** | 期望 / 实际运行状态 |
| `READY` | **就绪** | 业务健康状态 |
| `AVAILABLE` | **可用** | 端口连通状态 |
| `OFFLINE` | **离线** | 服务未启动 |
| `HEALTHY` | **健康** | 模型治理状态 |
| `DEGRADED` | **已降权** | 模型降级状态 |
| `QUARANTINED`| **已熔断** | 熔断静默状态 |
| `RECOVERING` | **恢复中** | 试探探测状态 |
| `NONE` | **暂无数据** | 冷启动置信度 / 成功率空值 |
| `LOW` | **低** | 样本置信度 |
| `MEDIUM` | **中** | 样本置信度 |
| `HIGH` | **高** | 样本置信度 |
