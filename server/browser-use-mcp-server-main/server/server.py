"""
Browser Use MCP 服务器

本模块实现了基于 browser_use 库的 MCP (Model-Control-Protocol) 服务器，用于浏览器自动化。
它提供了通过异步任务队列与浏览器实例交互的功能，允许异步执行长时间运行的浏览器任务，
并提供状态更新和结果查询。

服务器支持基于 SSE (Server-Sent Events) 的 Web 接口交互。
"""

# 标准库导入
import asyncio
import json
import logging
import os
import sys

# 设置 SSE 传输
import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, Union

# 第三方库导入
import click
import mcp.types as types
import uvicorn

# Browser-use 库导入
from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from dotenv import load_dotenv
from langchain_core.language_models import BaseLanguageModel

# LLM 提供商
from langchain_openai import ChatOpenAI

# MCP 服务器组件
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from pythonjsonlogger import jsonlogger
from starlette.applications import Starlette
from starlette.routing import Mount, Route

# 配置日志
logger = logging.getLogger()
logger.handlers = []  # 移除所有现有处理器
handler = logging.StreamHandler(sys.stderr)
formatter = jsonlogger.JsonFormatter(
    '{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}'
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# 确保 uvicorn 也使用 JSON 格式输出日志到 stderr
uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.handlers = []
uvicorn_logger.addHandler(handler)

# 确保所有其他 logger 使用相同的格式
logging.getLogger("browser_use").addHandler(handler)
logging.getLogger("playwright").addHandler(handler)
logging.getLogger("mcp").addHandler(handler)

# 加载环境变量
load_dotenv()


def parse_bool_env(env_var: str, default: bool = False) -> bool:
    """
    解析布尔类型的环境变量。

    参数:
        env_var: 环境变量名称
        default: 未设置时的默认值

    返回:
        环境变量的布尔值
    """
    value = os.environ.get(env_var)
    if value is None:
        return default

    # 考虑布尔值的各种表示形式
    return value.lower() in ("true", "yes", "1", "y", "on")


def init_configuration() -> Dict[str, Any]:
    """
    从环境变量初始化配置，并使用默认值。

    返回:
        包含所有配置参数的字典
    """
    config = {
        # 浏览器窗口设置
        "DEFAULT_WINDOW_WIDTH": int(os.environ.get("BROWSER_WINDOW_WIDTH", 1280)),
        "DEFAULT_WINDOW_HEIGHT": int(os.environ.get("BROWSER_WINDOW_HEIGHT", 1100)),
        # 浏览器配置设置
        "DEFAULT_LOCALE": os.environ.get("BROWSER_LOCALE", "zh-CN"), # 默认为中文环境
        "DEFAULT_USER_AGENT": os.environ.get(
            "BROWSER_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36",
        ),
        # 任务设置
        "DEFAULT_TASK_EXPIRY_MINUTES": int(os.environ.get("TASK_EXPIRY_MINUTES", 60)),
        "DEFAULT_ESTIMATED_TASK_SECONDS": int(
            os.environ.get("ESTIMATED_TASK_SECONDS", 60)
        ),
        "CLEANUP_INTERVAL_SECONDS": int(
            os.environ.get("CLEANUP_INTERVAL_SECONDS", 3600)
        ),  # 1 小时
        "MAX_AGENT_STEPS": int(os.environ.get("MAX_AGENT_STEPS", 10)),
        # 浏览器参数
        "BROWSER_ARGS": [
            "--no-sandbox",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=0",  # 使用随机端口以避免冲突
        ],
        # 耐心模式 - 如果为 true，函数将等待任务完成后再返回
        "PATIENT_MODE": parse_bool_env("PATIENT", False),
        # LLM 设置
        "OPENAI_MODEL": os.environ.get("OPENAI_MODEL", "gpt-4o"),
        "LLM_TEMPERATURE": float(os.environ.get("LLM_TEMPERATURE", 0.0)),
    }

    return config


# 初始化配置
CONFIG = init_configuration()

# 用于异步操作的任务存储
task_store: Dict[str, Dict[str, Any]] = {}
# 用于存储正在运行的 asyncio 任务以便取消
running_tasks: Dict[str, asyncio.Task] = {}


async def create_browser_context_for_task(
    chrome_path: Optional[str] = None,
    window_width: int = CONFIG["DEFAULT_WINDOW_WIDTH"],
    window_height: int = CONFIG["DEFAULT_WINDOW_HEIGHT"],
    locale: str = CONFIG["DEFAULT_LOCALE"],
) -> Tuple[Browser, BrowserContext]:
    """
    为任务创建一个新的浏览器和上下文。

    此函数创建一个隔离的浏览器实例和上下文，
    并为单个任务进行适当的配置。

    参数:
        chrome_path: Chrome 可执行文件路径
        window_width: 浏览器窗口宽度
        window_height: 浏览器窗口高度
        locale: 浏览器语言区域

    返回:
        包含浏览器实例和浏览器上下文的元组

    抛出:
        Exception: 如果浏览器或上下文创建失败
    """
    try:
        # 创建浏览器配置
        browser_config = BrowserConfig(
            extra_chromium_args=CONFIG["BROWSER_ARGS"],
        )

        # 如果提供了 chrome 路径则设置
        if chrome_path:
            browser_config.chrome_instance_path = chrome_path

        # 创建浏览器实例
        browser = Browser(config=browser_config)

        # 创建上下文配置
        context_config = BrowserContextConfig(
            wait_for_network_idle_page_load_time=0.6,
            maximum_wait_page_load_time=1.2,
            minimum_wait_page_load_time=0.2,
            browser_window_size={"width": window_width, "height": window_height},
            locale=locale,
            user_agent=CONFIG["DEFAULT_USER_AGENT"],
            highlight_elements=True,
            viewport_expansion=0,
        )

        # 使用浏览器创建上下文
        context = BrowserContext(browser=browser, config=context_config)

        return browser, context
    except Exception as e:
        logger.error(f"创建浏览器上下文出错: {str(e)}")
        raise


async def run_browser_task_async(
    task_id: str,
    url: str,
    action: str,
    llm: BaseLanguageModel,
    window_width: int = CONFIG["DEFAULT_WINDOW_WIDTH"],
    window_height: int = CONFIG["DEFAULT_WINDOW_HEIGHT"],
    locale: str = CONFIG["DEFAULT_LOCALE"],
) -> None:
    """
    异步运行浏览器任务并存储结果。

    此函数执行具有给定 URL 和操作的浏览器自动化任务，
    并更新任务存储中的进度和结果。

    当启用 PATIENT_MODE 时，调用函数将在返回客户端之前等待此函数完成。

    参数:
        task_id: 任务唯一标识符
        url: 要导航到的 URL
        action: 导航后执行的操作
        llm: 浏览器代理使用的语言模型
        window_width: 浏览器窗口宽度
        window_height: 浏览器窗口高度
        locale: 浏览器语言区域
    """
    browser = None
    context = None

    try:
        # 更新任务状态为运行中
        task_store[task_id]["status"] = "running"
        task_store[task_id]["start_time"] = datetime.now().isoformat()
        task_store[task_id]["progress"] = {
            "current_step": 0,
            "total_steps": 0,
            "steps": [],
        }

        # 定义具有正确签名的步骤回调函数
        async def step_callback(
            browser_state: Any, agent_output: Any, step_number: int
        ) -> None:
            # 更新任务存储中的进度
            task_store[task_id]["progress"]["current_step"] = step_number
            task_store[task_id]["progress"]["total_steps"] = max(
                task_store[task_id]["progress"]["total_steps"], step_number
            )

            # 添加包含最少细节的步骤信息
            step_info = {"step": step_number, "time": datetime.now().isoformat()}

            # 如果可用，添加目标
            if agent_output and hasattr(agent_output, "current_state"):
                if hasattr(agent_output.current_state, "next_goal"):
                    step_info["goal"] = agent_output.current_state.next_goal

            # 添加到进度步骤
            task_store[task_id]["progress"]["steps"].append(step_info)

            # 记录进度
            logger.info(f"任务 {task_id}: 第 {step_number} 步已完成")

        # 定义具有正确签名的完成回调函数
        async def done_callback(history: Any) -> None:
            # 记录完成
            logger.info(f"任务 {task_id}: 已完成，共 {len(history.history)} 步")

            # 添加最后一步
            current_step = task_store[task_id]["progress"]["current_step"] + 1
            task_store[task_id]["progress"]["steps"].append(
                {
                    "step": current_step,
                    "time": datetime.now().isoformat(),
                    "status": "completed",
                }
            )

        # 如果可用，从环境获取 Chrome 路径
        chrome_path = os.environ.get("CHROME_PATH")

        # 为此任务创建一个新的浏览器和上下文
        browser, context = await create_browser_context_for_task(
            chrome_path=chrome_path,
            window_width=window_width,
            window_height=window_height,
            locale=locale,
        )

        # 使用新上下文创建代理
        agent = Agent(
            task=f"First, navigate to {url}. Then, {action}", # 保持内部指令为英文以确保模型理解，或者根据需要改为中文
            llm=llm,
            browser_context=context,
            register_new_step_callback=step_callback,
            register_done_callback=done_callback,
        )

        # 运行代理，设置合理的步数限制
        agent_result = await agent.run(max_steps=CONFIG["MAX_AGENT_STEPS"])

        # 获取最终结果
        final_result = agent_result.final_result()

        # 检查是否有有效结果
        if final_result and hasattr(final_result, "raise_for_status"):
            final_result.raise_for_status()
            result_text = str(final_result.text)
        else:
            result_text = (
                str(final_result) if final_result else "无可用最终结果"
            )

        # 从代理历史中收集基本信息
        is_successful = agent_result.is_successful()
        has_errors = agent_result.has_errors()
        errors = agent_result.errors()
        urls_visited = agent_result.urls()
        action_names = agent_result.action_names()
        extracted_content = agent_result.extracted_content()
        steps_taken = agent_result.number_of_steps()

        # 创建包含最相关信息的聚焦响应
        response_data = {
            "final_result": result_text,
            "success": is_successful,
            "has_errors": has_errors,
            "errors": [str(err) for err in errors if err],
            "urls_visited": [str(url) for url in urls_visited if url],
            "actions_performed": action_names,
            "extracted_content": extracted_content,
            "steps_taken": steps_taken,
        }

        # 存储结果
        task_store[task_id]["status"] = "completed"
        task_store[task_id]["end_time"] = datetime.now().isoformat()
        task_store[task_id]["result"] = response_data

    except asyncio.CancelledError:
        logger.info(f"任务 {task_id} 已取消")
        task_store[task_id]["status"] = "cancelled"
        task_store[task_id]["end_time"] = datetime.now().isoformat()
        # 无需重新抛出，我们只想标记为已取消

    except Exception as e:
        logger.error(f"异步浏览器任务出错: {str(e)}")
        tb = traceback.format_exc()

        # 存储错误
        task_store[task_id]["status"] = "failed"
        task_store[task_id]["end_time"] = datetime.now().isoformat()
        task_store[task_id]["error"] = str(e)
        task_store[task_id]["traceback"] = tb

    finally:
        # 从运行任务中移除
        if task_id in running_tasks:
            del running_tasks[task_id]

        # 清理浏览器资源
        try:
            if context:
                await context.close()
            if browser:
                await browser.close()
            logger.info(f"任务 {task_id} 的浏览器资源已清理")
        except Exception as e:
            logger.error(
                f"清理任务 {task_id} 的浏览器资源时出错: {str(e)}"
            )


async def cleanup_old_tasks() -> None:
    """
    定期清理旧的已完成任务以防止内存泄漏。

    此函数在后台持续运行，删除已完成或失败超过 1 小时的任务
    以节省内存。
    """
    while True:
        try:
            # 先睡眠以避免过早清理任务
            await asyncio.sleep(CONFIG["CLEANUP_INTERVAL_SECONDS"])

            current_time = datetime.now()
            tasks_to_remove = []

            # 查找超过 1 小时的已完成任务
            for task_id, task_data in task_store.items():
                if (
                    task_data["status"] in ["completed", "failed"]
                    and "end_time" in task_data
                ):
                    end_time = datetime.fromisoformat(task_data["end_time"])
                    hours_elapsed = (current_time - end_time).total_seconds() / 3600

                    if hours_elapsed > 1:  # 删除超过 1 小时的任务
                        tasks_to_remove.append(task_id)

            # 删除旧任务
            for task_id in tasks_to_remove:
                del task_store[task_id]

            if tasks_to_remove:
                logger.info(f"清理了 {len(tasks_to_remove)} 个旧任务")

        except Exception as e:
            logger.error(f"任务清理出错: {str(e)}")


def create_mcp_server(
    llm: BaseLanguageModel,
    task_expiry_minutes: int = CONFIG["DEFAULT_TASK_EXPIRY_MINUTES"],
    window_width: int = CONFIG["DEFAULT_WINDOW_WIDTH"],
    window_height: int = CONFIG["DEFAULT_WINDOW_HEIGHT"],
    locale: str = CONFIG["DEFAULT_LOCALE"],
) -> Server:
    """
    创建并配置用于浏览器交互的 MCP 服务器。

    参数:
        llm: 浏览器代理使用的语言模型
        task_expiry_minutes: 任务被视为过期的分钟数
        window_width: 浏览器窗口宽度
        window_height: 浏览器窗口高度
        locale: 浏览器语言区域

    返回:
        配置好的 MCP 服务器实例
    """
    # 创建 MCP 服务器实例
    app = Server("browser_use")

    @app.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
        """
        处理来自 MCP 客户端的工具调用。

        参数:
            name: 要调用的工具名称
            arguments: 传递给工具的参数

        返回:
            返回给客户端的内容对象列表。
            当启用 PATIENT_MODE 时，browser_use 工具将等待任务完成
            并立即返回完整结果，而不仅仅是任务 ID。

        抛出:
            ValueError: 如果缺少必需参数
        """
        # 处理 browser_use 工具
        if name == "browser_use":
            # 检查必需参数
            if "url" not in arguments:
                raise ValueError("缺少必需参数 'url'")
            if "action" not in arguments:
                raise ValueError("缺少必需参数 'action'")

            # 生成任务 ID
            task_id = str(uuid.uuid4())

            # 在存储中初始化任务
            task_store[task_id] = {
                "id": task_id,
                "status": "pending",
                "url": arguments["url"],
                "action": arguments["action"],
                "created_at": datetime.now().isoformat(),
            }

            # 在后台启动任务
            _task = asyncio.create_task(
                run_browser_task_async(
                    task_id=task_id,
                    url=arguments["url"],
                    action=arguments["action"],
                    llm=llm,
                    window_width=window_width,
                    window_height=window_height,
                    locale=locale,
                )
            )
            
            # 存储任务对象
            running_tasks[task_id] = _task

            # 如果设置了 PATIENT，等待任务完成
            if CONFIG["PATIENT_MODE"]:
                try:
                    await _task
                    # 返回完成的任务结果而不是 ID
                    task_data = task_store[task_id]
                    if task_data["status"] == "failed":
                        logger.error(
                            f"任务 {task_id} 失败: {task_data.get('error', '未知错误')}"
                        )
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(task_data, indent=2, ensure_ascii=False),
                        )
                    ]
                except Exception as e:
                    logger.error(f"耐心模式执行出错: {str(e)}")
                    traceback_str = traceback.format_exc()
                    # 更新任务存储中的错误
                    task_store[task_id]["status"] = "failed"
                    task_store[task_id]["error"] = str(e)
                    task_store[task_id]["traceback"] = traceback_str
                    task_store[task_id]["end_time"] = datetime.now().isoformat()
                    # 返回错误信息
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(task_store[task_id], indent=2, ensure_ascii=False),
                        )
                    ]

            # 立即返回任务 ID 和明确的睡眠指令
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "task_id": task_id,
                            "status": "pending",
                            "message": f"浏览器任务已启动。请等待 {CONFIG['DEFAULT_ESTIMATED_TASK_SECONDS']} 秒，然后使用 browser_get_result 或资源 URI 检查结果。请始终在状态检查之间等待 5 秒。",
                            "estimated_time": f"{CONFIG['DEFAULT_ESTIMATED_TASK_SECONDS']} 秒",
                            "resource_uri": f"resource://browser_task/{task_id}",
                            "sleep_command": "sleep 5",
                            "instruction": "使用终端命令 'sleep 5' 等待 5 秒后再检查状态。重要提示：请务必等待 5 秒，不多不少。",
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                )
            ]

        # 处理 browser_get_result 工具
        elif name == "browser_get_result":
            # 获取异步任务结果
            if "task_id" not in arguments:
                raise ValueError("缺少必需参数 'task_id'")

            task_id = arguments["task_id"]

            if task_id not in task_store:
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {"error": "未找到任务", "task_id": task_id}, indent=2, ensure_ascii=False
                        ),
                    )
                ]

            # 获取当前任务数据
            task_data = task_store[task_id].copy()

            # 如果任务仍在运行，添加简单的指导
            if task_data["status"] == "running":
                # 添加简单的下次检查建议
                progress = task_data.get("progress", {})
                current_step = progress.get("current_step", 0)

                if current_step > 0:
                    # 基于当前步骤的简单消息
                    task_data["message"] = (
                        f"任务正在运行 (第 {current_step} 步)。请等待 5 秒后再次检查。"
                    )
                    task_data["sleep_command"] = "sleep 5"
                    task_data["instruction"] = (
                        "使用终端命令 'sleep 5' 等待 5 秒后再检查状态。重要提示：请务必等待 5 秒，不多不少。"
                    )
                else:
                    task_data["message"] = (
                        "任务正在启动。请等待 5 秒后再次检查。"
                    )
                    task_data["sleep_command"] = "sleep 5"
                    task_data["instruction"] = (
                        "使用终端命令 'sleep 5' 等待 5 秒后再检查状态。重要提示：请务必等待 5 秒，不多不少。"
                    )

            # 返回当前任务状态和结果（如果可用）
            return [
                types.TextContent(type="text", text=json.dumps(task_data, indent=2, ensure_ascii=False))
            ]

        # 处理 browser_stop_task 工具
        elif name == "browser_stop_task":
            if "task_id" not in arguments:
                raise ValueError("缺少必需参数 'task_id'")
            
            task_id = arguments["task_id"]
            
            if task_id in running_tasks:
                running_tasks[task_id].cancel()
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps({"status": "cancelled", "task_id": task_id}, indent=2, ensure_ascii=False)
                    )
                ]
            else:
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {"status": "not_found_or_already_finished", "task_id": task_id},
                            indent=2,
                            ensure_ascii=False
                        )
                    )
                ]

        # 处理 browser_list_tasks 工具
        elif name == "browser_list_tasks":
            active_tasks = []
            for t_id, t_data in task_store.items():
                if t_data["status"] in ["pending", "running"]:
                    active_tasks.append({
                        "task_id": t_id,
                        "status": t_data["status"],
                        "url": t_data.get("url"),
                        "created_at": t_data.get("created_at")
                    })
            
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"active_tasks": active_tasks}, indent=2, ensure_ascii=False)
                )
            ]

        else:
            raise ValueError(f"未知工具: {name}")

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        """
        列出 MCP 客户端可用的工具。

        根据 PATIENT_MODE 配置返回不同的工具描述。
        当启用 PATIENT_MODE 时，browser_use 工具描述指示它直接返回完整结果。
        禁用时，指示它是异步操作。

        返回:
            适合当前配置的工具定义列表
        """
        patient_mode = CONFIG["PATIENT_MODE"]

        if patient_mode:
            return [
                types.Tool(
                    name="browser_use",
                    description="执行浏览器操作并直接返回完整结果（耐心模式已激活）",
                    inputSchema={
                        "type": "object",
                        "required": ["url", "action"],
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "要导航到的 URL",
                            },
                            "action": {
                                "type": "string",
                                "description": "在浏览器中执行的操作",
                            },
                        },
                    },
                ),
                types.Tool(
                    name="browser_get_result",
                    description="获取异步浏览器任务的结果（在耐心模式下不需要，因为 browser_use 直接返回完整结果）",
                    inputSchema={
                        "type": "object",
                        "required": ["task_id"],
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "要获取结果的任务 ID",
                            }
                        },
                    },
                ),
                types.Tool(
                    name="browser_stop_task",
                    description="停止/取消正在运行的浏览器任务",
                    inputSchema={
                        "type": "object",
                        "required": ["task_id"],
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "要停止的任务 ID",
                            }
                        },
                    },
                ),
                types.Tool(
                    name="browser_list_tasks",
                    description="列出所有当前活动的浏览器任务",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
            ]
        else:
            return [
                types.Tool(
                    name="browser_use",
                    description="执行浏览器操作并返回用于异步执行的任务 ID",
                    inputSchema={
                        "type": "object",
                        "required": ["url", "action"],
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "要导航到的 URL",
                            },
                            "action": {
                                "type": "string",
                                "description": "在浏览器中执行的操作",
                            },
                        },
                    },
                ),
                types.Tool(
                    name="browser_get_result",
                    description="获取异步浏览器任务的结果",
                    inputSchema={
                        "type": "object",
                        "required": ["task_id"],
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "要获取结果的任务 ID",
                            }
                        },
                    },
                ),
                types.Tool(
                    name="browser_stop_task",
                    description="停止/取消正在运行的浏览器任务",
                    inputSchema={
                        "type": "object",
                        "required": ["task_id"],
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "要停止的任务 ID",
                            }
                        },
                    },
                ),
                types.Tool(
                    name="browser_list_tasks",
                    description="列出所有当前活动的浏览器任务",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
            ]

    @app.list_resources()
    async def list_resources() -> list[types.Resource]:
        """
        列出 MCP 客户端可用的资源。

        返回:
            资源定义列表
        """
        # 列出所有已完成的任务作为资源
        resources = []
        for task_id, task_data in task_store.items():
            if task_data["status"] in ["completed", "failed"]:
                resources.append(
                    types.Resource(
                        uri=f"resource://browser_task/{task_id}",
                        title=f"浏览器任务结果: {task_id[:8]}",
                        description=f"URL 的浏览器任务结果: {task_data.get('url', '未知')}",
                    )
                )
        return resources

    @app.read_resource()
    async def read_resource(uri: str) -> list[types.ResourceContents]:
        """
        为 MCP 客户端读取资源。

        参数:
            uri: 要读取的资源 URI

        返回:
            资源内容
        """
        # 从 URI 提取任务 ID
        if not uri.startswith("resource://browser_task/"):
            return [
                types.ResourceContents(
                    type="text",
                    text=json.dumps(
                        {"error": f"无效的资源 URI: {uri}"}, indent=2, ensure_ascii=False
                    ),
                )
            ]

        task_id = uri.replace("resource://browser_task/", "")
        if task_id not in task_store:
            return [
                types.ResourceContents(
                    type="text",
                    text=json.dumps({"error": f"未找到任务: {task_id}"}, indent=2, ensure_ascii=False),
                )
            ]

        # 返回任务数据
        return [
            types.ResourceContents(
                type="text", text=json.dumps(task_store[task_id], indent=2, ensure_ascii=False)
            )
        ]

    # 将 cleanup_old_tasks 函数添加到 app 以便稍后调度
    app.cleanup_old_tasks = cleanup_old_tasks

    return app


