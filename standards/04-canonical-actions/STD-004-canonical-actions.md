# STD-004: Canonical Action Standard (规范运维动作契约)

```text
STANDARD_ID=STD-004
VERSION=1.0.0
STATUS=ACTIVE
SCOPE=所有通过 AI-Hub 或 Windows Host Action Bridge 执行的运维控制指令
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-09-23
SCHEMA_REF=schemas/canonical-action.schema.json
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 规范动作集合定义

所有跨工程受控运维调用 **MUST** 限制在以下白名单规范动作之一：
- `start`: 启动服务或拉起隧道
- `stop`: 正常停止服务或释放隧道
- `restart`: 重启服务
- `status`: 查询当前服务运行态快照（只读无副作用）
- `test`: 快速连通性验证（只读，低延迟握手）

---

## 2. 安全与执行约束

1. **参数化注入防护 (No Shell Injection)**：
   所有动作执行 **MUST** 绑定预定义的固定脚本路径与子命令，**MUST NOT** 接受任意外部拼接参数执行。
2. **幂等性要求**：
   - 当服务已运行时执行 `start`，**SHOULD** 返回成功并标记已运行，不得崩溃或引发多进程冲突；
   - 当服务已停止时执行 `stop`，**SHOULD** 返回成功并安全退出。
3. **超时与隔离红线**：
   单次 Action 执行超时上限 **MUST NOT** 超过 30 秒；Action 执行日志 **MUST** 写入独立的审计记录。
