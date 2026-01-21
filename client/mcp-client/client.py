import asyncio
import os
import time
import uuid
import re
from urllib.parse import quote_plus, urlparse
from openai import OpenAI
from dotenv import load_dotenv
from contextlib import AsyncExitStack, suppress
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载 .env 文件
load_dotenv()

SYSTEM_PROMPT = """你是一个智能农业决策助手。你的目标是协调多个工具（天气、灌溉、浏览器、文件系统）来为用户提供精准的农业建议。

**核心工作流程 (SOP)：**

当用户询问关于作物灌溉或生长环境的问题时（例如："曲靖今天天气怎么样？可以结合传感器告诉我小麦需要灌溉吗？"）：

1.  **第一步：获取上下文信息**
    *   调用 `irrigation.get_sensor_data` 获取当前的土壤湿度和环境温湿度。
    *   调用 `weather.get_observe` 或 `weather.get_forecast_week` 获取指定地点的天气。
    

2.  **第二步：获取知识（如果需要）**
    *   如果本地工具数据不足以得出结论，或用户明确要求"查一下/搜索/外部资料"：
    *   调用 `browser_use` 工具访问搜索引擎页面（例如 `https://www.bing.com/search?q=小麦+需水量`），并在 `action` 里说明要提取/总结的要点。
    *   若 `browser_use` 返回的是 task_id（异步模式），则继续调用 `browser_get_result` 获取最终结果。

3.  **第三步：综合分析与建议**
    *   **优先级规则**：**土壤湿度**是最高优先级的判断依据。
    *   如果土壤湿度低于 20%（尤其是 0%），这属于**严重缺水**，除非当前正在下暴雨，否则**必须建议立即灌溉**。此时气温低或多云都不是拒绝灌溉的理由。
    *   结合 **天气**（是否有雨？）、**土壤湿度**（是否干燥？）、**作物习性**（是否处于需水期？）。
    *   给出明确的建议：是否需要灌溉？如果需要，灌溉的原因是什么？

4.  **第四步：执行行动（仅在用户授权后）**
    *   **开启水泵**：只有当用户明确说"打开水泵"、"浇水"时，才调用 `irrigation.control_pump(turn_on=True)`。
    *   **关闭水泵**：当用户说"关闭水泵"、"停止灌溉"时，应立即调用 `irrigation.control_pump(turn_on=False)`。
    *   **禁止**在用户没有明确指令的情况下自动开启水泵。

**重要规则：**
*   **允许多工具链**：针对同一个用户问题，可以连续调用多个工具来收集信息（按顺序执行，拿到一个结果后继续执行下一个），直到足够回答为止。
*   **优先自动收集**：若问题需要天气与土壤信息，直接调用 `weather.*` 与 `irrigation.*` 获取数据，不要反问用户是否要查。
*   **必要时再上网**：只有在本地工具数据不足以得出结论时，才使用 `browser-use` 获取公开信息补充依据。
*   **不要拒绝联网**：你可以通过 `browser_use` 工具进行外部检索；不要声称"无法访问外部搜索引擎/网络请求"。
*   **数据驱动**：不要瞎猜。必须基于工具返回的真实数据说话。

**回复风格指南：**

你需要像一个专业的农业顾问一样，用自然、流畅的语言与用户交流。不要使用固定模板，而是根据实际情况灵活组织语言。

**必须包含的核心信息：**
1. **当前环境状况**：清晰说明实时天气、传感器数据（土壤湿度、温度、空气湿度）和设备状态
2. **作物需求分析**：结合作物类型和生长阶段，说明当前的水分需求情况
3. **决策建议**：基于数据给出明确的灌溉建议，并解释原因
4. **操作指引**：告诉用户接下来该做什么

**决策逻辑优先级：**
- 土壤湿度是最关键的指标
- 土壤湿度 < 20%：严重缺水，通常需要立即灌溉（除非正在下大雨）
- 土壤湿度 20-40%：可能需要灌溉，结合天气预报和作物需求判断
- 土壤湿度 > 60%：水分充足，一般不需要灌溉

**语言风格要求：**
- 用自然、专业但易懂的语言表达
- 根据具体情况灵活调整表述方式
- 重要信息可以用 emoji 和加粗强调，但不要过度使用
- 避免机械地填充模板，要像真人顾问一样思考和表达
- 当情况紧急时（如土壤湿度0%），语气要更加明确和果断
- 当情况正常时，可以更加从容和详细地分析

**示例风格（仅供参考，不要照搬）：**
"根据刚才获取的数据，曲靖目前气温11.5°C，天气晴朗。但是传感器显示土壤湿度为0%，这是一个非常严重的缺水信号。

对于玉米来说，整个生长期都需要充足的水分供应，尤其是在拔节期和抽穗期。当前土壤完全干燥的状态会严重影响作物生长，甚至可能导致植株萎蔫。

虽然气温不高，但土壤湿度0%意味着根系已经无法吸收到水分。查看未来一周的天气预报，主要是多云天气，短期内没有降雨计划。因此**我强烈建议立即开启灌溉**。

如果你同意，请回复"开启水泵"，我会立即启动灌溉系统。"
"""


