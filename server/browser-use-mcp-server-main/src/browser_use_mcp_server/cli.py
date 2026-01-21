"""
Browser-use MCP 服务器的命令行界面。

此模块提供了一个命令行界面，用于启动 browser-use MCP 服务器。
它将现有的服务器功能封装在一个 CLI 中。
"""

import json
import logging
import sys
from typing import Optional

import click
from pythonjsonlogger import jsonlogger

# 直接从我们的包导入
from browser_use_mcp_server.server import main as server_main

# 配置 CLI 日志
logger = logging.getLogger()
logger.handlers = []  # 移除所有现有处理器
handler = logging.StreamHandler(sys.stderr)
formatter = jsonlogger.JsonFormatter(
    '{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}'
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def log_error(message: str, error: Optional[Exception] = None):
    """以 JSON 格式记录错误到 stderr"""
    error_data = {"error": message, "traceback": str(error) if error else None}
    print(json.dumps(error_data, ensure_ascii=False), file=sys.stderr)


@click.group()
def cli():
    """Browser-use MCP 服务器命令行界面。"""


@cli.command()
@click.argument("subcommand")
@click.option("--port", default=8000, help="SSE 监听端口")
@click.option(
    "--proxy-port",
    default=None,
    type=int,
    help="代理监听端口（使用 stdio 模式时）",
)
@click.option("--chrome-path", default=None, help="Chrome 可执行文件路径")
@click.option("--window-width", default=1280, help="浏览器窗口宽度")
@click.option("--window-height", default=1100, help="浏览器窗口高度")
@click.option("--locale", default="en-US", help="浏览器语言区域")
@click.option(
    "--task-expiry-minutes",
    default=60,
    help="任务过期分钟数",
)
@click.option(
    "--stdio", is_flag=True, default=False, help="启用带 mcp-proxy 的 stdio 模式"
)
def run(
    subcommand,
    port,
    proxy_port,
    chrome_path,
    window_width,
    window_height,
    locale,
    task_expiry_minutes,
    stdio,
):
    """运行 browser-use MCP 服务器。

    SUBCOMMAND: 应该是 'server'
    """
    if subcommand != "server":
        log_error(f"未知子命令: {subcommand}. 仅支持 'server'。")
        sys.exit(1)

    try:
        # 我们需要构造命令行参数以传递给服务器的 Click 命令
        old_argv = sys.argv.copy()

        # 为服务器命令构建新的参数列表
        new_argv = [
            "server",  # 程序名称
            "--port",
            str(port),
        ]

        if chrome_path:
            new_argv.extend(["--chrome-path", chrome_path])

        if proxy_port is not None:
            new_argv.extend(["--proxy-port", str(proxy_port)])

        new_argv.extend(["--window-width", str(window_width)])
        new_argv.extend(["--window-height", str(window_height)])
        new_argv.extend(["--locale", locale])
        new_argv.extend(["--task-expiry-minutes", str(task_expiry_minutes)])

        if stdio:
            new_argv.append("--stdio")

        # 临时替换 sys.argv
        sys.argv = new_argv

        # 直接运行服务器的命令
        try:
            return server_main()
        finally:
            # 恢复原始 sys.argv
            sys.argv = old_argv

    except Exception as e:
        log_error("启动服务器时出错", e)
        sys.exit(1)


if __name__ == "__main__":
    cli()
