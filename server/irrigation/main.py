import logging
import sys
import os
import io
from mcp.server.fastmcp import FastMCP

# Add project root to sys.path to allow absolute imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from server.irrigation.tools.start_irrigation import start_irrigation
from server.irrigation.tools.stop_irrigation import stop_irrigation
from server.irrigation.tools.get_status import get_irrigation_status

# Force UTF-8 for stdout/stderr
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

# Initialize FastMCP
mcp = FastMCP("irrigation")

# Register tools
mcp.tool()(start_irrigation)
mcp.tool()(stop_irrigation)
mcp.tool()(get_irrigation_status)

if __name__ == "__main__":
    try:
        mcp.run(transport='stdio')
    except Exception as e:
        logger.error(f"MCP Server crashed: {e}")
        sys.exit(1)
