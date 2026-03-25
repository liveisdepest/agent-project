import asyncio
import argparse
import os
import sys
import time
import uuid
import re
from urllib.parse import urlparse
from openai import OpenAI
from dotenv import load_dotenv
from contextlib import AsyncExitStack, suppress
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
import json
import logging
from prompts import ORCHESTRATOR_PROMPT, PERCEPTION_PROMPT, REASONING_PROMPT, ACTION_PROMPT

# Configure logging to file and console
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server", "mcp")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "mcp_client.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def _configure_stdio_encoding():
    """Avoid runtime crashes on Windows GBK consoles when printing emoji/unicode."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


_configure_stdio_encoding()

# 如果需要调试，可以设置为 DEBUG
# logging.basicConfig(level=logging.DEBUG)

# 加载 .env 文件（优先从脚本所在目录加载）
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_env_path)

# SYSTEM_PROMPT Removed in favor of multi-agent promptsr of multi-agent prompts

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
        self.active_irrigation_task = None
        self.active_irrigation_context = None
        self.latest_perception_weather = None
        
        # 超时和重试配置
        self.connection_timeout = connection_timeout
        self.max_retries = max_retries
        self.tool_timeout = tool_timeout
        
        # 针对不同工具的专用超时配置
        self.tool_timeouts = {
            'weather': 30,      # 天气工具：30秒
            'search': 45,       # 搜索工具：45秒
            'fetch_content': 60, # 内容获取：60秒
            'irrigation': 15,   # 灌溉工具：15秒
            'sensor': 20,       # 传感器：20秒
            'default': tool_timeout  # 默认超时时间
        }
        
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

        # Check for OWM_API_KEY
        if not os.getenv("OWM_API_KEY"):
            logger.warning("⚠️  未找到 OWM_API_KEY。天气服务将无法获取数据。请在 .env 文件中配置 OWM_API_KEY。")

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
            logger.debug(f"Attempting to connect to {server_id}...")
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
                logger.debug(f"Connecting to local server {server_id} with command: {command} {args}")
                success = await self.connect_to_local_server(
                    server_id,
                    command,
                    args,
                    env,
                    cwd=cwd,
                    timeout=timeout,
                    max_retries=max_retries,
                )
            logger.debug(f"Connection to {server_id} result: {success}")
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
                logger.info(f"🚀 [{server_id}] 启动进程: {command} {' '.join(args)}")
                
                stdio_transport = await attempt_stack.enter_async_context(stdio_client(server_params))
                stdio, write = stdio_transport
                
                logger.info(f"📡 [{server_id}] 进程已启动，创建会话...")
                
                session = await attempt_stack.enter_async_context(ClientSession(stdio, write))
                
                logger.info(f"🔗 [{server_id}] 会话已创建，开始初始化...")
                
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                
                logger.info(f"✅ [{server_id}] 初始化完成")
                
                self._server_exit_stacks[server_id] = attempt_stack
                self.sessions[server_id] = {"session": session}
            except Exception as e:
                logger.error(f"❌ [{server_id}] 连接失败: {e}")
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
                logger.info(f"🔍 [{server_id}] 开始获取工具列表...")
                start_time = time.time()
                
                # 减少超时时间到 10 秒，更快发现问题
                response = await asyncio.wait_for(session.list_tools(), timeout=10)
                
                elapsed = time.time() - start_time
                tool_count = len(response.tools)
                
                for tool in response.tools:
                    self.tools_map[tool.name] = {
                        "server_id": server_id,
                        "description": tool.description,
                        "input_schema": tool.inputSchema
                    }
                    logger.info(f"  📧 工具: {tool.name}, 来源: {server_id}")
                
                logger.info(f"✅ [{server_id}] 加载了 {tool_count} 个工具 (耗时: {elapsed:.2f}秒)")
                successful_loads += 1
                
            except asyncio.TimeoutError:
                logger.error(f"❌ [{server_id}] 获取工具列表超时 (>10秒)")
            except Exception as e:
                logger.error(f"❌ [{server_id}] 获取工具列表时出错: {e}")
        
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
            # 调试：显示发送给 LLM 的消息
            logger.debug(f"📤 发送给 LLM 的消息数: {len(messages)}")
            for i, msg in enumerate(messages):
                role = msg.get("role", "unknown")
                if role == "tool":
                    content_preview = msg.get("content", "")[:50]
                    logger.debug(f"  [{i}] {role}: {content_preview}...")
                elif "tool_calls" in msg:
                    logger.debug(f"  [{i}] {role}: {len(msg['tool_calls'])} tool calls")
                else:
                    content_preview = msg.get("content", "")[:50]
                    logger.debug(f"  [{i}] {role}: {content_preview}...")
            
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

                print()  # 换行
                print(f"🔧 执行 {len(tool_calls)} 个工具调用...")
                logger.info(f"🔧 执行 {len(tool_calls)} 个工具调用...")
                
                tool_results = await self._process_tool_calls(tool_calls)
                
                # 显示工具结果摘要
                print(f"📥 收到 {len(tool_results)} 个工具结果:")
                for i, result in enumerate(tool_results, 1):
                    content = result["content"]
                    preview = content[:100] + "..." if len(content) > 100 else content
                    print(f"  ✅ 工具 {i} 返回: {preview}")
                    logger.info(f"  ✅ 工具 {i} 返回: {preview}")
                
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
                
                # 检查错误循环
                all_errors = True
                for result in tool_results:
                     if not result["content"].startswith("Error:"):
                         all_errors = False
                         break
                
                if all_errors:
                     return "工具调用失败，请检查参数或重试。"
                
                print(f"🔄 继续对话，等待 LLM 处理工具结果...\n")
                logger.info(f"🔄 继续对话，等待 LLM 处理工具结果...")
                continue
            else:
                print()
                messages.append({"role": "assistant", "content": final_content})
                return final_content

    async def _run_perception_phase(self, query: str):
        print(f"\n📡 [Phase 1] 感知层启动...")
        # 工具名称可能带或不带前缀，根据实际加载情况匹配
        target_tools = ['get_irrigation_status', 'get_forecast_week', 'get_forecast_48h', 'get_sensor_data', 'get_crop_info', 'list_devices', 'get_observe']
        tools = []
        
        all_tools = await self._build_tool_list()
        for t in all_tools:
            name = t['function']['name']
            # 检查名称是否完全匹配或作为后缀匹配（例如 weather.get_forecast_week）
            if any(name == target or name.endswith(f".{target}") for target in target_tools):
                tools.append(t)
        
        tool_names = [t['function']['name'] for t in tools]
        logger.info(f"感知层可用工具数: {len(tools)} -> {tool_names}")
        if len(tools) == 0:
            logger.warning("⚠️ 感知层无可用工具！请检查 sensor/weather/crop_knowledge MCP 服务是否已连接。运行 python client.py --init-only 可查看连接状态。")
                
        messages = [
            {"role": "system", "content": PERCEPTION_PROMPT},
            {"role": "user", "content": f"任务：获取当前环境状态。用户上下文：{query}\n\n请先调用 get_sensor_data、get_forecast_week、get_forecast_48h、get_observe、get_crop_info 获取数据，再输出 JSON。"}
        ]
        return await self._execute_agent_loop(messages, tools)

    async def _run_reasoning_phase(self, query: str, perception_data: str):
        print(f"\n🧠 [Phase 2] 决策层启动...")
        # 启用 search 工具 和 决策工具
        target_tools = ['search', 'make_irrigation_decision']
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
        target_tools = ['start_irrigation', 'get_irrigation_status']
        tools = []
        all_tools = await self._build_tool_list()
        for t in all_tools:
            name = t['function']['name']
            if any(name == target or name.endswith(f".{target}") for target in target_tools):
                tools.append(t)
        messages = [
            {"role": "system", "content": ACTION_PROMPT},
            {"role": "user", "content": f"已确认决策：\n{json.dumps(decision_json, ensure_ascii=False)}\n\n用户已确认执行。请下发指令。"}
        ]
        return await self._execute_agent_loop(messages, tools)

    def _parse_json_object(self, content: str) -> dict | None:
        """???????? JSON ???dict??"""
        raw = (content or "").strip()
        if not raw:
            return None

        with suppress(json.JSONDecodeError):
            data = json.loads(raw)
            if isinstance(data, dict):
                return data

        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            with suppress(json.JSONDecodeError):
                data = json.loads(raw[start:end])
                if isinstance(data, dict):
                    return data
        return None

    def _extract_json_from_response(self, text: str) -> dict | None:
        """?????????? JSON ???"""
        content = (text or "").strip()
        if not content:
            return None

        # 1. ???? markdown ?????????
        code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        for block in code_blocks:
            data = self._parse_json_object(block)
            if isinstance(data, dict) and ("decision" in data or "decision_reasoning" in data):
                return data

        # 2. ???????????
        return self._parse_json_object(content)

    def _extract_generic_json_object(self, text: str) -> dict | None:
        """??????????? JSON ???"""
        content = (text or "").strip()
        if not content:
            return None

        if "```json" in content or "```" in content:
            content = content.replace("```json", "").replace("```", "").strip()

        return self._parse_json_object(content)

    def _to_float_or_none(self, value) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _is_unknown_value(self, value) -> bool:
        if value is None:
            return True
        text = str(value).strip().lower()
        return text in {"", "unknown", "未知", "n/a", "null", "none", "--", "作物", "crop"}

    def _crop_aliases(self) -> dict:
        return {
            "番茄": "tomato",
            "西红柿": "tomato",
            "tomato": "tomato",
            "玉米": "corn",
            "corn": "corn",
            "小麦": "wheat",
            "wheat": "wheat",
            "菠萝": "pineapple",
            "凤梨": "pineapple",
            "pineapple": "pineapple",
        }

    def _normalize_crop_key(self, crop_name: str) -> str:
        key = (crop_name or "").strip().lower()
        aliases = self._crop_aliases()
        return aliases.get(key, key)

    def _crop_profiles(self) -> dict:
        return {
            "tomato": {
                "name": "番茄",
                "ideal_moisture": 60.0,
                "min_temp": 10.0,
                "max_temp": 35.0,
                "daily_light_hours": 7.0,
                "growth_stages": ["Seedling", "Vegetative", "Flowering", "Fruit Formation", "Ripening"],
                "water_needs": {
                    "Seedling": "Low",
                    "Vegetative": "Medium",
                    "Flowering": "High",
                    "Fruit Formation": "High",
                    "Ripening": "Medium"
                }
            },
            "corn": {
                "name": "玉米",
                "ideal_moisture": 70.0,
                "min_temp": 15.0,
                "max_temp": 35.0,
                "daily_light_hours": 8.0,
                "growth_stages": ["Germination", "Vegetative", "Tasseling", "Silking", "Grain Fill", "Maturity"],
                "water_needs": {
                    "Germination": "Medium",
                    "Vegetative": "High",
                    "Tasseling": "Very High",
                    "Silking": "Very High",
                    "Grain Fill": "High",
                    "Maturity": "Low"
                }
            },
            "wheat": {
                "name": "小麦",
                "ideal_moisture": 50.0,
                "min_temp": 5.0,
                "max_temp": 30.0,
                "daily_light_hours": 6.0,
                "growth_stages": ["Seedling", "Tillering", "Stem Extension", "Heading", "Ripening"],
                "water_needs": {
                    "Seedling": "Low",
                    "Tillering": "Medium",
                    "Stem Extension": "High",
                    "Heading": "High",
                    "Ripening": "Low"
                }
            },
            "pineapple": {
                "name": "菠萝",
                "ideal_moisture": 65.0,
                "min_temp": 18.0,
                "max_temp": 30.0,
                "daily_light_hours": 6.0,
                "growth_stages": ["Seedling", "Vegetative", "Flower Induction", "Fruit Development", "Maturity"],
                "water_needs": {
                    "Seedling": "Medium",
                    "Vegetative": "Medium",
                    "Flower Induction": "Medium",
                    "Fruit Development": "High",
                    "Maturity": "Medium"
                }
            }
        }

    def _extract_crop_from_query(self, query: str) -> str:
        q = (query or "").strip().lower()
        aliases = self._crop_aliases()
        for token, mapped in aliases.items():
            if token in q:
                return mapped
        return "wheat"

    def _normalize_perception_crop_payload(self, perception_output: str, query: str) -> str:
        payload = self._extract_generic_json_object(perception_output)
        if not isinstance(payload, dict):
            return perception_output

        crop = payload.get("crop_info")
        if not isinstance(crop, dict):
            crop = {}

        crop_name = crop.get("name", "")
        crop_key = self._normalize_crop_key(str(crop_name))
        profiles = self._crop_profiles()

        if crop_key not in profiles:
            crop_key = self._extract_crop_from_query(query)

        profile = profiles.get(crop_key, profiles["wheat"])
        normalized = dict(crop)

        if self._is_unknown_value(normalized.get("name")):
            normalized["name"] = profile["name"]

        field_map = {
            "ideal_moisture": "ideal_moisture",
            "min_temp": "min_temp",
            "max_temp": "max_temp",
            "daily_light_hours": "daily_light_hours",
        }
        for target, source in field_map.items():
            if self._is_unknown_value(normalized.get(target)):
                normalized[target] = profile[source]

        growth_stages = normalized.get("growth_stages")
        if not isinstance(growth_stages, list) or len(growth_stages) == 0:
            normalized["growth_stages"] = profile["growth_stages"]

        water_needs = normalized.get("water_needs")
        if not isinstance(water_needs, dict) or len(water_needs) == 0:
            normalized["water_needs"] = profile["water_needs"]

        payload["crop_info"] = normalized
        return json.dumps(payload, ensure_ascii=False)

    def _format_metric(self, value, unit: str = "") -> str:
        if self._is_unknown_value(value):
            return "未知"
        return f"{value}{unit}"

    def _format_range(self, min_value, max_value, unit: str = "") -> str:
        if self._is_unknown_value(min_value) or self._is_unknown_value(max_value):
            return "未知"
        return f"{min_value}-{max_value}{unit}"

    def _normalize_perception_weather_payload(self, perception_output: str) -> str:
        """归一化感知层天气标志，区分“晴天(0/0)”和“数据缺失”。"""
        payload = self._extract_generic_json_object(perception_output)
        if not isinstance(payload, dict):
            return perception_output

        rain_probability = self._to_float_or_none(payload.get("rain_probability"))
        expected_rainfall = self._to_float_or_none(payload.get("expected_rainfall"))
        precip_data_available = not (rain_probability is None and expected_rainfall is None)

        flags_raw = payload.get("flags", [])
        if isinstance(flags_raw, list):
            flags = [str(item) for item in flags_raw]
        elif flags_raw is None:
            flags = []
        else:
            flags = [str(flags_raw)]

        if precip_data_available:
            # 只要降水字段可用（包括 0），就不是天气缺失
            normalized_flags = [f for f in flags if f != "weather_unavailable"]
        else:
            # 两个关键降水字段都缺失时，标记天气缺失
            normalized_flags = list(flags)
            if "weather_unavailable" not in normalized_flags:
                normalized_flags.append("weather_unavailable")

        if normalized_flags != flags:
            payload["flags"] = normalized_flags
            return json.dumps(payload, ensure_ascii=False)

        return perception_output

    def _update_weather_context_from_perception(self, perception_output: str) -> None:
        """
        根据感知层 JSON 缓存天气可用性。
        规则：降水概率与预期降水量都缺失才算天气缺失。
        """
        self.latest_perception_weather = None
        payload = self._extract_generic_json_object(perception_output)
        if not isinstance(payload, dict):
            return

        flags_raw = payload.get("flags", [])
        if isinstance(flags_raw, list):
            flags = {str(item) for item in flags_raw}
        elif flags_raw is None:
            flags = set()
        else:
            flags = {str(flags_raw)}

        rain_probability = self._to_float_or_none(payload.get("rain_probability"))
        expected_rainfall = self._to_float_or_none(payload.get("expected_rainfall"))
        weather_unavailable = "weather_unavailable" in flags

        precip_data_available = not (rain_probability is None and expected_rainfall is None)
        weather_available = precip_data_available
        clear_sky = (
            rain_probability is not None and rain_probability == 0 and
            expected_rainfall is not None and expected_rainfall == 0
        )

        self.latest_perception_weather = {
            "weather_available": weather_available,
            "precip_data_available": precip_data_available,
            "clear_sky": clear_sky,
            "weather_unavailable_flag": weather_unavailable,
            "rain_probability": rain_probability,
            "expected_rainfall": expected_rainfall,
        }

    def _weather_context_text(self) -> str:
        """Build a weather summary based on latest perception payload."""
        weather_ctx = self.latest_perception_weather or {}
        weather_missing_msg = "天气数据缺失，无法获取降雨预报。"

        if weather_ctx.get("weather_available"):
            rain_probability = self._to_float_or_none(weather_ctx.get("rain_probability"))
            expected_rainfall = self._to_float_or_none(weather_ctx.get("expected_rainfall"))
            rain_probability = 0.0 if rain_probability is None else rain_probability
            expected_rainfall = 0.0 if expected_rainfall is None else expected_rainfall

            if weather_ctx.get("clear_sky"):
                return "天气预报已获取：降雨概率 0%，预计降雨量 0.0 mm，可判断为晴天。"

            return (
                f"天气预报已获取：降雨概率 {rain_probability:.0f}% ，"
                f"预计降雨量 {expected_rainfall:.1f} mm。"
            )

        return weather_missing_msg

    def _normalize_weather_claims_in_text(self, text: str) -> str:
        """Fix contradictory weather wording in free-text reasoning output."""
        content = (text or "").strip()
        if not content:
            return content

        weather_ctx = self.latest_perception_weather or {}
        weather_available = bool(weather_ctx.get("weather_available"))
        missing_a = "\u5929\u6c14\u6570\u636e\u7f3a\u5931"
        missing_b = "\u65e0\u6cd5\u83b7\u53d6\u964d\u96e8\u9884\u62a5"
        missing_claim = (missing_a in content) or (missing_b in content)

        if weather_available and missing_claim:
            weather_line = self._weather_context_text()
            content = content.replace(missing_a, "").replace(missing_b, "")
            content = content.replace("??", "?")
            while "\n\n\n" in content:
                content = content.replace("\n\n\n", "\n\n")
            content = content.strip()

            weather_impact = "\u5929\u6c14\u5f71\u54cd"
            if weather_impact in content:
                import re as _re
                content = _re.sub(rf"({weather_impact}[?:])\s*[^\n\r]*", rf"\1{weather_line}", content)
            else:
                content = f"{content}\n{weather_impact}?{weather_line}" if content else f"{weather_impact}?{weather_line}"

        return content

    def _summary_has_conflict(self, text: str, irrigate: bool, enforce_weather_context: bool = False) -> bool:
        content = (text or "").strip()
        if not content:
            return False

        positive_tokens = [
            "\u5efa\u8bae\u6267\u884c\u704c\u6e89",
            "\u7acb\u5373\u704c\u6e89",
            "\u5efa\u8bae\u704c\u6e89",
            "\u8f7b\u5ea6\u704c\u6e89",
            "?????????",
            "??????",
            "??????",
            "??????",
        ]
        negative_tokens = [
            "\u6682\u4e0d\u704c\u6e89",
            "\u65e0\u9700\u704c\u6e89",
            "\u4e0d\u5efa\u8bae\u704c\u6e89",
            "\u5148\u89c2\u5bdf\u4e0d\u704c\u6e89",
            "??????",
            "??????",
            "????????",
            "?????????",
        ]
        has_pos = any(t in content for t in positive_tokens)
        has_neg = any(t in content for t in negative_tokens)

        direction_conflict = (irrigate and has_neg) or ((not irrigate) and has_pos)

        weather_missing_a = "天气数据缺失"
        weather_missing_b = "无法获取降雨预报"
        no_rain_terms = [
            "\u65e0\u964d\u96e8\u9884\u62a5",
            "\u6ca1\u6709\u964d\u96e8\u9884\u62a5",
            "\u4e0d\u964d\u96e8",
            "\u4eca\u5929\u65e0\u96e8",
            "\u660e\u65e5\u65e0\u96e8",
            "????????",
            "?????????",
            "?????",
        ]
        weather_conflict = ((weather_missing_a in content) and (weather_missing_b in content) and any(t in content for t in no_rain_terms))

        weather_availability_conflict = False
        if enforce_weather_context:
            weather_ctx = self.latest_perception_weather or {}
            if weather_ctx.get("weather_available") and ((weather_missing_a in content) or (weather_missing_b in content)):
                weather_availability_conflict = True

        return direction_conflict or weather_conflict or weather_availability_conflict

    def _sanitize_weather_text(self, text: str) -> str:
        content = (text or "").strip()
        weather_ctx = self.latest_perception_weather or {}
        weather_missing_a = "天气数据缺失"
        weather_missing_b = "无法获取降雨预报"
        plain = re.sub(r"[，。！？；：、,.!?;:\s]", "", content)

        if not content or not plain:
            return self._weather_context_text()

        if weather_ctx.get("weather_available"):
            if weather_missing_a in content or weather_missing_b in content:
                return self._weather_context_text()
            return content

        if weather_missing_a in content or weather_missing_b in content:
            for token in ["\u65e0\u964d\u96e8\u9884\u62a5", "\u6ca1\u6709\u964d\u96e8\u9884\u62a5", "\u4e0d\u964d\u96e8", "\u4eca\u5929\u65e0\u96e8", "\u660e\u65e5\u65e0\u96e8"]:
                content = content.replace(token, "")
            return "天气数据缺失，无法获取降雨预报。"

        return content

    def _build_consistent_summary(
        self,
        decision_core: dict,
        reasoning_core: dict,
        confidence_score: float
    ) -> str:
        irrigate = bool(decision_core.get("irrigate"))
        weather_text = self._sanitize_weather_text(reasoning_core.get("weather_impact_analysis", ""))
        reason_text = (reasoning_core.get("water_saving_strategy", "") or "结合现有数据采取保守策略。").strip()
        reason_text = self._align_reason_text_with_decision(reason_text, irrigate)
        water_text = (reasoning_core.get("water_stress_assessment", "") or "").strip()
        if not water_text:
            water_text = "已根据当前土壤湿度、温度与天气信息完成综合评估。"

        if irrigate:
            return (
                "💬 专家分析\n\n"
                f"{water_text} {weather_text}\n\n"
                "📋 具体建议\n\n"
                "✅ 建议执行灌溉\n"
                f"• 灌溉量：{decision_core.get('irrigation_amount_mm', 0)} mm\n"
                f"• 灌溉时长：{decision_core.get('irrigation_duration_min', 0)} 分钟\n"
                f"• 最佳时机：{decision_core.get('irrigation_time_window', '立即')}\n"
                f"• 主要理由：{reason_text}\n"
                f"• 决策置信度：{confidence_score*100:.0f}%"
            )

        return (
            "💬 专家分析\n\n"
            f"{water_text} {weather_text}\n\n"
            "📋 具体建议\n\n"
            "❌ 暂不灌溉\n"
            f"• 系统建议：{decision_core.get('action_label', '暂不灌溉')}\n"
            f"• 主要理由：{reason_text}\n"
            f"• 天气影响：{weather_text}\n"
            f"• 复检计划：{decision_core.get('recheck_after_min', 60)} 分钟后复检"
        )

    async def _call_tool_direct(self, tool_name: str, tool_args: dict) -> str:
        """直接调用工具并返回文本结果。"""
        tool_call = {
            "id": f"manual_{uuid.uuid4().hex[:8]}",
            "name": tool_name,
            "arguments": json.dumps(tool_args or {}, ensure_ascii=False)
        }
        result = await self._execute_single_tool(tool_call)
        return result.get("content", "")

    def _align_reason_text_with_decision(self, reason_text: str, irrigate: bool) -> str:
        content = (reason_text or "").strip()
        if not content:
            return "当前缺水明显，建议先小水补灌并复检。" if irrigate else "当前先监测并复检后再决定是否灌溉。"
        positive_tokens = ["建议执行灌溉", "立即灌溉", "建议灌溉"]
        negative_tokens = ["暂不灌溉", "无需灌溉", "不建议灌溉", "先观察不灌溉", "提高后再灌溉", "湿度提高后再灌溉"]
        has_pos = any(t in content for t in positive_tokens)
        has_neg = any(t in content for t in negative_tokens)
        if irrigate and has_neg and not has_pos:
            return "当前缺水明显，建议先小水补灌并复检。"
        if (not irrigate) and has_pos and not has_neg:
            return "当前先监测并复检后再决定是否灌溉。"
        if irrigate and has_neg and has_pos:
            return "当前缺水明显，建议先小水补灌并复检。"
        if (not irrigate) and has_pos and has_neg:
            return "当前先监测并复检后再决定是否灌溉。"
        return content

    def _extract_decision_from_plain_text(self, text: str) -> dict | None:
        """从非结构化文本中尝试提取决策信息"""
        content = (text or "").strip()
        if not content:
            return None
            
        decision = {}
        positive_tokens = ["建议执行灌溉", "立即灌溉", "建议灌溉"]
        negative_tokens = ["暂不灌溉", "无需灌溉", "不建议灌溉", "先观察不灌溉"]
        has_pos = any(t in content for t in positive_tokens)
        has_neg = any(t in content for t in negative_tokens)

        if has_pos and not has_neg:
            decision["irrigate"] = True
        elif has_neg and not has_pos:
            decision["irrigate"] = False
        elif has_pos and has_neg:
            tail = content
            marker = content.rfind("📋 具体建议")
            if marker != -1:
                tail = content[marker:]
            if "✅ 建议执行灌溉" in tail:
                decision["irrigate"] = True
            elif "❌ 暂不灌溉" in tail:
                decision["irrigate"] = False
            else:
                pos_idx = max((tail.rfind(t) for t in positive_tokens), default=-1)
                neg_idx = max((tail.rfind(t) for t in negative_tokens), default=-1)
                if pos_idx == neg_idx:
                    return None
                decision["irrigate"] = pos_idx > neg_idx
        else:
            return None
            
        # 尝试提取数值
        # 灌溉量
        amount_match = re.search(r"灌溉量[：:]\s*(\d+(?:\.\d+)?)", content)
        if amount_match:
            decision["irrigation_amount_mm"] = float(amount_match.group(1))
            
        # 灌溉时长
        duration_match = re.search(r"灌溉时长[：:]\s*(\d+)", content)
        if duration_match:
            decision["irrigation_duration_min"] = int(duration_match.group(1))
            
        # 决策建议
        action_match = re.search(r"系统建议[：:]\s*([^\n]+)", content)
        if action_match:
            decision["action_label"] = action_match.group(1).strip()
            
        return decision

    def _extract_soil_moisture(self, status_text: str) -> float | None:
        match = re.search(r"土壤湿度:\s*([0-9]+(?:\.[0-9]+)?)%", status_text or "")
        if match:
            return float(match.group(1))
        return None

    def _extract_pump_status(self, status_text: str) -> str:
        match = re.search(r"水泵状态:\s*([^\n\r]+)", status_text or "")
        if match:
            return match.group(1).strip()
        return "未知"

    def _is_irrigation_status_query(self, query: str) -> bool:
        q = (query or "").strip().lower()
        specific_keywords = ["灌溉状态", "监测数据", "当前湿度", "水泵状态", "灌溉进展"]
        if any(k in q for k in specific_keywords):
            return True
        return ("状态" in q) and (self.active_irrigation_context is not None)

    def _resolve_target_moisture(self, decision: dict) -> float:
        target = decision.get("target_soil_moisture_pct")
        if target is not None:
            try:
                return float(target)
            except Exception:
                pass

        target_range = decision.get("target_moisture_range_pct")
        if isinstance(target_range, dict):
            if target_range.get("ideal") is not None:
                try:
                    return float(target_range["ideal"])
                except Exception:
                    pass
            if target_range.get("max") is not None:
                try:
                    return float(target_range["max"])
                except Exception:
                    pass
            if target_range.get("min") is not None:
                try:
                    return float(target_range["min"])
                except Exception:
                    pass

        return 50.0

    async def _monitor_and_auto_stop(
        self,
        target_moisture: float,
        interval_sec: int,
        max_duration_sec: int
    ):
        """后台监测土壤湿度，达到目标后自动停泵。"""
        start_ts = time.time()
        try:
            while True:
                status_text = await self._call_tool_direct("get_irrigation_status", {})
                moisture = self._extract_soil_moisture(status_text)
                pump_status = self._extract_pump_status(status_text)
                now_str = time.strftime("%Y-%m-%d %H:%M:%S")

                if self.active_irrigation_context is not None:
                    self.active_irrigation_context["last_status_text"] = status_text
                    self.active_irrigation_context["last_soil_moisture"] = moisture
                    self.active_irrigation_context["last_pump_status"] = pump_status
                    self.active_irrigation_context["history"].append({
                        "time": now_str,
                        "soil_moisture": moisture,
                        "pump_status": pump_status,
                    })

                elapsed = int(time.time() - start_ts)
                reached_target = moisture is not None and moisture >= target_moisture
                reached_timeout = elapsed >= max_duration_sec

                if reached_target or reached_timeout:
                    stop_result = await self._call_tool_direct("stop_irrigation", {})
                    reason = "target_reached" if reached_target else "max_duration_reached"
                    if self.active_irrigation_context is not None:
                        self.active_irrigation_context["finished"] = True
                        self.active_irrigation_context["finish_reason"] = reason
                        self.active_irrigation_context["stop_result"] = stop_result
                        self.active_irrigation_context["stopped_at"] = now_str
                    break

                await asyncio.sleep(interval_sec)
        except Exception as e:
            logger.error(f"自动监测任务异常: {e}")
            stop_result = await self._call_tool_direct("stop_irrigation", {})
            if self.active_irrigation_context is not None:
                self.active_irrigation_context["finished"] = True
                self.active_irrigation_context["finish_reason"] = "monitor_error_auto_stopped"
                self.active_irrigation_context["stop_result"] = stop_result
                self.active_irrigation_context["error"] = str(e)
        finally:
            self.active_irrigation_task = None

    async def _start_irrigation_with_auto_monitor(self, decision: dict) -> str:
        """启动灌溉并开启后台监测，达到理想湿度自动关泵。"""
        duration = int(decision.get("irrigation_duration_min", 15) or 15)
        duration = max(1, duration)
        target_moisture = self._resolve_target_moisture(decision)

        start_result = await self._call_tool_direct(
            "start_irrigation",
            {"zone": "zone_1", "duration_minutes": duration}
        )
        if start_result.startswith("Error:") or "Failed to start irrigation" in start_result:
            return f"❌ 开启水泵失败：{start_result}"

        # 如果已有监测任务，先取消旧任务
        if self.active_irrigation_task and not self.active_irrigation_task.done():
            self.active_irrigation_task.cancel()

        self.active_irrigation_context = {
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "target_moisture": target_moisture,
            "planned_duration_min": duration,
            "finished": False,
            "finish_reason": "",
            "stop_result": "",
            "last_status_text": "",
            "last_soil_moisture": None,
            "last_pump_status": "未知",
            "history": [],
        }

        # 监测频率 15 秒；最长运行到建议时长后自动停泵
        self.active_irrigation_task = asyncio.create_task(
            self._monitor_and_auto_stop(
                target_moisture=target_moisture,
                interval_sec=15,
                max_duration_sec=duration * 60
            )
        )

        first_status = await self._call_tool_direct("get_irrigation_status", {})
        first_moisture = self._extract_soil_moisture(first_status)

        return (
            f"✅ 已收到“打开”指令，水泵已开启。\n"
            f"🎯 目标土壤湿度：{target_moisture:.1f}%\n"
            f"⏱️ 计划运行时长：{duration} 分钟（达到目标会提前自动停泵）\n"
            f"📡 当前土壤湿度：{first_moisture if first_moisture is not None else '未知'}%\n"
            f"你可以随时发送“灌溉状态”查看动态监测。"
        )

    def _format_irrigation_status(self) -> str:
        if not self.active_irrigation_context:
            return "当前没有正在执行的自动灌溉任务。"

        ctx = self.active_irrigation_context
        latest_m = ctx.get("last_soil_moisture")
        latest_p = ctx.get("last_pump_status", "未知")
        finished = ctx.get("finished", False)

        if not finished:
            return (
                f"📡 灌溉进行中\n"
                f"• 开始时间：{ctx.get('started_at')}\n"
                f"• 目标湿度：{ctx.get('target_moisture')}%\n"
                f"• 当前湿度：{latest_m if latest_m is not None else '未知'}%\n"
                f"• 水泵状态：{latest_p}\n"
                f"• 采样次数：{len(ctx.get('history', []))}"
            )

        reason = ctx.get("finish_reason", "unknown")
        reason_text = {
            "target_reached": "已达到理想湿度，自动停泵",
            "max_duration_reached": "达到计划时长，自动停泵",
            "monitor_error_auto_stopped": "监测异常，已安全停泵"
        }.get(reason, reason)
        return (
            f"✅ 灌溉任务已结束\n"
            f"• 结束原因：{reason_text}\n"
            f"• 目标湿度：{ctx.get('target_moisture')}%\n"
            f"• 最后湿度：{latest_m if latest_m is not None else '未知'}%\n"
            f"• 停泵结果：{ctx.get('stop_result', 'N/A')}"
        )

    async def _handle_manual_control(self, query: str) -> str | None:
        """处理手动控制指令"""
        q = query.strip()
        if q == "手动开启":
             # 默认开启15分钟，目标湿度70%
             decision = {
                 "irrigation_duration_min": 15,
                 "target_soil_moisture_pct": 70.0
             }
             return await self._start_irrigation_with_auto_monitor(decision)
        elif q == "手动关闭":
             res = await self._call_tool_direct("stop_irrigation", {})
             if self.active_irrigation_task:
                 self.active_irrigation_task.cancel()
                 self.active_irrigation_task = None
             if self.active_irrigation_context:
                 self.active_irrigation_context["finished"] = True
                 self.active_irrigation_context["finish_reason"] = "manual_stop"
                 self.active_irrigation_context["stop_result"] = res
             return f"✅ 水泵已手动关闭。\n{res}"
        return None

    async def _handle_confirmation(self, query: str) -> str | None:
        """处理待确认的决策请求"""
        if not self.pending_decision:
            return None
            
        q = query.lower().strip()
        positive_keywords = ['y', 'yes', '是', '确认', 'ok', '好的', '打开', '开启', 'open', 'start']
        
        if q in positive_keywords:
            result = await self._start_irrigation_with_auto_monitor(self.pending_decision)
            self.pending_decision = None
            return result
        else:
            self.pending_decision = None
            return "❌ 用户已取消灌溉操作。"

    async def process_query(self, query: str) -> str:
        # 1. 检查是否为状态查询
        if self._is_irrigation_status_query(query):
            return self._format_irrigation_status()

        # 1.5. 检查是否为手动控制
        if manual_result := await self._handle_manual_control(query):
            return manual_result

        # 2. 检查是否为确认操作
        if confirmation_result := await self._handle_confirmation(query):
            return confirmation_result

        # 3. 执行感知阶段
        self.latest_perception_weather = None
        perception_output = await self._run_perception_phase(query)

        # 简单验证输出并清理 Markdown
        if not perception_output.strip().startswith("{"):
             logger.warning(f"感知层输出格式可能不正确: {perception_output[:50]}...")
        if "```json" in perception_output:
            perception_output = perception_output.replace("```json", "").replace("```", "").strip()

        perception_output = self._normalize_perception_crop_payload(perception_output, query)
        perception_output = self._normalize_perception_weather_payload(perception_output)
        self._update_weather_context_from_perception(perception_output)

        # 4. 执行决策阶段
        reasoning_output = await self._run_reasoning_phase(query, perception_output)

        # 5. 解析决策结果
        return await self._process_decision_result(reasoning_output, perception_output)

    async def _process_decision_result(self, reasoning_output: str, perception_output: str = "{}") -> str:
        """处理决策层的输出结果"""
        try:
            decision_json = self._extract_json_from_response(reasoning_output)
            
            if decision_json:
                return self._handle_structured_decision(decision_json, reasoning_output, perception_output)
            else:
                return self._handle_unstructured_decision(reasoning_output, perception_output)

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            return f"❌ 系统错误：无法解析决策结果\n错误: {str(e)}\n原始输出：{reasoning_output}\n\n调试信息:\n{error_detail}"

    def _handle_structured_decision(self, decision_json: dict, original_output: str, perception_output: str = "{}") -> str:
        """处理结构化的 JSON 决策"""
        decision_core = decision_json.get("decision", {})
        reasoning_core = decision_json.get("decision_reasoning", {})

        # 尝试提取自然语言总结
        brace_index = original_output.find("{")
        summary = original_output[:brace_index].strip() if brace_index != -1 else ""
        summary = summary.replace("```json", "").replace("```", "").strip()

        final_explanation = summary if summary else f"???????????????? {reasoning_core.get('water_stress_assessment', 'N/A')}?"
        final_explanation = self._normalize_weather_claims_in_text(final_explanation)

        # 检查总结与决策是否一致，必要时重新生成总结
        if self._summary_has_conflict(
            final_explanation,
            bool(decision_core.get("irrigate")),
            enforce_weather_context=True
        ):
            confidence = float(decision_json.get("confidence_score", 0.8))
            final_explanation = self._build_consistent_summary(decision_core, reasoning_core, confidence)

        if decision_core.get("irrigate") is True:
            self.pending_decision = decision_core
            return self._format_irrigation_proposal(final_explanation, decision_core, decision_json.get("confidence_score", 0.8), reasoning_core, perception_output)
        else:
            return self._format_no_irrigation_report(final_explanation, decision_json.get("confidence_score", 0.8), reasoning_core, perception_output)

    def _handle_unstructured_decision(self, text: str, perception_output: str = "{}") -> str:
        """处理非结构化决策"""
        plain_decision = self._extract_decision_from_plain_text(text)
        normalized_text = self._normalize_weather_claims_in_text(text)

        if plain_decision:
            irrigate = plain_decision.get("irrigate", False)
            if self._summary_has_conflict(normalized_text, bool(irrigate), enforce_weather_context=True):
                reasoning = {
                    "water_stress_assessment": "已从非结构化输出中提取动作建议，并完成一致性修正。",
                    "weather_impact_analysis": self._weather_context_text(),
                    "water_saving_strategy": self._align_reason_text_with_decision("", bool(irrigate)),
                }
                normalized_text = self._build_consistent_summary(plain_decision, reasoning, 0.8)
            if irrigate:
                self.pending_decision = plain_decision
                return self._format_irrigation_proposal(normalized_text, plain_decision, 0.8, {}, perception_output)
            return self._format_no_irrigation_report(normalized_text, 0.8, {}, perception_output)

        # 兜底逻辑：如果无法提取结构化信息，直接返回处理后的文本
        if self._summary_has_conflict(normalized_text, False, enforce_weather_context=True) or self._summary_has_conflict(normalized_text, True, enforce_weather_context=True):
            return (
                "⚠️ 系统检测到决策建议存在冲突，请重新发起查询。\n"
                "建议检查天气数据源是否正常。"
            )

        return normalized_text

    def _build_report_header(self, perception_output: str) -> str:
        try:
            data = self._parse_json_object(perception_output) or {}
        except:
            data = {}

        # Line 1: Soil sensor data, Temperature, Humidity
        soil_moisture = data.get("soil_moisture", "N/A")
        air_temp = data.get("air_temperature", "N/A")
        air_humidity = data.get("air_humidity", "N/A")
        line1 = f"📊 **环境监测**: 土壤湿度 {soil_moisture}% | 气温 {air_temp}°C | 空气湿度 {air_humidity}%"

        # Line 2: Crop growth habits
        crop = data.get("crop_info", {})
        crop_name = crop.get("name", "作物")
        ideal_moisture = self._format_metric(crop.get("ideal_moisture", "未知"), "%")
        min_temp = crop.get("min_temp", "未知")
        max_temp = crop.get("max_temp", "未知")
        temp_range = self._format_range(min_temp, max_temp, "°C")
        light = self._format_metric(crop.get("daily_light_hours", "未知"), "小时")
        optimal_air_humidity_min = crop.get("optimal_air_humidity_min", "未知")
        optimal_air_humidity_max = crop.get("optimal_air_humidity_max", "未知")
        humidity_range = self._format_range(optimal_air_humidity_min, optimal_air_humidity_max, "%")
        soil_ph_min = crop.get("soil_ph_min", "未知")
        soil_ph_max = crop.get("soil_ph_max", "未知")
        soil_ph_range = self._format_range(soil_ph_min, soil_ph_max)

        growth_stages = crop.get("growth_stages", [])
        if isinstance(growth_stages, list) and len(growth_stages) > 0:
            stage_text = " / ".join([str(s) for s in growth_stages])
        else:
            stage_text = "未知"

        water_needs = crop.get("water_needs", {})
        if isinstance(water_needs, dict) and len(water_needs) > 0:
            pairs = []
            if isinstance(growth_stages, list) and len(growth_stages) > 0:
                for stage in growth_stages:
                    need = water_needs.get(str(stage))
                    if need:
                        pairs.append(f"{stage}:{need}")
            else:
                for stage, need in water_needs.items():
                    pairs.append(f"{stage}:{need}")
            water_need_text = " | ".join(pairs) if pairs else "未知"
        else:
            water_need_text = "未知"

        line2 = (
            f"🌱 **作物习性 ({crop_name})**: 适宜湿度 {ideal_moisture} | 适宜温度 {temp_range} | 光照 {light}\n"
            f"   适宜空气湿度 {humidity_range} | 适宜土壤pH {soil_ph_range}\n"
            f"   生长阶段 {stage_text} | 需水特征 {water_need_text}"
        )

        # Line 3: Weather conditions (48h forecast)
        forecast_48h = data.get("forecast_48h")
        if not forecast_48h:
             # Fallback
             rain_prob = data.get("rain_probability", 0)
             rain_amount = data.get("expected_rainfall", 0)
             line3 = f"🌦️ **天气情况**: 未来48小时预报数据缺失 (当前预测: 降雨概率 {rain_prob}%, 降雨量 {rain_amount}mm)"
        else:
             summary_parts = []
             if isinstance(forecast_48h, list):
                 # Show first few entries to keep it concise
                 for item in forecast_48h[:5]: 
                     time_str = item.get("time", "")[11:16]
                     temp = item.get("temperature", "")
                     weather = item.get("weather", "")
                     summary_parts.append(f"{time_str} {temp}°C {weather}")
                 line3 = f"🌦️ **天气情况 (未来48h)**: {' | '.join(summary_parts)} ..."
             else:
                 line3 = f"🌦️ **天气情况**: {str(forecast_48h)}"
        
        return f"{line1}\n{line2}\n{line3}"

    def _format_irrigation_proposal(self, explanation: str, decision: dict, confidence: float, reasoning: dict, perception_output: str = "{}") -> str:
        """格式化灌溉建议报告"""
        header = self._build_report_header(perception_output)
        
        irrigation_msg = (
            f"💡 **智能建议**: {explanation}\n\n"
            f"⚠️ **系统提示**: 当前{decision.get('action_label', '需要灌溉')}，请确认。\n"
            f"   回复 '确认' / '打开' -> 开启水泵\n"
            f"   回复 '取消' -> 不执行操作"
        )
        
        return f"{header}\n\n{irrigation_msg}"

    def _format_no_irrigation_report(self, explanation: str, confidence: float, reasoning: dict, perception_output: str = "{}") -> str:
        """格式化无需灌溉报告"""
        header = self._build_report_header(perception_output)
        
        irrigation_msg = (
            f"💡 **智能建议**: {explanation}\n\n"
            f"🔧 **手动操作**:\n"
            f"   手动开启     手动关闭\n"
            f"   (回复 '手动开启' -> 打开水泵，回复 '手动关闭' -> 关闭水泵)"
        )
        
        return f"{header}\n\n{irrigation_msg}"




    async def _execute_single_tool(self, tool_call) -> dict:
        """执行单个工具调用，带重试机制"""
        tool_call_id, tool_name, tool_args_str = self._normalize_tool_call(tool_call)

        try:
            tool_args = json.loads(tool_args_str)
        except json.JSONDecodeError:
            logger.error(f"无法解析工具参数 JSON: {tool_args_str}")
            return {
                "role": "tool",
                "content": f"Error: Invalid JSON arguments received: {tool_args_str}",
                "tool_call_id": tool_call_id,
            }

        tool_info = self.tools_map.get(tool_name)
        
        # 尝试处理带有前缀的工具名 (e.g. "sensor.get_sensor_data" -> "get_sensor_data")
        if not tool_info and "." in tool_name:
            short_name = tool_name.split(".")[-1]
            tool_info = self.tools_map.get(short_name)
            if tool_info:
                tool_name = short_name

        if not tool_info:
            error_message = f"错误：未找到工具 {tool_name} 的配置信息。"
            logger.error(error_message)
            return {
                "role": "tool",
                "content": error_message,
                "tool_call_id": tool_call_id,
            }

        server_id = tool_info["server_id"]
        session = self.sessions[server_id]["session"]
        
        # 根据工具类型选择适当的超时时间
        tool_timeout = self.tool_timeouts.get('default', self.tool_timeout)
        for tool_type, timeout in self.tool_timeouts.items():
            if tool_type in tool_name.lower():
                tool_timeout = timeout
                break
        
        # 重试机制
        max_retries = 2 if tool_name in ['get_forecast_week', 'get_observe', 'search', 'fetch_content'] else 1
        
        for attempt in range(max_retries):
            try:
                logger.info(f"🔧 调用工具 {tool_name} (服务: {server_id}, 参数: {tool_args}, 超时: {tool_timeout}s, 尝试: {attempt + 1}/{max_retries})")
                
                result = await asyncio.wait_for(session.call_tool(tool_name, tool_args), timeout=tool_timeout)
                
                # 成功获取结果
                result_content = result.content[0].text
                if tool_name == "browser-use":
                    # result_content = await self._maybe_wait_browser_use_result(session, result_content)
                    pass
                logger.info(f"✅ 工具 {tool_name} 执行成功")

                return {
                    "role": "tool",
                    "content": result_content,
                    "tool_call_id": tool_call_id,
                }
                
            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(f"⏱️ 工具 {tool_name} 超时，等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)
                    continue
                # 最后一次超时，返回错误信息
                error_message = f"工具 {tool_name} 调用超时 ({tool_timeout}秒)"
                logger.error(f"❌ {error_message}")
                
                # 针对天气和搜索工具的特殊处理
                if tool_name in ['get_forecast_week', 'get_observe', 'search', 'fetch_content']:
                    return {
                        "role": "tool", 
                        "content": f"⚠️ {error_message}\n\n这可能是因为网络连接问题或服务响应缓慢。请稍后重试，或检查相关服务是否正常运行。",
                        "tool_call_id": tool_call_id,
                    }
                
                return {
                    "role": "tool",
                    "content": f"Error: {error_message}",
                    "tool_call_id": tool_call_id,
                }
            
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ 工具 {tool_name} 调用失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}，正在重试...")
                    await asyncio.sleep(1)
                    continue
                # 最后一次尝试失败
                error_message = f"调用工具 {tool_name} 时出错: {str(e)}"
                logger.error(f"❌ {error_message}")
                return {
                    "role": "tool",
                    "content": f"Error: {error_message}",
                    "tool_call_id": tool_call_id,
                }

    async def _process_tool_calls(self, tool_calls) -> list:
        """并行处理工具调用"""
        tasks = [self._execute_single_tool(tc) for tc in tool_calls]
        return await asyncio.gather(*tasks)

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
        """??????"""
        if self.active_irrigation_task and not self.active_irrigation_task.done():
            self.active_irrigation_task.cancel()
            with suppress(Exception):
                await asyncio.wait_for(self.active_irrigation_task, timeout=5)

        for server_id, stack in list(self._server_exit_stacks.items()):
            try:
                await asyncio.wait_for(stack.aclose(), timeout=8)
            except asyncio.TimeoutError:
                logger.warning(f"????? {server_id} ????????")
            except Exception as e:
                msg = str(e)
                if "cancel scope" in msg:
                    logger.warning(f"????? {server_id} ????????????: {msg}")
                else:
                    logger.error(f"????? {server_id} ???????: {msg}")

        for server_id, process in list(self._server_processes.items()):
            with suppress(Exception):
                await asyncio.wait_for(self._terminate_process(process), timeout=8)

        self._server_exit_stacks.clear()
        self._server_processes.clear()
        self.sessions.clear()
        self.tools_map.clear()
        self.conversation_history.clear()
        self.latest_perception_weather = None
        self.pending_decision = None
        self.active_irrigation_context = None
        self.active_irrigation_task = None
        logger.info("[CLEAN] ???????")


async def main():
    parser = argparse.ArgumentParser(description="FarmMind MCP Client")
    parser.add_argument("--init-only", action="store_true", help="只初始化连接并列出工具后退出")
    args = parser.parse_args()

    # 启动并初始化 MCP 客户端
    client = MCPClient()
    try:
        # 从配置文件加载 MCP 服务
        await client.load_servers_from_config("mcp_servers.json")
        # 列出 MCP 服务器上的工具
        await client.list_tools()
        if args.init_only:
            return
        # 运行交互式聊天循环，处理用户对话
        await client.chat_loop()
    finally:
        # 清理资源
        await client.clean()


if __name__ == "__main__":
    asyncio.run(main())
