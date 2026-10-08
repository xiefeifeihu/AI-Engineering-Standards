# STD-025: Owner Action Execution Contract (资源拥有者动作执行契约规范)

```text
STANDARD_ID=STD-025
VERSION=1.7.0
STATUS=ACTIVE
SCOPE=Model Ops Owner Action 执行平面规范：控制平面决策、Resource Owner 校验执行、独占租约、幂等恢复、零敏感凭据、事实结果与 Hub 独立验证
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-07
RELATED_STANDARDS=STD-004, STD-007, STD-008, STD-012, STD-013, STD-014, STD-019, STD-020, STD-024
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 架构目标与双平面所有权原则 (Architectural Principles & Hard Boundary)

在 AI 平台架构演进中，Model Ops 运维自治进入 R2 阶段（执行平面）。系统必须严格遵守“控制平面与资源拥有者执行平面双边界物理隔离”原则：

### 1.1 角色与职责严格划分
- **AI-Engineering-Hub = 控制平面 (Control Plane)**：
  - 负责运行期观测（Observe）、自愈与挑战推荐（Recommend）、动作请求创建（Request）、人工审批把关（Approval）、发放执行租约（Lease Dispatch）、结果摄入（Result Ingest）、独立效果验证（Independent Verification）与生命周期闭环评估（Close Loop）。
  - **Hub 绝对禁令（Hub Invariants）**：
    - Hub **MUST NOT** 直接调用 `docker` 命令或操作客户端容器。
    - Hub **MUST NOT** 直接执行 `ollama pull`、`ollama rm` 等底层模型操作。
    - Hub **MUST NOT** 直接修改 AI-KB 仓库下的 Compose 文件或配置清单。
    - Hub **MUST NOT** 直接启停或重启 CPA 容器服务。
    - Hub **MUST NOT** 直接管理 Cloud CPA 的本地 SSH 隧道守护进程。
    - Hub **MUST NOT** SSH 登录远程 VPS 服务器执行基建变更。
    - Hub **MUST NOT** 修改或持有机器级所有者原始凭据（API Keys / SSH 私钥 / 密码）。
- **AI-KB = 资源拥有者与执行平面 (Resource Owner + Execution Plane)**：
  - 负责真实物理资源的合法持有、安全防护与执行调度。
  - 负责从 Hub 消费已审批的 Owner Action，校验资源归属（`owner == "AI-KB"`）与动作合法性。
  - 获取独占执行锁，映射调用本地已有权威生命周期脚本（如 `ops/cpa/local_cpa.py`、`ops/cpa/cloud_cpa_tunnel.py`、Ollama 本地接口）。
  - 采集非敏感执行事实并回传执行结果。
  - **AI-KB 执行器禁令**：AI-KB 执行器 **MUST NOT** 自行决定模型在 Hub 侧的生命周期晋升状态。

### 1.2 规范执行闭环时序 (Canonical End-to-End Flow)
任何运维动作 **MUST** 遵循以下严格递进时序，严禁跳步或折叠：
```text
OBSERVE
  ???> RECOMMEND
        ???> OWNER_ACTION_REQUEST
              ???> APPROVAL
                    ???> OWNER_ACK
                          ???> EXECUTION_LEASE
                                ???> OWNER_EXECUTION
                                      ???> OWNER_RESULT
                                            ???> HUB_REDISCOVERY
                                                  ???> HUB_CAPABILITY_PROBE
                                                        ???> VERIFY
                                                              ???> ACTION_COMPLETED | ACTION_FAILED
                                                                    ???> LIFECYCLE_REEVALUATION
