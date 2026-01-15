from mcp.server.fastmcp import FastMCP

# 初始化FastMCP服务器
mcp = FastMCP("filesystem")

@mcp.tool()
async def create_file(file_name: str, content: str) -> str:
    """
    创建文件
    :param file_name: 文件名
    :param content: 文件内容
    :return: 创建成功消息
    """
    try:
        with open(file_name, "w", encoding="utf-8") as file:
            file.write(content)
        return f"文件'{file_name}'创建成功"
    except Exception as e:
        return f"创建文件失败: {str(e)}"

@mcp.tool()
async def read_file(file_name: str) -> str:
    """
    读取文件内容
    :param file_name: 文件名
    :return: 文件内容或错误消息
    """
    try:
        with open(file_name, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        return f"文件'{file_name}'未找到"
    except Exception as e:
        return f"读取文件失败: {str(e)}"

@mcp.tool()
async def write_file(file_name: str, content: str) -> str:
    """
    写入文件内容
    :param file_name: 文件名
    :param content: 文件内容
    :return: 写入成功消息
    """
    try:
        with open(file_name, "w", encoding="utf-8") as file:
            file.write(content)
        return f"文件'{file_name}'写入成功"
    except Exception as e:
        return f"写入文件失败: {str(e)}"

if __name__ == "__main__":
    # 以标准 I/O 方式运行 MCP 服务器
    mcp.run(transport="stdio")