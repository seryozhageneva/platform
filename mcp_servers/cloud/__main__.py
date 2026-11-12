"""Запуск MCP-сервера облака по stdin/stdout: python -m mcp_servers.cloud"""

import os

from mcp_servers.cloud.server import quiet_http_logs, server_from_env

if __name__ == "__main__":
    quiet_http_logs()
    server_from_env(dict(os.environ)).run("stdio")
