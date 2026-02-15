from typing import Any, Dict, List
import httpx
from mcp.server.fastmcp import FastMCP, Context
import datetime
import os
import json
from collections import Counter
import sys
from pypinyin import lazy_pinyin

# 初始化 FastMCP 服务器
mcp = FastMCP("weather")

# 常量
OWM_BASE_URL = "https://api.openweathermap.org/data/2.5"

# 移除全局 HTTP 客户端，避免初始化阻塞
# 改为每次请求时创建临时客户端

def get_api_key() -> str | None:
    """获取 API Key，未配置时返回 None（请设置 OWM_API_KEY 环境变量）"""
    return os.getenv("OWM_API_KEY") or None

async def make_owm_request(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any] | None:
    """向 OpenWeatherMap API 发送请求并返回响应数据."""
    api_key = get_api_key()
    if not api_key:
        return None  # 未配置 OWM_API_KEY，跳过请求
    url = f"{OWM_BASE_URL}/{endpoint}"
    params["appid"] = api_key
    params["units"] = "metric"  # 使用公制单位 (摄氏度)
    params["lang"] = "zh_cn"    # 返回中文描述
    
    # 每次创建新的客户端，避免全局状态和初始化阻塞
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            # print(f"API Request Error: {e}", file=sys.stderr)
            return None

def _format_time(timestamp: int, timezone_offset: int = 0) -> str:
    """将 Unix 时间戳转换为 ISO 格式字符串 (考虑时区)"""
    dt = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc) + datetime.timedelta(seconds=timezone_offset)
    return dt.isoformat()

def _is_valid_response(data: Dict[str, Any] | None) -> bool:
    """检查 API 响应是否有效"""
    if not data:
        return False
    # API 返回的 cod 可能是 int 200 或 string "200"
    cod = str(data.get("cod", "200"))
    # 如果 cod 不是 200，说明 API 返回了错误信息（如 404 Not Found）
    if cod != "200":
        return False
    return True

def _ensure_pinyin(text: str) -> str:
    """如果包含中文，转换为拼音"""
    if not text:
        return text
    # 简单的检查：如果包含非 ASCII 字符，假设是中文
    if not all(ord(c) < 128 for c in text):
        # lazy_pinyin 返回 list，例如 ['bei', 'jing']
        return "".join(lazy_pinyin(text))
    return text

async def _fetch_owm_data(endpoint: str, city: str, province: str = "") -> Dict[str, Any] | None:
    """尝试获取 OWM 数据，带有重试策略（CN后缀 vs 无后缀）"""
    # 自动转换为拼音
    city_pinyin = _ensure_pinyin(city)

    # 策略 1: City,CN (优先尝试带国家代码)
    params = {"q": f"{city_pinyin},CN"}
    data = await make_owm_request(endpoint, params)
    
    if _is_valid_response(data):
        return data
        
    # 策略 2: 仅 City (针对中文名称可能不需要后缀的情况，或者其他模糊情况)
    # OpenWeatherMap 有时对 "北京" 比 "北京,CN" 处理得更好，或者反之。
    params = {"q": city_pinyin}
    data = await make_owm_request(endpoint, params)
    
    if _is_valid_response(data):
        return data
        
    return None

@mcp.tool()
async def get_forecast_48h(city: str, province: str = "") -> str:
    """获取中国某个省，某个城市的未来48个小时天气预报。
    
    返回 JSON 格式数据，包含未来 48 小时内的预报数据（约 16 个时间点）。

    参数:
        city: 城市名称 (拼音或英文)
        province: 省份名称 (可选，用于辅助说明)
    """
    data = await _fetch_owm_data("forecast", city, province)
    
    if not data or "list" not in data:
        return json.dumps({"error": f"无法获取 {city} 的天气预报，请检查城市名称是否正确。"}, ensure_ascii=False)

    forecasts = []
    # 获取前 16 个数据点 (16 * 3 = 48小时)
    timezone_offset = data.get("city", {}).get("timezone", 28800)
    
    for item in data["list"][:16]:
        # 使用 timestamp 计算准确的时间，不依赖 dt_txt 字符串
        dt_iso = _format_time(item["dt"], timezone_offset)
        
        forecast = {
            "time": dt_iso,
            "temperature": item['main']['temp'],
            "weather": item["weather"][0]["description"] if item["weather"] else "未知",
            "wind_direction": item['wind']['deg'],
            "wind_speed": item['wind']['speed'],
            "humidity": item['main']['humidity']
        }
        forecasts.append(forecast)

    return json.dumps(forecasts, ensure_ascii=False, indent=2)

@mcp.tool()
async def get_alarms(city: str, province: str = "") -> str:
    """获取中国某个省，某个城市的天气预警。
    
    参数:
        city: 城市名称
        province: 省份名称
    """
    return json.dumps({
        "status": "not_supported",
        "message": "当前使用的 OpenWeatherMap 标准版 API 不支持获取气象预警信息（需要 One Call API 订阅）。"
    }, ensure_ascii=False)

