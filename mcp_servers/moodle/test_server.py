"""MCP-сервер Moodle на подделке Moodle: без сети и без Docker (задача 23).

Подделка отвечает так же, как Web Services Moodle 5.3 тестового контейнера: ответы сняты
с него и сокращены. Данные — выдуманные.
"""

import asyncio
import base64
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from mcp import Client

from mcp_servers.moodle.moodle_api import MAX_FILE_SIZE, MoodleApi, MoodleError
from mcp_servers.moodle.server import build_server, server_from_env

SITE = "http://moodle.test"
TOKEN = "0123456789abcdef0123456789abcdef"
FILES = {
    "1/work1.pdf": b"%PDF-1.4 work one",
    "2/work2.docx": b"PK docx work two",
    "3/solution.py": b"def f(x):\n    return 2 * x + 3\n",
    "4/draft.pdf": b"%PDF-1.4 draft",
}


def _file(path: str, mimetype: str, site: str = SITE) -> dict[str, Any]:
    return {
        "filename": path.split("/")[-1],
        "filepath": "/",
        "filesize": len(FILES.get(path, b"")),
        "fileurl": f"{site}/webservice/pluginfile.php/14/assignsubmission_file/"
        f"submission_files/{path}",
        "mimetype": mimetype,
    }


def _submission(number: int, user: int, status: str, files: list[dict]) -> dict[str, Any]:
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
    _submission(1, 4, "submitted", [_file("1/work1.pdf", "application/pdf")]),
    _submission(
        2,
        5,
        "submitted",
        [
            _file(
                "2/work2.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        ],
    ),
    _submission(3, 6, "submitted", [_file("3/solution.py", "document/unknown")]),
    _submission(4, 7, "draft", [_file("4/draft.pdf", "application/pdf")]),
    _submission(5, 8, "new", []),
]


class FakeMoodle:
    """Отвечает как Moodle; запоминает, куда и с каким токеном ходили."""

    def __init__(self, submissions: list[dict] | None = None, token: str = TOKEN) -> None:
        self.submissions = SUBMISSIONS if submissions is None else submissions
        self.token = token
        self.requests: list[httpx.Request] = []
        self.files = dict(FILES)

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
                        "courses": [{"id": 2, "assignments": [{"id": 1, "name": "Контрольная"}]}],
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
            return httpx.Response(200, json={"exception": "x", "errorcode": "accessexception"})
        if request.url.path.startswith("/webservice/pluginfile.php/"):
            if request.url.params.get("token") != self.token:
                return httpx.Response(403)
            key = "/".join(request.url.path.split("/")[-2:])
            return httpx.Response(200, content=self.files[key])
        return httpx.Response(404)


def _api(moodle: FakeMoodle, *, token: str = TOKEN) -> Callable[[], MoodleApi]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(moodle))
    return lambda: MoodleApi(SITE, token, client)


def _call(make_api: Callable[[], MoodleApi], **arguments: Any):
    async def go():
        async with Client(build_server(make_api)) as client:
            return await client.call_tool(
                "get_submissions", {"course_id": 2, "assignment_id": 1, **arguments}
            )

    return asyncio.run(go())


def test_tool_is_marked_read_only():
    async def go():
        async with Client(build_server(_api(FakeMoodle()))) as client:
            return (await client.list_tools()).tools

    tools = asyncio.run(go())
    assert [tool.name for tool in tools] == ["get_submissions"]
    assert tools[0].annotations.read_only_hint is True
    assert tools[0].annotations.destructive_hint is False
    assert set(tools[0].input_schema["required"]) == {"course_id", "assignment_id"}


def test_only_submitted_works_with_content_and_no_names():
    result = _call(_api(FakeMoodle()))
    assert result.is_error is False
    data = result.structured_content
    assert data["outcome"] == "ok"
    works = data["works"]
    assert [(w["name"], w["kind"], w["media_type"]) for w in works] == [
        ("work1.pdf", "document", "application/pdf"),
        (
            "work2.docx",
            "document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        # Moodle не знает тип файла с кодом, сервер подставляет его по расширению.
        ("solution.py", "code", "text/x-python"),
    ]
    assert base64.b64decode(works[2]["content_base64"]) == FILES["3/solution.py"]
    assert works[2]["size"] == len(FILES["3/solution.py"])
    assert works[0]["meta"] == {
        "moodle_user_id": 4,
        "moodle_submission_id": 1,
        "moodle_assignment_id": 1,
        "submitted_at": 1794393677,
    }
    # Имён студентов в ответе нет: Moodle их здесь и не присылает.
    assert "Студент" not in str(data)


def test_no_submitted_works_is_empty_outcome():
    moodle = FakeMoodle([_submission(4, 7, "draft", [_file("4/draft.pdf", "application/pdf")])])
    result = _call(_api(moodle))
    assert result.structured_content == {"works": [], "outcome": "empty"}


def test_wrong_token_is_clear_error_without_token():
    result = _call(_api(FakeMoodle(token="ffffffffffffffffffffffffffffffff")))
    assert result.is_error is True
    text = result.content[0].text
    assert "Moodle не принял токен" in text
    assert TOKEN not in text


def test_unknown_assignment_is_error():
    result = _call(_api(FakeMoodle()), assignment_id=99)
    assert result.is_error is True
    assert "нет такого задания" in result.content[0].text


def test_token_is_not_sent_to_another_site():
    moodle = FakeMoodle(
        [
            _submission(
                1, 4, "submitted", [_file("1/work1.pdf", "application/pdf", "http://evil.test")]
            )
        ]
    )
    result = _call(_api(moodle))
    assert result.is_error is True
    assert "с другого сайта" in result.content[0].text
    assert all(request.url.host == "moodle.test" for request in moodle.requests)


def test_too_big_file_is_refused():
    moodle = FakeMoodle()
    moodle.files["1/work1.pdf"] = b"x" * (MAX_FILE_SIZE + 1)
    result = _call(_api(moodle))
    assert result.is_error is True
    assert "больше 10 МиБ" in result.content[0].text


def test_unreachable_moodle_is_clear_error():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет связи", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(down))
    result = _call(lambda: MoodleApi(SITE, TOKEN, client))
    assert result.is_error is True
    assert "Moodle недоступен по адресу http://moodle.test" in result.content[0].text


@pytest.mark.parametrize(
    ("url", "token", "match"),
    [
        ("ftp://moodle.test", TOKEN, "адрес Moodle"),
        ("http://moodle.test?x=1", TOKEN, "адрес Moodle"),
        (SITE, "", "токен Moodle"),
        (SITE, "abc&wsfunction=core_user_delete_users", "токен Moodle"),
    ],
)
def test_bad_connection_settings(url, token, match):
    with pytest.raises(MoodleError, match=match):
        MoodleApi(url, token, httpx.AsyncClient())


def test_server_without_settings_reports_error():
    async def go():
        async with Client(server_from_env({})) as client:
            return await client.call_tool("get_submissions", {"course_id": 2, "assignment_id": 1})

    result = asyncio.run(go())
    assert result.is_error is True
    assert "адрес Moodle" in result.content[0].text
