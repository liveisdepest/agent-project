# MCP Client 代码功能介绍

本文档详细介绍了 `client.py` 中 `MCPClient` 类及其相关功能的实现逻辑。该客户端经过重构，现在采用 **FarmMind 多智能体架构 (Orchestrator Architecture)**，将复杂的农业决策任务拆解为感知、决策、执行三个独立阶段，确保系统的安全性与可解释性。

## 核心类：MCPClient

`MCPClient` 是整个系统的总控（Orchestrator），负责协调各个子智能体（Agents），管理 MCP 服务器连接，并执行严格的状态机流程。

### 1. 初始化与配置
- **`__init__(self, ...)`**: 
  - 初始化客户端状态，包括服务器连接栈、进程管理、会话存储等。
  - **状态管理**：新增 `self.pending_decision` 用于存储待用户确认的决策结果。
  - 配置连接超时、重试次数等参数。
  - 初始化 OpenAI 客户端。

- **`_load_env_variables(self)`**: 
  - 从环境变量中加载 `API_KEY`, `BASE_URL`, `MODEL`。

### 2. 服务器连接管理
- **`load_servers_from_config(self, config_path)`**: 
  - 读取 `mcp_servers.json`，支持 SSE 和 Stdio 两种连接模式。
  - 自动管理子进程的生命周期。

- **连接方法** (`connect_to_sse_server`, `connect_to_local_server`):
  - 建立与 `irrigation` (灌溉), `weather` (天气), `browser-use` (浏览器) 等 MCP 服务的连接。

### 3. FarmMind 多智能体架构 (核心逻辑)

系统不再使用单一的 System Prompt，而是拆分为四个角色的 Prompt（定义在 `prompts.py`）：
1. **Orchestrator (总控)**: 代码逻辑本身充当总控，不直接由 LLM 扮演，而是由 `process_query` 函数硬编码流程。
2. **Perception Agent (感知)**: 负责收集环境数据。
3. **Reasoning Agent (决策)**: 负责分析数据并制定方案。
4. **Action Agent (执行)**: 负责执行具体的硬件控制。

#### 流程控制 (`process_query`)
`process_query(self, query)` 实现了严格的 **Phase-based State Machine**：

1. **Phase 0: 状态检查**
   - 检查 `self.pending_decision`。如果存在待确认的决策，优先处理用户的“是/否”反馈。
   - 如果用户确认（"yes"），进入执行层；否则取消操作。

2. **Phase 1: 感知层 (`_run_perception_phase`)**
   - **System Prompt**: `PERCEPTION_PROMPT`
   - **可用工具**: 仅限 `irrigation.get_sensor_data`, `weather.get_forecast_week`。
   - **目标**: 获取环境快照。
   - **输出**: 纯 JSON 格式的环境数据（土壤湿度、天气预报等）。

3. **Phase 2: 决策层 (`_run_reasoning_phase`)**
   - **System Prompt**: `REASONING_PROMPT`
   - **输入**: 用户的原始请求 + 感知层输出的 JSON 数据。
   - **可用工具**: 仅限 `browser_use`（用于查询作物阈值）。
   - **目标**: 结合农学知识进行推理。
   - **输出**: 包含决策结论（IRRIGATE/DO_NOT_IRRIGATE）、理由、建议灌溉量的 JSON。

4. **Phase 3: 用户确认与执行层 (`_run_action_phase`)**
   - **触发条件**: 仅当决策层建议 "IRRIGATE" 且用户回复 "yes" 时触发。
   - **System Prompt**: `ACTION_PROMPT`
   - **可用工具**: 仅限 `irrigation.control_pump`。
   - **目标**: 安全地调用硬件接口。

### 4. 通用 Agent 执行循环
- **`_execute_agent_loop(self, messages, tools)`**: 
  - 一个通用的 ReAct 循环，被上述三个阶段复用。
  - 负责与 LLM 交互、解析工具调用请求、执行工具并回传结果。
  - 支持 **纯文本 JSON 工具调用拦截** (`_extract_text_tool_calls`)，以兼容某些不严格遵循 OpenAI Tool Call 协议的模型。

### 5. 工具与安全
- **工具隔离**: 每个阶段只能访问其职责范围内的工具，物理上杜绝了“感知层乱开水泵”或“执行层上网冲浪”的风险。
- **Browser Use 集成**: 特殊处理 `browser_use` 工具的异步结果，支持轮询等待。

### 6. 辅助功能
- **`chat_loop`**: 命令行交互界面。
- **`clean`**: 资源清理，确保子进程不残留。

## 总结
重构后的 `client.py` 从“单体智能体”进化为“分层协作系统”，大大提高了在真实农业场景下的安全性、稳定性和可维护性。
