"""Запросы к Moodle через Web Services (REST) — только чтение (задача 23, ADR 0028).

Адрес сайта и токен приходят от того, кто запускает адаптер. Токен — секрет: он уходит только
на сам сайт Moodle и никогда не попадает в текст ошибок.
"""

import mimetypes
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import httpx

# Как у загрузки файлов платформы: один файл работы — до 10 МиБ.
MAX_FILE_SIZE = 10 * 1024 * 1024
# Все файлы одного ответа вместе: ответ целиком идёт через канал MCP.
MAX_TOTAL_SIZE = 50 * 1024 * 1024
TIMEOUT = httpx.Timeout(60, connect=5)

DOCUMENT_EXTENSIONS = {".pdf", ".docx"}
CODE_EXTENSIONS = {
    ".py", ".ipynb", ".js", ".ts", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go",
    ".rs", ".kt", ".swift", ".rb", ".php", ".pas", ".sql",
}  # fmt: skip
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic"}
# Moodle не всегда знает тип файла (код на Python у него «document/unknown»).
EXTRA_TYPES = {".py": "text/x-python", ".ipynb": "application/x-ipynb+json"}

# Понятные тексты для частых ошибок Moodle; остальное — по коду ошибки.
_ERRORS = {
    "invalidtoken": "Moodle не принял токен: проверь токен в подключении",
    "accessexception": "у пользователя токена нет доступа к этой функции Moodle",
    "servicenotavailable": "веб-сервис Moodle выключен или недоступен для этого токена",
    "nopermissions": "у пользователя токена нет прав на это задание",
    "invalidrecord": "в Moodle нет такого курса или задания",
}


class MoodleError(Exception):
    """Ошибка, о которой можно сказать преподавателю: в тексте нет токена."""


@dataclass(frozen=True)
class MoodleFile:
    name: str
    kind: str
    media_type: str
    content: bytes
    meta: dict[str, Any] = field(default_factory=dict)


def file_kind(name: str) -> str:
    """Вид файла по расширению: документ, код, картинка или прочее (как `FileKind`)."""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in DOCUMENT_EXTENSIONS:
        return "document"
    if suffix in CODE_EXTENSIONS:
        return "code"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "other"


def media_type(name: str, reported: str | None) -> str:
    if reported and "/" in reported and reported != "document/unknown":
        return reported
    suffix = PurePosixPath(name).suffix.lower()
    guessed = EXTRA_TYPES.get(suffix) or mimetypes.guess_type(name)[0]
    return guessed or "application/octet-stream"


class MoodleApi:
    def __init__(self, url: str, token: str, client: httpx.AsyncClient) -> None:
        base = httpx.URL(url)
        if base.scheme not in ("http", "https") or not base.host or base.query or base.fragment:
            raise MoodleError("адрес Moodle должен быть вида https://moodle.example.ru")
        if not token or not token.isalnum():
            raise MoodleError("токен Moodle пуст или похож не на токен")
        self._base = base
        self._root = str(base).rstrip("/")
        self._token = token
        self._client = client

    async def call(self, function: str, params: dict[str, Any]) -> Any:
        data = {"wstoken": self._token, "wsfunction": function, "moodlewsrestformat": "json"}
        data.update(params)
        try:
            response = await self._client.post(
                f"{self._root}/webservice/rest/server.php", data=data, timeout=TIMEOUT
            )
        except httpx.HTTPError:
            raise MoodleError(f"Moodle недоступен по адресу {self._root}") from None
        if response.status_code != 200:
            raise MoodleError(f"Moodle ответил кодом {response.status_code}")
        try:
            result = response.json()
        except ValueError:
            raise MoodleError("Moodle ответил не JSON: проверь адрес сайта") from None
        if isinstance(result, dict) and "exception" in result:
            code = str(result.get("errorcode", ""))
            raise MoodleError(_ERRORS.get(code, f"Moodle вернул ошибку «{code or 'без кода'}»"))
        return result

    async def download(self, file_url: str, limit: int) -> bytes:
        """Скачивает файл сдачи. Токен уходит только на тот же сайт, что в подключении."""
        url = httpx.URL(file_url)
        if (url.scheme, url.host, url.port) != (
            self._base.scheme,
            self._base.host,
            self._base.port,
        ):
            raise MoodleError("Moodle прислал ссылку на файл с другого сайта — файл не скачан")
        try:
            async with self._client.stream(
                "GET", url, params={"token": self._token}, timeout=TIMEOUT
            ) as response:
                if response.status_code != 200:
                    raise MoodleError(f"файл работы не скачан: код {response.status_code}")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > limit:
                        raise MoodleError("файл работы больше 10 МиБ")
        except httpx.HTTPError:
            raise MoodleError("файл работы не скачан: Moodle недоступен") from None
        return bytes(content)

    async def submitted_files(self, course_id: int, assignment_id: int) -> list[MoodleFile]:
        """Файлы сданных работ задания; черновики и пустые сдачи не берутся."""
        assignments = await self.call("mod_assign_get_assignments", {"courseids[0]": course_id})
        courses = assignments.get("courses", []) if isinstance(assignments, dict) else []
        known = {a.get("id") for course in courses for a in course.get("assignments", [])}
        if assignment_id not in known:
            raise MoodleError("в этом курсе Moodle нет такого задания или к нему нет доступа")

        result = await self.call("mod_assign_get_submissions", {"assignmentids[0]": assignment_id})
        files: list[MoodleFile] = []
        total = 0
        for assignment in result.get("assignments", []):
            for submission in assignment.get("submissions", []):
                if submission.get("status") != "submitted":
                    continue
                for plugin in submission.get("plugins", []):
                    for area in plugin.get("fileareas", []):
                        for item in area.get("files", []):
                            name = PurePosixPath(str(item.get("filename", ""))).name
                            if not name or not item.get("fileurl"):
                                continue
                            content = await self.download(item["fileurl"], MAX_FILE_SIZE)
                            total += len(content)
                            if total > MAX_TOTAL_SIZE:
                                raise MoodleError("работы задания вместе больше 50 МиБ")
                            files.append(
                                MoodleFile(
                                    name=name,
                                    kind=file_kind(name),
                                    media_type=media_type(name, item.get("mimetype")),
                                    content=content,
                                    meta={
                                        "moodle_user_id": submission.get("userid"),
                                        "moodle_submission_id": submission.get("id"),
                                        "moodle_assignment_id": assignment_id,
                                        "submitted_at": submission.get("timemodified"),
                                    },
                                )
                            )
        return files
