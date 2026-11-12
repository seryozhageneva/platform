"""Подделка Moodle для тестов: отвечает как Web Services Moodle 5.3 (задача 23).

Ответы сняты с тестового контейнера и сокращены. Данные — выдуманные. Пользуются ею тесты
сервера (`test_server.py`) и тесты платформы, которым нужен сервер Moodle без сети.
"""

from typing import Any
from urllib.parse import parse_qs

import httpx

from mcp_servers.moodle.moodle_api import MoodleApi
from mcp_servers.moodle.server import build_server

SITE = "http://moodle.test"
TOKEN = "0123456789abcdef0123456789abcdef"
FILES = {
    "1/work1.pdf": b"%PDF-1.4 work one",
    "2/work2.docx": b"PK docx work two",
    "3/solution.py": b"def f(x):\n    return 2 * x + 3\n",
    "4/draft.pdf": b"%PDF-1.4 draft",
}


def make_file(path: str, mimetype: str, site: str = SITE) -> dict[str, Any]:
    return {
        "filename": path.split("/")[-1],
        "filepath": "/",
        "filesize": len(FILES.get(path, b"")),
        "fileurl": f"{site}/webservice/pluginfile.php/14/assignsubmission_file/"
        f"submission_files/{path}",
        "mimetype": mimetype,
    }


def make_submission(number: int, user: int, status: str, files: list[dict]) -> dict[str, Any]:
    return {
        "id": number,
        "userid": user,
        "status": status,
        "timemodified": 1794393677,
        "plugins": [
            {"type": "file", "name": "File submissions", "fileareas": [
                {"area": "submission_files", "files": files}
            ]},
            {"type": "comments", "name": "Submission comments"},
        ],
    }  # fmt: skip


SUBMISSIONS = [
    make_submission(1, 4, "submitted", [make_file("1/work1.pdf", "application/pdf")]),
    make_submission(
        2,
        5,
        "submitted",
        [
            make_file(
                "2/work2.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    ),
    make_submission(3, 6, "submitted", [make_file("3/solution.py", "document/unknown")]),
    make_submission(4, 7, "draft", [make_file("4/draft.pdf", "application/pdf")]),
    make_submission(5, 8, "new", []),
]


class FakeMoodle:
    """Отвечает как Moodle; запоминает, куда и с каким токеном ходили."""

    def __init__(
        self, submissions: list[dict] | None = None, token: str = TOKEN, max_grade: float = 100
    ) -> None:
        self.submissions = SUBMISSIONS if submissions is None else submissions
        self.token = token
        self.max_grade = max_grade
        self.requests: list[httpx.Request] = []
        self.files = dict(FILES)
        # Выставленные оценки: номер студента → поля запроса mod_assign_save_grade.
        self.grades: dict[int, dict[str, str]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host != "moodle.test":
            return httpx.Response(200, content=b"secret-collector")
        if request.url.path == "/webservice/rest/server.php":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form.get("wstoken") != self.token:
                return httpx.Response(
                    200,
                    json={
                        "exception": "moodle_exception",
                        "errorcode": "invalidtoken",
                        "message": "Invalid token - token not found",
                    },
                )
            if form["wsfunction"] == "mod_assign_get_assignments":
                return httpx.Response(
                    200,
                    json={
                        "courses": [
                            {
                                "id": 2,
                                "assignments": [
                                    {"id": 1, "name": "Контрольная", "grade": self.max_grade}
                                ],
                            }
                        ],
                        "warnings": [],
                    },
                )
            if form["wsfunction"] == "mod_assign_get_submissions":
                return httpx.Response(
                    200,
                    json={
                        "assignments": [{"assignmentid": 1, "submissions": self.submissions}],
                        "warnings": [],
                    },
                )
            if form["wsfunction"] == "mod_assign_save_grade":
                self.grades[int(form["userid"])] = form
                return httpx.Response(200, content=b"null")
            return httpx.Response(200, json={"exception": "x", "errorcode": "accessexception"})
        if request.url.path.startswith("/webservice/pluginfile.php/"):
            if request.url.params.get("token") != self.token:
                return httpx.Response(403)
            key = "/".join(request.url.path.split("/")[-2:])
            return httpx.Response(200, content=self.files[key])
        return httpx.Response(404)


def fake_server(moodle: "FakeMoodle | None" = None):
    """MCP-сервер Moodle в том же процессе, который ходит в подделку Moodle."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(moodle or FakeMoodle()))
    return build_server(lambda: MoodleApi(SITE, TOKEN, client))
