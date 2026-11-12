"""Настройки запуска по событию Moodle через API (ADR 0034).

Включение с настоящим блоком Moodle проверяет сквозной тест сценария 2; здесь — доступ,
отказы и выключение.
"""

from copy import deepcopy

from api_fakes import THREE_FAKES, saved

API = "/api/v1/pipelines"


def _graph(poll_minutes=5):
    graph = deepcopy(THREE_FAKES)
    graph["nodes"][0]["launches"].append(
        {"type": "moodle_event", "settings": {"poll_minutes": poll_minutes}}
    )
    return graph


def test_teacher_sees_only_own_watch_and_cannot_enable_without_moodle_source(client, me, stranger):
    pipeline_id = saved(client, me, _graph(poll_minutes=10))
    path = f"{API}/{pipeline_id}/moodle-watch"

    assert client.get(path, headers=me).json() == {
        "enabled": False,
        "params": {},
        "poll_minutes": 10,
        "last_polled_at": None,
        "last_error": None,
        "seen_submissions": 0,
    }
    assert client.get(path, headers=stranger).status_code == 404
    settings = {"enabled": True, "expected_version": 1}
    assert client.put(path, headers=stranger, json=settings).status_code == 404

    refused = client.put(path, headers=me, json=settings)
    assert refused.status_code == 422, refused.text
    assert refused.json()["problems"][0]["code"] == "moodle_source_needed"

    off = client.put(path, headers=me, json={**settings, "enabled": False})
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    assert client.put(path, headers=me, json={**settings, "expected_version": 2}).status_code == 409


def test_pipeline_without_moodle_launch_cannot_enable_watch(client, me):
    pipeline_id = saved(client, me, THREE_FAKES)
    response = client.put(
        f"{API}/{pipeline_id}/moodle-watch",
        headers=me,
        json={"enabled": True, "expected_version": 1},
    )
    assert response.status_code == 422, response.text
    assert response.json()["problems"][0]["code"] == "launch_not_allowed"
    assert (
        client.get(f"{API}/{pipeline_id}/moodle-watch", headers=me).json()["poll_minutes"] is None
    )
