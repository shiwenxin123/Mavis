"""
Marvis MCP Server — 标准 MCP (Model Context Protocol) 服务器。

启动: python -m marvis.mcp.server  或  marvis-mcp  或  marvis mcp-server
支持任意 MCP 客户端：Claude Desktop, Cursor, Windsurf, GitHub Copilot, Codex 等。
"""


def main():
    """同步入口。未安装 mcp 时给出可执行的安装提示，而不是堆栈。"""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError as exc:
        raise SystemExit(
            "未安装 MCP 依赖，无法启动服务器。\n"
            "安装: pip install 'marvis[mcp]'\n"
            f"详情: {exc}"
        ) from exc

    import asyncio

    from marvis.mcp.tools import ALL_TOOLS, execute_tool

    server = Server("marvis")

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return [
            Tool(
                name=tool["name"],
                description=tool["description"],
                inputSchema=tool["inputSchema"],
            )
            for tool in ALL_TOOLS
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
        result_str = execute_tool(name, arguments or {})
        return [TextContent(type="text", text=result_str)]

    async def _serve():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(_serve())


def run():
    main()


if __name__ == "__main__":
    main()
