"""
智能农业Web服务器 - 简化版
快速启动: python server/web/app.py
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Dict, List, Optional
import asyncio
import json
from datetime import datetime
import sys
import os
from contextlib import suppress
from uuid import uuid4

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
# 添加 client 目录到路径，以便直接导入 mcp-client
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../client/mcp-client'))

app = FastAPI(
    title="智能农业Web API",
    description="基于MCP的智能农业决策系统Web接口",
    version="1.0.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 数据模型 ====================

class QueryRequest(BaseModel):
    query: str
    user_id: Optional[str] = "anonymous"

class ConfirmRequest(BaseModel):
    action: str
    user_id: Optional[str] = "anonymous"

class SensorDataResponse(BaseModel):
    temperature: float
    humidity: float
    soil_moisture: float
    pump_status: bool
    last_update: Optional[str]

# ==================== WebSocket管理 ====================

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"✅ 新的WebSocket连接，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"❌ WebSocket断开，当前连接数: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        dead_connections: List[WebSocket] = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        for connection in dead_connections:
            self.disconnect(connection)

manager = ConnectionManager()

# ==================== 全局变量 ====================

user_clients: Dict[str, object] = {}
user_clients_lock = asyncio.Lock()
mcp_server_config_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '../../client/mcp-client/mcp_servers.json')
)
mcp_boot_ready = False
mcp_boot_error: Optional[str] = None

# ==================== 启动事件 ====================

@app.on_event("startup")
async def startup_event():
    global mcp_boot_ready, mcp_boot_error
    if os.path.exists(mcp_server_config_path):
        mcp_boot_ready = True
        mcp_boot_error = None
        print("✅ MCP配置已就绪，将按用户按需初始化会话")
    else:
        mcp_boot_ready = False
        mcp_boot_error = f"MCP配置文件不存在: {mcp_server_config_path}"
        print(f"❌ {mcp_boot_error}")

async def get_user_client(user_id: Optional[str]):
    uid = (user_id or "anonymous").strip() or "anonymous"
    cached = user_clients.get(uid)
    if cached:
        return cached
    if not mcp_boot_ready:
        raise RuntimeError(mcp_boot_error or "MCP客户端未初始化")
    async with user_clients_lock:
        cached = user_clients.get(uid)
        if cached:
            return cached
        from client import MCPClient
        client = MCPClient()
        await client.load_servers_from_config(mcp_server_config_path)
        await client.list_tools()
        user_clients[uid] = client
        return client

async def remove_user_client(user_id: Optional[str]) -> None:
    uid = (user_id or "anonymous").strip() or "anonymous"
    async with user_clients_lock:
        client = user_clients.pop(uid, None)
    if client:
        try:
            await client.clean()
        except Exception as e:
            print(f"⚠️ 清理用户会话失败({uid}): {e}")

@app.on_event("shutdown")
async def shutdown_event():
    print("👋 正在关闭服务器...")
    clients = list(user_clients.values())
    user_clients.clear()
    for client in clients:
        try:
            await client.clean()
        except Exception as e:
            print(f"⚠️  清理资源时出错: {e}")

# ==================== 全局状态存储 ====================
# 用于存储最新的传感器数据和控制指令
global_state = {
    "sensor_data": {
        "temperature": 0.0,
        "humidity": 0.0,
        "soil_moisture": 0.0,
        "pump_status": False,
        "last_update": None
    },
    "command": {
        "pump_on": False,
        "last_update": None
    }
}

# 传感器数据文件路径 (用于与 Sensor MCP 共享数据)
SENSOR_DB_FILE = os.path.join(os.path.dirname(__file__), "..", "sensor", "sensor.db")

def save_sensor_data_to_file(data: dict):
    """将传感器数据写入共享数据库，供 Sensor MCP 读取"""
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(SENSOR_DB_FILE), exist_ok=True)
        
        device_id = "ESP8266_001"
        import sqlite3
        with sqlite3.connect(SENSOR_DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sensor_data (
                    device_id TEXT PRIMARY KEY,
                    temperature REAL,
                    humidity REAL,
                    soil_moisture REAL,
                    timestamp TEXT
                )
            """)
            conn.execute("""
                INSERT OR REPLACE INTO sensor_data (device_id, temperature, humidity, soil_moisture, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (
                device_id, 
                data.get("temperature", 0), 
                data.get("humidity", 0), 
                data.get("soil_moisture", 0), 
                datetime.now().isoformat()
            ))
            conn.commit()
            
    except Exception as e:
        print(f"⚠️  写入传感器数据数据库失败: {e}")

# ==================== REST API 端点 ====================

@app.post("/api/command/update")
async def update_command(cmd: dict):
    """更新控制指令（供 MCP Server 调用）"""
    pump_on = bool(cmd.get("pump_on", False))
    now = datetime.now().isoformat()
    global_state["command"]["pump_on"] = pump_on
    global_state["command"]["last_update"] = now
    # 与实时状态保持一致，避免接口短时不一致
    global_state["sensor_data"]["pump_status"] = pump_on
    global_state["sensor_data"]["last_update"] = now

    await manager.broadcast({
        "type": "sensor_update",
        "data": global_state["sensor_data"],
        "timestamp": now,
    })
    return {"status": "success"}

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ... (在 app = FastAPI(...) 之后添加)

# 挂载静态文件目录
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    """返回主页"""
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/health")
async def health_check():
    active_sessions = sum(len(client.sessions) for client in user_clients.values())
    available_tools = sum(len(client.tools_map) for client in user_clients.values())
    return {
        "status": "healthy",
        "mcp_initialized": mcp_boot_ready,
        "mcp_connected": len(user_clients) > 0,
        "active_users": len(user_clients),
        "active_sessions": active_sessions,
        "available_tools": available_tools,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/sensor/current", response_model=SensorDataResponse)
async def get_current_sensor_data():
    """获取当前传感器数据（直接从全局状态获取，不再通过 MCP）"""
    data = global_state["sensor_data"]
    
    # 构造响应数据
    response_data = {
        'temperature': data.get('temperature', 0.0),
        'humidity': data.get('humidity', 0.0),
        'soil_moisture': data.get('soil_moisture', 0.0),
        'pump_status': data.get('pump_status', False),
        'last_update': data.get('last_update')
    }
    
    return SensorDataResponse(**response_data)

@app.post("/api/query")
async def process_query(request: QueryRequest):
    try:
        print(f"📝 收到查询: {request.query}")
        client = await get_user_client(request.user_id)
        response = await asyncio.wait_for(
            client.process_query(request.query),
            timeout=120
        )
        
        return {
            "success": True,
            "response": response,
            "timestamp": datetime.now().isoformat()
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="查询处理超时")
    except Exception as e:
        print(f"❌ 查询处理失败: {e}")
        raise HTTPException(status_code=500, detail="查询处理失败")

@app.post("/api/confirm")
async def confirm_action(request: ConfirmRequest):
    try:
        client = await get_user_client(request.user_id)
        response = await client.process_query(request.action)
        return {
            "success": True,
            "response": response,
            "timestamp": datetime.now().isoformat()
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        print(f"❌ 操作确认失败: {e}")
        raise HTTPException(status_code=500, detail="操作确认失败")

# ==================== Arduino 专用接口 ====================

@app.post("/upload_data")
async def upload_sensor_data(data: dict):
    """接收 Arduino 上报的传感器数据"""
    try:
        print(f"📡 收到传感器数据: {data}")
        
        # 更新全局状态
        global_state["sensor_data"].update({
            "temperature": data.get("temperature", 0),
            "humidity": data.get("humidity", 0),
            "soil_moisture": data.get("soil_moisture", 0),
            "last_update": datetime.now().isoformat()
        })
        
        # 同步写入到 Sensor MCP 的数据文件
        save_sensor_data_to_file(global_state["sensor_data"])
        
        # 广播给 WebSocket 前端展示
        await manager.broadcast({
            "type": "sensor_update",
            "data": global_state["sensor_data"],
            "timestamp": datetime.now().isoformat()
        })
        return {"status": "success"}
    except Exception as e:
        print(f"❌ 处理传感器数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_command")
async def get_arduino_command():
    """Arduino 获取控制指令"""
    return {"pump_on": global_state["command"]["pump_on"]}

# ==================== WebSocket 端点 ====================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    session_user_id = f"ws_{uuid4().hex[:8]}"
    push_task = None
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket连接成功",
            "timestamp": datetime.now().isoformat()
        })

        async def push_sensor_data():
            while True:
                try:
                    await asyncio.sleep(10)
                    data = await get_current_sensor_data()
                    await websocket.send_json({
                        "type": "sensor_update",
                        "data": data.dict(),
                        "timestamp": datetime.now().isoformat()
                    })
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass

        push_task = asyncio.create_task(push_sensor_data())
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            if message.get("type") == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": datetime.now().isoformat()
                })
            elif message.get("type") == "query":
                try:
                    query = message.get("query", "")
                    user_id = message.get("user_id") or session_user_id
                    session_user_id = user_id
                    client = await get_user_client(user_id)
                    response = await client.process_query(query)
                    await websocket.send_json({
                        "type": "query_response",
                        "response": response,
                        "timestamp": datetime.now().isoformat()
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                        "timestamp": datetime.now().isoformat()
                    })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket错误: {e}")
    finally:
        if push_task:
            push_task.cancel()
            with suppress(asyncio.CancelledError):
                await push_task
        manager.disconnect(websocket)
        await remove_user_client(session_user_id)

# ==================== 主程序 ====================

if __name__ == "__main__":
    import uvicorn
    
    print("="*60)
    print("🌾 智能农业Web服务器")
    print("="*60)
    print("📡 启动地址: http://localhost:8080")
    print("="*60)
    print()
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info"
    )
