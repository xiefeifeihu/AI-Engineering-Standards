# STD-006: Port Governance Standard (端口治理规范)

```text
STANDARD_ID=STD-006
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=开发机 Windows 宿主、WSL2 与 Docker 容器向宿主映射的所有 TCP 端口
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

## 1. Windows 动态端口认知与预检红线

1. **禁止假设 Windows 动态端口固定不变**：
   Windows 系统的动态端口范围（Dynamic Port Range）和保留/排除端口范围（Excluded Port Range）受 Hyper-V、WSL2、NAT 及系统策略动态分配。
2. **机器级预检要求**：
   任何工程在固定新端口前，**MUST** 实际运行以下命令排查：
   ```powershell
   netsh int ipv4 show dynamicport tcp
   netsh int ipv4 show excludedportrange tcp
   Get-NetTCPConnection -LocalPort <TARGET_PORT> -ErrorAction SilentlyContinue
   ```
   严禁将已列入 excluded port range 的端口配置为静态绑定。

---

## 2. 18000-19999 机器级工程约定网段

`18000-19999` 是本 AI 开发环境约定的机器级保留规划段（非 IANA 官方注册段，属于工程自律约定）：

| 端口范围 | 规划职能 | 现有稳定分配实例 | 约束原则 |
| :--- | :--- | :--- | :--- |
| **18000 - 18099** | 应用入口 / Web 控制台 | `18080` (RAGFlow Web), `18090` (AI-KB Control) | 仅供业务系统 Web UI 暴露 |
| **18100 - 18199** | 本地 AI 推理网关 / 代理 | `18117` (Local CPA 网关) | 境内高速低时延推理代理 |
| **18300 - 18399** | 云端按需隧道 / 出站代理 | `18317` (Cloud CPA 隧道, 候选: 18318-18320) | 按需加密隧道专用 |
| **18700 - 18799** | 宿主桥接 / Agent 扩展 | `18787` (Host Action Bridge) | 宿主与容器隔离桥接通信 |
| **18800 - 18999** | 监控 / 诊断 / 测试入口 | 验收与测试用临时端口 | 测试完成后必须释放 |
| **19000 - 19999** | 未来扩展示例保留 | 保留备用 | 需由架构评审后分配 |

---

## 3. 历史稳定端口保护原则

以下已稳定运行的核心端口 **MUST NOT** 为追求数字对齐而进行无意义迁移：
- **Port 80**: `AI-Engineering-Hub`（机器级统一门户）
- **Port 11434**: `Ollama`（本地离线模型原生默认端口）
- **Port 8799**: `VTIP-AI-SIDECAR`（已稳定接入的业务 Sidecar 端口）
- **Port 18080 / 18090**: `RAGFlow` / `AI-KB Control`
