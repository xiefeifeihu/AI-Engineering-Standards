# STD-030: Unified AI Capability Platform Contract: Deployment Intelligence, Multimodal Runtime Abstraction, and Multi-Consumer Autonomy (统一AI能力平台契约规范：模型部署智能、多模态运行时抽象与多消费端自治接入)

```text
STANDARD_ID=STD-030
VERSION=2.1.0
STATUS=ACTIVE
SCOPE=四库分离架构、模型部署智能(Deployment Intelligence)、6大推理引擎能力目录、只读硬件资源画像、显存/KV-Cache可行性评估、多模态运行时抽象(18项能力分类/异步作业状态机/零提示词二进制持久化/SSRF防护/预算阻断)、多消费端隔离治理(7类消费端/质量反馈隔离/定制路由计划)
OWNER=AI Platform Governance Committee
LAST_UPDATED=2026-10-09
RELATED_STANDARDS=STD-008, STD-009, STD-010, STD-011, STD-021, STD-022, STD-023, STD-024, STD-025, STD-026, STD-027, STD-028
```

### 规范性关键词说明 (Normative Keywords)
本文档严格遵循 RFC 2119 规范性用词：
- **MUST / 必须**：绝对强制要求，违反即判定为不合规。
- **MUST NOT / 严禁**：绝对禁止项，绝不允许出现。
- **SHOULD / 应当**：在有充分合理理由的前提下可以例外，但常规情况下必须遵守。
- **SHOULD NOT / 不宜**：不推荐的做法，存在隐患或更优实践。
- **MAY / 可以**：完全可选功能或扩展实现。

---

## 1. 架构目标与四库分离原则 (Architecture Goal & Four-Repository Separation)

统一 AI 能力平台将控制平面从单一文本模型路由与 Champion 选举升级为覆盖模型供给、开源部署可行性、多模态调度以及多业务消费端治理的统一能力控制平面。

### 1.1 四库清晰分离原则 (Hard Four-Repository Separation)
系统 **MUST** 保持以下四库在物理属主、数据生命周期与访问权限上的清晰分离，严禁将动态状态或敏感数据混淆注入静态知识：
1. **模型知识库 (Model Knowledge Repository)**：
   - 属主：`AI-KB`
   - 内容：Model Cards、官方架构说明、理论能力、开源 License、官方发布权重信息、部署指南。
   - 特征：静态知识、结构化元数据沉淀，支持 RAG 检索。
2. **API 资源库 (API Resource Repository)**：
   - 属主：`Hub`
   - 内容：Provider、ProviderAccount、ModelOffering、AccessRoute、Credential Ref、定价阶梯与配额限制。
   - 特征：外部商业与开源服务接口账本，仅存储凭据引用 (`credential_ref`)，严禁明文凭据。
3. **部署资源库 (Deployment Resource Repository)**：
   - 属主：`Hub`
   - 内容：开源权重元数据、量化阶梯 (Quantization Tiers)、推理引擎兼容性、硬件资源需求估算与可行性判据。
   - 特征：连接开源模型定义与物理计算资源的部署智能账本。
4. **运行资源库 (Runtime Resource Repository)**：
   - 属主：`Hub`
   - 内容：RuntimeEndpoint、实时健康探针、实测延迟与错误率、熔断状态、Scout 评测、Champion 分流与运行时拓扑。
   - 特征：高频动态状态，严禁作为静态 RAG 知识持久化回写到模型知识库。

---

## 2. 模型部署智能 (Deployment Intelligence)

