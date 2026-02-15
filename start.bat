@echo off
chcp 65001 >nul
echo ============================================
echo 🌾 智能农业MCP系统 - 启动脚本
echo ============================================
echo.

REM 检查 uv 是否安装
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ 错误: 未找到 uv 包管理器
    echo.
    echo 请先安装 uv:
    echo powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo.
    pause
    exit /b 1
)

REM 检查 .env 文件
if not exist "client\mcp-client\.env" (
    echo ⚠️  警告: 未找到 .env 配置文件
    echo.
    echo 正在从模板创建...
    if exist "client\mcp-client\.env.example" (
        copy "client\mcp-client\.env.example" "client\mcp-client\.env"
        echo ✅ 已创建 .env 文件
        echo.
        echo ⚠️  请编辑 client\mcp-client\.env 文件，填入你的配置
        echo.
        pause
        exit /b 1
    ) else (
        echo ❌ 错误: 未找到 .env.example 模板文件
        pause
        exit /b 1
    )
)

echo 📋 选择启动模式:
echo.
echo [1] 命令行客户端（推荐测试）
echo [2] Web 服务器（推荐生产）
echo [3] 仅初始化检查（不启动聊天）
echo [4] 退出
echo.
set /p choice="请输入选项 (1-4): "

if "%choice%"=="1" goto start_cli
if "%choice%"=="2" goto start_web
if "%choice%"=="3" goto init_only
if "%choice%"=="4" goto end

echo ❌ 无效选项
pause
exit /b 1

:start_cli
echo.
echo 🚀 启动命令行客户端...
echo.
cd client\mcp-client
uv run client.py
goto end

:start_web
echo.
echo 🌐 启动 Web 服务器...
echo.
echo 📡 服务地址: http://localhost:8080
echo 📚 API 文档: http://localhost:8080/docs
echo.
cd server\web
uv run app.py
goto end

:init_only
echo.
echo 🔍 执行初始化检查...
echo.
cd client\mcp-client
uv run client.py --init-only
echo.
echo ✅ 检查完成
pause
goto end

:end
exit /b 0
