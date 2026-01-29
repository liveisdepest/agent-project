import asyncio
import time
import os
import sys
import json
import logging
import statistics
import io
from datetime import datetime

# 强制 stdout/stderr 使用 UTF-8 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 切换工作目录到 client/mcp-client，确保 mcp_servers.json 中的相对路径正确
PROJECT_ROOT = os.getcwd()
CLIENT_DIR = os.path.join(PROJECT_ROOT, 'client', 'mcp-client')
if os.path.exists(CLIENT_DIR):
    os.chdir(CLIENT_DIR)
    print(f"📂 已切换工作目录至: {os.getcwd()}")

# 添加 client 目录到路径 (现在是当前目录)
sys.path.insert(0, os.getcwd())

try:
    from client import MCPClient
except ImportError:
    print("❌ 无法导入 MCPClient")
    sys.exit(1)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 添加文件日志处理器，确保输出 UTF-8 编码的报告
file_handler = logging.FileHandler('benchmark_report.utf8.txt', mode='w', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)
# 同时将 print 输出也重定向到文件（或者用 logger 替代 print）
class LoggerWriter:
    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level
        self.buffer = ""

    def write(self, message):
        if message.strip():
            self.logger.log(self.level, message.strip())

    def flush(self):
        pass

# 替换 sys.stdout 可能会影响 subprocess，所以我们只在 generate_report 里用 logger
# 或者简单点，把所有 print 换成 logger.info

# 测试配置
CONFIG_PATH = 'mcp_servers.json' # 现在可以直接用相对路径
CONCURRENT_REQUESTS = 5  # 并发请求数
TEST_ROUNDS = 3          # 测试轮数

class MCPBenchmark:
    def __init__(self):
        self.client = MCPClient()
        self.results = {
            "irrigation": {"latency": [], "success": 0, "total": 0},
            "weather": {"latency": [], "success": 0, "total": 0}
        }

    async def setup(self):
        """初始化 MCP 客户端"""
        logger.info("🚀 初始化 MCP 客户端...")
        if not os.path.exists(CONFIG_PATH):
            logger.error(f"配置文件未找到: {CONFIG_PATH}")
            return False
        
        await self.client.load_servers_from_config(CONFIG_PATH)
        await self.client.list_tools()
        return True

    async def call_tool(self, service, tool_name, args):
        """调用单个工具并记录耗时"""
        start_time = time.perf_counter()
        success = False
        try:
            if service not in self.client.sessions:
                logger.error(f"服务 {service} 未连接")
                return
            
            session = self.client.sessions[service]["session"]
            await asyncio.wait_for(session.call_tool(tool_name, args), timeout=10)
            success = True
        except Exception as e:
            logger.error(f"调用 {tool_name} 失败: {e}")
        finally:
            end_time = time.perf_counter()
            latency = (end_time - start_time) * 1000  # 转换为毫秒
            
            self.results[service]["total"] += 1
            if success:
                self.results[service]["success"] += 1
                self.results[service]["latency"].append(latency)
            
            return latency, success

    async def run_concurrent_tests(self, service, tool_name, args):
        """执行并发测试"""
        logger.info(f"🔥 开始测试服务: {service} (工具: {tool_name})")
        tasks = []
        for _ in range(CONCURRENT_REQUESTS):
            tasks.append(self.call_tool(service, tool_name, args))
        
        await asyncio.gather(*tasks)

    async def run_benchmark(self):
        """运行完整基准测试"""
        try:
            if not await self.setup():
                return

            logger.info("="*60)
            logger.info(f"📊 MCP 多源数据获取性能测试")
            logger.info(f"并发数: {CONCURRENT_REQUESTS} | 轮数: {TEST_ROUNDS}")
            logger.info("="*60)

            for round in range(1, TEST_ROUNDS + 1):
                logger.info(f"--- 第 {round} 轮测试 ---")
                
                # 1. 测试传感器数据 (Irrigation Service)
                await self.run_concurrent_tests("irrigation", "get_sensor_data", {})
                
                # 2. 测试气象服务 (Weather Service)
                await self.run_concurrent_tests("weather", "get_observe", {"province": "北京", "city": "北京"})
                
                # 间隔一下，避免请求过快
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"测试过程中发生未捕获异常: {e}", exc_info=True)
        finally:
            # 无论如何都生成报告
            self.generate_report()
            # 最后尝试清理资源
            try:
                await self.client.clean()
            except Exception as e:
                logger.error(f"清理资源时出错: {e}")

    def generate_report(self):
        """生成并打印测试报告"""
        logger.info("="*60)
        logger.info("📈 测试报告")
        logger.info("="*60)
        
        for service, data in self.results.items():
            total = data["total"]
            if total == 0:
                logger.info(f"服务: {service} (无数据)")
                continue
                
            success_rate = (data["success"] / total) * 100
            latencies = data["latency"]
            
            logger.info(f"🔹 服务: {service.upper()}")
            logger.info(f"   - 总请求数: {total}")
            logger.info(f"   - 成功率:   {success_rate:.1f}%")
            
            if latencies:
                avg_lat = statistics.mean(latencies)
                min_lat = min(latencies)
                max_lat = max(latencies)
                p95_lat = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max_lat
                
                logger.info(f"   - 平均响应: {avg_lat:.2f} ms")
                logger.info(f"   - 最小响应: {min_lat:.2f} ms")
                logger.info(f"   - 最大响应: {max_lat:.2f} ms")
                logger.info(f"   - P95 响应: {p95_lat:.2f} ms")
            else:
                logger.info("   - 响应时间: N/A (全失败)")

        logger.info("="*60)

if __name__ == "__main__":
    benchmark = MCPBenchmark()
    asyncio.run(benchmark.run_benchmark())