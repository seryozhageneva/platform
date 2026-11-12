"""Чтение файла с Яндекс Диска преподавателя через REST API Диска (задача 29, ADR 0036).

Токен OAuth — секрет. Он уходит только на постоянный адрес API Диска и никогда не
попадает в текст ошибок. Ссылка на скачивание, которую выдаёт API, уже подписана Диском:
по ней файл берётся без токена, и только с серверов Яндекса по HTTPS.
"""

import mimetypes
from dataclasses import dataclass
from pathlib import PurePosixPath

import httpx

API = "https://cloud-api.yandex.net/v1/disk"
# Как у загрузки файлов платформы: один файл — до 10 МиБ.
MAX_FILE_SIZE = 10 * 1024 * 1024
TIMEOUT = httpx.Timeout(60, connect=5)
# Сервер скачивания Диска может переадресовать на соседний сервер хранения.
MAX_REDIRECTS = 5
# Файлы Диска отдают только серверы Яндекса: на другой адрес платформа не пойдёт.
DOWNLOAD_DOMAINS = ("yandex.ru", "yandex.net")
MAX_PATH = 1024

DOCUMENT_EXTENSIONS = {".pdf", ".docx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic"}

_ERRORS = {
    401: "Яндекс Диск не принял токен: проверь токен в подключении",
    403: "у токена нет доступа к этому файлу на Яндекс Диске",
}
_UNAVAILABLE = "Яндекс Диск не ответил: попробуй позже"


class DiskError(Exception):
    """Ошибка, о которой можно сказать преподавателю: в тексте нет токена."""


@dataclass(frozen=True)
class DiskFile:
    path: str
    name: str
    kind: str
    media_type: str
    content: bytes


def disk_path(value: str) -> str:
    """Путь на Диске: `/Лекции/лекция.pdf` или `disk:/Лекции/лекция.pdf`."""
    path = value.strip()
    if path.startswith("disk:"):
        path = path.removeprefix("disk:")
    if not path.startswith("/") or path.rstrip("/") == "":
        raise DiskError("нужен путь к файлу на Диске, например /Лекции/лекция.pdf")
    if len(path) > MAX_PATH or any(ord(char) < 32 for char in path):
        raise DiskError("путь к файлу на Диске записан с ошибкой")
    return "disk:" + path


def file_kind(name: str) -> str:
    """Вид файла по расширению (как `FileKind`): документ, картинка или прочее."""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in DOCUMENT_EXTENSIONS:
        return "document"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "other"


def _is_yandex(url: httpx.URL) -> bool:
    host = url.host.lower()
    return url.scheme == "https" and any(
        host == domain or host.endswith("." + domain) for domain in DOWNLOAD_DOMAINS
    )


class YandexDisk:
    def __init__(self, token: str, client: httpx.AsyncClient) -> None:
        if not token:
            raise DiskError("не настроен токен Яндекс Диска: добавь подключение «cloud»")
        self._headers = {"Authorization": f"OAuth {token}", "Accept": "application/json"}
        self._client = client

    async def read(self, path: str) -> DiskFile | None:
        """Файл по пути; `None` — по этому пути ничего нет."""
        path = disk_path(path)
        found = await self._api("/resources", {"path": path, "fields": "type,name,size,mime_type"})
        if found is None:
            return None
        if found.get("type") != "file":
            raise DiskError("по этому пути на Диске лежит папка, а нужен файл")
        name = str(found.get("name") or PurePosixPath(path).name)
        size = found.get("size")
        if isinstance(size, int) and size > MAX_FILE_SIZE:
            raise DiskError("файл на Диске больше 10 МиБ")
        link = await self._api("/resources/download", {"path": path})
        if link is None:
            return None
        href = link.get("href")
        if not isinstance(href, str):
            raise DiskError(_UNAVAILABLE)
        content = await self._download(href)
        reported = found.get("mime_type")
        media_type = (
            reported
            if isinstance(reported, str) and reported
            else mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        return DiskFile(
            path=path, name=name, kind=file_kind(name), media_type=media_type, content=content
        )

    async def _api(self, route: str, params: dict[str, str]) -> dict | None:
        try:
            response = await self._client.get(
                API + route, params=params, headers=self._headers, timeout=TIMEOUT
            )
        except httpx.HTTPError:
            raise DiskError(_UNAVAILABLE) from None
        if response.status_code == 404:
            return None
        if response.status_code in _ERRORS:
            raise DiskError(_ERRORS[response.status_code])
        if response.status_code != 200:
            raise DiskError(_UNAVAILABLE)
        try:
            answer = response.json()
        except ValueError:
            raise DiskError(_UNAVAILABLE) from None
        if not isinstance(answer, dict):
            raise DiskError(_UNAVAILABLE)
        return answer

    async def _download(self, href: str) -> bytes:
        """Скачать по подписанной ссылке без токена, не больше 10 МиБ."""
        try:
            url = httpx.URL(href)
        except httpx.InvalidURL:
            raise DiskError(_UNAVAILABLE) from None
        for _ in range(MAX_REDIRECTS + 1):
            if not _is_yandex(url):
                raise DiskError("Яндекс Диск прислал ссылку на чужой сайт: файл не скачан")
            try:
                async with self._client.stream("GET", url, timeout=TIMEOUT) as response:
                    if response.is_redirect and "location" in response.headers:
                        url = url.join(response.headers["location"])
                        continue
                    if response.status_code != 200:
                        raise DiskError(_UNAVAILABLE)
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_FILE_SIZE:
                            raise DiskError("файл на Диске больше 10 МиБ")
                    return bytes(content)
            except (httpx.HTTPError, httpx.InvalidURL):
                raise DiskError(_UNAVAILABLE) from None
        raise DiskError(_UNAVAILABLE)
