import asyncio
import json
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 配置文件路径
CONFIG_PATH = os.path.join("client", "mcp-client", "mcp_servers.json")

async def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ 错误: 找不到配置文件 {CONFIG_PATH}")
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

async def run_server_test(server_name, server_config):
    print(f"\n🔌 正在连接到 {server_name} ...")
    
    server_params = StdioServerParameters(
        command=server_config["command"],
        args=server_config["args"],
        cwd=server_config["cwd"],
        env={**os.environ, **server_config.get("env", {})}
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            print(f"✅ 已连接到 {server_name}")
            
            # 列出工具
            tools_result = await session.list_tools()
            tools = tools_result.tools
            
            print(f"\n🔧 {server_name} 提供的工具:")
            for i, tool in enumerate(tools):
                print(f"  [{i+1}] {tool.name}: {tool.description}")
            
            while True:
                print("\n-----------------------------------")
                choice = input(f"输入工具序号进行测试 (输入 q 返回上级): ").strip()
                if choice.lower() == 'q':
                    break
                
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(tools):
                        tool = tools[idx]
                        print(f"\n🛠️  测试工具: {tool.name}")
                        print(f"📝 参数模版: {json.dumps(tool.inputSchema, indent=2, ensure_ascii=False)}")
                        
                        args_str = input("请输入参数 JSON (直接回车使用空对象 {}): ").strip()
                        if not args_str:
                            args = {}
                        else:
                            try:
                                args = json.loads(args_str)
                            except json.JSONDecodeError:
                                print("❌ JSON 格式错误")
                                continue
                        
                        print("⏳ 调用中...")
                        result = await session.call_tool(tool.name, args)
                        
                        print("\n📄 调用结果:")
                        for content in result.content:
                            if content.type == "text":
                                print(content.text)
                            else:
                                print(f"[{content.type} data]")
                    else:
                        print("❌ 无效的序号")
                except ValueError:
                    print("❌ 请输入数字")
                except Exception as e:
                    print(f"❌ 调用出错: {e}")

async def main():
    config = await load_config()
    if not config:
        return

    servers = config.get("mcpServers", {})
    server_names = list(servers.keys())

    while True:
        print("\n" + "="*40)
        print("🧪 MCP 独立测试工具")
        print("="*40)
        
        for i, name in enumerate(server_names):
            print(f"[{i+1}] {name}")
        
        print("\n[q] 退出")
        
        choice = input("\n请选择要测试的 MCP Server: ").strip()
        
        if choice.lower() == 'q':
            break
            
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(server_names):
                server_name = server_names[idx]
                await run_server_test(server_name, servers[server_name])
            else:
                print("❌ 无效的选择")
        except ValueError:
            print("❌ 请输入数字")
        except Exception as e:
            print(f"❌ 发生错误: {e}")

if __name__ == "__main__":
    # 确保在项目根目录运行
    if not os.path.exists("client"):
        print("⚠️  请在项目根目录 (d:\\agent-project) 运行此脚本")
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\n👋 已退出")
