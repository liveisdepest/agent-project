import httpx
import logging
import yaml
import os

logger = logging.getLogger(__name__)

# Load config
config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

async def get_irrigation_status() -> str:
    """
    Returns the current status of the irrigation system and environmental sensors.
    """
    api_url = config.get('api_url')
    endpoint = config.get('sensor_data_endpoint')
    url = f"{api_url}{endpoint}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            
            status = "开启" if data.get('pump_status', False) else "关闭"
            
            return f"""
--- 实时环境数据 ---
温度: {data.get('temperature', 0.0)}°C
空气湿度: {data.get('humidity', 0.0)}%
土壤湿度: {data.get('soil_moisture', 0.0)}%
水泵状态: {status}
数据更新时间: {data.get('last_update') or '暂无数据'}
"""
    except Exception as e:
        logger.error(f"Failed to fetch status: {e}")
        return f"Failed to fetch status: {str(e)}"
