"""Запуск MCP-сервера Telegram по stdin/stdout."""

import logging
import os

from mcp_servers.telegram.server import build_server

if __name__ == "__main__":
    # URL Bot API содержит токен. Отключаем сетевую трассировку в дочернем процессе.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).disabled = True
        logging.getLogger(name).setLevel(logging.CRITICAL + 1)
    build_server(os.environ.get("TELEGRAM_TOKEN", "")).run("stdio")