@click.command()
@click.option("--port", default=8000, help="SSE 监听端口")
@click.option(
    "--proxy-port",
    default=None,
    type=int,
    help="代理监听端口。如果指定，将启用代理模式。",
)
@click.option("--chrome-path", default=None, help="Chrome 可执行文件路径")
@click.option(
    "--window-width",
    default=CONFIG["DEFAULT_WINDOW_WIDTH"],
    help="浏览器窗口宽度",
)
@click.option(
    "--window-height",
    default=CONFIG["DEFAULT_WINDOW_HEIGHT"],
    help="浏览器窗口高度",
)
@click.option("--locale", default=CONFIG["DEFAULT_LOCALE"], help="浏览器语言区域")
@click.option(
    "--task-expiry-minutes",
    default=CONFIG["DEFAULT_TASK_EXPIRY_MINUTES"],
    help="任务过期分钟数",
)
@click.option(
    "--stdio",
    is_flag=True,
    default=False,
    help="启用 stdio 模式。如果指定，将启用代理模式。",
)
def main(
    port: int,
    proxy_port: Optional[int],
    chrome_path: str,
    window_width: int,
    window_height: int,
    locale: str,
    task_expiry_minutes: int,
    stdio: bool,
) -> int:
    """
    运行 browser-use MCP 服务器。

    此函数初始化 MCP 服务器并使用 SSE 传输运行它。
    每个浏览器任务都将创建自己隔离的浏览器上下文。

    服务器可以在两种模式下运行：
    1. 直接 SSE 模式（默认）：仅运行 SSE 服务器
    2. 代理模式（通过 --stdio 或 --proxy-port 启用）：同时运行 SSE 服务器和 mcp-proxy

    参数:
        port: SSE 监听端口
        proxy_port: 代理监听端口。如果指定，启用代理模式。
        chrome_path: Chrome 可执行文件路径
        window_width: 浏览器窗口宽度
        window_height: 浏览器窗口高度
        locale: 浏览器语言区域
        task_expiry_minutes: 任务过期分钟数
        stdio: 启用 stdio 模式。如果指定，启用代理模式。

    返回:
        退出代码（0 表示成功）
    """
    # 如果提供了 Chrome 路径，则存储在环境变量中
    if chrome_path:
        os.environ["CHROME_PATH"] = chrome_path
        logger.info(f"使用 Chrome 路径: {chrome_path}")
    else:
        logger.info(
            "未指定 Chrome 路径，让 Playwright 使用其默认浏览器"
        )

    # 初始化 LLM
    llm = ChatOpenAI(
        model=CONFIG["OPENAI_MODEL"],
        temperature=CONFIG["LLM_TEMPERATURE"],
    )

    # 创建 MCP 服务器
    app = create_mcp_server(
        llm=llm,
        task_expiry_minutes=task_expiry_minutes,
        window_width=window_width,
        window_height=window_height,
        locale=locale,
    )

    sse = SseServerTransport("/messages/")

    # 为 SSE 创建 Starlette 应用
    async def handle_sse(request):
        """处理来自客户端的 SSE 连接。"""
        try:
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await app.run(
                    streams[0], streams[1], app.create_initialization_options()
                )
        except Exception as e:
            logger.error(f"handle_sse 出错: {str(e)}")
            raise

    starlette_app = Starlette(
        debug=True,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

    # 添加启动事件
    @starlette_app.on_event("startup")
    async def startup_event():
        """在启动时初始化服务器。"""
        logger.info("正在启动 MCP 服务器...")

        # 关键配置的健全性检查
        if port <= 0 or port > 65535:
            logger.error(f"无效的端口号: {port}")
            raise ValueError(f"无效的端口号: {port}")

        if window_width <= 0 or window_height <= 0:
            logger.error(f"无效的窗口尺寸: {window_width}x{window_height}")
            raise ValueError(
                f"无效的窗口尺寸: {window_width}x{window_height}"
            )

        if task_expiry_minutes <= 0:
            logger.error(f"无效的任务过期分钟数: {task_expiry_minutes}")
            raise ValueError(f"无效的任务过期分钟数: {task_expiry_minutes}")

        # 启动后台任务清理
        asyncio.create_task(app.cleanup_old_tasks())
        logger.info("任务清理进程已调度")

    # 在单独线程中运行 uvicorn 的函数
    def run_uvicorn():
        # 配置 uvicorn 使用 JSON 日志
        log_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "fmt": '{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}',
                }
            },
            "handlers": {
                "default": {
                    "formatter": "json",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                }
            },
            "loggers": {
                "": {"handlers": ["default"], "level": "INFO"},
                "uvicorn": {"handlers": ["default"], "level": "INFO"},
                "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
                "uvicorn.access": {"handlers": ["default"], "level": "INFO"},
            },
        }

        uvicorn.run(
            starlette_app,
            host="0.0.0.0",  # nosec
            port=port,
            log_config=log_config,
            log_level="info",
        )

    # 如果启用了代理模式，同时运行 SSE 服务器和 mcp-proxy
    if stdio:
        import subprocess  # nosec

        # 在单独线程中启动 SSE 服务器
        sse_thread = threading.Thread(target=run_uvicorn)
        sse_thread.daemon = True
        sse_thread.start()

        # 给 SSE 服务器一点启动时间
        time.sleep(1)

        proxy_cmd = [
            "mcp-proxy",
            f"http://localhost:{port}/sse",
            "--sse-port",
            str(proxy_port),
            "--allow-origin",
            "*",
        ]

        logger.info(f"运行代理命令: {' '.join(proxy_cmd)}")
        logger.info(
            f"SSE 服务器运行在端口 {port}, 代理运行在端口 {proxy_port}"
        )

        try:
            # 使用来自 CLI 参数的可信命令参数
            with subprocess.Popen(proxy_cmd) as proxy_process:  # nosec
                proxy_process.wait()
        except Exception as e:
            logger.error(f"启动 mcp-proxy 出错: {str(e)}")
            logger.error(f"命令是: {' '.join(proxy_cmd)}")
            return 1
    else:
        logger.info(f"在端口 {port} 上以直接 SSE 模式运行")
        run_uvicorn()

    return 0


if __name__ == "__main__":
    main()
