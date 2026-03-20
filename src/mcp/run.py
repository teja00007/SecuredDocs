"""Entry point to run the Nexus MCP server (stdio transport for Claude Desktop)."""
import asyncio
from src.mcp.server import nexus_mcp_server

if __name__ == "__main__":
    asyncio.run(nexus_mcp_server.run_stdio())
