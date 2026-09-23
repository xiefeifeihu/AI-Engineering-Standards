# [DEPRECATED] Cloud CPA 隧道旧管理脚本路径说明

```text
STATUS=DEPRECATED
REPLACEMENT=scripts/cpa/cloud-cpa-tunnel.cmd
EFFECTIVE_DATE=2026-08-15
TARGET_REPO=D:\AI-KB\Repo\ai-kb-infra
```

---

## 1. 废弃背景

早期工程规划中，Cloud CPA 隧道管理脚本曾暂存或规划于：
- `scripts/tunnel/cloud-cpa-tunnel.cmd`
- `scripts/tunnel/cloud-cpa-tunnel.sh`

随着 `ai-kb-infra` 基础设施规范化，CPA 本地代理与云端隧道统一收敛至 `scripts/cpa/` 目录下集中管控。

---

## 2. 替代路径与当前 Ground Truth

| 属性 | 废弃路径 (DEPRECATED) | 正式 Canonical 路径 (ACTIVE) |
| :--- | :--- | :--- |
| **脚本路径** | `scripts/tunnel/cloud-cpa-tunnel.cmd` | `scripts/cpa/cloud-cpa-tunnel.cmd` |
| **所属仓库** | `ai-kb-infra` | `ai-kb-infra` (`D:\AI-KB\Repo\ai-kb-infra`) |
| **宿主端口** | `127.0.0.1:18317` | `127.0.0.1:18317` (容错候选: 18318, 18319, 18320) |
| **远端拓扑** | SSH 端口转发至 VPS `127.0.0.1:8317` | SSH 端口转发至 VPS `127.0.0.1:8317` |
| **动作支持** | `start`, `stop`, `status` | `start`, `stop`, `restart`, `status`, `test` |

---

## 3. 跨工程迁移指引

1. 任何工程文档、AI 提示词或自动化脚本中，若出现 `scripts/tunnel/cloud-cpa-tunnel.cmd`，一律替换为 `scripts/cpa/cloud-cpa-tunnel.cmd`；
2. 任何消费者系统（包括 AI-Engineering-Hub、VTIP-AI-SIDECAR、VTIP）严禁在自身仓库复制代码，必须通过 Canonical Action 或宿主桥接调用。
