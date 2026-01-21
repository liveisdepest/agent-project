# Browser-Use MCP Server 代码结构详解

本文档详细解析了 `server/browser-use-mcp-server-main` 目录下的核心代码文件，帮助理解该 MCP 服务器的实现原理和模块结构。

该项目包含两个主要的代码目录：
1. `server/`：包含服务器的实际核心实现逻辑。
2. `src/browser_use_mcp_server/`：作为 Python 包的封装层，方便安装和 CLI 调用。

---

## 1. 核心实现层 (`server/`)

这一层包含了业务逻辑的具体实现。

### 1.1 `server/server.py` (核心实现)
这是整个项目的**心脏**。它实现了基于 `browser-use` 库的浏览器自动化 MCP 服务器。

*   **配置管理 (`init_configuration`)**：
    *   从环境变量加载配置，如窗口大小、超时时间、OpenAI 模型配置等。
    *   支持 `PATIENT_MODE`（耐心模式），决定是异步返回 Task ID 还是同步等待任务完成。

*   **浏览器上下文管理 (`create_browser_context_for_task`)**：
    *   为每个任务创建独立的浏览器实例 (Browser) 和上下文 (Context)，确保任务间的隔离性。
    *   配置了反检测参数、窗口大小和 User-Agent。

*   **异步任务执行 (`run_browser_task_async`)**：
    *   **核心逻辑**：使用 `browser_use.Agent` 执行具体的浏览任务。
    *   **状态追踪**：通过 `step_callback` 和 `done_callback` 实时更新 `task_store` 中的任务进度。
    *   **结果处理**：收集执行结果、截图、日志和错误信息，并保存到内存中的 `task_store`。
    *   **资源清理**：`finally` 块确保浏览器资源被关闭。

*   **MCP 工具定义 (`create_mcp_server`)**：
    *   定义了对外暴露的 MCP 工具：
        *   `browser_use`: 启动浏览器任务（导航到 URL 并执行 Action）。
        *   `browser_get_result`: 查询异步任务的执行状态和结果。
        *   `browser_stop_task`: 停止正在运行的任务。
        *   `browser_list_tasks`: 列出活跃任务。
    *   **资源接口 (`list_resources`, `read_resource`)**：允许客户端通过 `resource://` 协议读取已完成的任务结果。

*   **HTTP/SSE 服务入口 (`main`)**：
    *   使用 `Starlette` 和 `uvicorn` 启动 HTTP 服务器。
    *   支持 **SSE (Server-Sent Events)** 协议，这是 MCP 协议推荐的传输方式。
    *   支持 **Proxy 模式**，可配合 `mcp-proxy` 使用。

### 1.2 `server/__init__.py` (包导出)
*   **作用**：将 `server.py` 中定义的关键类和函数（如 `Server`, `main`, `task_store`）导出，使得外部模块可以通过 `from server import ...` 方便地引用。

### 1.3 `server/__main__.py` (执行入口)
*   **作用**：当用户直接运行 `python -m server` 时调用的入口文件。
*   **逻辑**：简单地导入并调用 `server.main()`。

---

## 2. 封装与 CLI 层 (`src/browser_use_mcp_server/`)

这一层是为了将核心代码打包成标准的 Python 包 (`browser_use_mcp_server`)，并提供命令行工具。

### 2.1 `src/browser_use_mcp_server/server.py` (重导出)
*   **作用**：这是一个“桥梁”文件。
*   **逻辑**：它从核心实现层 (`server.server`) 导入所有内容，并再次导出。这样做是为了让安装了该包的用户可以直接从 `browser_use_mcp_server.server` 导入功能，而不需要关心底层的目录结构。

### 2.2 `src/browser_use_mcp_server/cli.py` (命令行接口)
*   **作用**：定义了终端命令 `browser-use-mcp-server` 的行为。
*   **实现**：
    *   使用 `click` 库构建命令行界面。
    *   定义了 `run` 命令及其参数（如 `--port`, `--chrome-path` 等）。
    *   **参数传递**：它解析命令行参数，构建参数列表，然后通过修改 `sys.argv` 并调用 `server_main()` 来启动服务器。这是一种复用核心逻辑的常见模式。

### 2.3 `src/browser_use_mcp_server/__init__.py` (包初始化)
*   **作用**：标记 `src/browser_use_mcp_server` 为一个 Python 包。
*   **内容**：通常包含包的元数据或顶层导出（在本例中可能为空或包含简单的文档字符串）。

---

## 总结

*   **逻辑流向**：CLI (`src/.../cli.py`) -> 重导出层 (`src/.../server.py`) -> 核心实现 (`server/server.py`)。
*   这种分离的设计模式使得核心逻辑保持纯净，同时提供了灵活的打包和调用方式。