```

---

## 2. 动作安全分类与白名单矩阵 (Action Safety Classification & Matrix)

为确保高危操作可控，平台所有 Owner Action **MUST** 进行确定性安全分级：

| 动作类型 (`action_type`) | 安全级别 (`safety_class`) | 默认执行模式 | 准入前置条件 | R2 活体准入状态 |
| :--- | :--- | :--- | :--- | :--- |
| `CPA_RESTART` | `REVERSIBLE_OPERATIONAL` | `APPROVAL_REQUIRED` | 目标 CPA 实例健康检查完成，无冲突锁 | **LIVE 启用** (R2 首选验收动作) |
| `CPA_CANARY_UPGRADE` | `HIGH_RISK_CHANGE` | `APPROVAL_REQUIRED` | 具备候选版本镜像、回滚预案与配置校验 | **实现但 LIVE 默认禁用** |
| `CPA_ROLLBACK` | `HIGH_RISK_RECOVERY` | `APPROVAL_REQUIRED` | 必须具备明确有效的历史部署凭证 (Provenance) | **实现但 LIVE 默认禁用** |
| `OLLAMA_PULL_MODEL` | `RESOURCE_MUTATION` | `APPROVAL_REQUIRED` | 必须完成磁盘可用空间与显存容量 Preflight 检查 | **实现但 LIVE 需显式审批** |
| `OLLAMA_REMOVE_MODEL` | `DESTRUCTIVE` | `DISABLED` | 严格禁止静默删除模型；生产默认阻断 | **LIVE 严格禁用** |
| `CPA_REGISTER_MODEL_ROUTE` | `RESOURCE_MUTATION` | `APPROVAL_REQUIRED` / `POLICY_PREAUTHORIZED` | 仅限已审批供应商追加模型路由，具备快照与回滚 | **LIVE 启用** (支持 STD-028 预授权安全自接入) |
| `CPA_DISABLE_MODEL_ROUTE` | `RESOURCE_MUTATION` | `APPROVAL_REQUIRED` / `POLICY_PREAUTHORIZED` | 禁用指定模型路由，不破坏其他模型与容器 | **LIVE 启用** |
| `CPA_REFRESH_MODEL_CATALOG` | `REVERSIBLE_OPERATIONAL` | `POLICY_PREAUTHORIZED` | 重新拉取上游目录，只读无损 | **LIVE 启用** |

---

## 3. 确定性执行状态机 (Deterministic State Machine)

动作请求生命周期必须遵循以下 14 个确定性状态：

### 3.1 状态枚举与操作语义
1. `REQUESTED`：Hub 或运维人员创建动作请求，初始持久化完成。
2. `APPROVAL_REQUIRED`：请求处于待审批状态，必须等待有权限的操作人员明确审批。
3. `APPROVED`：操作人员通过界面或授权 API 确认批准执行。
4. `ACKNOWLEDGED`：AI-KB 资源拥有者收到并确认（ACK）了该已审批动作。
5. `LEASED`：Hub 控制平面向 AI-KB 执行器派发独占执行租约（携带 lease_id 与有效时限）。
6. `EXECUTING`：AI-KB 执行器正式调用底层脚本或服务，处于真实执行中。
7. `EXECUTION_SUCCEEDED`：底层执行脚本返回码为 0，事实采集完毕并回传给 Hub。
8. `EXECUTION_FAILED`：底层执行失败、返回非 0 退出码或执行超时。
9. `VERIFYING`：Hub 收到成功结果，启动独立重发现与分级能力探测。
10. `VERIFIED`：Hub 独立验证完全通过（端口通、模型可发现、L1 探针成功、智能体契约未降级）。
11. `COMPLETED`：动作闭环圆满完成（最终终态）。
12. `REJECTED`：审批阶段被人工明确驳回，或因校验违规被系统拒绝。
13. `EXPIRED`：租约超时未完成或执行响应超时。
14. `CANCELLED`：在执行开始前由操作人员主动撤销。

### 3.2 核心防伪定则 (Verification Non-Equivalence Invariant)
- **铁律：`OWNER_EXECUTION_SUCCEEDED != ACTION_COMPLETED`**。
- 执行器命令退出码为 0 仅代表宿主操作完成（如容器重启命令成功发出），绝不代表业务可用性恢复。
- 只有 Hub 独立完成网络连通性探测、资源自发现刷新、能力探针验证后，才能迁移至 `VERIFIED` 并标记为 `COMPLETED`。

### 3.3 状态迁移审计记录 (Immutable Transition Record)
每次状态流转 **MUST** 产生一条不可箭改的审计记录：
```json
{
  "record_type": "OWNER_ACTION_TRANSITION",
  "transition_id": "trans-act-20261007-001",
  "request_id": "act-req-20261007-001",
  "from_status": "APPROVED",
  "to_status": "LEASED",
  "actor": "hub-lease-dispatcher",
  "reason_code": "LEASE_GRANTED",
  "evidence_ref": "lease-aikb-cpa-001",
  "attempt": 1,
  "transitioned_at": "2026-10-07T09:30:00Z"
}
```

---

## 4. 动作唯一标识与单一效果不变式 (Identity & Idempotency)

### 4.1 动作完整身份要素
每个 Owner Action 实例 **MUST** 具备以下元数据：
- `request_id`：全局唯一请求标识（如 `act-req-timestamp-uuid`）。
- `action_type`：白名单动作枚举。
- `safety_class`：安全分级枚举。
- `target_resource`：目标资源唯一标识（如 `local-cpa`、`cloud-cpa-tunnel`、`ollama`）。
- `owner`：资源归属者，强制为 `"AI-KB"`。
- `requested_by`：发起方身份。
- `requested_at`：ISO 8601 UTC 时间戳。
- `approval_state`：审批状态（`PENDING_APPROVAL`, `APPROVED`, `REJECTED`, `AUTO_BYPASSED`）。
- `idempotency_key`：幂等键，防止重复提交。
- `execution_mode`：执行模式（`APPROVAL_REQUIRED`, `DRY_RUN`, `DISABLED`）。
- `lease_id`：当前租约标识（未出租时为 null）。
- `executor_id`：当前执行器标识（如 `"aikb-owner-executor"`）。
- `attempt`：当前尝试序号（>= 1）。
- `status`：当前规范状态。
- `reason_code`：机器可读原因代码。
- `reason_cn`：可读原因描述。
- `parameters`：参数白名单对象。
- `credential_ref`：逻辑凭据标识（若需）。
- `evidence_ref`：事实证明引用。

### 4.2 单一效果不变式 (One Request ID, One Effect)
- **不变式**：`ONE_REQUEST_ID_ONE_EFFECT=true`。
- 重复投递同一 `request_id` 或相同 `idempotency_key` 时，系统必须返回既有状态或幂等确认，绝不得重复触发底层真实变更。

---

## 5. 执行租约与并发互斥安全 (Execution Lease & Concurrency Guard)

为防止分布式并发与重复执行，系统 **MUST** 实施租约机制：
1. **租约要素**：
   - `lease_id`：租约唯一标识。
   - `request_id`：关联动作请求标识。
   - `executor_id`：被授权执行器。
   - `target_resource`：锁定目标资源。
   - `leased_at`：租约起始时间。
   - `lease_expires_at`：租约过期时间（默认 120 秒）。
   - `attempt`：执行尝试代号。
2. **目标资源并发互斥 (Resource Serialization)**：
   - 对同一个物理资源（如 `local-cpa`），任何时刻只允许存在一个活跃的执行租约。
   - 对同类相斥动作（如同时对同一 Ollama 模型触发 `pull` 和 `remove`），必须排队等待，严禁交错执行。
3. **租约超时与安全夺回**：
   - 若租约超时（`now > lease_expires_at`）且执行器未汇报心跳或结果，租约状态置为 `EXPIRED`。
   - 系统可经过重试判定由新租约接管，旧租约提交的滞后结果必须予以拒绝。

---

## 6. 零敏感信息与凭据边界 (Zero-Secrets & Credential Boundary)

遵循 STD-007 与 STD-024 铁律：
1. **凭据仅传引用**：Hub **MUST NOT** 持有或传递 API Key、Token、密码、SSH 私钥。仅允许传递逻辑标识符（`credential_ref: "LOCAL_CPA_KEY"`）。
2. **本地解析凭据**：AI-KB 执行器依据 `credential_ref` 在本地安全读取配置（如 `D:\AI-KB\LocalConfig\`），绝不外传。
3. **结果脱敏**：AI-KB 回传的 `OWNER_ACTION_RESULT` 严禁包含凭据、完整环境变量或未脱敏的调试日志。
4. **递归防护**：所有输入与输出数据结构均需通过递归零敏感字段校验（`_assert_zero_sensitive_data`）。

---

## 7. 事实型执行结果契约 (Owner Result Contract)

AI-KB 执行完成后，回传的 `OWNER_ACTION_RESULT` 必须仅包含技术客观事实：
```json
{
  "record_type": "OWNER_ACTION_RESULT",
  "request_id": "act-req-20261007-001",
  "lease_id": "lease-aikb-cpa-001",
  "executor_id": "aikb-owner-executor",
  "attempt": 1,
  "execution_started_at": "2026-10-07T09:30:05Z",
  "execution_finished_at": "2026-10-07T09:30:15Z",
  "exit_status": "SUCCESS",
  "exit_code": 0,
  "owner_result": {
    "command_executed": "ops/cpa/local_cpa.py restart",
    "duration_seconds": 10.2,
    "status_summary": "Local CPA restarted and verified on port 18117"
  },
  "reason_code": "LOCAL_CPA_RESTART_SUCCESS",
  "resource_state_before": {
    "status": "RUNNING",
    "port": 18117
  },
  "resource_state_after": {
    "status": "RUNNING",
    "port": 18117,
    "healthy": true
  },
  "evidence_ref": "exec-fact-1779234567"
}
```

---

## 8. Hub 独立验证规范 (Independent Hub Verification Contract)

AI-KB 上报 `EXECUTION_SUCCEEDED` 后，Hub 控制平面自动发起四重独立验证：
1. **端口可达性检查 (HTTP Reachability)**：向目标资源发起 HTTP GET 探测，必须返回 HTTP 200 且响应体符合预期架构。
2. **目录重发现 (Catalog Rediscovery)**：Hub 后台主动刷新模型目录，验证目标资源是否被正确感知且元数据完整。
3. **轻量推理探针 (L1 Inference Probe)**：发起低消耗语义推理验证，证明模型通道真实具备生成能力。
4. **智能体兼容性保护 (Agent Compatibility Invariant)**：若目标资源服务于 Coding Agent，确保关键工具调用协议与契约未发生损坏。

所有检查项全部为 `pass: true`，记录 `OWNER_ACTION_VERIFICATION`（`verification_status: "PASS"`），请求方可流转至 `VERIFIED` 并最终标记为 `COMPLETED`。

---

## 9. 治理不变式与性能隔离 (Governance Invariants & Performance Isolation)

1. **零指标污染 (Zero Double-Counting)**：
   - 动作执行与验证探针流量属于治理流量，**MUST NOT** 虚增用户真实调用的成功统计（`OWNER_ACTION_L1_DOUBLE_COUNT=false`）。
   - **MUST NOT** 虚增 Layer 2 Coding Outcome 的样本数据（`OWNER_ACTION_CODING_OUTCOME_DOUBLE_COUNT=false`）。
2. **生命周期严禁自动越权晋升**：
   - 动作执行成功绝不代表模型获得生产主路由资格。
   - `AUTOMATIC_PRODUCTION_PROMOTION=false`，`AUTOPILOT_ENFORCEMENT_MODE` 在 R2 阶段持续保持 `SHADOW_ONLY`。
3. **路由关键路径绝对零阻塞**：
   - 动作调度与验证完全在后台异步线程池执行，绝对不阻塞 `POST /api/model/select`、Coding Gateway 或 Sidecar。
   - 核心路由延迟保持指标：`SELECT_P95_MS <= 50`。
4. **测试与生产严格隔离**：
   - 单元测试与集成测试必须运行在独立的临时 SQLite 数据库中。
   - 严禁向生产数据库插入测试动作记录：`TEST_OWNER_ACTION_ROWS_IN_PRODUCTION=0`。
