"""Запуск MCP-сервера почты по stdin/stdout."""

import os

from mcp_servers.email.server import build_server

if __name__ == "__main__":
    build_server(os.environ).run("stdio")