### 2.1 模型定义规范 (ModelDefinition Schema)
系统 **MUST** 对每个开源权重模型维护包含以下 20 项核心字段的 `ModelDefinition`：
- `model_id`: 规范化唯一标识符。
- `model_family`: 模型家族 (如 `qwen2.5`, `deepseek-v3`, `llama-3.1`)。
- `revision`: 权威版本号或 Git commit hash。
- `parameter_count`: 标称参数量 (如 `7B`, `671B`)。
- `total_parameter_count`: 物理权重总参数量 (以十亿为单位，如 MoE 模型的 671.0)。
- `active_parameter_count`: 单次推理激活参数量 (以十亿为单位，如 MoE 模型的 37.0)。
- `architecture`: 网络架构分类 (`dense`, `moe`, `encoder-decoder`, `diffusion`)。
- `moe_information`: MoE 路由配置字典 (包含 `num_experts`, `active_experts`, `shared_experts`)。
- `context_length`: 原生最大上下文长度 (token 数)。
- `modalities`: 支持的模态列表 (如 `["text", "image", "audio"]`)。
- `open_weights`: 是否开源权重 (`true` / `false`)。
- `license`: 开源许可协议 (如 `Apache-2.0`, `MIT`, `DeepSeek License`)。
- `commercial_use_constraints`: 商业使用限制说明。
- `weights_url`: 权重权威源下载链接。
- `download_source`: 权重托管源类型 (`huggingface`, `modelscope`, `ollama_library`, `github`)。
- `file_format`: 权重文件格式 (`gguf`, `safetensors`, `onnx`)。
- `quantization`: 基准量化格式 (`FP16`, `BF16`, `Q8`, `Q4_K_M` 等)。
- `deployment_engine`: 推荐默认推理引擎。
- `official_model_card`: 官方模型说明文档 URI。
- `metadata_confidence`: 元数据置信度评分 (`0.0` - `1.0`)。
- `last_verified_at`: 最近一次权威验证时间戳。

### 2.2 推理引擎能力目录 (Inference Engine Catalog)
系统 **MUST** 明确建模并维护 6 大标准推理引擎的能力边界与兼容性状态：
1. `Ollama`: 面向本地桌面与轻量服务器的开箱即用引擎。
2. `llama.cpp`: 高性能多硬件量化推理核心。
3. `vLLM`: 高吞吐分布式 PagedAttention 推理引擎。
4. `SGLang`: 面向复杂结构化生成与多轮调用的快速推理框架。
5. `Transformers`: Hugging Face 参考级推理实现。
6. `NVIDIA NIM`: 企业级微服务优化推理容器。

引擎兼容性判定 **MUST** 严格区分以下状态枚举：
- `ENGINE_SUPPORTED`: 经实测验证完全兼容并稳定支持。
- `ENGINE_DECLARED`: 官方声明支持但尚未经本地实测验证。
- `ENGINE_NOT_VERIFIED`: 缺乏官方声明与本地验证数据。
- `ENGINE_INCOMPATIBLE`: 明确不兼容 (如架构缺失、内核指令集不支持)。

系统 **MUST NOT** 混淆以下三项独立事实：
1. 模型是否可下载；
2. 模型是否可被特定推理引擎加载；
3. 模型是否可在当前物理硬件上稳定运行。

---

## 3. 本机硬件画像与部署可行性评估 (Hardware Profile & Feasibility Assessment)

### 3.1 只读硬件扫描 (Read-Only Hardware Introspection)
系统 **MUST** 提供安全、只读的本机硬件采集能力，生成包含以下指标的 `HostHardwareProfile`：
- CPU 型号、物理核心数、逻辑线程数。
- 宿主机物理内存 (RAM) 总量与空闲量。
- GPU 型号、计算能力 (Compute Capability)、驱动版本、CUDA 版本。
- GPU 显存 (VRAM) 总量与当前空闲量。
- WSL GPU 透传状态 (WSL Passthrough Status)。
- 运行盘与模型存储盘剩余磁盘空间。

**安全铁律**：
- 采集过程 **MUST NOT** 要求管理员/Root 提权。
- 采集过程 **MUST NOT** 更改显卡驱动、BIOS 设置或系统 CUDA 环境变量。

### 3.2 内存与显存消耗模型 (Memory & KV-Cache Estimation)
对于开源权重模型，系统 **MUST** 按照以下公式结构估算运行所需物理内存与显存：
$$\text{Memory}_{\text{total}} = \text{Weights} + \text{KV\_Cache} + \text{Runtime\_Overhead} + \text{Concurrency\_Overhead}$$

- **权重显存计算 (Weights Memory)**：
  - 对于稠密模型 (Dense)：按标称参数量与比特位宽计算。
  - 对于稀疏混合专家模型 (MoE)：**MUST** 按照总参数量 (`total_parameter_count`) 计算权重加载内存，严禁仅使用激活参数量 (`active_parameter_count`) 估算加载内存。
- **KV Cache 显存**：依据上下文窗口大小 (`context_length`)、注意力头数与并发请求量动态估算。
- **运行时开销 (Runtime Overhead)**：为推理引擎执行上下文与 CUDA Context 保留 1.0GB - 2.0GB 基础开销。

