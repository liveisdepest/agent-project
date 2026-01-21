import logging
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import threading
import datetime
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING)  # 改为 WARNING，减少日志输出
logger = logging.getLogger(__name__)

# 线程安全的全局状态存储
class SystemState:
    def __init__(self):
        self._temperature = 25.0
        self._humidity = 60.0
        self._soil_moisture = 50.0  # 0-100%
        self._pump_status = False   # False: Off, True: On
        self._last_update = None
        self._lock = threading.Lock()
    
    def update_sensor_data(self, temperature: float, humidity: float, soil_moisture: float):
        """线程安全地更新传感器数据"""
        with self._lock:
            self._temperature = temperature
            self._humidity = humidity
            self._soil_moisture = soil_moisture
            self._last_update = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def set_pump_status(self, status: bool):
        """线程安全地设置水泵状态"""
        with self._lock:
            self._pump_status = status
    
    def get_pump_status(self) -> bool:
        """线程安全地获取水泵状态"""
        with self._lock:
            return self._pump_status
    
    def get_sensor_data(self) -> dict:
        """线程安全地获取所有传感器数据"""
        with self._lock:
            return {
                'temperature': self._temperature,
                'humidity': self._humidity,
                'soil_moisture': self._soil_moisture,
                'pump_status': self._pump_status,
                'last_update': self._last_update
            }

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
    data = state.get_sensor_data()
    status = "开启" if data['pump_status'] else "关闭"
    return f"""
--- 实时环境数据 ---
温度: {data['temperature']}°C
空气湿度: {data['humidity']}%
土壤湿度: {data['soil_moisture']}%
水泵状态: {status}
数据更新时间: {data['last_update'] or '暂无数据'}
"""

@mcp.tool()
async def control_pump(turn_on: bool) -> str:
    """控制水泵（灌溉系统）的开关。
    
    参数:
        turn_on: True 开启水泵，False 关闭水泵
    """
    state.set_pump_status(turn_on)
    action = "开启" if turn_on else "关闭"
    return f"指令已下发: {action}水泵"

@mcp.tool()
async def get_irrigation_advice(weather_forecast: str, crop_type: str = "通用作物") -> str:
    """根据当前传感器数据、天气预报和作物类型生成专业灌溉建议。
    
    参数:
        weather_forecast: 天气预报的文本描述
        crop_type: 作物类型（如：小麦、玉米、水稻等），默认为通用作物
    """
    # 获取当前传感器数据
    data = state.get_sensor_data()
    soil_moisture = data['soil_moisture']
    temperature = data['temperature']
    humidity = data['humidity']
    
    # 专业的规则引擎逻辑
    advice = []
    urgency_level = "正常"
    
    # 基于土壤湿度的基础判断
    if soil_moisture < 20:
        advice.append(f"🚨 紧急：土壤湿度严重不足 ({soil_moisture}%)，{crop_type}面临干旱风险，建议立即灌溉！")
        urgency_level = "紧急"
    elif soil_moisture < 30:
        advice.append(f"⚠️  警告：土壤湿度偏低 ({soil_moisture}%)，{crop_type}需要补充水分，建议尽快灌溉。")
        urgency_level = "警告"
    elif soil_moisture < 40:
        advice.append(f"💡 提示：土壤湿度略低 ({soil_moisture}%)，可考虑适量灌溉。")
        urgency_level = "提示"
    elif soil_moisture > 80:
        advice.append(f"✅ 良好：土壤湿度充足 ({soil_moisture}%)，暂时无需灌溉。")
        urgency_level = "良好"
    else:
        advice.append(f"✅ 适宜：土壤湿度适中 ({soil_moisture}%)，{crop_type}生长环境良好。")
        urgency_level = "适宜"
        
    # 基于天气的智能判断
    if "雨" in weather_forecast or "降水" in weather_forecast:
        if "大雨" in weather_forecast or "暴雨" in weather_forecast:
            advice.append("🌧️  天气：预报有大雨/暴雨，建议暂停灌溉，注意排水防涝。")
        else:
            advice.append("🌦️  天气：预报有降雨，可适当减少或延迟灌溉。")
    elif "晴" in weather_forecast and temperature > 30:
        advice.append(f"☀️  天气：高温晴天 ({temperature}°C)，水分蒸发快，需密切监测土壤湿度。")
    elif "干燥" in weather_forecast or humidity < 40:
        advice.append(f"🏜️  天气：空气干燥 (湿度{humidity}%)，{crop_type}水分需求增加。")
        
    # 基于温度的专业建议
    if temperature > 35:
        advice.append(f"🌡️  高温警告：气温过高 ({temperature}°C)，建议在早晨或傍晚进行灌溉，避免中午高温时段。")
    elif temperature < 5:
        advice.append(f"❄️  低温提醒：气温较低 ({temperature}°C)，减少灌溉频次，防止根系受冻。")
        
    # 作物特定建议（基础版本，实际应用中可以更详细）
    crop_specific_advice = {
        "小麦": "小麦在拔节期和灌浆期需水量大，土壤湿度应保持在60-70%。",
        "玉米": "玉米在大喇叭口期和抽雄期需水关键，土壤湿度应保持在65-75%。",
        "水稻": "水稻需要保持浅水层，田间应有2-3cm水层。",
        "番茄": "番茄需要均匀供水，避免忽干忽湿，土壤湿度保持在60-70%。",
        "黄瓜": "黄瓜需水量大，土壤湿度应保持在70-80%，但要注意排水。"
    }
    
    if crop_type in crop_specific_advice:
        advice.append(f"🌾 {crop_type}专业建议：{crop_specific_advice[crop_type]}")
        
    # 综合建议
    if not advice:
        advice.append("当前环境条件适宜，建议继续监控。")
        
    # 格式化输出
    result = f"""
=== 🌱 智能灌溉建议报告 ===
作物类型：{crop_type}
紧急程度：{urgency_level}
当前环境：温度{temperature}°C，湿度{humidity}%，土壤湿度{soil_moisture}%

📋 专业建议：
{chr(10).join(f"  {i+1}. {item}" for i, item in enumerate(advice))}

⏰ 最佳灌溉时间：
  - 夏季：早晨6-8点或傍晚6-8点
  - 冬季：上午10-12点
  - 避免中午高温时段灌溉

💧 灌溉量参考：
  - 轻度缺水：每平方米2-3升
  - 中度缺水：每平方米4-6升  
  - 重度缺水：每平方米7-10升
"""
    
    return result

