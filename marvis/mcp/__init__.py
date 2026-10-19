"""Marvis MCP Server — 通用 AI 工具接口。

工具层不依赖 mcp 包，便于在未安装 extras 时单测和本地调用。
`main` / `run` 在真正启动服务器时才加载 mcp。
"""

from marvis.mcp.tools import ALL_TOOLS, execute_tool

__all__ = ["main", "run", "ALL_TOOLS", "execute_tool"]


def __getattr__(name: str):
    if name in ("main", "run"):
        from marvis.mcp import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
