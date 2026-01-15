# mcp-agent-project

# mcp-agent-project

## 项目介绍
基于LLM、MCP构建的客户端项目，支持通过OpenAI库连接LLM服务，以及通过MCP连接本地MCP服务端。目前支持本地MCP服务（如npx、docker等方式部署），暂不支持SSE；支持单次会话记忆功能。

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

## 功能特点
- 支持连接OpenAI兼容的LLM服务
- 支持连接本地MCP服务
- 实现了天气查询功能（天气预报、天气预警等）
- 实现了文件系统操作功能（创建、读取、写入文件）
- 支持单次会话记忆

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