### 3.3 可行性判定与三档硬件建议 (Feasibility Classification & Tiers)
系统输出的可行性评估结果 **MUST** 明确归类为以下 5 种状态之一：
- `RUNNABLE_NOW`: 纯 GPU 显存完全容纳权重、KV-Cache 与并发开销，无需任何额外硬件升级。
- `RUNNABLE_WITH_OFFLOAD`: GPU 显存不足以容纳全部层，但 GPU + 系统 RAM 总量满足，支持 GPU/CPU 异构卸载 (Offloading)。
- `HARDWARE_UPGRADE_REQUIRED`: 当前计算设备显存与内存均无法安全承载模型。
- `INSUFFICIENT_METADATA`: 模型参数或量化元数据不足，无法完成准确估算。
- `ENGINE_INCOMPATIBLE`: 当前引擎不支持该模型架构。

当判定为无法立即运行或需要升级时，系统 **MUST** 输出三档推荐配置：
1. **最低可运行规格 (Minimum Runnable)**：满足单并发、量化卸载的基准硬件需求。
2. **推荐推理规格 (Recommended Inference)**：实现纯 GPU 显存驻留、典型并发流畅推理的推荐硬件。
3. **高并发服务规格 (High-Concurrency Serving)**：满足全精度/高量化、大并发、大上下文吞吐的生产级硬件配置。

系统 **MUST NOT** 将估算结果宣称为真实运行成功，且 **MUST** 明确标注误差假设。

---

## 4. 自治部署安全铁律 (Autonomous Deployment Safety Invariants)

在平台自治运行中，以下安全默认策略 **MUST** 始终为 `false`：
- `AUTO_MODEL_DOWNLOAD = false`：严禁自动向磁盘拉取未核准的大型模型权重。
- `AUTO_MODEL_DELETE = false`：严禁自动删除宿主机或 Ollama 已存在的模型。
- `AUTO_GPU_DRIVER_CHANGE = false`：严禁变更 GPU 驱动或系统软件环境。
- `AUTO_INFRASTRUCTURE_UPGRADE = false`：严禁自动对基础设施发起具有破坏性的变更。

当需要实际下载或部署模型时，Hub **MUST** 遵循受控事务契约：生成包含预演检查 (Dry Run)、磁盘容量校验、License 合规审核的 `Owner Action Request`，由运维人员或授权代理执行并完成双向重检。

---

## 5. 多模态运行时抽象 (Multimodal Runtime Abstraction)

### 5.1 18 项标准多模态能力目录 (18 Canonical Capabilities)
系统 **MUST** 规范建模以下 18 项多模态能力原子：
1. `IMAGE_GENERATION`: 文本生成图像 (如 SD, FLUX)。
2. `IMAGE_EDITING`: 图像局部重绘、修图与风格迁移。
3. `VISION_UNDERSTANDING`: 图像问答、OCR、结构化视觉解析。
4. `TEXT_TO_SPEECH`: 语音合成 (TTS)。
5. `SPEECH_TO_TEXT`: 语音识别转写 (STT / ASR)。
6. `AUDIO_UNDERSTANDING`: 音频事件检测与内容理解。
7. `VIDEO_GENERATION`: 文本/图像生成视频。
8. `VIDEO_UNDERSTANDING`: 视频关键帧分析与时空理解。
9. `DOCUMENT_OCR_EXTRACTION`: 文档扫描、表格识别与版面恢复。
10. `EMBEDDING_TEXT`: 纯文本向量化。
11. `EMBEDDING_MULTIMODAL`: 图文跨模态多向量融合。
12. `RERANKING`: 混合语义重排序。
13. `CODE_COMPLETION`: 实时代码补全。
14. `CODE_REASONING`: 复杂代码架构分析与推理。
15. `FUNCTION_CALLING`: 结构化工具调用与 JSON 严格生成。
16. `WEB_SEARCH_GROUNDING`: 联网检索增强生成。
17. `STRUCTURED_EXTRACTION`: 正则/模式化结构提取。
18. `LONG_CONTEXT_ANALYSIS`: 超长文本及书籍综合归纳。

### 5.2 架构双轨路由 (Two-Track Routing)
- **通用 CPA 兼容通道 (CPA Track)**：
  - 针对符合 OpenAI / Anthropic 兼容的视觉对话、文本嵌入、重排序与函数调用，**MUST** 沿用现有标准 CPA 路由通道。
- **专用异步适配器通道 (Specialized Adapter Track)**：
  - 针对音视频生成、重型文档处理等具有复杂异步生命周期、自定义轮询或专有数据格式的能力，**MUST** 由专用运行时适配器 (`SpecializedRuntimeAdapter`) 托管。

