我将修改 `client/mcp-client/.env` 文件，将 AI 模型切换为 Ollama 中的 `gemma3:4b`。

**实施步骤：**
1.  **修改 `.env` 配置文件**：
    *   将 `MODEL` 字段的值从 `qwen2.5-coder:latest` 更新为 `gemma3:4b`。
    *   确保 `BASE_URL` 指向本地 Ollama 服务 (`http://localhost:11434/v1`)。
    *   保留 `API_KEY=ollama`（Ollama 兼容模式通常需要非空 key）。

**预期效果：**
重启客户端后，系统将使用 `gemma3:4b` 模型来处理您的农业咨询。该模型将接收传感器数据、天气信息和作物知识，进行推理并生成灌溉建议。得益于之前优化的 System Prompt，它会正确处理极端缺水情况并根据您的指令控制水泵。