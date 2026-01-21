# 🌱 智能农业MCP系统

## 项目介绍
基于AI和物联网技术的智能农业决策系统，集成了环境监测、天气分析、作物知识获取和自动控制四大核心功能，能够为用户提供专业的农业管理建议和自动化控制服务。

## ✨ 核心特性

### 🔗 四大功能模块深度关联
1. **环境监测** - 实时获取温度、湿度、土壤湿度数据
2. **天气服务** - 查询实时天气、预报、预警信息  
3. **作物知识** - 网络搜索作物生长习性和管理要求
4. **智能控制** - 基于综合分析的自动化灌溉控制

### 🧠 智能决策流程
```
用户询问 → 数据收集 → 综合分析 → 专业建议 → 用户确认 → 执行控制
```

### 💡 典型使用场景
```
用户："曲靖今天的天气怎么样，我的小麦需要灌溉吗？"

AI助手自动执行：
1. 🔍 获取传感器数据
2. 🌤️ 查询曲靖天气
3. 🌐 搜索小麦生长习性  
4. 🧠 综合分析生成建议
5. ⚡ 等待用户确认后执行控制
```

## 🏗️ 系统架构

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   ESP8266       │    │   MCP服务集群     │    │   AI客户端       │
│   物联网设备     │◄──►│                  │◄──►│   智能决策       │
│                 │    │  • 灌溉服务       │    │                 │
│  • 传感器采集   │    │  • 天气服务       │    │  • 多模态分析   │
│  • 设备控制     │    │  • 浏览器服务     │    │  • 工具调用     │
│  • 状态上报     │    │  • 文件系统       │    │  • 决策生成     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## 项目结构
```
├── .gitignore
├── .idea/
├── .vscode/
├── LICENSE
├── README.md
├── client/
│   └── mcp-client/
│       ├── .env.example
│       ├── .python-version
│       ├── README.md
│       ├── __pycache__/
│       ├── client.py
│       ├── mcp_servers.json.example
│       ├── pyproject.toml
│       └── uv.lock
├── package-lock.json
├── package.json
└── server/
    ├── filesystem/
    │   ├── .python-version
    │   ├── README.md
    │   ├── filesystem.py
    │   ├── pyproject.toml
    │   └── uv.lock
    └── weather/
        ├── .python-version
        ├── README.md
        ├── pyproject.toml
        ├── uv.lock
        └── weather.py
```

## 🚀 快速开始

### 方式一：增强版客户端（推荐）
```bash
cd client/mcp-client
uv run client_enhanced.py
```

### 方式二：集成测试
```bash
python test_integration.py
```

### 方式三：原版客户端
```bash
cd client/mcp-client
uv run client.py
```

## 💬 使用示例

### 综合农业决策
```
问：曲靖今天的天气怎么样，我的小麦需要灌溉吗？

AI会自动：
1. 获取传感器数据 → 土壤湿度45%，温度28°C
2. 查询曲靖天气 → 晴天，无降雨预报
3. 搜索小麦需求 → 小麦拔节期需水量大
4. 综合分析建议 → 建议适量灌溉
5. 等待用户确认 → "请帮我开启水泵"
6. 执行控制操作 → 水泵已开启
```

### 作物知识查询
```
问：帮我查一下玉米的最佳生长环境

AI会搜索玉米种植知识，结合当前环境数据给出对比分析
```

### 设备控制
```
问：开启水泵 / 关闭水泵

AI会安全地执行设备控制操作
```

## 安装教程

### 1. 克隆项目到本地
```
git clone https://gitee.com/lue-yu/mcp-agent-project.git
```

### 2. 确保你已有Python环境
- 安装了Python 3.10或更高版本
- 安装了Python MCP SDK 1.2.0或更高版本

### 3. 配置虚拟环境
#### 3.1 安装uv
```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 4. 配置LLM服务地址、模型、密钥
编辑`client\mcp-client\.env.example`示例配置文件：
```
BASE_URL=http://localhost:11434/v1 # 可以是线上地址，也可以是Ollama的本地地址
MODEL=your_model_name   # 模型名称
API_KEY=your_api_key # 模型密钥，Ollama没有密钥则留空
```
完成编辑后，重命名为`.env`。

### 5. 配置MCP服务
编辑`client\mcp-client\mcp_servers.json.example`示例配置文件：
```
{
    "mcpServers": {
    	"amap-maps": {
            "command": "npx",
            "args": [
                "-y",
                "@amap/amap-maps-mcp-server"
            ],
            "env": {
                "AMAP_MAPS_API_KEY": "你的key"
            }
        },
        "weather": {
            "command": "uv",
            "args": [
                "--directory",
                "..\\..\\server\\weather",
                "run",
                "weather.py"
            ]
        },
        "filesystem": {
            "command": "uv",
            "args": [
                "--directory",
                "..\\..\\server\\filesystem",
                "run",
                "filesystem.py"
            ]
        }
    }
}
```
配置好后，重命名为`mcp_servers.json`。

### 6. 安装依赖
进入客户端目录并安装依赖：
```
cd client\mcp-client
uv install
```

### 7. 启动客户端
```
cd client\mcp-client
uv venv
.venv\Scripts\activate
uv run client.py
```

启动后，你可以开始与智能体聊天并使用其提供的功能。
