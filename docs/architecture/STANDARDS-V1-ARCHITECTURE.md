# AI Engineering Standards V1.0 架构总览与基线规范体系

```text
DOCUMENT_ID=ARCH-STANDARDS-V1-001
VERSION=1.0.0
STATUS=ACTIVE
AUTHOR=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
```

---

## 1. 规范体系全景图

AI Engineering Standards 是本机跨工程（AI-KB、VTIP、VTIP-AI-SIDECAR、AI-Engineering-Hub）共享的架构规范与契约中心（Source of Truth）。

```text
AI-Engineering-Standards (V1.0.0 基线)
├── VERSION & CHANGELOG.md (语义化版本与发布记录)
├── standards/ (18 项正式规范)
│   ├── 00-governance/           -> STD-001 清单规范, STD-002 资源所有权
│   ├── 03-endpoint-registry/    -> STD-003 端点注册与拓扑映射
│   ├── 04-canonical-actions/    -> STD-004 规范运维动作契约
│   ├── 05-health-status/        -> STD-005 递进式健康模型与四类生命周期
│   ├── 06-port-governance/      -> STD-006 端口治理 (18000-19999 机器级约定)
│   ├── 07-credential-security/  -> STD-007 凭据引用与零密钥安全
│   ├── 08-model-governance/     -> STD-008 模型注册, STD-009 路由, STD-010 反馈, STD-011 消费
│   ├── 09-observability/        -> STD-013 统一审计日志
│   ├── 10-runtime-boundary/     -> STD-012 Windows/WSL/Docker 运行时边界
│   ├── 11-testing/              -> STD-014 跨项目分层测试
│   ├── 12-acceptance/           -> STD-015 Playwright 验收, STD-016 验收包
│   ├── 13-git-release/          -> STD-017 独立 Git 发布规范
│   └── 14-ui-diagnostics/       -> STD-018 UI 诊断与中文枚举呈现
├── schemas/ (9 项 Machine-readable JSON Schema)
│   ├── engineering-manifest.schema.json
│   ├── resource.schema.json
│   ├── endpoint.schema.json
│   ├── canonical-action.schema.json
│   ├── model-registry.schema.json
│   ├── model-routing-request.schema.json
│   ├── model-routing-response.schema.json
│   ├── model-feedback.schema.json
│   └── audit-event.schema.json
├── handoff/ (跨项目长期会话交接)
│   ├── AI-KB-Model-Governance-Integration-Handoff.md
│   ├── Sidecar-Model-Governance-Integration-Handoff.md
│   └── VTIP-Model-Governance-Architecture-Handoff.md
├── deprecated/ (已废弃路径与兼容存档)
│   └── CLOUD-CPA-TUNNEL-DEPRECATED.md
└── tools/
    ├── validate-schemas.py      (Schema 自动化自检回归套件)
    └── check-shared-inference.py (三层推理资源轻量探测工具)
```

---

## 2. 事实优先级法则

1. **当前 Runtime（运行态真实状态）**
2. **Owner Repo 当前代码（所有者仓库源码实现）**
3. **Owner Manifest（所有者声明清单 `engineering-manifest.yaml`）**
4. **Hub Runtime Registry（AI-Hub 运行时动态注册表）**
5. **Git 历史提交记录**
6. **Standards（跨工程规范库）**
7. **旧聊天与历史会话记录**

Standards 库负责提供 Contract 与边界约束，但**绝不能反向强迫真实正确的 Runtime 倒退适配过期的静态文档**。
