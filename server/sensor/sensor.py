from mcp.server.fastmcp import FastMCP
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any
import contextlib

mcp = FastMCP("sensor")
DB_FILE = Path(__file__).parent / "sensor.db"

def _init_db():
    """初始化 SQLite 数据库。"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sensor_data (
                device_id TEXT PRIMARY KEY,
                temperature REAL,
                humidity REAL,
                soil_moisture REAL,
                timestamp TEXT
            )
        """)
        conn.commit()

# Initialize DB on module load
_init_db()

def _init_demo_data():
    """Initialize demo data if no data exists."""
    try:
        with _get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM sensor_data")
            count = cursor.fetchone()[0]
            if count == 0:
                conn.execute("""
                    INSERT INTO sensor_data (device_id, temperature, humidity, soil_moisture, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, ("ESP8266_001", 25.0, 60.0, 45.0, "2023-10-01T12:00:00"))
                conn.commit()
    except Exception:
        pass

# Initialize demo data
_init_demo_data()

def _get_connection():
    return sqlite3.connect(DB_FILE)

def _load_data() -> Dict[str, Any]:
    try:
        with _get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM sensor_data")
            rows = cursor.fetchall()
            data = {}
            for row in rows:
                data[row["device_id"]] = {
                    "temperature": row["temperature"],
                    "humidity": row["humidity"],
                    "soil_moisture": row["soil_moisture"],
                    "timestamp": row["timestamp"]
                }
            return data
    except Exception as e:
        # Log error in a real app
        return {}

def _save_device_data(device_id: str, data: Dict[str, Any]):
    with _get_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO sensor_data (device_id, temperature, humidity, soil_moisture, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (device_id, data["temperature"], data["humidity"], data["soil_moisture"], data["timestamp"]))
        conn.commit()

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
    data = {
        "temperature": temperature,
        "humidity": humidity,
        "soil_moisture": soil_moisture,
        "timestamp": "latest" # In a real app, use datetime.now().isoformat()
    }
    _save_device_data(device_id, data)
    return f"Data uploaded for {device_id}"

@mcp.tool()
def get_sensor_data(device_id: str) -> str:
    """
    获取特定设备的最新传感器数据。
    
    参数:
        device_id: 传感器设备ID
    """
    data = _load_data()
    if device_id not in data:
        return f"未找到设备数据: {device_id}"
    
    device_data = data[device_id]
    return json.dumps(device_data, ensure_ascii=False)

@mcp.tool()
def list_devices() -> str:
    """列出所有可用设备。"""
    data = _load_data()
    return json.dumps(list(data.keys()), ensure_ascii=False)

if __name__ == "__main__":
    mcp.run(transport='stdio')
