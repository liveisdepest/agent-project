# 贡献指南

感谢你考虑为智能农业MCP系统做出贡献！

## 🤝 如何贡献

### 报告问题

如果你发现了 bug 或有功能建议：

1. 在 [Issues](https://github.com/your-username/mcp-agent-project/issues) 中搜索是否已有相关问题
2. 如果没有，创建新的 Issue
3. 使用清晰的标题和详细的描述
4. 如果是 bug，请提供：
   - 复现步骤
   - 预期行为
   - 实际行为
   - 系统环境（OS、Python 版本等）
   - 相关日志

### 提交代码

1. **Fork 仓库**
   ```bash
   # 在 GitHub 上点击 Fork 按钮
   ```

2. **克隆你的 Fork**
   ```bash
   git clone https://github.com/your-username/mcp-agent-project.git
   cd mcp-agent-project
   ```

3. **创建特性分支**
   ```bash
   git checkout -b feature/amazing-feature
   ```

4. **进行修改**
   - 遵循代码规范
   - 添加必要的测试
   - 更新相关文档

5. **提交更改**
   ```bash
   git add .
   git commit -m "feat: add amazing feature"
   ```

6. **推送到你的 Fork**
   ```bash
   git push origin feature/amazing-feature
   ```

7. **创建 Pull Request**
   - 在 GitHub 上打开 Pull Request
   - 填写 PR 模板
   - 等待代码审查

## 📝 代码规范

### Python 代码

遵循 [PEP 8](https://pep8.org/) 规范：

```python
# 好的示例
def calculate_irrigation_amount(
    soil_moisture: float,
    target_moisture: float,
    area: float
) -> float:
    """
    计算灌溉量。
    
    Args:
        soil_moisture: 当前土壤湿度 (%)
        target_moisture: 目标土壤湿度 (%)
        area: 灌溉面积 (m²)
    
    Returns:
        所需灌溉量 (L)
    """
    moisture_gap = target_moisture - soil_moisture
    return moisture_gap * area * 10  # 简化计算
```

### 提交信息

使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
<类型>(<范围>): <描述>

[可选的正文]

[可选的脚注]
```

**类型**：
- `feat`: 新功能
- `fix`: 问题修复
- `docs`: 文档更新
- `style`: 代码格式（不影响功能）
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具相关

**示例**：
```
feat(sensor): add temperature calibration

- Add calibration offset parameter
- Update sensor reading logic
- Add unit tests

Closes #123
```

## 🧪 测试

在提交 PR 前，请确保：

1. **运行系统检查**
   ```bash
   python check_system.py
   ```

2. **测试核心功能**
   ```bash
   cd client/mcp-client
   uv run client.py --init-only
   ```

3. **检查代码格式**
   ```bash
   # 使用 black 格式化
   black .
   
   # 使用 flake8 检查
   flake8 .
   ```

## 📚 文档

更新文档时：

1. 保持简洁清晰
2. 使用示例代码
3. 更新相关的 README
4. 检查链接是否有效

## 🎯 开发环境设置

1. **安装开发依赖**
   ```bash
   cd client/mcp-client
   uv sync --dev
   ```

2. **配置 pre-commit hooks**
   ```bash
   pre-commit install
   ```

3. **运行测试**
   ```bash
   pytest
   ```

## 🔍 代码审查

PR 会经过以下审查：

- ✅ 代码质量和规范
- ✅ 测试覆盖率
- ✅ 文档完整性
- ✅ 功能正确性
- ✅ 性能影响

## 💡 开发建议

### 添加新的 MCP 服务器

1. 在 `server/` 下创建新目录
2. 实现服务器逻辑
3. 添加 `pyproject.toml`
4. 更新 `mcp_servers.json`
5. 添加文档和测试

### 修改 Agent 逻辑

1. 编辑 `client/mcp-client/prompts.py`
2. 更新相关的 Agent 提示词
3. 测试三阶段流程
4. 更新文档

### 添加硬件支持

1. 更新 `arduino_code.ino`
2. 添加传感器/执行器代码
3. 更新接线说明
4. 测试硬件集成

## 🙏 行为准则

- 尊重所有贡献者
- 保持友好和专业
- 接受建设性批评
- 关注项目目标

## 📧 联系方式

有问题？可以通过以下方式联系：

- GitHub Issues
- 邮箱: your-email@example.com
- 讨论区: [Discussions](https://github.com/your-username/mcp-agent-project/discussions)

---

再次感谢你的贡献！🌾
