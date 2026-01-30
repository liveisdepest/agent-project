"""
智能农业Web服务器 - 简化版
快速启动: python server/web/app.py
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import json
from datetime import datetime
import sys
import os

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
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# ==================== 全局变量 ====================

mcp_client = None
mcp_initialized = False

# ==================== 启动事件 ====================

@app.on_event("startup")
async def startup_event():
    """应用启动时初始化MCP客户端（后台任务）"""
    asyncio.create_task(init_mcp_client())

async def init_mcp_client():
    """后台初始化 MCP 客户端"""
    global mcp_client, mcp_initialized
    
    print("⏳ 等待 Web 服务器启动...")
    await asyncio.sleep(3)  # 给 Uvicorn 一点时间启动 HTTP 服务
    
    print("🚀 正在初始化 MCP 客户端...")
    
    try:
        # 动态导入MCP客户端 (适配调整后的 sys.path)
        from client import MCPClient
        
        mcp_client = MCPClient()
        
        # 加载MCP服务器配置
        config_path = os.path.join(
            os.path.dirname(__file__),
            '../../client/mcp-client/mcp_servers.json'
        )
        
        if not os.path.exists(config_path):
            print(f"⚠️  配置文件不存在: {config_path}")
            print("⚠️  MCP客户端将在受限模式下运行")
            return
        
        await mcp_client.load_servers_from_config(config_path)
        await mcp_client.list_tools()
        
        mcp_initialized = True
        print("✅ MCP客户端初始化成功")
        print(f"📊 已连接 {len(mcp_client.sessions)} 个MCP服务")
        print(f"🔧 可用工具: {len(mcp_client.tools_map)} 个")
        
    except Exception as e:
        print(f"❌ MCP客户端初始化失败: {e}")
        print("⚠️  服务器将在受限模式下运行")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时清理资源"""
    global mcp_client
    
    print("👋 正在关闭服务器...")
    
    if mcp_client:
        try:
            await mcp_client.clean()
            print("✅ MCP客户端资源已清理")
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
SENSOR_DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "sensor", "sensor_data.json")

def save_sensor_data_to_file(data: dict):
    """将传感器数据写入共享文件，供 Sensor MCP 读取"""
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(SENSOR_DATA_FILE), exist_ok=True)
        
        # 读取现有数据
        existing_data = {}
        if os.path.exists(SENSOR_DATA_FILE):
            try:
                with open(SENSOR_DATA_FILE, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except:
                pass
        
        # 更新默认设备数据 (假设设备ID为 ESP8266_001)
        device_id = "ESP8266_001"
        existing_data[device_id] = {
            "temperature": data.get("temperature", 0),
            "humidity": data.get("humidity", 0),
            "soil_moisture": data.get("soil_moisture", 0),
            "timestamp": datetime.now().isoformat()
        }
        
        # 写入文件
        with open(SENSOR_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, indent=2, ensure_ascii=False)
            
    except Exception as e:
        print(f"⚠️  写入传感器数据文件失败: {e}")

# ==================== REST API 端点 ====================

@app.post("/api/command/update")
async def update_command(cmd: dict):
    """更新控制指令（供 MCP Server 调用）"""
    global_state["command"]["pump_on"] = cmd.get("pump_on", False)
    global_state["command"]["last_update"] = datetime.now().isoformat()
    return {"status": "success"}

from fastapi.responses import HTMLResponse, FileResponse
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
    """健康检查端点"""
    return {
        "status": "healthy",
        "mcp_initialized": mcp_initialized,
        "mcp_connected": mcp_client is not None,
        "active_sessions": len(mcp_client.sessions) if mcp_client else 0,
        "available_tools": len(mcp_client.tools_map) if mcp_client else 0,
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
    """处理用户查询（AI决策）"""
    if not mcp_initialized or not mcp_client:
        raise HTTPException(status_code=503, detail="MCP客户端未初始化")
    
    try:
        print(f"📝 收到查询: {request.query}")
        
        response = await asyncio.wait_for(
            mcp_client.process_query(request.query),
            timeout=120
        )
        
        # 广播到所有WebSocket连接
        await manager.broadcast({
            "type": "query_response",
            "query": request.query,
            "response": response,
            "timestamp": datetime.now().isoformat()
        })
        
        return {
            "success": True,
            "response": response,
            "timestamp": datetime.now().isoformat()
        }
        
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="查询处理超时")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询处理失败: {str(e)}")

@app.post("/api/confirm")
async def confirm_action(action: str):
    """确认执行操作"""
    if not mcp_initialized or not mcp_client:
        raise HTTPException(status_code=503, detail="MCP客户端未初始化")
    
    try:
        response = await mcp_client.process_query(action)
        return {
            "success": True,
            "response": response,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"操作确认失败: {str(e)}")

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
    """WebSocket连接，用于实时数据推送"""
    await manager.connect(websocket)
    
    try:
        # 发送欢迎消息
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket连接成功",
            "timestamp": datetime.now().isoformat()
        })
        
        # 定时推送传感器数据
        async def push_sensor_data():
            while True:
                try:
                    await asyncio.sleep(10)  # 每10秒推送一次
                    
                    if mcp_initialized and mcp_client and "irrigation" in mcp_client.sessions:
                        try:
                            data = await get_current_sensor_data()
                            await websocket.send_json({
                                "type": "sensor_update",
                                "data": data.dict(),
                                "timestamp": datetime.now().isoformat()
                            })
                        except:
                            pass
                except asyncio.CancelledError:
                    break
                except:
                    pass
        
        # 启动推送任务
        push_task = asyncio.create_task(push_sensor_data())
        
        # 接收客户端消息
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
                    response = await mcp_client.process_query(message.get("query", ""))
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
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket错误: {e}")
        manager.disconnect(websocket)

# ==================== 主程序 ====================

if __name__ == "__main__":
    import uvicorn
    
    print("="*60)
    print("🌾 智能农业Web服务器")
    print("="*60)
    print("📡 启动地址: http://localhost:8080")
    print("📚 API文档: http://localhost:8080/docs")
    print("🔌 WebSocket: ws://localhost:8080/ws")
    print("="*60)
    print()
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info"
    )
