from typing import Any, Dict, List
import httpx
from mcp.server.fastmcp import FastMCP, Context
import datetime
import os
import json
from collections import Counter
import sys
from pypinyin import lazy_pinyin
from dotenv import load_dotenv
load_dotenv()

# 初始化 FastMCP 服务器
mcp = FastMCP("weather")

# 常量
OWM_BASE_URL = "https://api.openweathermap.org/data/2.5"

# 移除全局 HTTP 客户端，避免初始化阻塞
# 改为每次请求时创建临时客户端

def get_api_key() -> str | None:
    key = os.getenv("OWM_API_KEY")
    print(f"OWM_API_KEY loaded: {'YES' if key else 'NO'}", file=sys.stderr)
    return key or None

def _build_weather_error_payload(city: str, endpoint: str, detail: str, attempts: List[str] | None = None) -> Dict[str, Any]:
    detail = detail or "unknown_error"
    hints: List[str] = []

    if "missing_api_key" in detail:
        hints = [
            "未检测到 OWM_API_KEY，请在 weather 服务运行环境中配置该变量。",
            "确认配置后重启 weather MCP 服务。"
        ]
    elif "timeout" in detail:
        hints = [
            "访问 OpenWeatherMap 超时，请检查本机网络连通性。",
            "若网络受限，请配置代理或切换可用网络。"
        ]
    elif "request_error" in detail:
        hints = [
            "请求 OpenWeatherMap 失败，请检查 DNS/网络/防火墙。",
            "确认服务端可以访问 api.openweathermap.org。"
        ]
    elif "http_status" in detail:
        hints = [
            "OpenWeatherMap 返回了非 2xx 状态，请检查 key 权限、配额和账号状态。",
            "可在日志中查看具体 status code 与 message。"
        ]
    elif "api_error" in detail:
        hints = [
            "OpenWeatherMap 已返回业务错误，请检查城市名、key 有效性和请求参数。",
            "必要时尝试改用英文城市名或拼音。"
        ]
    else:
        hints = [
            "请检查天气服务日志以定位具体失败原因。"
        ]

    payload: Dict[str, Any] = {
        "error": f"无法获取 {city} 的天气数据。",
        "endpoint": endpoint,
        "detail": detail,
        "hints": hints,
    }
    if attempts:
        payload["query_attempts"] = attempts
    return payload

async def make_owm_request(endpoint: str, params: Dict[str, Any]) -> tuple[Dict[str, Any] | None, str | None]:
    """向 OpenWeatherMap API 发送请求并返回 (响应数据, 错误原因)."""
    api_key = get_api_key()
    if not api_key:
        return None, "missing_api_key"
    url = f"{OWM_BASE_URL}/{endpoint}"
    params["appid"] = api_key
    params["units"] = "metric"  # 使用公制单位 (摄氏度)
    params["lang"] = "zh_cn"    # 返回中文描述
    
    # 每次创建新的客户端，避免全局状态和初始化阻塞
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            # API 返回的 cod 可能是 int 200 或 string "200"
            cod = str(data.get("cod", "200"))
            if cod != "200":
                message = str(data.get("message", "unknown"))
                return None, f"api_error:cod={cod},message={message}"
            return data, None
        except httpx.TimeoutException:
            return None, "timeout"
        except httpx.HTTPStatusError as e:
            detail = f"http_status:{e.response.status_code}"
            try:
                err_payload = e.response.json()
                message = err_payload.get("message")
                if message:
                    detail = f"{detail},message={message}"
            except Exception:
                pass
            return None, detail
        except httpx.RequestError as e:
            return None, f"request_error:{str(e)}"
        except Exception as e:
            return None, f"unexpected_error:{str(e)}"

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
    """如果包含中文，转换为拼音，处理特殊城市名称"""
    if not text:
        return text
    
    # 特殊城市名称映射表
    city_mapping = {
        '西安': 'xian',
        '重庆': 'chongqing',
        '长春': 'changchun',
        '长沙': 'changsha',
        '成都': 'chengdu',
        '广州': 'guangzhou',
        '贵阳': 'guiyang',
        '哈尔滨': 'harbin',
        '杭州': 'hangzhou',
        '合肥': 'hefei',
        '呼和浩特': 'huhehaote',
        '济南': 'jinan',
        '昆明': 'kunming',
        '曲靖': 'qujing',
        '兰州': 'lanzhou',
        '拉萨': 'lasa',
        '南昌': 'nanchang',
        '南京': 'nanjing',
        '南宁': 'nanning',
        '北京': 'beijing',
        '上海': 'shanghai',
        '天津': 'tianjin',
        '石家庄': 'shijiazhuang',
        '太原': 'taiyuan',
        '武汉': 'wuhan',
        '乌鲁木齐': 'wulumuqi',
        '银川': 'yinchuan',
        '郑州': 'zhengzhou'
    }
    
    # 简单的检查：如果包含非 ASCII 字符，假设是中文
    if not all(ord(c) < 128 for c in text):
        # 首先检查是否在映射表中
        if text in city_mapping:
            return city_mapping[text]
        # 使用 lazy_pinyin 转换，但处理多音字问题
        pinyin_list = lazy_pinyin(text)
        # 对于两个字的拼音，添加分隔符避免歧义
        if len(pinyin_list) == 2:
            return f"{pinyin_list[0]}{pinyin_list[1]}"
        return "".join(pinyin_list)
    return text

