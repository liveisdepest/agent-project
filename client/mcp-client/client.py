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
from prompts import ORCHESTRATOR_PROMPT, PERCEPTION_PROMPT, REASONING_PROMPT, ACTION_PROMPT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载 .env 文件
load_dotenv()

# SYSTEM_PROMPT Removed in favor of multi-agent prompts

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
        
        # 状态管理
        self.pending_decision = None
        
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

    async def load_servers_from_config(self, config_filename: str):
        """从配置文件加载服务器（支持失败跳过）
        
        Args:
            config_filename: 配置文件名，将自动解析为相对于脚本的绝对路径
        """
        # 获取脚本所在目录的绝对路径
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, config_filename)

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
            cwd = server_config.get("cwd", None)
            timeout = server_config.get("timeout", None)
            max_retries = server_config.get("max_retries", None)
            
            env = self._build_child_env(server_id, env_config)
            
            # 尝试连接，失败则跳过
            print(f"DEBUG: Attempting to connect to {server_id}...")
            if url:
                success = await self.connect_to_sse_server(
                    server_id,
                    url,
                    command=command,
                    args=args,
                    env=env,
                    cwd=cwd,
                    timeout=timeout,
                    max_retries=max_retries,
                )
            else:
                if not command:
                    logger.error(f"❌ 服务端 {server_id} 缺少 command/url 配置，跳过")
                    continue
                print(f"DEBUG: Connecting to local server {server_id} with command: {command} {args}")
                success = await self.connect_to_local_server(
                    server_id,
                    command,
                    args,
                    env,
                    cwd=cwd,
                    timeout=timeout,
                    max_retries=max_retries,
                )
            print(f"DEBUG: Connection to {server_id} result: {success}")
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

    async def _connect_with_retry(self, server_id: str, connect_func, max_retries: int, timeout: int):
        """统一的连接重试逻辑"""
        if server_id in self.sessions:
            logger.warning(f"服务端 {server_id} 已经连接，跳过")
            return True

        for attempt in range(max_retries):
            try:
                logger.info(f"正在连接 {server_id}... ({attempt + 1}/{max_retries})")
                await connect_func()
                logger.info(f"✅ 成功连接: {server_id}")
                return True
            except asyncio.TimeoutError:
                logger.error(f"❌ {server_id} 超时 ({attempt + 1}/{max_retries})")
            except Exception as e:
                import traceback
                logger.error(f"❌ {server_id} 失败 ({attempt + 1}/{max_retries}): {e}")
                logger.error(traceback.format_exc())
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"⏳ {wait_time}秒后重试 {server_id}...")
                await asyncio.sleep(wait_time)

        logger.error(f"🚫 {server_id} 连接失败，已达最大重试次数")
        return False

    async def connect_to_sse_server(
        self,
        server_id: str,
        url: str,
        command: str | None,
        args: list,
        env: dict,
        cwd: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ):
        timeout = timeout or self.connection_timeout
        max_retries = max_retries or self.max_retries

        async def _connect():
            attempt_stack = AsyncExitStack()
            process = None
            try:
                # 检查端点是否已存活
                should_start = command is not None
                if should_start:
                    try:
                        if await self._is_sse_endpoint_alive(url):
                            should_start = False
                    except Exception:
                        pass

                # 启动进程（如需要）
                if should_start:
                    process = await asyncio.create_subprocess_exec(command, *args, env=env, cwd=cwd)
                    self._server_processes[server_id] = process
                    
                    # 等待服务启动
                    start_time = time.monotonic()
                    while time.monotonic() - start_time < 10:
                        if await self._is_sse_endpoint_alive(url):
                            break
                        await asyncio.sleep(0.5)
                    else:
                         logger.warning(f"⚠️ 服务端 {server_id} 启动较慢，尝试直接连接...")

                # 建立连接
                transport = await attempt_stack.enter_async_context(
                    sse_client(url, timeout=5, sse_read_timeout=600)
                )
                read_stream, write_stream = transport
                session = await attempt_stack.enter_async_context(ClientSession(read_stream, write_stream))
                await asyncio.wait_for(session.initialize(), timeout=timeout)

                self._server_exit_stacks[server_id] = attempt_stack
                self.sessions[server_id] = {"session": session}
            except Exception:
                with suppress(Exception):
                    await attempt_stack.aclose()
                if process:
                    with suppress(Exception):
                        await self._terminate_process(process)
                    self._server_processes.pop(server_id, None)
                raise

        return await self._connect_with_retry(server_id, _connect, max_retries, timeout)

    async def connect_to_local_server(
        self,
        server_id: str,
        command: str,
        args: list,
        env: dict,
        cwd: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ):
        timeout = timeout or self.connection_timeout
        max_retries = max_retries or self.max_retries

        async def _connect():
            server_params = StdioServerParameters(
                command=command, 
                args=args, 
                env=env,
                cwd=cwd,
                encoding_error_handler="ignore"
            )
            attempt_stack = AsyncExitStack()
            try:
                stdio_transport = await attempt_stack.enter_async_context(stdio_client(server_params))
                stdio, write = stdio_transport
                session = await attempt_stack.enter_async_context(ClientSession(stdio, write))
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                
                self._server_exit_stacks[server_id] = attempt_stack
                self.sessions[server_id] = {"session": session}
            except Exception:
                with suppress(Exception):
                    await attempt_stack.aclose()
                raise

        return await self._connect_with_retry(server_id, _connect, max_retries, timeout)

    
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
    
    def _append_assistant_tool_calls(self, tool_calls: list[dict], history: list = None):
        target_history = history if history is not None else self.conversation_history
        target_history.append(
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

    async def _execute_agent_loop(self, messages: list, tools: list) -> str:
        """通用 Agent 执行循环"""
        tool_cycle_count = 0
        while True:
            # print(f"DEBUG: Sending messages to LLM: {json.dumps(messages, ensure_ascii=False, indent=2)}")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                max_tokens=8192,
                temperature=0.7,
                tools=tools if tools else None, # 如果没有工具，不传 tools 参数
            )

            final_content = ""
            has_tool_calls = False
            is_intercepted_json = False
            tool_calls = []
            json_buffer = ""

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta
                    try:
                        if delta.reasoning_content:
                            print("\033[92m" + delta.reasoning_content + "\033[0m", end="", flush=True)
                    except:
                        pass
                    if delta.content:
                        content = delta.content
                        print(content, end="", flush=True)
                        final_content += content
                        json_buffer += content
                    if delta.tool_calls:
                        has_tool_calls = True
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
                    logger.info(f"检测到 {len(extracted)} 个纯文本 JSON 工具调用")
                    tool_calls = extracted
                    has_tool_calls = True
                    is_intercepted_json = True

            if has_tool_calls:
                tool_cycle_count += 1
                if tool_cycle_count > 10:
                    return "系统检测到循环调用，已停止执行。"

                tool_results = await self._process_tool_calls(tool_calls)
                
                # 统一转换 tool_calls 为 dict 格式
                tool_calls_dicts = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tool_calls_dicts.append(tc)
                    else:
                        tool_calls_dicts.append({
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        })
                
                self._append_assistant_tool_calls(tool_calls_dicts, history=messages)
                messages.extend(tool_results)
                
                # Check for errors loop
                all_errors = True
                for result in tool_results:
                     if not result["content"].startswith("Error:"):
                         all_errors = False
                         break
                
                if all_errors:
                     return "工具调用失败，请检查参数或重试。"
                continue
            else:
                print()
                messages.append({"role": "assistant", "content": final_content})
                return final_content

    async def _run_perception_phase(self, query: str):
        print(f"\n📡 [Phase 1] 感知层启动...")
        # 工具名称可能带或不带前缀，根据实际加载情况匹配
        # 这里我们放宽匹配条件，只要包含 'get_irrigation_status' 或 'get_forecast_week' 即可
        target_tools = ['get_irrigation_status', 'get_forecast_week']
        tools = []
        
        all_tools = await self._build_tool_list()
        for t in all_tools:
            name = t['function']['name']
            # 检查名称是否完全匹配或作为后缀匹配（例如 weather.get_forecast_week）
            if any(name == target or name.endswith(f".{target}") for target in target_tools):
                tools.append(t)
                
        messages = [
            {"role": "system", "content": PERCEPTION_PROMPT},
            {"role": "user", "content": f"任务：获取当前环境状态。用户上下文：{query}"}
        ]
        return await self._execute_agent_loop(messages, tools)

    async def _run_reasoning_phase(self, query: str, perception_data: str):
        print(f"\n🧠 [Phase 2] 决策层启动...")
        # 启用 search 工具
        target_tools = ['search']
        tools = []
        
        all_tools = await self._build_tool_list()
        for t in all_tools:
            name = t['function']['name']
            if any(name == target or name.endswith(f".{target}") for target in target_tools):
                tools.append(t)

        messages = [
            {"role": "system", "content": REASONING_PROMPT},
            {"role": "user", "content": f"感知数据：\n{perception_data}\n\n用户请求：{query}"}
        ]
        return await self._execute_agent_loop(messages, tools)

    async def _run_action_phase(self, decision_json: dict):
        print(f"\n🚜 [Phase 3] 执行层启动...")
        tools = [t for t in await self._build_tool_list() if t['function']['name'] in ['start_irrigation']]
        messages = [
            {"role": "system", "content": ACTION_PROMPT},
            {"role": "user", "content": f"已确认决策：\n{json.dumps(decision_json, ensure_ascii=False)}\n\n用户已确认执行。请下发指令。"}
        ]
        return await self._execute_agent_loop(messages, tools)

    def _extract_json_from_response(self, text: str) -> dict | None:
        """从响应文本中提取 JSON 对象"""
        text = text.strip()
        
        # 1. 尝试提取 markdown 代码块（处理多个块的情况）
        code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        for block in code_blocks:
            try:
                # 尝试解析每个代码块，看是否包含决策结构
                data = json.loads(block.strip())
                if isinstance(data, dict) and ("decision" in data or "decision_reasoning" in data):
                    return data
            except json.JSONDecodeError:
                continue

        # 2. 尝试直接解析
        with suppress(json.JSONDecodeError):
            return json.loads(text)

        # 3. 尝试查找最外层的 {}
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
            
        return None

    async def process_query(self, query: str) -> str:
        # 0. 状态检查：是否在等待确认
        if self.pending_decision:
            if query.lower() in ['y', 'yes', '是', '确认', 'ok', '好的']:
                result = await self._run_action_phase(self.pending_decision)
                self.pending_decision = None
                return result
            else:
                self.pending_decision = None
                return "❌ 用户已取消灌溉操作。"

        # 1. 感知阶段
        perception_output = await self._run_perception_phase(query)
        # 简单验证输出是否看起来像 JSON
        if not perception_output.strip().startswith("{"):
             logger.warning(f"感知层输出格式可能不正确: {perception_output[:50]}...")

        # 2. 决策阶段
        reasoning_output = await self._run_reasoning_phase(query, perception_output)
        
        # 3. 解析决策并处理
        try:
            decision_json = self._extract_json_from_response(reasoning_output)
            
            if decision_json:
                # 提取自然语言总结（JSON 之前的部分）
                summary = reasoning_output[:reasoning_output.find("{")].strip()
                if summary:
                    print(f"\n{summary}\n")
                
                decision_core = decision_json.get("decision", {})
                reasoning_core = decision_json.get("decision_reasoning", {})

                if decision_core.get("irrigate") is True:
                    self.pending_decision = decision_core
                    
                    # 构造确认请求
                    confirm_msg = (
                        f"\n{'='*60}\n"
                        f"🌾 **智能灌溉决策报告**\n"
                        f"{'='*60}\n\n"
                        f"📊 **当前状态分析**\n"
                        f"   💧 水分胁迫评估: {reasoning_core.get('water_stress_assessment', 'N/A')}\n"
                        f"   🌤️  气象影响分析: {reasoning_core.get('weather_impact_analysis', 'N/A')}\n"
                        f"   🌱 作物需水分析: {reasoning_core.get('crop_demand_analysis', 'N/A')}\n\n"
                        f"💡 **决策建议**\n"
                        f"   ✅ 建议执行灌溉\n"
                        f"   💧 建议灌溉量: {decision_core.get('irrigation_amount_mm', 0)} mm\n"
                        f"   ⏱️ 建议时长: {decision_core.get('irrigation_duration_min', 0)} 分钟\n"
                        f"   🕒 执行时机: {decision_core.get('irrigation_time_window', '立即')}\n"
                        f"   📈 决策置信度: {decision_json.get('confidence_score', 0)*100:.0f}%\n\n"
                        f"📝 **节水策略**\n"
                        f"   {reasoning_core.get('water_saving_strategy', 'N/A')}\n"
                        f"\n{'='*60}\n"
                        f"❓ **是否立即执行灌溉？**\n"
                        f"   输入 'y' 或 '是' 确认执行\n"
                        f"   输入其他内容取消操作\n"
                        f"{'='*60}\n"
                    )
                    return confirm_msg
                else:
                    result = (
                        f"\n{'='*60}\n"
                        f"🌾 **智能灌溉决策报告**\n"
                        f"{'='*60}\n\n"
                        f"📊 **当前状态分析**\n"
                        f"   💧 水分胁迫评估: {reasoning_core.get('water_stress_assessment', 'N/A')}\n"
                        f"   🌤️  气象影响分析: {reasoning_core.get('weather_impact_analysis', 'N/A')}\n\n"
                        f"💡 **决策建议**\n"
                        f"   ✅ 无需灌溉\n"
                        f"   📈 决策置信度: {decision_json.get('confidence_score', 0)*100:.0f}%\n\n"
                        f"📝 **决策依据**\n"
                        f"   {reasoning_core.get('water_saving_strategy', 'N/A')}\n"
                        f"\n{'='*60}\n"
                    )
                    return result
            else:
                return f"⚠️ 决策层返回了非标准格式，请人工检查：\n{reasoning_output}"
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            return f"❌ 系统错误：无法解析决策结果\n错误: {str(e)}\n原始输出：{reasoning_output}\n\n调试信息:\n{error_detail}"




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
                logger.info(f"🔧 调用工具 {tool_name} (服务: {server_id}, 参数: {tool_args})")
                
                # 添加工具调用超时控制
                result = await asyncio.wait_for(session.call_tool(tool_name, tool_args), timeout=self.tool_timeout)
                
                result_content = result.content[0].text
                if tool_name == "browser-use":
                    # result_content = await self._maybe_wait_browser_use_result(session, result_content)
                    pass
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
