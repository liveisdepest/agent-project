from mcp.server.fastmcp import FastMCP
import os

# 初始化FastMCP服务器
mcp = FastMCP("filesystem")

# 定义基础目录，确保文件操作在 file 目录及其子目录下
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "file"))

def _get_safe_path(file_name: str) -> str:
    """
    获取安全的文件路径，防止路径遍历攻击
    """
    # 确保 file 目录存在
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)
        
    # 如果文件名包含路径，只取文件名部分，或者确保它在 BASE_DIR 下
    # 这里简化处理，直接拼接并检查是否在 BASE_DIR 内
    full_path = os.path.abspath(os.path.join(BASE_DIR, file_name))
    
    if not full_path.startswith(BASE_DIR):
        raise ValueError(f"访问被拒绝：路径 {full_path} 超出允许范围 {BASE_DIR}")
        
    return full_path

@mcp.tool()
async def create_file(file_name: str, content: str) -> str:
    """
    在 file 目录下创建文件
    :param file_name: 文件名 (例如: "report.txt")
    :param content: 文件内容
    :return: 创建成功消息
    """
    try:
        full_path = _get_safe_path(file_name)
        with open(full_path, "w", encoding="utf-8") as file:
            file.write(content)
        return f"文件'{file_name}'已成功创建在 file 目录"
    except Exception as e:
        return f"创建文件失败: {str(e)}"

@mcp.tool()
async def read_file(file_name: str) -> str:
    """
    读取 file 目录下的文件内容
    :param file_name: 文件名
    :return: 文件内容或错误消息
    """
    try:
        full_path = _get_safe_path(file_name)
        with open(full_path, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        return f"文件'{file_name}'未找到"
    except Exception as e:
        return f"读取文件失败: {str(e)}"

@mcp.tool()
async def write_file(file_name: str, content: str) -> str:
    """
    向 file 目录下的文件写入内容
    :param file_name: 文件名
    :param content: 文件内容
    :return: 写入成功消息
    """
    try:
        full_path = _get_safe_path(file_name)
        with open(full_path, "w", encoding="utf-8") as file:
            file.write(content)
        return f"文件'{file_name}'写入成功"
    except Exception as e:
        return f"写入文件失败: {str(e)}"

if __name__ == "__main__":
    # 以标准 I/O 方式运行 MCP 服务器
    mcp.run(transport="stdio")