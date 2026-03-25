import httpx
import logging
import yaml
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def load_config() -> Dict[str, Any]:
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')
        if not os.path.exists(config_path):
            logger.warning(f"Config file not found at {config_path}, using defaults")
            return {
                "api_url": "http://127.0.0.1:8080/api",
                "pump_control_endpoint": "/command/update",
                "sensor_data_endpoint": "/sensor/current"
            }
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}

config = load_config()

async def set_pump_state(turn_on: bool):
    """
    Sends a command to the pump controller.
    """
    api_url = config.get('api_url')
    endpoint = config.get('pump_control_endpoint')
    
    if not api_url or not endpoint:
        logger.error("Missing API URL or endpoint configuration")
        raise ValueError("Missing API URL or endpoint configuration")

    url = f"{api_url}{endpoint}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={"pump_on": turn_on},
                timeout=5.0
            )
            response.raise_for_status()
            logger.info(f"Pump set to {'ON' if turn_on else 'OFF'}")
    except Exception as e:
        logger.error(f"Failed to set pump state: {e}")
        raise e

async def get_pump_status() -> Optional[bool]:
    """
    Fetches the current pump status from sensor data.
    Returns None if status cannot be determined (error or misconfiguration).
    """
    api_url = config.get('api_url')
    endpoint = config.get('sensor_data_endpoint')
    
    if not api_url or not endpoint:
        logger.error("Missing API URL or endpoint configuration")
        return None

    url = f"{api_url}{endpoint}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            return data.get('pump_status', False)
    except Exception as e:
        logger.error(f"Failed to fetch pump status: {e}")
        return None
