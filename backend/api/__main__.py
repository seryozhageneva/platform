"""Запуск сервера API:  uv run python -m backend.api

На своём компьютере сервер слушает только этот компьютер (127.0.0.1) и из сети не виден.
Страница с описанием API — http://127.0.0.1:8000/docs

На сервере (ADR 0030) API работает в контейнере за Caddy: адрес и то, кому верить в вопросе
«пришёл ли запрос по HTTPS», задают переменные `PLATFORM_API_HOST` и
`PLATFORM_TRUSTED_PROXIES`.
"""

import asyncio
import sys

import uvicorn
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.api.app import create_app
from backend.llm.factory import make_llm
from backend.llm.providers import LLMError
from backend.models.db import ROOT, database_url

HOST, PORT = "127.0.0.1", 8000


class ServerSettings(BaseSettings):
    """Где слушать и чьим заголовкам `X-Forwarded-*` верить."""

    # Пустая строка в .env значит «по умолчанию», а не «слушать все адреса».
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="PLATFORM_", extra="ignore", env_ignore_empty=True
    )

    api_host: str = HOST
    # Адреса посредников через запятую. Только их заголовок `X-Forwarded-Proto` сообщает
    # серверу, что браузер пришёл по HTTPS: от этого зависят пометка `Secure` у cookie входа и
    # проверка источника запроса. Заголовки от остальных адресов не учитываются.
    trusted_proxies: str = "127.0.0.1"


def server_config(app: FastAPI, settings: ServerSettings | None = None) -> uvicorn.Config:
    settings = settings or ServerSettings()
    return uvicorn.Config(
        app,
        host=settings.api_host,
        port=PORT,
        proxy_headers=True,
        forwarded_allow_ips=settings.trusted_proxies,
    )


def main() -> int:
    # Настройки проверяются до старта: понятная строка лучше, чем отчёт об ошибке сервера.
    try:
        database_url()
        asyncio.run(make_llm().aclose())
    except (RuntimeError, LLMError) as error:
        print(f"Сервер не запущен: {error}")
        return 1
    uvicorn.Server(server_config(create_app())).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
