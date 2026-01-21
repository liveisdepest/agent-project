"""
快速测试脚本 - 土豆灌溉决策
"""
import asyncio
from client import MCPClient

async def test_potato_irrigation():
    print("\n" + "="*60)
    print("🥔 土豆灌溉决策测试")
    print("="*60 + "\n")
    
    client = MCPClient(connection_timeout=30, max_retries=2, tool_timeout=60)
    
    try:
        # 1. 连接服务
        print("📡 连接 MCP 服务...")
        await client.load_servers_from_config("mcp_servers.json")
        await client.list_tools()
        
        # 2. 测试查询
        query = "曲靖天气怎么样，结合传感器，土豆需要灌溉吗"
        print(f"\n💬 测试问题: {query}\n")
        
        response = await client.process_query(query)
        print(f"\n{response}\n")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.clean()

if __name__ == "__main__":
    asyncio.run(test_potato_irrigation())
