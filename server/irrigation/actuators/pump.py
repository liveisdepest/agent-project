import httpx
import logging
import yaml
import os

# Load config
config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

logger = logging.getLogger(__name__)

async def set_pump_state(turn_on: bool):
    """
    Sends a command to the pump controller.
    """
    api_url = config.get('api_url')
    endpoint = config.get('pump_control_endpoint')
    url = f"{api_url}{endpoint}"
    
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                url,
                json={"pump_on": turn_on},
                timeout=5.0
            )
            logger.info(f"Pump set to {'ON' if turn_on else 'OFF'}")
    except Exception as e:
        logger.error(f"Failed to set pump state: {e}")
        raise e

async def get_pump_status() -> bool:
    """
    Fetches the current pump status from sensor data.
    """
    api_url = config.get('api_url')
    endpoint = config.get('sensor_data_endpoint')
    url = f"{api_url}{endpoint}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            return data.get('pump_status', False)
    except Exception as e:
        logger.error(f"Failed to fetch pump status: {e}")
        return False