class MCPClient:
    def __init__(self, connection_timeout: int = 60, max_retries: int = 3, tool_timeout: int = 120):
        """初始化 MCP 客户端"""
        self._server_exit_stacks = {}
        self._server_processes = {}
        self._load_env_variables()

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.sessions = {}
        self.tools_map = {}
        self.conversation_history = []
        
        # 超时和重试配置
        self.connection_timeout = connection_timeout
        self.max_retries = max_retries
        self.tool_timeout = tool_timeout
        
        logger.info(f"⚙️  超时配置: 连接={connection_timeout}s, 工具调用={tool_timeout}s, 重试={max_retries}次")

    def _load_env_variables(self):
        """加载并验证环境变量"""
        self.api_key = os.getenv("API_KEY")
        self.base_url = os.getenv("BASE_URL")
        self.model = os.getenv("MODEL")
    
        if not self.api_key:
            raise ValueError("未找到 API KEY. 请在 .env 文件中配置 API_KEY")
        if not self.base_url:
            logger.warning("未找到 BASE_URL，将使用默认值或可能导致错误。请在 .env 文件中配置 BASE_URL")
        if not self.model:
            logger.warning("未找到 MODEL，将使用默认值或可能导致错误。请在 .env 文件中配置 MODEL")

    async def load_servers_from_config(self, config_path: str):
        """从配置文件加载服务器（支持失败跳过）"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件 {config_path} 未找到")
        except json.JSONDecodeError:
            raise ValueError(f"配置文件 {config_path} 格式错误")

        servers = config.get("mcpServers", {})
        successful_connections = 0
        total_servers = len(servers)
        
        logger.info(f"开始连接 {total_servers} 个MCP服务...")
        
        for server_id, server_config in servers.items():
            url = server_config.get("url", None)
            command = server_config.get("command", None)
            args = server_config.get("args", [])
            env_config = server_config.get("env", None)
            timeout = server_config.get("timeout", None)
            max_retries = server_config.get("max_retries", None)
            
            env = self._build_child_env(server_id, env_config)
            
            # 尝试连接，失败则跳过
            if url:
                success = await self.connect_to_sse_server(
                    server_id,
                    url,
                    command=command,
                    args=args,
                    env=env,
                    timeout=timeout,
                    max_retries=max_retries,
                )
            else:
                if not command:
                    logger.error(f"❌ 服务端 {server_id} 缺少 command/url 配置，跳过")
                    continue
                success = await self.connect_to_local_server(
                    server_id,
                    command,
                    args,
                    env,
                    timeout=timeout,
                    max_retries=max_retries,
                )
            if success:
                successful_connections += 1

        logger.info(f"📊 连接结果: {successful_connections}/{total_servers} 个服务连接成功")
        
        if successful_connections == 0:
            logger.error("⚠️  没有任何MCP服务连接成功，请检查配置和服务状态")
        elif successful_connections < total_servers:
            logger.warning(f"⚠️  部分服务连接失败，当前可用服务数: {successful_connections}")

    def _build_child_env(self, server_id: str, env_config: dict | None):
        env = os.environ.copy()
        if env_config:
            env.update(env_config)

        if server_id == "browser-use":
            env.setdefault("OPENAI_API_KEY", os.environ.get("API_KEY", ""))
            env.setdefault("OPENAI_BASE_URL", os.environ.get("BASE_URL", ""))
            env.setdefault("OPENAI_MODEL", os.environ.get("MODEL", ""))

        return env

    async def _terminate_process(self, process: asyncio.subprocess.Process):
        if process.returncode is not None:
            return
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=5)
        except Exception:
            with suppress(Exception):
                process.kill()
            with suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=5)

    async def connect_to_sse_server(
        self,
        server_id: str,
        url: str,
        command: str | None,
        args: list,
        env: dict,
        timeout: int | None = None,
        max_retries: int | None = None,
    ):
        if timeout is None:
            timeout = self.connection_timeout
        if max_retries is None:
            max_retries = self.max_retries

        if server_id in self.sessions:
            logger.warning(f"服务端 {server_id} 已经连接，跳过重复连接")
            return True

        for attempt in range(max_retries):
            attempt_stack = AsyncExitStack()
            process = None
            try:
                logger.info(f"正在连接服务端 {server_id}... (尝试 {attempt + 1}/{max_retries})")

                should_start = command is not None
                try:
                    if await self._is_sse_endpoint_alive(url):
                        should_start = False
                except Exception:
                    pass

                if should_start:
                    process = await asyncio.create_subprocess_exec(command, *args, env=env)
                    self._server_processes[server_id] = process
                    await asyncio.sleep(0.5)

                transport = await attempt_stack.enter_async_context(
                    sse_client(url, timeout=5, sse_read_timeout=60 * 10)
                )
                read_stream, write_stream = transport
                session = await attempt_stack.enter_async_context(ClientSession(read_stream, write_stream))
                await self._await_with_timeout(session.initialize(), timeout)

                self._server_exit_stacks[server_id] = attempt_stack
                self.sessions[server_id] = {"session": session}
                logger.info(f"✅ 成功连接到 MCP 服务: {server_id}")
                return True
            except asyncio.TimeoutError:
                logger.error(f"❌ 连接服务端 {server_id} 超时 (尝试 {attempt + 1}/{max_retries})，超时时间: {timeout}秒")
            except Exception as e:
                logger.error(f"❌ 连接服务端 {server_id} 失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
            
            with suppress(Exception):
                await attempt_stack.aclose()
            if process is not None:
                with suppress(Exception):
                    await self._terminate_process(process)
                self._server_processes.pop(server_id, None)

            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"⏳ {wait_time}秒后重试连接 {server_id}...")
                await asyncio.sleep(wait_time)

        logger.error(f"🚫 服务端 {server_id} 连接失败，已达到最大重试次数 ({max_retries})，跳过该服务")
        return False

    async def connect_to_local_server(
        self,
        server_id: str,
        command: str,
        args: list,
        env: dict,
        timeout: int | None = None,
        max_retries: int | None = None,
    ):
        """
        连接到本地 MCP 服务（带超时和重试机制）
        :param server_id: 服务端标识符
        :param command: 本地服务的启动命令
        :param args: 启动命令的参数
        :param env: 环境变量
        :param timeout: 连接超时时间（秒）
        :param max_retries: 最大重试次数
        """

        if timeout is None:
            timeout = self.connection_timeout
        if max_retries is None:
            max_retries = self.max_retries

        if server_id in self.sessions:
            logger.warning(f"服务端 {server_id} 已经连接，跳过重复连接")
            return True

        for attempt in range(max_retries):
            try:
                logger.info(f"正在连接服务端 {server_id}... (尝试 {attempt + 1}/{max_retries})")
                
                await self._do_connect(server_id, command, args, env, initialize_timeout=timeout)
                
                logger.info(f"✅ 成功连接到 MCP 服务: {server_id}")
                return True
                
            except asyncio.TimeoutError:
                logger.error(f"❌ 连接服务端 {server_id} 超时 (尝试 {attempt + 1}/{max_retries})，超时时间: {timeout}秒")
            except Exception as e:
                logger.error(f"❌ 连接服务端 {server_id} 失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
            
            # 如果不是最后一次尝试，等待一段时间再重试
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 指数退避：2秒, 4秒, 8秒
                logger.info(f"⏳ {wait_time}秒后重试连接 {server_id}...")
                await asyncio.sleep(wait_time)

        logger.error(f"🚫 服务端 {server_id} 连接失败，已达到最大重试次数 ({max_retries})，跳过该服务")
        return False

    async def _do_connect(
        self,
        server_id: str,
        command: str,
        args: list,
        env: dict,
        initialize_timeout: int,
    ):
        """执行实际的连接操作"""
        server_params = StdioServerParameters(command=command, args=args, env=env)
        attempt_stack = AsyncExitStack()
        try:
            stdio_transport = await attempt_stack.enter_async_context(stdio_client(server_params))
            stdio, write = stdio_transport
            session = await attempt_stack.enter_async_context(ClientSession(stdio, write))
            await self._await_with_timeout(session.initialize(), initialize_timeout)
        except BaseException:
            with suppress(Exception):
                await attempt_stack.aclose()
            raise

        self._server_exit_stacks[server_id] = attempt_stack
        self.sessions[server_id] = {"session": session}
    
    async def list_tools(self):
        """列出所有服务端的工具并将详细信息存储起来（容错处理）"""
        if not self.sessions:
            logger.error("没有已连接的服务端")
            return

        logger.info("加载服务端工具:")
        self.tools_map.clear()
        
        successful_loads = 0
        total_sessions = len(self.sessions)
        
        for server_id, session_info in self.sessions.items():
            session = session_info["session"]
            try:
                # 添加超时控制到工具列表获取
                response = await asyncio.wait_for(session.list_tools(), timeout=20)
                
                tool_count = len(response.tools)
                for tool in response.tools:
                    self.tools_map[tool.name] = {
                        "server_id": server_id,
                        "description": tool.description,
                        "input_schema": tool.inputSchema
                    }
                    logger.info(f"  📧 工具: {tool.name}, 来源: {server_id}")
                
                logger.info(f"✅ 服务端 {server_id}: 加载了 {tool_count} 个工具")
                successful_loads += 1
                
            except asyncio.TimeoutError:
                logger.error(f"❌ 从服务端 {server_id} 获取工具列表超时")
            except Exception as e:
                logger.error(f"❌ 从服务端 {server_id} 获取工具列表时出错: {e}")
        
        total_tools = len(self.tools_map)
        logger.info(f"📊 工具加载结果: {successful_loads}/{total_sessions} 个服务，共 {total_tools} 个工具可用")
    
    async def _build_tool_list(self):
        """根据存储的工具信息构建统一的工具列表"""
        available_tools = []
        for tool_name, tool_info in self.tools_map.items():
            available_tools.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_info["description"],
                    "parameters": tool_info["input_schema"] 
                }
            })
        return available_tools
    
    async def process_query(self, query: str) -> str:
        # 确保有 System Prompt
        if not self.conversation_history:
            self.conversation_history.append({
                "role": "system", 
                "content": SYSTEM_PROMPT
            })

        # 将用户的新查询添加到历史记录
        self.conversation_history.append({"role": "user", "content": query})

        # 构建统一的工具列表
        available_tools = await self._build_tool_list()

        # 循环处理工具调用
        forced_final_answer_attempted = False
        tool_cycle_count = 0
        while True:
            # 先使用流式请求检查是否需要工具调用
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.conversation_history,
                stream=True,
                max_tokens=8192,
                stop=None,
                temperature=0.7,
                top_p=0.7,
                frequency_penalty=0.5,
                n=1,
                response_format={
                    "type": "text"
                },
                tools=available_tools,
            )

            final_content = ""
            has_tool_calls = False
            # 标记是否是手动拦截的 JSON 调用
            is_intercepted_json = False
            tool_calls = []
            
            # 用于检测是否返回了纯 JSON 文本的缓冲区
            json_buffer = ""

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta
                    try:
                        if delta.reasoning_content:
                            # 逐字输出 Reasoning 内容
                            reasoning_content = delta.reasoning_content
                            print("\033[92m" + reasoning_content + "\033[0m", end="", flush=True)
                    except:
                        pass
                    if delta.content:
                        # 逐字输出内容
                        content = delta.content
                        print(content, end="", flush=True)
                        final_content += content
                        json_buffer += content
                    if delta.tool_calls:
                        has_tool_calls = True
                        # 新增参数合并逻辑
                        for tc in delta.tool_calls:
                            existing = next((x for x in tool_calls if x.index == tc.index), None)
                            if existing:
                                existing.function.arguments += tc.function.arguments
                                if tc.function.name:
                                    existing.function.name = (existing.function.name or "") + tc.function.name
                            else:
                                tool_calls.append(tc)

            if not has_tool_calls:
                extracted = self._extract_text_tool_calls(json_buffer)
                if extracted:
                    logger.info(f"检测到 {len(extracted)} 个纯文本 JSON 工具调用，正在转换...")
                    tool_calls = extracted
                    has_tool_calls = True
                    is_intercepted_json = True
                    print(f"\n[系统] 已拦截并执行 {len(tool_calls)} 个工具调用...", end="", flush=True)

            # 等待 delta的tool_calls的返回为空
            if has_tool_calls:
                tool_cycle_count += 1
                if tool_cycle_count > 10:
                    logger.warning("检测到可能的死循环（工具链过长），强制停止工具链。")
                    return "系统检测到循环调用，已停止执行。请尝试重新表述您的问题或分步骤提出需求。"

                # 如果有工具调用，组合tool_calss内容
                # print(tool_calls) # 调试输出
                tool_results = await self._process_tool_calls(tool_calls)
                
                # 检查是否所有的工具调用都是错误的，如果是，则不继续循环，避免死循环
                all_errors = True
                for result in tool_results:
                     if not result["content"].startswith("Error:"):
                         all_errors = False
                         break
                
                if is_intercepted_json:
                    self._append_assistant_tool_calls(tool_calls)
                
                self.conversation_history.extend(tool_results)
                
                # 如果工具调用成功，清空 json_buffer 以便下一轮使用
                # 并继续循环，让模型根据工具结果生成最终回答
                if not all_errors:
                    continue
                else:
                     return "工具调用失败，请检查参数或重试。"

            else:
                # 如果没有工具调用，直接返回流式内容
                print()

                forced = self._decide_forced_action(query, final_content, forced_final_answer_attempted)
                if forced:
                    action_type = forced["type"]
                    if action_type == "tool":
                        tool_call_id = str(uuid.uuid4())
                        tool_name = forced["name"]
                        tool_args = forced["arguments"]
                        notice = forced.get("notice")

                        self._append_assistant_tool_calls(
                            [{"id": tool_call_id, "name": tool_name, "arguments": json.dumps(tool_args, ensure_ascii=False)}]
                        )
                        if notice:
                            print(notice)
                        tool_results = await self._process_tool_calls(
                            [{"id": tool_call_id, "name": tool_name, "arguments": json.dumps(tool_args, ensure_ascii=False)}]
                        )
                        self.conversation_history.extend(tool_results)
                        continue

                    if action_type == "final_text":
                        forced_final_answer_attempted = True
                        advice = forced["content"]
                        print(advice, end="", flush=True)
                        print()
                        self.conversation_history.append({"role": "assistant", "content": advice})
                        return advice

                    if action_type == "followup_prompt":
                        forced_final_answer_attempted = True
                        self.conversation_history.append({"role": "user", "content": forced["content"]})
                        continue

                return final_content

    async def _stream_response(self, content: str) -> str:
        """流式输出文本内容"""
        print(content, end="", flush=True)
        print()  # 添加换行符
        return content

    async def _process_tool_calls(self, tool_calls) -> list:
        """处理工具调用（非流式，带超时控制）"""
        tool_results = []
        for tool_call in tool_calls:
            tool_call_id, tool_name, tool_args_str = self._normalize_tool_call(tool_call)

            try:
                tool_args = json.loads(tool_args_str)
            except json.JSONDecodeError:
                logger.error(f"无法解析工具参数 JSON: {tool_args_str}")
                tool_results.append({
                    "role": "tool",
                    "content": f"Error: Invalid JSON arguments received: {tool_args_str}",
                    "tool_call_id": tool_call_id,
                })
                continue

            tool_info = self.tools_map.get(tool_name)
            if not tool_info:
                error_message = f"错误：未找到工具 {tool_name} 的配置信息。"
                logger.error(error_message)
                tool_results.append({
                    "role": "tool",
                    "content": error_message,
                    "tool_call_id": tool_call_id,
                })
                continue

            server_id = tool_info["server_id"]
            session = self.sessions[server_id]["session"]
            
            try:
                # -----------------------------------------------------------
                # 安全拦截逻辑：如果是控制水泵的工具，必须经过用户确认
                # -----------------------------------------------------------
                if tool_name == "control_pump":
                    pump_action = "开启" if tool_args.get("turn_on") else "关闭"
                    print(f"\n⚠️  【安全警告】AI 建议执行高风险操作：{pump_action}水泵")
                    user_confirm = input("请确认是否执行？(输入 'y' 或 'yes' 确认，其他键取消): ").strip().lower()
                    
                    if user_confirm not in ['y', 'yes']:
                        logger.info(f"🚫 用户拒绝了工具调用: {tool_name}")
                        tool_results.append({
                            "role": "tool",
                            "content": f"User denied the execution of {tool_name}. The pump state remains unchanged.",
                            "tool_call_id": tool_call_id,
                        })
                        continue
                    else:
                        print("✅ 用户已确认，正在执行...")

                logger.info(f"🔧 调用工具 {tool_name} (服务: {server_id}, 参数: {tool_args})")
                
                # 添加工具调用超时控制
                result = await asyncio.wait_for(session.call_tool(tool_name, tool_args), timeout=self.tool_timeout)
                
                result_content = result.content[0].text
                if tool_name == "browser_use":
                    result_content = await self._maybe_wait_browser_use_result(session, result_content)
                logger.info(f"✅ 工具 {tool_name} 执行成功")

                tool_results.append({
                    "role": "tool",
                    "content": result_content,
                    "tool_call_id": tool_call_id,
                })
                
            except asyncio.TimeoutError:
                error_message = f"工具 {tool_name} 调用超时 ({self.tool_timeout}秒)"
                logger.error(f"❌ {error_message}")
                tool_results.append({
                    "role": "tool",
                    "content": f"Error: {error_message}",
                    "tool_call_id": tool_call_id,
                })
            except Exception as e:
                error_message = f"调用工具 {tool_name} 时出错: {str(e)}"
                logger.error(f"❌ {error_message}")
                tool_results.append({
                    "role": "tool",
                    "content": f"Error: {error_message}",
                    "tool_call_id": tool_call_id,
                })
        
        return tool_results

    def _normalize_tool_call(self, tool_call):
        if isinstance(tool_call, dict):
            return tool_call["id"], tool_call["name"], tool_call["arguments"]
        return tool_call.id, tool_call.function.name, tool_call.function.arguments

    def _append_assistant_tool_calls(self, tool_calls: list[dict]):
        self.conversation_history.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tool_calls
                ],
            }
        )

    def _extract_text_tool_calls(self, text: str) -> list[dict]:
        buf = (text or "").strip()
        if not buf:
            return []
        if "arguments" not in buf:
            return []

        candidates: list[dict] = []

        code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", buf)
        for block in code_blocks:
            block = block.strip()
            if not block:
                continue
            candidates.extend(self._extract_text_tool_calls(block))

        for line in buf.splitlines():
            line = line.strip()
            if not line or line.startswith("```"):
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                    candidates.append(obj)
            except Exception:
                pass

        if not candidates:
            cleaned = buf.replace("```json", "").replace("```", "").strip()
            try:
                obj = json.loads(cleaned)
                if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                    candidates.append(obj)
            except Exception:
                pass

        result: list[dict] = []
        for obj in candidates:
            name = obj.get("name")
            arguments = obj.get("arguments", {})
            if not name:
                continue
            args_str = json.dumps(arguments, ensure_ascii=False) if isinstance(arguments, (dict, list)) else str(arguments)
            result.append({"id": f"call_{uuid.uuid4()}", "name": str(name), "arguments": args_str})

        return result

    def _decide_forced_action(self, user_query: str, assistant_text: str, forced_final_answer_attempted: bool) -> dict | None:
        if self._should_force_browser_search(user_query, assistant_text):
            return {
                "type": "tool",
                "name": "browser_use",
                "arguments": {
                    "url": self._build_search_url(user_query),
                    "action": f"搜索并用中文总结：{user_query}。优先给出清晰定义/要点，附上关键出处信息（网站/标题）。",
                },
                "notice": "[系统] 检测到模型未调用浏览器工具，已自动改用 browser_use 进行外部检索...",
            }

        if self._should_force_sensor_data(user_query, assistant_text):
            return {
                "type": "tool",
                "name": "get_sensor_data",
                "arguments": {},
                "notice": "[系统] 已自动获取传感器数据（get_sensor_data）...",
            }

        return None

    def _should_force_browser_search(self, user_query: str, assistant_text: str) -> bool:
        if "browser_use" not in self.tools_map:
            return False
        q = (user_query or "").lower()
        t = (assistant_text or "").lower()

        want_search = any(k in q for k in ["查一下", "搜索", "检索", "查找", "定义", "是什么", "什么意思"])
        refused = any(k in t for k in ["无法", "不能", "不可以"]) and any(
            k in t for k in ["外部", "搜索引擎", "网络请求", "联网", "浏览器"]
        )
        return want_search and refused

    def _build_search_url(self, query: str) -> str:
        return f"https://www.bing.com/search?q={quote_plus(query)}"

    async def _is_sse_endpoint_alive(self, url: str) -> bool:
        parsed = urlparse(url)
        if (parsed.scheme or "http").lower() not in {"http", "https"}:
            return False

        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if (parsed.scheme or "http").lower() == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=0.5)
        except Exception:
            return False

        try:
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Accept: text/event-stream\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            writer.write(request.encode("utf-8"))
            await writer.drain()

            status_line = await asyncio.wait_for(reader.readline(), timeout=0.5)
            return b" 200 " in status_line or status_line.startswith(b"HTTP/1.1 200")
        except Exception:
            return False
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    def _should_force_sensor_data(self, user_query: str, assistant_text: str) -> bool:
        q = user_query or ""
        t = (assistant_text or "")

        about_irrigation = any(k in q for k in ["灌溉", "浇水", "开泵", "需要水", "缺水"])
        if not about_irrigation:
            return False
        if "get_sensor_data" not in self.tools_map:
            return False
        if self._has_sensor_snapshot_since_last_user():
            return False

        user_asked_sensor = any(k in q for k in ["传感器", "土壤", "土壤湿度", "水分", "结合"])
        asking_sensor = any(k in t for k in ["土壤湿度", "传感器", "土壤水分"])
        return user_asked_sensor or asking_sensor

    def _has_sensor_snapshot_since_last_user(self) -> bool:
        last_user_idx = None
        for i in range(len(self.conversation_history) - 1, -1, -1):
            if self.conversation_history[i].get("role") == "user":
                last_user_idx = i
                break
        start = (last_user_idx + 1) if last_user_idx is not None else 0
        for msg in self.conversation_history[start:]:
            if msg.get("role") == "tool" and "土壤湿度" in (msg.get("content", "")):
                return True
        return False

    async def _maybe_wait_browser_use_result(self, session: ClientSession, result_content: str) -> str:
        try:
            data = json.loads(result_content)
        except Exception:
            return result_content

        task_id = data.get("task_id")
        status = data.get("status")
        if not task_id or status not in {"pending", "running"}:
            return result_content

        deadline = time.monotonic() + self.tool_timeout
        latest = data

        while time.monotonic() + 5 <= deadline:
            await asyncio.sleep(5)
            try:
                res = await asyncio.wait_for(
                    session.call_tool("browser_get_result", {"task_id": task_id}),
                    timeout=max(1, int(deadline - time.monotonic())),
                )
                txt = res.content[0].text
                latest = json.loads(txt)
                if latest.get("status") in {"completed", "failed"}:
                    break
            except Exception:
                break

        # 尝试提取对大模型更友好的文本结果
        if latest.get("status") == "completed":
            result_data = latest.get("result", {})
            # 优先使用 final_result (由 Agent 总结过的)
            final_text = result_data.get("final_result", "")
            if final_text:
                return f"[Browser Result]\n{final_text}"
            
            # 其次使用 extracted_content
            extracted = result_data.get("extracted_content", "")
            if extracted:
                 return f"[Browser Result (Raw Content)]\n{extracted}"
        
        if latest.get("status") == "failed":
            return f"[Browser Task Failed]\nError: {latest.get('error', 'Unknown error')}"

        try:
            return json.dumps(latest, ensure_ascii=False, indent=2)
        except Exception:
            return result_content

    async def _await_with_timeout(self, coro, timeout_seconds: int):
        if timeout_seconds is None:
            return await coro
        if hasattr(asyncio, "timeout"):
            async with asyncio.timeout(timeout_seconds):
                return await coro
        return await asyncio.wait_for(coro, timeout=timeout_seconds)

    async def call_tool(self, server_id: str, tool_name: str, tool_args: dict):
        """
        调用指定服务端的工具
        :param server_id: 服务端标识符
        :param tool_name: 工具名称
        :param tool_args: 工具参数
        """
        session_info = self.sessions.get(server_id)
        if not session_info:
            raise ValueError(f"服务端 {server_id} 未连接")
        session = session_info["session"]
        return await session.call_tool(tool_name, tool_args)

    
    async def chat_loop(self):
        """运行交互式聊天循环"""
        print("\n" + "="*60)
        print("🌾 智能农业决策助手已启动！")
        print("="*60)
        print("💡 提示：")
        print("  - 输入 'exit' 退出程序")
        print("  - 输入 'clear' 清空对话历史")
        print("="*60 + "\n")

        while True:
            try:
                # 使用更明显的提示符
                print("\n" + "-"*60)
                query = input("🤔 您的问题: ").strip()
                print("-"*60 + "\n")
                
                if query.lower() == 'exit':
                    print("👋 再见！")
                    break
                if query.lower() == 'clear':
                    self.conversation_history = [] # 清空历史
                    print("✅ 对话历史已清空。\n")
                    continue
                
                if not query:
                    print("⚠️  请输入问题\n")
                    continue

                response = await self.process_query(query)
                # logger.info(f"AI回复: {response}")

            except KeyboardInterrupt:
                print("\n\n👋 检测到中断信号，正在退出...")
                break
            except Exception as e:
                logger.error(f"发生错误: {str(e)}") # 改为 error 级别日志

    async def clean(self):
        """清理所有资源"""
        for server_id, stack in list(self._server_exit_stacks.items()):
            try:
                await stack.aclose()
            except Exception as e:
                msg = str(e)
                if "cancel scope" in msg:
                    logger.warning(f"清理服务端 {server_id} 资源时发生异常（已忽略）: {msg}")
                else:
                    logger.error(f"清理服务端 {server_id} 资源时发生错误: {msg}")

        for server_id, process in list(self._server_processes.items()):
            with suppress(Exception):
                await self._terminate_process(process)

        self._server_exit_stacks.clear()
        self._server_processes.clear()
        self.sessions.clear()
        self.tools_map.clear()
        self.conversation_history.clear()
        logger.info("[CLEAN] 已清理所有资源")


async def main():
    # 启动并初始化 MCP 客户端
    client = MCPClient()
    try:
        # 从配置文件加载 MCP 服务
        await client.load_servers_from_config("mcp_servers.json")
        # 列出 MCP 服务器上的工具
        await client.list_tools()
        # 运行交互式聊天循环，处理用户对话
        await client.chat_loop()
    finally:
        # 清理资源
        await client.clean()


if __name__ == "__main__":
    asyncio.run(main())
