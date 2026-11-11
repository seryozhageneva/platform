"""Запуск MCP-сервера Moodle по stdin/stdout: python -m mcp_servers.moodle"""

import os

from mcp_servers.moodle.server import quiet_http_logs, server_from_env

if __name__ == "__main__":
    quiet_http_logs()
    server_from_env(dict(os.environ)).run("stdio")
