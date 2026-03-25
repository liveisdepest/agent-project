from mcp.server.fastmcp import FastMCP
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, List
import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("sensor_server")

mcp = FastMCP("sensor")
DB_FILE = Path(__file__).parent / "sensor.db"

def _get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    return sqlite3.connect(DB_FILE)

def _init_db():
    """初始化 SQLite 数据库。"""
    try:
        with _get_connection() as conn:
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
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

def _init_demo_data():
    """初始化演示数据（如果没有任何数据）。"""
    try:
        with _get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM sensor_data")
            count = cursor.fetchone()[0]
            if count == 0:
                conn.execute("""
                    INSERT INTO sensor_data (device_id, temperature, humidity, soil_moisture, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, ("ESP8266_001", 25.0, 60.0, 45.0, datetime.datetime.now().isoformat()))
                conn.commit()
                logger.info("Demo data initialized")
    except Exception as e:
        logger.error(f"Failed to initialize demo data: {e}")

# Initialize DB on module load
_init_db()
_init_demo_data()

def _load_data() -> Dict[str, Any]:
    """加载所有设备数据"""
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
        logger.error(f"Error loading data: {e}")
        return {}

def _save_device_data(device_id: str, data: Dict[str, Any]):
    """保存设备数据"""
    try:
        with _get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sensor_data (device_id, temperature, humidity, soil_moisture, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (device_id, data["temperature"], data["humidity"], data["soil_moisture"], data["timestamp"]))
            conn.commit()
    except Exception as e:
        logger.error(f"Error saving data for {device_id}: {e}")
        raise

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
        "timestamp": datetime.datetime.now().isoformat()
    }
    try:
        _save_device_data(device_id, data)
        logger.info(f"Data uploaded for {device_id}: {data}")
        return f"Data uploaded for {device_id}"
    except Exception as e:
        return f"Error uploading data: {str(e)}"

@mcp.tool()
def get_sensor_data(device_id: str) -> str:
    """
    获取特定设备的最新传感器数据。
    
    Args:
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
