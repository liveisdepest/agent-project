import asyncio

from client import MCPClient


async def main():
    client = MCPClient()
    try:
        await client.load_servers_from_config("mcp_servers.json")
        await client.list_tools()
        await client.process_query("今天曲靖的天气怎么样，结合传感器帮我分析小麦需要灌溉吗")
    finally:
        await client.clean()


if __name__ == "__main__":
    asyncio.run(main())

