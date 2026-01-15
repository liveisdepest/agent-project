from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn
import asyncio
import threading
from mcp.server.fastmcp import FastMCP

# 全局状态存储
class SystemState:
    def __init__(self):
        self.temperature = 25.0
        self.humidity = 60.0
        self.soil_moisture = 50.0  # 0-100%
        self.pump_status = False   # False: Off, True: On
        self.last_update = None

state = SystemState()

# 定义数据模型
class SensorData(BaseModel):
    temperature: float
    humidity: float
    soil_moisture: float

class PumpCommand(BaseModel):
    pump_on: bool

# 初始化 FastMCP
mcp = FastMCP("irrigation")

# --- MCP 工具定义 ---

@mcp.tool()
async def get_sensor_data() -> str:
    """获取最新的传感器数据（温度、湿度、土壤湿度）。"""
    status = "开启" if state.pump_status else "关闭"
    return f"""
--- 实时环境数据 ---
温度: {state.temperature}°C
空气湿度: {state.humidity}%
土壤湿度: {state.soil_moisture}%
水泵状态: {status}
数据更新时间: {state.last_update or '暂无数据'}
"""

@mcp.tool()
async def control_pump(turn_on: bool) -> str:
    """控制水泵（灌溉系统）的开关。
    
    参数:
        turn_on: True 开启水泵，False 关闭水泵
    """
    state.pump_status = turn_on
    action = "开启" if turn_on else "关闭"
    return f"指令已下发: {action}水泵"

@mcp.tool()
async def get_irrigation_advice(weather_forecast: str) -> str:
    """根据当前传感器数据和天气预报生成灌溉建议。
    
    参数:
        weather_forecast: 天气预报的文本描述
    """
    # 简单的规则引擎逻辑 (实际应用中可以让 LLM 自己判断，这里提供辅助计算)
    advice = []
    
    if state.soil_moisture < 30:
        advice.append("警告：土壤湿度过低 (<30%)，建议立即灌溉。")
    elif state.soil_moisture > 80:
        advice.append("提示：土壤湿度充足 (>80%)，无需灌溉。")
        
    if "雨" in weather_forecast:
        advice.append("提示：预报有雨，可适当减少或暂停灌溉。")
        
    if state.temperature > 30:
        advice.append("提示：气温较高，水分蒸发快，请注意监测土壤湿度。")
        
    if not advice:
        advice.append("当前环境适宜，保持监控即可。")
        
    return "\n".join(advice)

# --- FastAPI HTTP 服务 ---

app = FastAPI()

@app.post("/upload_data")
async def receive_data(data: SensorData):
    """ESP8266 上报数据的接口"""
    import datetime
    state.temperature = data.temperature
    state.humidity = data.humidity
    state.soil_moisture = data.soil_moisture
    state.last_update = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 在控制台打印接收到的数据
    print(f"\n[IoT] 收到数据: 温度={data.temperature}°C, 湿度={data.humidity}%, 土壤={data.soil_moisture}%")
    
    return {"status": "success", "message": "Data received"}

@app.get("/get_command")
async def get_command():
    """ESP8266 获取控制指令的接口"""
    # 打印被轮询的日志，方便调试
    # print(f"[IoT] ESP8266 正在请求指令，当前状态: {state.pump_status}")
    return {"pump_on": state.pump_status}

@app.get("/")
async def root():
    return {"message": "Irrigation MCP Server Running"}

# --- 启动逻辑 ---

def run_http_server():
    """在后台线程运行 FastAPI"""
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

if __name__ == "__main__":
    # 启动 HTTP 服务器线程 (供 ESP8266 连接)
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    print("HTTP Server started on port 8000 for ESP8266...")
    
    # 启动 MCP 服务器 (供 AI 客户端连接)
    # 注意：mcp.run() 是阻塞的，所以 HTTP server 要在线程里跑
    mcp.run(transport='stdio')
