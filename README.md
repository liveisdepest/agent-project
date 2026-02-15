# 🌱 智能农业MCP系统

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-1.6.0-orange)](https://modelcontextprotocol.io/)

> 基于 AI 和物联网技术的智能农业决策系统，集成环境监测、天气分析、作物知识获取和自动控制四大核心功能，为用户提供专业的农业管理建议和自动化控制服务。

## 📖 目录

- [项目介绍](#项目介绍)
- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [详细安装](#详细安装)
- [使用示例](#使用示例)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

## 项目介绍

智能农业MCP系统是一个创新的农业管理解决方案，采用 Model Context Protocol (MCP) 架构，将多个专业服务整合为统一的智能决策系统。系统通过 AI 大模型协调各个服务，实现从数据采集、分析决策到执行控制的全流程自动化。

## ✨ 核心特性

### 🔗 核心功能模块
1. **环境监测（sensor）** - 实时获取温度、湿度、土壤湿度数据
2. **天气服务（weather）** - 查询实时天气、预报、预警信息
3. **作物知识（crop_knowledge + search）** - 作物生育期与生长习性知识检索
4. **决策推理（decision）** - 基于感知数据生成灌溉决策
5. **灌溉执行（irrigation）** - 执行水泵/阀门控制指令
6. **文件系统（filesystem）** - 日志与结果存储
7. **Web 接口（web）** - 提供 HTTP / WebSocket 接入

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

## 📁 项目结构

```
mcp-agent-project/
├── client/                          # 客户端
│   └── mcp-client/
│       ├── .env.example            # 环境变量模板
│       ├── client.py               # 主程序
│       ├── prompts.py              # Agent 提示词
│       ├── mcp_servers.json        # MCP 服务器配置
│       └── pyproject.toml          # 依赖配置
├── server/                          # 服务器端
│   ├── sensor/                     # 传感器服务
│   │   ├── sensor.py
│   │   └── sensor.db               # SQLite 数据库
│   ├── weather/                    # 天气服务
│   │   └── weather.py
│   ├── crop_knowledge/             # 作物知识服务
│   │   └── knowledge.py
│   ├── decision/                   # 决策服务
│   │   └── decision.py
│   ├── irrigation/                 # 灌溉控制服务
│   │   ├── main.py
│   │   ├── config.yaml
│   │   ├── actuators/              # 执行器
│   │   └── tools/                  # 工具函数
│   ├── filesystem/                 # 文件系统服务
│   │   └── filesystem.py
│   ├── search/                     # 搜索服务
│   │   └── src/duckduckgo_mcp_server/
│   └── web/                        # Web 服务器
│       ├── app.py
│       └── static/
│           └── index.html
├── docs/                            # 文档
│   ├── 快速启动指南.md
│   ├── 环境配置指南.md
│   └── 项目问题检查报告.md
├── arduino_code.ino                 # Arduino 硬件代码
├── start.bat                        # Windows 启动脚本
├── check_system.py                  # 系统检查脚本
├── README.md                        # 项目说明
└── 系统总体设计.md                  # 架构设计文档
```

## 🚀 快速开始

### 前置要求

- Python 3.10 或更高版本
- [uv](https://github.com/astral-sh/uv) 包管理器
- [Ollama](https://ollama.ai/) 或其他 LLM 服务

### 5分钟快速启动

#### 1. 克隆项目
```bash
git clone https://github.com/your-username/mcp-agent-project.git
cd mcp-agent-project
```

#### 2. 安装 uv（如果未安装）
```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 3. 配置环境变量
```bash
cd client/mcp-client
cp .env.example .env
# 编辑 .env 文件，填入你的配置
```

`.env` 配置示例：
```env
API_KEY=ollama
BASE_URL=http://localhost:11434/v1
MODEL=qwen2.5-coder
OWM_API_KEY=your_openweathermap_api_key
```

> 💡 获取 OpenWeatherMap API Key：访问 [OpenWeatherMap](https://openweathermap.org/api) 免费注册

#### 4. 运行系统检查
```bash
python check_system.py
```

#### 5. 启动系统

**方式一：使用启动脚本（推荐）**
```bash
start.bat  # Windows
# 或
./start.sh  # macOS/Linux
```

**方式二：命令行模式**
```bash
cd client/mcp-client
uv run client.py
```

**方式三：Web 界面**
```bash
cd server/web
uv run app.py
# 访问 http://localhost:8080
```

### 测试系统

启动后输入测试问题：
```
曲靖今天的天气怎么样，我的小麦需要灌溉吗？
```

系统会自动完成数据采集、分析和决策，并等待你的确认。

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

## 📦 详细安装

### 环境准备

#### 1. Python 环境
确保安装 Python 3.10 或更高版本：
```bash
python --version  # 应显示 3.10.x 或更高
```

#### 2. 安装 uv 包管理器
```bash
# Windows (PowerShell - 管理员权限)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

验证安装：
```bash
uv --version
```

#### 3. 安装 Ollama（推荐本地开发）
1. 访问 [Ollama 官网](https://ollama.ai/download) 下载安装
2. 拉取模型：
```bash
ollama pull qwen2.5-coder
# 或
ollama pull deepseek-coder
```

### 配置步骤

#### 1. 配置环境变量

复制配置模板：
```bash
cd client/mcp-client
cp .env.example .env
```

编辑 `.env` 文件：
```env
# LLM 配置
API_KEY=ollama                          # Ollama 本地部署填 "ollama"
BASE_URL=http://localhost:11434/v1      # Ollama 默认地址
MODEL=qwen2.5-coder                     # 使用的模型名称

# 天气服务配置
OWM_API_KEY=your_openweathermap_api_key # 从 OpenWeatherMap 获取
```

#### 2. 获取天气 API Key

1. 访问 [OpenWeatherMap](https://openweathermap.org/api)
2. 注册免费账号
3. 在 "API keys" 页面复制密钥
4. 填入 `.env` 文件的 `OWM_API_KEY`

> 免费版限制：60次/分钟，1000次/天（足够开发使用）

#### 3. 安装依赖

```bash
cd client/mcp-client
uv sync
```

#### 4. 验证配置

运行系统检查脚本：
```bash
python check_system.py
```

预期输出：
```
✅ Python 版本: 3.x.x
✅ uv 已安装
✅ .env 配置完整
✅ 所有服务器文件存在
🎉 所有检查通过！系统可以正常运行。
```

### Arduino 硬件集成（可选）

#### 硬件清单
- ESP8266 开发板（NodeMCU）
- DHT11 温湿度传感器
- 土壤湿度传感器
- 继电器模块
- 水泵

#### 接线说明
```
DHT11:
  VCC  -> 3.3V
  GND  -> GND
  DATA -> D4 (GPIO2)

土壤湿度传感器:
  VCC  -> 3.3V
  GND  -> GND
  AO   -> A0

继电器:
  VCC  -> 5V
  GND  -> GND
  IN   -> D1 (GPIO5)
```

#### 配置 Arduino

编辑 `arduino_code.ino`：
```cpp
// 修改 WiFi 配置
const char* ssid = "你的WiFi名称";
const char* password = "你的WiFi密码";

// 修改服务器地址（改为你电脑的局域网IP）
const char* serverURL = "http://192.168.1.100:8080";
```

查找电脑 IP：
```bash
# Windows
ipconfig

# macOS/Linux
ifconfig
```

上传代码到 ESP8266，然后启动 Web 服务器。


## 🔧 配置说明

### MCP 服务器配置

MCP 服务器配置文件位于 `client/mcp-client/mcp_servers.json`，默认配置已包含所有必需的服务。

如需添加自定义服务，可以按以下格式添加：

```json
{
  "mcpServers": {
    "your_service": {
      "command": "uv",
      "args": ["run", "your_script.py"],
      "cwd": "../../server/your_service",
      "env": {}
    }
  }
}
```

### 灌溉系统配置

灌溉系统配置文件位于 `server/irrigation/config.yaml`：

```yaml
api_url: "http://127.0.0.1:8080/api"
default_duration_minutes: 10
pump_control_endpoint: "/command/update"
sensor_data_endpoint: "/sensor/current"
```

## 🐛 常见问题

### Q1: 提示 "未找到 API KEY"

**解决方案**：
1. 确认 `.env` 文件在正确位置（`client/mcp-client/.env`）
2. 检查文件内容是否正确填写
3. 确保没有多余的空格或引号

### Q2: MCP 服务连接失败

**解决方案**：
```bash
# 检查 Python 版本
python --version  # 需要 ≥3.10

# 重新安装依赖
cd client/mcp-client
uv sync

# 运行系统检查
python check_system.py
```

### Q3: 天气查询失败

**解决方案**：
1. 验证 `OWM_API_KEY` 是否正确
2. 检查网络连接
3. 确认 API Key 已激活（新注册需等待几分钟）
4. 检查是否超过免费额度（60次/分钟）

### Q4: Arduino 无法连接

**解决方案**：
1. 检查 WiFi 配置是否正确
2. 确认电脑和 Arduino 在同一局域网
3. 验证服务器地址（使用电脑的局域网 IP）
4. 确认 Web 服务器已启动（`python server/web/app.py`）

### Q5: Ollama 连接失败

**解决方案**：
```bash
# 检查 Ollama 是否运行
ollama list

# 重启 Ollama 服务
# Windows: 在任务管理器中重启 Ollama
# macOS/Linux: killall ollama && ollama serve
```

## 📚 文档

- [快速启动指南](docs/快速启动指南.md) - 5分钟快速开始
- [环境配置指南](docs/环境配置指南.md) - 详细配置说明
- [系统总体设计](系统总体设计.md) - 架构设计文档
- [项目问题检查报告](docs/项目问题检查报告.md) - 已知问题和解决方案
- [API 文档](http://localhost:8080/docs) - Web API 文档（启动服务后访问）

## 🛠️ 技术栈

### 后端
- **Python 3.10+** - 主要编程语言
- **FastMCP** - MCP 服务器框架
- **FastAPI** - Web 框架
- **SQLite** - 数据存储
- **httpx** - HTTP 客户端

### 前端
- **HTML/CSS/JavaScript** - Web 界面
- **WebSocket** - 实时通信

### 硬件
- **ESP8266** - 物联网控制器
- **DHT11** - 温湿度传感器
- **Arduino IDE** - 硬件编程

### AI/LLM
- **Ollama** - 本地 LLM 服务
- **OpenAI API** - 兼容的 API 接口
- **MCP Protocol** - 模型上下文协议

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出建议！

### 贡献流程

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 开发规范

- 遵循 PEP 8 Python 代码规范
- 添加必要的注释和文档
- 编写单元测试
- 更新相关文档

## 🔒 安全建议

1. **不要提交 `.env` 文件**
   - 已在 `.gitignore` 中配置
   - 包含敏感信息（API Keys）

2. **定期更换 API Keys**
   - 特别是在公开仓库中

3. **使用环境变量**
   - 生产环境建议使用系统环境变量
   - 避免硬编码敏感信息

## 📊 项目状态

- ✅ 核心功能完整
- ✅ 文档齐全
- ✅ 测试通过
- 🚧 持续优化中

## 🙏 致谢

- [MCP Protocol](https://modelcontextprotocol.io/) - 模型上下文协议
- [Ollama](https://ollama.ai/) - 本地 LLM 服务
- [OpenWeatherMap](https://openweathermap.org/) - 天气数据服务
- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [uv](https://github.com/astral-sh/uv) - Python 包管理器

## 📧 联系方式

- 项目主页: [GitHub](https://github.com/your-username/mcp-agent-project)
- 问题反馈: [Issues](https://github.com/your-username/mcp-agent-project/issues)
- 邮箱: your-email@example.com

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

---

<div align="center">

**如果这个项目对你有帮助，请给一个 ⭐️ Star！**

Made with ❤️ by [Your Name]

</div>
