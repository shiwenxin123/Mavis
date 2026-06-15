"""
Marvis MCP Server — 标准 MCP (Model Context Protocol) 服务器。

启动: python -m marvis.mcp.server  或  marvis-mcp
支持任意 MCP 客户端：Claude Desktop, Cursor, Windsurf, GitHub Copilot, Codex 等。
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from marvis.mcp.tools import ALL_TOOLS, execute_tool
import json

server = Server("marvis")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """列出所有可用工具"""
    return [
        Tool(
            name=t["name"],
            description=t["description"],
            inputSchema=t["inputSchema"],
        )
        for t in ALL_TOOLS
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """执行工具调用"""
    result_str = execute_tool(name, arguments)
        # execute_tool 已返回 JSON 字符串
        return [TextContent(type="text", text=result_str)]


async def main():
    """启动 MCP 服务器（stdio 模式）"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run():
    """同步入口"""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    run()
