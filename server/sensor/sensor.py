from mcp.server.fastmcp import FastMCP
import json
from pathlib import Path
from typing import Dict, Any

mcp = FastMCP("sensor")
DATA_FILE = Path(__file__).parent / "sensor_data.json"

def _load_data() -> Dict[str, Any]:
    if not DATA_FILE.exists():
        return {}
    try:
        return json.loads(DATA_FILE.read_text(encoding='utf-8'))
    except:
        return {}

def _save_data(data: Dict[str, Any]):
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')

@mcp.tool()
def upload_sensor_data(device_id: str, temperature: float, humidity: float, soil_moisture: float) -> str:
    """
    Upload sensor data for a specific device.
    
    Args:
        device_id: The ID of the sensor device (e.g., "ESP8266_001")
        temperature: Current temperature in Celsius
        humidity: Current humidity percentage
        soil_moisture: Current soil moisture percentage (0-100)
    """
    data = _load_data()
    data[device_id] = {
        "temperature": temperature,
        "humidity": humidity,
        "soil_moisture": soil_moisture,
        "timestamp": "latest" # In a real app, use time.time()
    }
    _save_data(data)
    return f"Data uploaded for {device_id}"

@mcp.tool()
def get_sensor_data(device_id: str) -> str:
    """
    Get the latest sensor data for a specific device.
    
    Args:
        device_id: The ID of the sensor device
    """
    data = _load_data()
    if device_id not in data:
        return f"No data found for device: {device_id}"
    
    device_data = data[device_id]
    return json.dumps(device_data, ensure_ascii=False)

@mcp.tool()
def list_devices() -> str:
    """List all available devices."""
    data = _load_data()
    return json.dumps(list(data.keys()), ensure_ascii=False)

if __name__ == "__main__":
    mcp.run(transport='stdio')
