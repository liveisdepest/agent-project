import asyncio
import os
from openai import OpenAI
from dotenv import load_dotenv
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载 .env 文件
load_dotenv()


class MCPClient:
    def __init__(self, connection_timeout: int = 10, max_retries: int = 3, tool_timeout: int = 30):
        """初始化 MCP 客户端"""
        self.exit_stack = AsyncExitStack()
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
            command = server_config["command"]
            args = server_config.get("args", [])
            env = server_config.get("env", None)
            
            # 尝试连接，失败则跳过
            success = await self.connect_to_local_server(server_id, command, args, env)
            if success:
                successful_connections += 1
        
        logger.info(f"📊 连接结果: {successful_connections}/{total_servers} 个服务连接成功")
        
        if successful_connections == 0:
            logger.error("⚠️  没有任何MCP服务连接成功，请检查配置和服务状态")
        elif successful_connections < total_servers:
            logger.warning(f"⚠️  部分服务连接失败，当前可用服务数: {successful_connections}")

    async def connect_to_local_server(self, server_id: str, command: str, args: list, env: dict, timeout: int = 10, max_retries: int = 3):
        """
        连接到本地 MCP 服务（带超时和重试机制）
        :param server_id: 服务端标识符
        :param command: 本地服务的启动命令
        :param args: 启动命令的参数
        :param env: 环境变量
        :param timeout: 连接超时时间（秒）
        :param max_retries: 最大重试次数
        """

        if server_id in self.sessions:
            logger.warning(f"服务端 {server_id} 已经连接，跳过重复连接")
            return True

        for attempt in range(max_retries):
            try:
                logger.info(f"正在连接服务端 {server_id}... (尝试 {attempt + 1}/{max_retries})")
                
                # 使用 asyncio.wait_for 实现超时控制
                await asyncio.wait_for(
                    self._do_connect(server_id, command, args, env),
                    timeout=timeout
                )
                
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

    async def _do_connect(self, server_id: str, command: str, args: list, env: dict):
        """执行实际的连接操作"""
        server_params = StdioServerParameters(command=command, args=args, env=env)
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        stdio, write = stdio_transport
        session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))
        await session.initialize()
        
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
                response = await asyncio.wait_for(
                    session.list_tools(), 
                    timeout=5  # 工具列表获取超时5秒
                )
                
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
                "content": "你是一个有用的助手。你可以使用提供的工具来回答用户的问题。如果需要使用工具，请生成标准的工具调用，而不是直接输出 JSON 文本。如果你的回复看起来像是一个 JSON 对象且包含 'name' 和 'arguments' 字段，请务必将其作为工具调用发送。"
            })

        # 将用户的新查询添加到历史记录
        self.conversation_history.append({"role": "user", "content": query})

        # 构建统一的工具列表
        available_tools = await self._build_tool_list()

        # 循环处理工具调用
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

            # 检查是否返回了纯 JSON 文本作为工具调用（Ollama 常见问题）
            if not has_tool_calls and json_buffer.strip().startswith("{") and "arguments" in json_buffer:
                try:
                    import uuid
                    # 尝试解析 JSON
                    potential_tool = json.loads(json_buffer.strip())
                    if "name" in potential_tool and "arguments" in potential_tool:
                        logger.info("检测到纯文本 JSON 工具调用，正在转换...")
                        
                        # 构造伪造的 ToolCall 对象
                        class MockFunction:
                            def __init__(self, name, arguments):
                                self.name = name
                                self.arguments = json.dumps(arguments) if isinstance(arguments, dict) else arguments

                        class MockToolCall:
                            def __init__(self, name, arguments):
                                self.id = f"call_{uuid.uuid4()}"
                                self.function = MockFunction(name, arguments)

                        tool_calls = [MockToolCall(potential_tool["name"], potential_tool["arguments"])]
                        has_tool_calls = True
                        is_intercepted_json = True
                        # 清除之前的文本输出，避免重复显示
                        print("\n[系统] 已拦截并执行工具调用...", end="", flush=True)
                except json.JSONDecodeError:
                    pass

            # 等待 delta的tool_calls的返回为空
            if has_tool_calls:
                # 如果有工具调用，组合tool_calss内容
                # print(tool_calls) # 调试输出
                tool_results = await self._process_tool_calls(tool_calls)
                
                # 检查是否所有的工具调用都是错误的，如果是，则不继续循环，避免死循环
                all_errors = True
                for result in tool_results:
                     if not result["content"].startswith("Error:"):
                         all_errors = False
                         break
                
                # 如果是拦截的JSON调用，我们需要手动将其添加到历史记录中，因为它不在正常的tool_calls流中
                # 检查 response 是否是 Stream 对象，Stream 对象没有 choices 属性，需要迭代
                is_stream_empty = True
                try:
                     # 尝试检查 Stream 对象是否已被迭代完，或者直接通过 json_buffer 判断
                     # 由于 response 是一个迭代器，且我们已经迭代过了，所以这里不能再从 response 中获取信息
                     # 我们的逻辑是：如果 json_buffer 不为空且以 { 开头，说明是流式输出的内容
                     pass
                except Exception:
                     pass

                if json_buffer.strip().startswith("{") and "arguments" in json_buffer: 
                     # 判断这些 tool_calls 是否已经在 response.choices 中被正确解析了
                     # 如果是，那么 has_tool_calls 会是 True，但这里不应该重复添加 assistant message
                     
                     # 只有当原始响应中没有检测到 tool_calls (即 has_tool_calls 原本为 False，是我们后来手动改为 True 的) 时
                     # 才需要手动构造 assistant message
                     
                     if is_intercepted_json:
                         # 更好的方式是构造一个 assistant 消息
                         self.conversation_history.append({
                             "role": "assistant",
                             "tool_calls": [
                                 {
                                     "id": tc.id,
                                     "type": "function",
                                     "function": {
                                         "name": tc.function.name,
                                         "arguments": tc.function.arguments
                                     }
                                 } for tc in tool_calls
                             ]
                         })
                
                self.conversation_history.extend(tool_results)
                
                if all_errors:
                     return "工具调用失败，请检查参数或重试。"

            else:
                # 如果没有工具调用，直接返回流式内容
                print()  # 添加换行符
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
            tool_name = tool_call.function.name
            tool_args_str = tool_call.function.arguments
            tool_call_id = tool_call.id

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
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, tool_args),
                    timeout=30  # 工具调用超时30秒
                )
                
                result_content = result.content[0].text
                logger.info(f"✅ 工具 {tool_name} 执行成功")

                tool_results.append({
                    "role": "tool",
                    "content": result_content,
                    "tool_call_id": tool_call_id,
                })
                
            except asyncio.TimeoutError:
                error_message = f"工具 {tool_name} 调用超时 (30秒)"
                logger.error(f"❌ {error_message}")
                tool_results.append({
                    "role": "tool",
                    "content": f"Error: {error_message}",
                    "tool_call_id": tool_call_id,
                })
            except Exception as e:
                logger.error(f"❌ 调用工具 {tool_name} 时出错: {e}")
                tool_results.append({
                    "role": "tool",
                    "content": f"Error calling tool {tool_name}: {str(e)}",
                    "tool_call_id": tool_call_id,
                })
        
        return tool_results

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
        logger.info("MCP 客户端已启动！输入 'exit' 退出，输入 'clear' 清空对话历史")

        while True:
            try:
                query = input("问: ").strip()
                if query.lower() == 'exit':
                    break
                if query.lower() == 'clear':
                    self.conversation_history = [] # 清空历史
                    logger.info("对话历史已清空。")
                    continue

                response = await self.process_query(query)
                # logger.info(f"AI回复: {response}")

            except Exception as e:
                logger.error(f"发生错误: {str(e)}") # 改为 error 级别日志

    async def clean(self):
        """清理所有资源"""
        try:
            await self.exit_stack.aclose()
        except Exception as e:
            logger.error(f"清理资源时发生错误: {str(e)}")
        finally:
            self.sessions.clear()
            self.tools_map.clear()
            self.conversation_history.clear() # 清理历史记录
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