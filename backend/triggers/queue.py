"""Связь ручного запуска с очередью arq (ADR 0022)."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

from arq.connections import ArqRedis, RedisSettings
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.exceptions import RedisError

QUEUE_NAME = "platform:manual"
JOB_NAME = "execute_manual"
ENQUEUE_TIMEOUT = 2
RUN_TIMEOUT = 15 * 60

EnqueueLaunch = Callable[[UUID], Awaitable[None]]


class QueueUnavailable(Exception):
    """Очередь не подтвердила приём задания."""


class QueueSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore"
    )
    redis_url: SecretStr = SecretStr("")

    def connection_settings(self) -> RedisSettings:
        url = self.redis_url.get_secret_value() or "redis://127.0.0.1:6379/0"
        try:
            parts = urlsplit(url)
            if parts.scheme not in {"redis", "rediss"} or parts.query or parts.fragment:
                raise ValueError
            settings = RedisSettings.from_dsn(url)
        except ValueError:
            raise RuntimeError(
                "REDIS_URL должен быть адресом redis:// или rediss:// без параметров запроса"
            ) from None
        if settings.username:
            settings.username = unquote(settings.username)
        if settings.password:
            settings.password = unquote(settings.password)
        settings.ssl_check_hostname = settings.ssl
        return settings


def serialize_job(job: dict[str, Any]) -> bytes:
    return json.dumps(job, ensure_ascii=False).encode()


@asynccontextmanager
async def open_queue_connection(settings: RedisSettings) -> AsyncIterator[ArqRedis]:
    # Без ping при старте API: недоступный Redis не мешает работать кабинету ученика.
    redis = ArqRedis(
        host=settings.host,
        port=settings.port,
        username=settings.username,
        password=settings.password,
        db=settings.database,
        ssl=settings.ssl,
        ssl_check_hostname=settings.ssl_check_hostname,
        socket_connect_timeout=settings.conn_timeout,
        job_serializer=serialize_job,
        job_deserializer=json.loads,
    )
    try:
        yield redis
    finally:
        await redis.aclose()


class LaunchQueue:
    def __init__(self, redis: ArqRedis, *, name: str = QUEUE_NAME) -> None:
        self.redis = redis
        self.name = name

    async def enqueue(self, run_id: UUID) -> None:
        try:
            async with asyncio.timeout(ENQUEUE_TIMEOUT):
                job = await self.redis.enqueue_job(
                    JOB_NAME, str(run_id), _job_id=str(run_id), _queue_name=self.name
                )
        except (RedisError, OSError, TimeoutError):
            raise QueueUnavailable from None
        if job is None:
            raise QueueUnavailable
