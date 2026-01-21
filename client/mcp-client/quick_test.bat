@echo off
echo ========================================
echo MCP Client Quick Test
echo ========================================
echo.

echo Step 1: Testing connection...
uv run python test_connection.py

echo.
echo ========================================
echo Test completed!
echo ========================================
echo.
echo If all tests passed, you can run:
echo   uv run python client.py
echo.
pause
