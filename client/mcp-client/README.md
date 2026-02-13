# FarmMind MCP Client

## 快速开始
1. 复制 `.env.example` 为 `.env`，填写 `API_KEY`、`BASE_URL`、`MODEL`
2. 确认 `mcp_servers.json` 中各服务的 `cwd` 路径正确
3. 安装依赖：`uv install`
4. 启动客户端：`uv run client.py`

## 说明
- 客户端会按配置自动启动本地 MCP 服务并连接
- 如需 Web 接口，请在 `server/web` 中启动 FastAPI 服务