### 5.3 异步作业状态机规范 (Async Job State Machine)
专用多模态作业必须严格遵循有限状态机流转：`CREATED` -> `VALIDATED` -> `SUBMITTED` -> `RUNNING` -> `SUCCEEDED` / `FAILED` / `CANCELLED`。

### 5.4 隐私、安全与成本硬防护 (Privacy, Security & Cost Guards)
1. **零提示词与二进制持久化 (Zero Prompt / Binary Persistence)**：
   - 作业状态数据库中 **MUST NOT** 存储原始用户输入提示词、生成的大型多媒体二进制文件或 Base64 原始内容。
   - 作业仅存储非敏感资产元数据引用 (`AssetRef`)、耗时、状态与安全哈希。
2. **SSRF 防护 (Server-Side Request Forgery Guard)**：
   - 系统接收到的所有多模态输入/输出 URL，**MUST** 经过严格的 IP/域名解析校验。
   - **MUST** 拦截并阻断指向回环地址 (`127.0.0.0/8`, `::1`)、私有私网网段 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) 以及云厂商元数据服务 (`169.254.169.254`) 的非法请求。
3. **单次资产体积限制 (Max Asset Size Limit)**：
   - 资产单文件体积上限默认为 50MB，超出时 **MUST** 阻断并返回合规错误。
4. **成本预估与预算阻断 (Cost Guard)**：
   - 调用外部收费专用多模态服务前，**MUST** 评估预估成本 (`CostEstimate`)。
   - 若预估成本超出单次上限且未经显式授权，或成本未知 (`COST_UNKNOWN`)，系统 **MUST** 阻断调用。

---

## 6. 多消费端隔离治理 (Multi-Consumer Isolation & Governance)

### 6.1 7 大标准消费端注册表 (7 Canonical Consumers)
系统 **MUST** 为接入的各类业务消费端维护显式登记的 `ConsumerProfile`，默认包含以下 7 大消费端类型：
1. `claude-code`: 代码生成与终端交互 Agent。
2. `antigravity`: 核心研发自治 Agent。
3. `aikb`: AI-KB 知识库系统 (RAG、分块与沉淀)。
4. `sidecar`: 业务伴侣应用 (企业 IM、轻量办公)。
5. `vtip-catalog`: VTIP 平台服务目录与治理工作流。
6. `generic-openai`: 兼容 OpenAI API 规范的通用第三方消费端。
7. `multimodal-apps`: 音视频创作与重模态业务应用。

### 6.2 消费端范围隔离治理 (Strict Scope Isolation)
为了防止跨场景能力相互干扰，系统 **MUST** 实施严格的范围隔离：
- **质量反馈隔离 (Outcome Isolation)**：
  - 各消费端提交的模型使用质量反馈 (`ConsumerOutcomeFeedback`) **MUST** 按 `consumer_id` 与场景完全分区存储。
  - Claude Code 的终端代码编写成功率 **MUST NOT** 污染 Sidecar 业务对话或 AI-KB RAG 的打分与 Champion 排名。
- **差异化路由计划 (Consumer-Tailored Routing Plans)**：
  - 系统根据消费端配置的允许模态、成本敏感度、延迟偏好与目标场景，为其生成专属的候选模型列表与降级链路。

### 6.3 接入模式 (Autonomy Modes)
消费端可配置以下三种自治接入模式之一：
- `SHADOW_ONLY`: 影子模式，仅记录日志与路由对比，不直接影响线上流量。
- `ADVISORY`: 建议模式，Hub 提供推荐模型与候选集，消费端可自主决定。
- `ENFORCED`: 强制路由模式，完全由 Hub 托管动态路由与故障熔断。

---

## 7. 审计与证据完整性 (Audit & Evidence Integrity)

所有基于本规范实施的 Hub 版本交付，**MUST** 输出机器可读的结构化证据，包括但不限于：
1. `deployment_catalog.json`: 完整开源模型部署目录与元数据。
2. `hardware_profile.json`: 只读采集的物理硬件与 GPU 画像。
3. `multimodal_capabilities.json`: 18 项多模态能力矩阵及运行时映射。
4. `consumer_registry.json`: 7 大消费端配置与隔离验证事实。
5. `docker_socket_security.json`: Docker Socket 挂载审计与权限消除结论。

人类可读的技术报告与验收文档中所引用的性能指标 (如 P95 延迟数值)，**MUST** 与结构化测试证据文件保持严格一致。