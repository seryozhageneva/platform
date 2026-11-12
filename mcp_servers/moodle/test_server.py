"""MCP-сервер Moodle на подделке Moodle: без сети и без Docker (задача 23)."""

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
from mcp_servers.moodle.testing import (
    FILES,
    SITE,
    TOKEN,
    FakeMoodle,
    make_file,
    make_submission,
)


def _api(moodle: FakeMoodle, *, token: str = TOKEN) -> Callable[[], MoodleApi]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(moodle))
    return lambda: MoodleApi(SITE, token, client)


def _call(make_api: Callable[[], MoodleApi], tool: str = "get_submissions", **arguments: Any):
    async def go():
        async with Client(build_server(make_api)) as client:
            return await client.call_tool(tool, {"course_id": 2, "assignment_id": 1, **arguments})

    return asyncio.run(go())


def test_reading_tools_are_read_only_and_grading_is_not():
    async def go():
        async with Client(build_server(_api(FakeMoodle()))) as client:
            return {tool.name: tool for tool in (await client.list_tools()).tools}

    tools = asyncio.run(go())
    assert list(tools) == ["get_submissions", "list_submissions", "get_course_grades", "save_grade"]
    for name in ("get_submissions", "list_submissions", "get_course_grades"):
        assert tools[name].annotations.read_only_hint is True
        assert tools[name].annotations.destructive_hint is False
    for name in ("get_submissions", "list_submissions"):
        assert set(tools[name].input_schema["required"]) == {"course_id", "assignment_id"}
    assert tools["get_course_grades"].input_schema["required"] == ["course_id"]
    grade = tools["save_grade"]
    assert grade.annotations.read_only_hint is False
    assert set(grade.input_schema["required"]) == {
        "course_id",
        "assignment_id",
        "user_id",
        "score",
        "max_score",
    }


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
        "moodle_course_id": 2,
        "moodle_assignment_id": 1,
        "submitted_at": 1794393677,
    }
    # Имён студентов в ответе нет: Moodle их здесь и не присылает.
    assert "Студент" not in str(data)


def test_no_submitted_works_is_empty_outcome():
    moodle = FakeMoodle(
        [make_submission(4, 7, "draft", [make_file("4/draft.pdf", "application/pdf")])]
    )
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
            make_submission(
                1, 4, "submitted", [make_file("1/work1.pdf", "application/pdf", "http://evil.test")]
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


def test_only_chosen_submissions_are_downloaded():
    moodle = FakeMoodle()
    result = _call(_api(moodle), submission_ids=[3])
    works = result.structured_content["works"]
    assert [work["name"] for work in works] == ["solution.py"]
    downloads = [r for r in moodle.requests if "pluginfile" in r.url.path]
    assert len(downloads) == 1


def test_list_of_submissions_has_no_files_and_no_drafts():
    moodle = FakeMoodle()
    result = _call(_api(moodle), "list_submissions")
    assert result.structured_content == {
        "submissions": [
            {"submission_id": 1, "user_id": 4, "submitted_at": 1794393677},
            {"submission_id": 2, "user_id": 5, "submitted_at": 1794393677},
            {"submission_id": 3, "user_id": 6, "submitted_at": 1794393677},
        ],
        "outcome": "ok",
    }
    assert not [r for r in moodle.requests if "pluginfile" in r.url.path]


def test_grade_is_scaled_to_assignment_and_comment_is_plain_text():
    moodle = FakeMoodle(max_grade=10)
    result = _call(
        _api(moodle),
        "save_grade",
        user_id=4,
        score=1,
        max_score=2,
        comment="Допишите <b>вывод</b>.",
    )
    assert result.structured_content == {"grade": 5.0, "outcome": "saved"}
    sent = moodle.grades[4]
    assert sent["assignmentid"] == "1"
    assert sent["grade"] == "5.0"
    assert sent["attemptnumber"] == "-1"
    assert sent["plugindata[assignfeedbackcomments_editor][text]"] == "Допишите <b>вывод</b>."
    assert sent["plugindata[assignfeedbackcomments_editor][format]"] == "2"


@pytest.mark.parametrize(
    ("score", "max_score", "max_grade", "match"),
    [
        (3, 2, 100, "от 0 до максимума"),
        (1, 0, 100, "от 0 до максимума"),
        (1, 2, -1, "не баллами"),
    ],
)
def test_bad_grade_is_refused_and_moodle_is_not_changed(score, max_score, max_grade, match):
    moodle = FakeMoodle(max_grade=max_grade)
    result = _call(_api(moodle), "save_grade", user_id=4, score=score, max_score=max_score)
    assert result.is_error is True
    assert match in result.content[0].text
    assert moodle.grades == {}


def _grades(moodle: FakeMoodle, course_id: int = 2):
    async def go():
        async with Client(build_server(_api(moodle))) as client:
            return await client.call_tool("get_course_grades", {"course_id": course_id})

    return asyncio.run(go())


def test_course_grades_have_numbers_without_names_and_skip_ungraded():
    moodle = FakeMoodle(max_grade=10)
    moodle.journal = {5: 7, 4: 9.5}
    result = _grades(moodle)
    assert result.is_error is False
    assert result.structured_content == {
        "assignments": [
            {
                "assignment_id": 1,
                "name": "Контрольная",
                "max_grade": 10.0,
                "grades": [
                    {"user_id": 4, "grade": 9.5, "graded_at": 1794393700},
                    {"user_id": 5, "grade": 7.0, "graded_at": 1794393700},
                ],
            }
        ],
        "outcome": "ok",
    }
    asked = [parse_qs(r.content.decode())["wsfunction"][0] for r in moodle.requests]
    assert asked == ["mod_assign_get_assignments", "mod_assign_get_grades"]


def test_course_grades_of_unknown_course_is_error():
    result = _grades(FakeMoodle(), course_id=3)
    assert result.is_error is True
    assert "нет такого курса" in result.content[0].text


def test_course_grades_take_the_last_attempt():
    rows = [
        {"userid": 4, "attemptnumber": 0, "timemodified": 1, "grade": "3.00000"},
        {"userid": 4, "attemptnumber": 1, "timemodified": 2, "grade": "8.00000"},
        {"userid": 5, "attemptnumber": 1, "timemodified": 2, "grade": "-1.00000"},
        {"userid": 5, "attemptnumber": 0, "timemodified": 1, "grade": "6.00000"},
    ]

    def moodle(request: httpx.Request) -> httpx.Response:
        function = parse_qs(request.content.decode())["wsfunction"][0]
        if function == "mod_assign_get_assignments":
            course = {"id": 2, "assignments": [{"id": 1, "name": "Лаба", "grade": 10}]}
            return httpx.Response(200, json={"courses": [course], "warnings": []})
        return httpx.Response(200, json={"assignments": [{"assignmentid": 1, "grades": rows}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(moodle))
    found = asyncio.run(MoodleApi(SITE, TOKEN, client).course_grades(2))
    # У студента 5 последняя попытка ещё не оценена: прошлая оценка к ней не относится.
    assert found[0]["grades"] == [{"user_id": 4, "grade": 8.0, "graded_at": 2}]
