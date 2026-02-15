#!/usr/bin/env python3
"""
智能农业MCP系统 - 完整性检查脚本
检查项目配置、依赖和服务状态
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Tuple

# 颜色输出
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")

def print_success(text: str):
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")

def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")

def print_error(text: str):
    print(f"{Colors.RED}❌ {text}{Colors.END}")

def print_info(text: str):
    print(f"{Colors.BLUE}ℹ️  {text}{Colors.END}")

def check_python_version() -> bool:
    """检查 Python 版本"""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 10:
        print_success(f"Python 版本: {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print_error(f"Python 版本过低: {version.major}.{version.minor}.{version.micro} (需要 ≥3.10)")
        return False

def check_uv_installed() -> bool:
    """检查 uv 是否安装"""
    try:
        result = subprocess.run(['uv', '--version'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        if result.returncode == 0:
            version = result.stdout.strip()
            print_success(f"uv 已安装: {version}")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    print_error("uv 未安装")
    print_info("安装命令: powershell -ExecutionPolicy ByPass -c \"irm https://astral.sh/uv/install.ps1 | iex\"")
    return False

def check_env_file() -> Tuple[bool, List[str]]:
    """检查 .env 文件"""
    env_path = Path("client/mcp-client/.env")
    issues = []
    
    if not env_path.exists():
        print_error(".env 文件不存在")
        print_info("请复制 .env.example 为 .env 并填写配置")
        return False, ["缺少 .env 文件"]
    
    print_success(".env 文件存在")
    
    # 检查必要的配置项
    required_keys = ['API_KEY', 'BASE_URL', 'MODEL', 'OWM_API_KEY']
    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for key in required_keys:
        if f"{key}=" not in content:
            issues.append(f"缺少配置项: {key}")
            print_warning(f"缺少配置项: {key}")
        elif f"{key}=your_" in content or f"{key}=\n" in content:
            issues.append(f"配置项未填写: {key}")
            print_warning(f"配置项未填写: {key}")
        else:
            print_success(f"配置项已设置: {key}")
    
    return len(issues) == 0, issues

def check_mcp_config() -> bool:
    """检查 MCP 服务器配置"""
    config_path = Path("client/mcp-client/mcp_servers.json")
    
    if not config_path.exists():
        print_error("mcp_servers.json 不存在")
        return False
    
    print_success("mcp_servers.json 存在")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        servers = config.get('mcpServers', {})
        print_info(f"配置了 {len(servers)} 个 MCP 服务器:")
        
        for server_name in servers.keys():
            print(f"  • {server_name}")
        
        return True
    except json.JSONDecodeError:
        print_error("mcp_servers.json 格式错误")
        return False

def check_server_files() -> Tuple[int, int]:
    """检查服务器文件"""
    servers = [
        'sensor',
        'weather',
        'crop_knowledge',
        'decision',
        'irrigation',
        'filesystem',
        'search'
    ]
    
    found = 0
    total = len(servers)
    
    for server in servers:
        # 检查主文件
        main_files = [
            f"server/{server}/{server}.py",
            f"server/{server}/main.py",
            f"server/{server}/knowledge.py",
            f"server/search/src/duckduckgo_mcp_server/server.py"
        ]
        
        exists = any(Path(f).exists() for f in main_files)
        
        if exists:
            print_success(f"服务器存在: {server}")
            found += 1
        else:
            print_error(f"服务器缺失: {server}")
    
    return found, total

def check_dependencies() -> bool:
    """检查依赖文件"""
    pyproject_files = [
        "client/mcp-client/pyproject.toml",
        "server/sensor/pyproject.toml",
        "server/weather/pyproject.toml",
        "server/crop_knowledge/pyproject.toml",
        "server/decision/pyproject.toml",
        "server/irrigation/pyproject.toml",
        "server/filesystem/pyproject.toml",
        "server/search/pyproject.toml",
    ]
    
    all_exist = True
    for file in pyproject_files:
        if Path(file).exists():
            print_success(f"依赖配置存在: {file}")
        else:
            print_error(f"依赖配置缺失: {file}")
            all_exist = False
    
    return all_exist

def check_ollama() -> bool:
    """检查 Ollama 服务"""
    try:
        result = subprocess.run(['ollama', 'list'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        if result.returncode == 0:
            print_success("Ollama 服务运行正常")
            models = [line.split()[0] for line in result.stdout.strip().split('\n')[1:]]
            if models:
                print_info(f"已安装的模型: {', '.join(models)}")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    print_warning("Ollama 未运行或未安装")
    print_info("如果使用 Ollama，请确保已启动服务")
    return False

def generate_report(checks: dict):
    """生成检查报告"""
    print_header("📊 检查报告")
    
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    
    print(f"总检查项: {total_checks}")
    print(f"通过: {passed_checks}")
    print(f"失败: {total_checks - passed_checks}")
    print(f"通过率: {passed_checks/total_checks*100:.1f}%")
    
    print("\n详细结果:")
    for check_name, passed in checks.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status} - {check_name}")
    
    if passed_checks == total_checks:
        print_success("\n🎉 所有检查通过！系统可以正常运行。")
        return 0
    else:
        print_warning(f"\n⚠️  有 {total_checks - passed_checks} 项检查未通过，请修复后再启动系统。")
        return 1

def main():
    print_header("🌾 智能农业MCP系统 - 完整性检查")
    
    checks = {}
    
    # 1. Python 版本
    print_header("1️⃣ 检查 Python 环境")
    checks['Python 版本'] = check_python_version()
    
    # 2. uv 安装
    print_header("2️⃣ 检查 uv 包管理器")
    checks['uv 安装'] = check_uv_installed()
    
    # 3. 配置文件
    print_header("3️⃣ 检查配置文件")
    env_ok, env_issues = check_env_file()
    checks['.env 配置'] = env_ok
    checks['MCP 配置'] = check_mcp_config()
    
    # 4. 服务器文件
    print_header("4️⃣ 检查服务器文件")
    found, total = check_server_files()
    checks['服务器文件'] = (found == total)
    
    # 5. 依赖配置
    print_header("5️⃣ 检查依赖配置")
    checks['依赖配置'] = check_dependencies()
    
    # 6. Ollama 服务（可选）
    print_header("6️⃣ 检查 Ollama 服务（可选）")
    ollama_ok = check_ollama()
    # Ollama 不是必需的，不计入总分
    
    # 生成报告
    return generate_report(checks)

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n👋 检查已取消")
        sys.exit(1)
    except Exception as e:
        print_error(f"检查过程中发生错误: {e}")
        sys.exit(1)
