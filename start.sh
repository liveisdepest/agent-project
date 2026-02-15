#!/bin/bash

# 设置颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "============================================"
echo "🌾 智能农业MCP系统 - 启动脚本"
echo "============================================"
echo ""

# 检查 uv 是否安装
if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ 错误: 未找到 uv 包管理器${NC}"
    echo ""
    echo "请先安装 uv:"
    echo "curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo ""
    exit 1
fi

# 检查 .env 文件
if [ ! -f "client/mcp-client/.env" ]; then
    echo -e "${YELLOW}⚠️  警告: 未找到 .env 配置文件${NC}"
    echo ""
    echo "正在从模板创建..."
    if [ -f "client/mcp-client/.env.example" ]; then
        cp "client/mcp-client/.env.example" "client/mcp-client/.env"
        echo -e "${GREEN}✅ 已创建 .env 文件${NC}"
        echo ""
        echo -e "${YELLOW}⚠️  请编辑 client/mcp-client/.env 文件，填入你的配置${NC}"
        echo ""
        exit 1
    else
        echo -e "${RED}❌ 错误: 未找到 .env.example 模板文件${NC}"
        exit 1
    fi
fi

echo "📋 选择启动模式:"
echo ""
echo "[1] 命令行客户端（推荐测试）"
echo "[2] Web 服务器（推荐生产）"
echo "[3] 仅初始化检查（不启动聊天）"
echo "[4] 退出"
echo ""
read -p "请输入选项 (1-4): " choice

case $choice in
    1)
        echo ""
        echo "🚀 启动命令行客户端..."
        echo ""
        cd client/mcp-client
        uv run client.py
        ;;
    2)
        echo ""
        echo "🌐 启动 Web 服务器..."
        echo ""
        echo "📡 服务地址: http://localhost:8080"
        echo "📚 API 文档: http://localhost:8080/docs"
        echo ""
        cd server/web
        uv run app.py
        ;;
    3)
        echo ""
        echo "🔍 执行初始化检查..."
        echo ""
        cd client/mcp-client
        uv run client.py --init-only
        echo ""
        echo "✅ 检查完成"
        ;;
    4)
        echo "👋 退出"
        exit 0
        ;;
    *)
        echo -e "${RED}❌ 无效选项${NC}"
        exit 1
        ;;
esac
