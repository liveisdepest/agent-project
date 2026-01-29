import logging
import httpx
from mcp.server.fastmcp import FastMCP
import sys
import io

# 强制 stdout/stderr 使用 UTF-8 且行缓冲
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

# Web 服务器地址 (假设运行在同一台机器的 8080 端口)
# 使用 127.0.0.1 而不是 localhost，避免 IPv6 解析问题导致 502 错误
WEB_SERVER_API = "http://127.0.0.1:8080/api"

# 初始化 FastMCP
mcp = FastMCP("irrigation")

async def fetch_sensor_data() -> dict:
    """从 Web 服务器获取最新的传感器数据"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{WEB_SERVER_API}/sensor/latest", timeout=5.0)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch sensor data: {e}")
        # 返回默认值或上次缓存的值
        return {
            "temperature": 0.0,
            "humidity": 0.0,
            "soil_moisture": 0.0,
            "pump_status": False,
            "last_update": None
        }

async def send_pump_command(pump_on: bool):
    """向 Web 服务器发送水泵控制指令"""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{WEB_SERVER_API}/command/update",
                json={"pump_on": pump_on},
                timeout=5.0
            )
    except Exception as e:
        logger.error(f"Failed to send pump command: {e}")

# --- MCP 工具定义 ---

@mcp.tool()
async def get_sensor_data() -> str:
    """获取最新的传感器数据（温度、湿度、土壤湿度）。"""
    data = await fetch_sensor_data()
    status = "开启" if data.get('pump_status', False) else "关闭"
    
    return f"""
--- 实时环境数据 ---
温度: {data.get('temperature', 0.0)}°C
空气湿度: {data.get('humidity', 0.0)}%
土壤湿度: {data.get('soil_moisture', 0.0)}%
水泵状态: {status}
数据更新时间: {data.get('last_update') or '暂无数据'}
"""

@mcp.tool()
async def control_pump(turn_on: bool) -> str:
    """控制水泵（灌溉系统）的开关。
    
    参数:
        turn_on: True 开启水泵，False 关闭水泵
    """
    await send_pump_command(turn_on)
    action = "开启" if turn_on else "关闭"
    return f"指令已下发: {action}水泵"

if __name__ == "__main__":
    # 启动 MCP 服务器 (供 AI 客户端连接)
    try:
        mcp.run(transport='stdio')
    except Exception as e:
        logger.error(f"MCP Server crashed: {e}")
        sys.exit(1)
