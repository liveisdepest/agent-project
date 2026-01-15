from typing import Any, Dict, List
import httpx
from mcp.server.fastmcp import FastMCP
from datetime import datetime, timedelta
import json

# 初始化FastMCP服务器
mcp = FastMCP("irrigation")

# 腾讯天气API基础URL
WIS_API_BASE = "https://wis.qq.com"

# 作物灌溉需求数据库
CROP_IRRIGATION_NEEDS = {
    "小麦": {
        "发芽期": {"daily_water": 2.0, "critical_temp": 15},
        "分蘖期": {"daily_water": 3.5, "critical_temp": 18},
        "拔节期": {"daily_water": 4.0, "critical_temp": 20},
        "抽穗期": {"daily_water": 5.0, "critical_temp": 22},
        "灌浆期": {"daily_water": 4.5, "critical_temp": 25},
        "成熟期": {"daily_water": 2.5, "critical_temp": 28}
    },
    "玉米": {
        "苗期": {"daily_water": 2.5, "critical_temp": 18},
        "拔节期": {"daily_water": 4.0, "critical_temp": 22},
        "抽雄期": {"daily_water": 5.5, "critical_temp": 25},
        "灌浆期": {"daily_water": 4.5, "critical_temp": 26},
        "成熟期": {"daily_water": 2.0, "critical_temp": 28}
    }
}

async def make_weather_request(url: str) -> dict[str, Any] | None:
    """向腾讯天气API发送请求并返回响应数据"""
    headers = {"Accept": "application/json"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

@mcp.tool()
async def get_irrigation_advice(province: str, city: str, crop: str, growth_stage: str, soil_moisture: float = None) -> str:
    """获取智能灌溉建议"""
    # 获取天气数据
    weather_url = f"{WIS_API_BASE}/weather/common?source=pc&weather_type=forecast_24h&province={province}&city={city}"
    weather_data = await make_weather_request(weather_url)
    
    if not weather_data:
        return "无法获取天气数据，请检查网络连接"
    
    # 获取实时天气
    observe_url = f"{WIS_API_BASE}/weather/common?source=pc&weather_type=observe&province={province}&city={city}"
    observe_data = await make_weather_request(observe_url)
    
    return f"""
=== {crop} {growth_stage} 灌溉建议 ===

【天气分析】
当前温度: {observe_data['data']['observe']['degree']}°C
当前湿度: {observe_data['data']['observe']['humidity']}%

【灌溉建议】
• 建议灌溉时间: 清晨或傍晚
• 灌溉方式: 滴灌或喷灌
• 注意事项: 避免中午高温时段灌溉
"""

@mcp.tool()
async def get_water_saving_plan(province: str, city: str, crop: str, growth_stage: str) -> str:
    """获取节水灌溉方案"""
    return f"""
=== {crop} {growth_stage} 节水灌溉方案 ===

【节水技术】
1. 滴灌系统: 减少水分蒸发
2. 智能控制: 根据天气自动调节
3. 土壤监测: 实时监控土壤湿度
4. 覆盖保墒: 使用地膜覆盖

【节水建议】
• 采用微灌技术，节水30-50%
• 实施水肥一体化
• 定期维护灌溉设备
"""

@mcp.tool()
async def get_flood_prevention_advice(province: str, city: str, crop: str) -> str:
    """获取防涝排水建议"""
    return f"""
=== {crop} 防涝排水建议 ===

【排水系统】
1. 明沟排水: 开挖排水沟渠
2. 暗管排水: 埋设排水管道
3. 泵站排水: 安装抽水泵站

【应急措施】
• 及时疏通排水沟渠
• 准备抽水设备
• 加固田埂堤坝
"""

@mcp.tool()
async def get_irrigation_schedule(province: str, city: str, crop: str, growth_stage: str, field_size: float) -> str:
    """生成灌溉时间表"""
    return f"""
=== {crop} {growth_stage} 灌溉时间表 ===
田地面积: {field_size}亩

【本周灌溉安排】
周一: 灌溉 2小时 (6:00-8:00)
周二: 休息
周三: 灌溉 2小时 (6:00-8:00)
周四: 休息
周五: 灌溉 2小时 (6:00-8:00)
周六: 休息
周日: 灌溉 2小时 (6:00-8:00)

【注意事项】
• 灌溉时间: 清晨6:00-8:00
• 根据天气情况调整灌溉量
• 每日检查土壤湿度
"""

if __name__ == "__main__":
    mcp.run(transport="stdio")
