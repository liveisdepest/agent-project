"""
MCP 连接测试脚本
用于诊断 MCP 服务器连接问题
"""
import asyncio
import json
import logging
from client import MCPClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_connections():
    """测试所有 MCP 服务器连接"""
    print("\n" + "="*60)
    print("🔍 MCP 连接诊断工具")
    print("="*60 + "\n")
    
    client = MCPClient(connection_timeout=30, max_retries=2, tool_timeout=60)
    
    try:
        # 1. 加载配置
        print("📋 步骤 1: 加载配置文件...")
        await client.load_servers_from_config("mcp_servers.json")
        
        # 2. 检查连接状态
        print(f"\n📊 步骤 2: 检查连接状态...")
        print(f"   已连接服务数: {len(client.sessions)}")
        for server_id in client.sessions:
            print(f"   ✅ {server_id}")
        
        # 3. 列出工具
        print(f"\n🔧 步骤 3: 加载工具列表...")
        await client.list_tools()
        
        # 4. 按服务器分组显示工具
        print(f"\n📦 步骤 4: 工具详情...")
        tools_by_server = {}
        for tool_name, tool_info in client.tools_map.items():
            server_id = tool_info["server_id"]
            if server_id not in tools_by_server:
                tools_by_server[server_id] = []
            tools_by_server[server_id].append(tool_name)
        
        for server_id, tools in tools_by_server.items():
            print(f"\n   📡 {server_id}:")
            for tool in tools:
                print(f"      - {tool}")
        
        # 5. 测试简单工具调用
        print(f"\n🧪 步骤 5: 测试工具调用...")
        if "get_sensor_data" in client.tools_map:
            try:
                session = client.sessions["irrigation"]["session"]
                result = await asyncio.wait_for(
                    session.call_tool("get_sensor_data", {}),
                    timeout=10
                )
                print(f"   ✅ get_sensor_data 测试成功")
                print(f"      返回: {result.content[0].text[:100]}...")
            except Exception as e:
                print(f"   ❌ get_sensor_data 测试失败: {e}")
        
        print("\n" + "="*60)
        print("✅ 诊断完成")
        print("="*60 + "\n")
        
    except Exception as e:
        logger.error(f"❌ 诊断过程出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.clean()

if __name__ == "__main__":
    asyncio.run(test_connections())
