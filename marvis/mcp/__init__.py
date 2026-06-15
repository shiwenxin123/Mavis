"""Marvis MCP Server — 通用 AI 工具接口"""

from marvis.mcp.server import main, run
from marvis.mcp.tools import ALL_TOOLS, execute_tool

__all__ = ["main", "run", "ALL_TOOLS", "execute_tool"]