@mcp.tool()
async def get_forecast_week(city: str, province: str = "") -> str:
    """获取中国某个省，某个城市的未来几天天气预报。
    
    注意：OpenWeatherMap 标准版提供 5 天预报。

    参数:
        city: 城市名称 (建议使用拼音，如 'Qujing')
        province: 省份名称
    """
    # 使用统一的重试策略获取数据
    data = await _fetch_owm_data("forecast", city, province)
    
    if not data or "list" not in data:
        return json.dumps({"error": f"无法获取 {city} 的天气预报。请尝试使用拼音 (例如: 'Qujing')。"}, ensure_ascii=False)

    timezone_offset = data.get("city", {}).get("timezone", 28800)
    
    # OWM 返回的是 3 小时步长的数据，我们需要按天聚合
    daily_forecasts = {}
    
    for item in data["list"]:
        # 使用带时区的时间戳来确定日期，避免 UTC 和本地时间跨天导致的归属错误
        dt_obj = datetime.datetime.fromtimestamp(item["dt"], datetime.timezone.utc) + datetime.timedelta(seconds=timezone_offset)
        date_str = dt_obj.strftime("%Y-%m-%d")
        
        if date_str not in daily_forecasts:
            daily_forecasts[date_str] = {
                "temps": [],
                "weather": [],
                "wind_speed": [],
                "wind_deg": [],
                "rain": [],
                "pop": []
            }
        
        daily_forecasts[date_str]["temps"].append(item["main"]["temp"])
        if item["weather"]:
            daily_forecasts[date_str]["weather"].append(item["weather"][0]["description"])
        daily_forecasts[date_str]["wind_speed"].append(item["wind"]["speed"])
        daily_forecasts[date_str]["wind_deg"].append(item["wind"]["deg"])
        
        # 处理降雨数据 (rain.3h)
        rain_volume = item.get("rain", {}).get("3h", 0)
        daily_forecasts[date_str]["rain"].append(rain_volume)
        
        # 处理降水概率 (pop)
        pop = item.get("pop", 0)
        daily_forecasts[date_str]["pop"].append(pop)

    forecast_list = []
    # 过滤掉数据点过少的天（比如第一天只剩最后几个小时，或最后一天只有开始几个小时），保证预报质量
    # 标准版 5天 * 8点/天 = 40点。
    
    sorted_dates = sorted(daily_forecasts.keys())
    
    for date in sorted_dates:
        info = daily_forecasts[date]
        
        # 简单统计
        min_temp = min(info["temps"])
        max_temp = max(info["temps"])
        most_common_weather = Counter(info["weather"]).most_common(1)[0][0] if info["weather"] else "未知"
        avg_wind = sum(info["wind_speed"]) / len(info["wind_speed"])
        
        # 降雨统计
        total_rain = sum(info["rain"])
        max_pop = max(info["pop"]) if info["pop"] else 0
        
        forecast_list.append({
            "date": date,
            "min_temp": round(min_temp, 1),
            "max_temp": round(max_temp, 1),
            "weather": most_common_weather,
            "avg_wind_speed": round(avg_wind, 1),
            "total_rain": round(total_rain, 1),
            "rain_probability": round(max_pop * 100, 0)
        })

    return json.dumps(forecast_list, ensure_ascii=False, indent=2)

@mcp.tool()
async def get_observe(city: str, province: str = "") -> str:
    """获取中国某个省，某个城市的实时天气。

    参数:
        city: 城市名称
        province: 省份名称
    """
    data = await _fetch_owm_data("weather", city, province)
    
    if not data:
        return json.dumps({"error": f"无法获取 {city} 的实时天气。"}, ensure_ascii=False)

    weather_desc = data["weather"][0]["description"] if data["weather"] else "未知"
    timezone_offset = data.get("timezone", 0)
    formatted_time = _format_time(data["dt"], timezone_offset)
    
    result = {
        "time": formatted_time,
        "temperature": data['main']['temp'],
        "humidity": data['main']['humidity'],
        "pressure": data['main']['pressure'],
        "weather": weather_desc,
        "wind_direction": data['wind']['deg'],
        "wind_speed": data['wind']['speed']
    }
    return json.dumps(result, ensure_ascii=False, indent=2)

@mcp.tool()
async def get_rise_14day(city: str, province: str = "") -> str:
    """获取中国某个省，某个城市的日出日落时间。
    
    注意：OpenWeatherMap 标准版 API 仅提供当天的日出日落时间。

    参数:
        city: 城市名称
        province: 省份名称
    """
    data = await _fetch_owm_data("weather", city, province)
    
    if not data:
        return json.dumps({"error": f"无法获取 {city} 的日出日落时间。"}, ensure_ascii=False)

    sys_data = data.get("sys", {})
    timezone_offset = data.get("timezone", 0)
    
    sunrise = sys_data.get("sunrise")
    sunset = sys_data.get("sunset")
    
    if not sunrise or not sunset:
        return json.dumps({"error": "数据中缺少日出日落信息。"}, ensure_ascii=False)

    # 仅提取时间部分 HH:MM:SS
    sunrise_iso = _format_time(sunrise, timezone_offset)
    sunset_iso = _format_time(sunset, timezone_offset)

    return json.dumps({
        "date": sunrise_iso.split('T')[0],
        "sunrise": sunrise_iso.split('T')[1],
        "sunset": sunset_iso.split('T')[1],
        "note": "OpenWeatherMap 标准版 API 不支持 14 天日出日落预测，仅返回今日数据。"
    }, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    import sys
    print("Starting weather MCP server...", file=sys.stderr)
    # 初始化并运行服务器
    try:
        mcp.run(transport='stdio')
    except Exception as e:
        print(f"Error running server: {e}", file=sys.stderr)
    print("Server stopped.", file=sys.stderr)