import logging
import time

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("weather_server")

# 简单的内存缓存: (endpoint, city_pinyin) -> (data, timestamp)
_CACHE: Dict[tuple[str, str], tuple[Dict[str, Any], float]] = {}
CACHE_TTL = 600  # 10 分钟缓存

async def _fetch_owm_data(endpoint: str, city: str, province: str = "") -> tuple[Dict[str, Any] | None, str]:
    """尝试获取 OWM 数据，带有重试策略（CN后缀 vs 无后缀）和缓存"""
    # 自动转换为拼音
    city_pinyin = _ensure_pinyin(city)
    cache_key = (endpoint, city_pinyin)

    # 1. 检查缓存
    if cache_key in _CACHE:
        data, timestamp = _CACHE[cache_key]
        if time.time() - timestamp < CACHE_TTL:
            logger.info(f"Using cached data for {city} ({endpoint})")
            return data, ""

    attempts: List[str] = []

    # 策略 1: City,CN (优先尝试带国家代码)
    params = {"q": f"{city_pinyin},CN"}
    data, err = await make_owm_request(endpoint, params)
    if err:
        attempts.append(f"{params['q']} -> {err}")
    
    if _is_valid_response(data):
        # 写入缓存
        _CACHE[cache_key] = (data, time.time())
        return data, ""
        
    # 策略 2: 仅 City (针对中文名称可能不需要后缀的情况，或者其他模糊情况)
    # OpenWeatherMap 有时对 "北京" 比 "北京,CN" 处理得更好，或者反之。
    params = {"q": city_pinyin}
    data, err = await make_owm_request(endpoint, params)
    if err:
        attempts.append(f"{params['q']} -> {err}")
    
    if _is_valid_response(data):
        # 写入缓存
        _CACHE[cache_key] = (data, time.time())
        return data, ""
        
    return None, "; ".join(attempts) if attempts else "unknown_error"


def _weather_error_json(city: str, endpoint: str, detail: str) -> str:
    """???????????? JSON?"""
    return json.dumps(
        _build_weather_error_payload(city, endpoint, detail),
        ensure_ascii=False
    )


async def _fetch_owm_or_error(
    endpoint: str,
    city: str,
    province: str = "",
    required_key: str | None = None
) -> tuple[Dict[str, Any] | None, str | None]:
    """?????????????????????? JSON?"""
    data, error_detail = await _fetch_owm_data(endpoint, city, province)
    if not data or (required_key and required_key not in data):
        return None, _weather_error_json(city, endpoint, error_detail)
    return data, None


@mcp.tool()
async def get_forecast_48h(city: str, province: str = "") -> str:
    """获取中国某个省，某个城市的未来48个小时天气预报。
    
    返回 JSON 格式数据，包含未来 48 小时内的预报数据（约 16 个时间点）。

    参数:
        city: 城市名称 (拼音或英文)
        province: 省份名称 (可选，用于辅助说明)
    """
    data, error_json = await _fetch_owm_or_error(
        "forecast",
        city,
        province,
        required_key="list"
    )
    if error_json:
        return error_json

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
    data, error_json = await _fetch_owm_or_error(
        "forecast",
        city,
        province,
        required_key="list"
    )
    if error_json:
        return error_json

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
    data, error_detail = await _fetch_owm_data("weather", city, province)
    
    if not data:
        # 返回类型错误而不是详细的错误payload
        return json.dumps(
            {"error": "类型错误", "detail": error_detail},
            ensure_ascii=False
        )

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
    data, error_json = await _fetch_owm_or_error("weather", city, province)
    if error_json:
        return error_json

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
