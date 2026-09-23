# STD-007: Credential Reference & Zero Secret Standard (凭据引用与零密钥安全规范)

```text
STANDARD_ID=STD-007
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=所有参与 AI 工程的仓库、Git 提交、日志输出、Manifest 与 Hub 注册表
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

## 1. 绝对零密钥入库红线 (Zero Secrets in Git)

1. **严禁明文入库**：
   代码仓库、Markdown 规范、Git 历史、Issue、Commit 信息及日志中，**MUST NOT** 出现任何真实明文 API Key、OAuth Token、私钥或密码。
2. **受控凭据存放目录**：
   所有包含敏感信息的本地配置文件（例如 `LocalConfig/`, `.env`）**MUST** 严格列入 `.gitignore`，且仅允许在宿主受控路径存放。

---

## 2. 凭据引用契约 (Credential Reference Contract)

工程清单与 Hub 注册表仅回答凭据的**元数据状态**，**MUST NOT** 返回凭据真实值：

```yaml
credential_references:
  - label: "CPA 本地网关 Token"
    env_var: "LOCAL_CPA_KEY"
    file_ref: "D:\AI-KB\LocalConfig\cpa\config.yaml"
    status_detector: "file_exists"
```

Hub 对外暴露的凭据状态仅允许为三态英文枚举：
- `CONFIGURED`: 经探测环境变量已声明或本地配置文件真实存在；
- `MISSING`: 声明了该凭据，但探测发现文件或变量缺失；
- `NONE`: 该服务属于本地免认证离线服务（如 Ollama），无需凭据。