@mcp.tool()
async def comprehensive_analysis(weather_data: str, crop_info: str = "") -> str:
    """综合分析当前环境、天气和作物信息，提供完整的农业决策建议。
    
    参数:
        weather_data: 天气数据（实时+预报）
        crop_info: 作物相关信息（生长习性、需水量等）
    """
    # 获取当前传感器数据
    data = state.get_sensor_data()
    
    analysis_report = f"""
=== 🌾 综合农业分析报告 ===
生成时间：{data['last_update'] or '数据获取中...'}

📊 当前环境状况：
  • 土壤湿度：{data['soil_moisture']}%
  • 空气温度：{data['temperature']}°C  
  • 空气湿度：{data['humidity']}%
  • 水泵状态：{'运行中' if data['pump_status'] else '停止'}

🌤️ 天气信息：
{weather_data}

🌱 作物信息：
{crop_info if crop_info else '未提供具体作物信息'}

🎯 综合建议：
基于以上数据，系统建议您：
1. 参考土壤湿度和天气预报决定是否灌溉
2. 结合作物特性调整灌溉策略
3. 关注天气变化，提前做好应对措施

💡 下一步操作：
如需灌溉，请确认后我将为您开启水泵系统。
"""
    
    return analysis_report

# --- FastAPI HTTP 服务 ---

app = FastAPI()

@app.post("/upload_data")
async def receive_data(data: SensorData):
    """ESP8266 上报数据的接口"""
    state.update_sensor_data(data.temperature, data.humidity, data.soil_moisture)
    
    # 改为 DEBUG 级别，避免刷屏影响用户交互
    logger.debug(
        f"[IoT] 收到数据: 温度={data.temperature}°C, 湿度={data.humidity}%, 土壤={data.soil_moisture}%"
    )
    
    return {"status": "success", "message": "Data received"}

@app.get("/get_command")
async def get_command():
    """ESP8266 获取控制指令的接口"""
    pump_status = state.get_pump_status()
    # 打印被轮询的日志，方便调试
    # print(f"[IoT] ESP8266 正在请求指令，当前状态: {pump_status}")
    return {"pump_on": pump_status}

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
    logger.info("HTTP Server started on port 8000 for ESP8266...")
    
    # 启动 MCP 服务器 (供 AI 客户端连接)
    # 注意：mcp.run() 是阻塞的，所以 HTTP server 要在线程里跑
    mcp.run(transport='stdio')
