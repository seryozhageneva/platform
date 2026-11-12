"""Подделка Яндекс Диска для тестов: отвечает как REST API Диска (задача 29).

Пользуются ею тесты сервера (`test_server.py`) и тесты платформы, которым нужен Диск без
сети. Данные — выдуманные.
"""

from urllib.parse import quote

import httpx

from mcp_servers.cloud.server import build_server
from mcp_servers.cloud.yandex_disk import YandexDisk

TOKEN = "y0_fake-test_token_0123456789abcdef"
DOWNLOAD = "https://downloader.disk.yandex.ru/disk/"


class FakeDisk:
    """Диск в памяти: `files` — путь «disk:/…» → содержимое; папки — в `folders`."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = dict(files or {})
        self.folders: set[str] = set()
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = request.url
        if url.host == "downloader.disk.yandex.ru":
            if "authorization" in request.headers:
                return httpx.Response(400, text="токен на сервер скачивания не нужен")
            path = "disk:/" + url.path.removeprefix("/disk/")
            return httpx.Response(200, content=self.files[path])
        if request.headers.get("authorization") != f"OAuth {TOKEN}":
            return httpx.Response(401, json={"error": "UnauthorizedError"})
        path = url.params.get("path", "")
        if url.path == "/v1/disk/resources":
            if path in self.folders:
                return httpx.Response(200, json={"type": "dir", "name": path.rsplit("/")[-1]})
            if path not in self.files:
                return httpx.Response(404, json={"error": "DiskNotFoundError"})
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "name": path.rsplit("/")[-1],
                    "size": len(self.files[path]),
                    "mime_type": "application/pdf" if path.endswith(".pdf") else "",
                },
            )
        if url.path == "/v1/disk/resources/download" and path in self.files:
            return httpx.Response(
                200,
                json={"href": DOWNLOAD + quote(path.removeprefix("disk:/")), "method": "GET"},
            )
        return httpx.Response(404, json={"error": "DiskNotFoundError"})


def fake_server(disk: FakeDisk, token: str = TOKEN):
    """Сервер облака в том же процессе, который ходит в подделку."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(disk))
    return build_server(lambda: YandexDisk(token, client))
