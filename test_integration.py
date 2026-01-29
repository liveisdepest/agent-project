import asyncio
import os
import sys
import logging

# 调整 path 以便导入 client
sys.path.append(os.path.join(os.path.dirname(__file__), 'client', 'mcp-client'))

from client import MCPClient

# Mock OpenAI (Optional, or just let it fail/run if key exists)
# 如果没有 API KEY，测试会失败。假设用户环境有 .env
# 为了不真正消耗 token 或依赖 key，我们可以 mock 
# 但这里主要是验证工具加载逻辑。

async def test_tool_loading():
    print("Testing MCP Client Tool Loading...")
    client = MCPClient()
    
    # 使用绝对路径加载配置文件
    config_path = os.path.join(os.path.dirname(__file__), 'client', 'mcp-client', 'mcp_servers.json')
    
    # 临时覆盖 load_servers_from_config 中的路径处理，或者我们手动加载
    # client.py 里的 load_servers_from_config 是相对于 client.py 的
    # 所以我们直接调用 client.load_servers_from_config("mcp_servers.json") 应该可以，
    # 前提是 cwd 对了，或者我们把 mcp_servers.json 复制到当前目录?
    # 不，client.py 内部处理了路径：
    # base_dir = os.path.dirname(os.path.abspath(__file__))
    # config_path = os.path.join(base_dir, config_filename)
    
    # 所以只要我们实例化 client，然后调用 load_servers_from_config
    
    try:
        await client.load_servers_from_config("mcp_servers.json")
        await client.list_tools()
        
        print("\nVerifying tools in Reasoning Phase...")
        # 模拟 _run_reasoning_phase 的工具筛选逻辑
        target_tools = ['search']
        tools = []
        all_tools = await client._build_tool_list()
        for t in all_tools:
            name = t['function']['name']
            if any(name == target or name.endswith(f".{target}") for target in target_tools):
                tools.append(t)
        
        if tools:
            print(f"✅ Success: Found search tools for Reasoning Phase: {[t['function']['name'] for t in tools]}")
        else:
            print("❌ Failure: No search tools found for Reasoning Phase.")
            
    finally:
        await client.clean()

if __name__ == "__main__":
    asyncio.run(test_tool_loading())
