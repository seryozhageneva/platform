"""Эндпоинты пайплайнов: сохранение с проверкой валидатором, версии, «каждый видит своё»."""

import asyncio
import copy
import uuid

from api_fakes import THREE_FAKES, chain, saved

from backend.models.users import UserRepository

API = "/api/v1"


def test_pipeline_is_saved_listed_and_read_back(client, me):
    created = client.post(f"{API}/pipelines", json=THREE_FAKES, headers=me)

    assert created.status_code == 201, created.text
    assert created.json()["version"] == 1
    assert created.json()["warnings"] == []
    pipeline_id = created.json()["id"]

    listed = client.get(f"{API}/pipelines", headers=me).json()
    assert [
        (item["id"], item["slug"], item["name"], item["latest_version"]) for item in listed
    ] == [(pipeline_id, "chain", "Цепочка фейковых блоков", 1)]

    read = client.get(f"{API}/pipelines/{pipeline_id}", headers=me).json()
    assert read["latest_version"] == 1
    # Граф возвращается в формате контракта — с теми же названиями полей, что и в файле.
    assert read["graph"]["transitions"][0] == {"from": "start", "when": None, "to": "make"}
    assert read["graph"]["nodes"][1]["config"] == {"text": {"$param": "phrase"}}


def test_new_version_is_saved_and_the_launch_takes_the_latest(client, me):
    pipeline_id = saved(client, me, THREE_FAKES)
    shorter = {**chain(("keep", "sink.fake_keep")), "name": "Короче"}

    updated = client.put(f"{API}/pipelines/{pipeline_id}", json=shorter, headers=me)

    assert updated.status_code == 200, updated.text
    assert updated.json() == {"id": pipeline_id, "version": 2, "warnings": []}
    read = client.get(f"{API}/pipelines/{pipeline_id}", headers=me).json()
    assert (read["name"], read["latest_version"]) == ("Короче", 2)
    assert [node["id"] for node in read["graph"]["nodes"]] == ["start", "make", "keep"]

    run = client.post(f"{API}/pipelines/{pipeline_id}/runs", headers=me).json()
    assert run["pipeline_version"] == 2
    events = client.get(f"{API}/runs/{run['id']}/events", headers=me).json()
    assert "upper" not in [event["node_id"] for event in events]


def test_pipeline_with_a_validator_error_is_not_saved(client, me):
    looped = copy.deepcopy(THREE_FAKES)
    # Круг без ограничителя: после «сохранить» снова «в верхний регистр».
    looped["transitions"].append({"from": "keep", "to": "upper"})
    looped["nodes"][3]["inputs"] = {"text": "upper.text"}

    refused = client.post(f"{API}/pipelines", json=looped, headers=me)

    assert refused.status_code == 422
    body = refused.json()
    assert body["message"] == "пайплайн не прошёл проверку и не сохранён"
    assert [problem["code"] for problem in body["problems"]] == ["unbounded_loop"]
    assert body["problems"][0]["node"] in ("upper", "keep")
    assert body["problems"][0]["message"]
    assert client.get(f"{API}/pipelines", headers=me).json() == []


def test_pipeline_with_an_unknown_block_is_not_saved(client, me):
    refused = client.post(
        f"{API}/pipelines", json=chain(("send", "sink.no_such_block")), headers=me
    )

    assert refused.status_code == 422
    assert [problem["node"] for problem in refused.json()["problems"]] == ["send"]
    assert client.get(f"{API}/pipelines", headers=me).json() == []


def test_new_version_with_an_error_is_not_saved(client, me):
    pipeline_id = saved(client, me, THREE_FAKES)

    refused = client.put(
        f"{API}/pipelines/{pipeline_id}", json=chain(("send", "sink.no_such_block")), headers=me
    )

    assert refused.status_code == 422
    assert client.get(f"{API}/pipelines/{pipeline_id}", headers=me).json()["latest_version"] == 1


def test_pipeline_with_a_warning_is_saved_and_the_warning_is_returned(client, me):
    """Блок с последствиями без Подтверждения — предупреждение, а не ошибка (ADR 0011)."""
    created = client.post(f"{API}/pipelines", json=chain(("send", "sink.fake_send")), headers=me)

    assert created.status_code == 201, created.text
    warnings = created.json()["warnings"]
    assert [(warning["node"], warning["code"]) for warning in warnings] == [("send", "no_approval")]
    assert len(client.get(f"{API}/pipelines", headers=me).json()) == 1


def test_request_not_in_the_pipeline_format_is_explained(client, me):
    misspelled = {**copy.deepcopy(THREE_FAKES), "nmae": "опечатка в названии поля"}
    del misspelled["name"]

    refused = client.post(f"{API}/pipelines", json=misspelled, headers=me)

    assert refused.status_code == 422
    body = refused.json()
    assert body["message"] == "запрос не соответствует формату"
    assert sorted((problem["code"], problem["message"]) for problem in body["problems"]) == [
        ("bad_format", "name: обязательное поле не заполнено"),
        ("bad_format", "nmae: неизвестное поле"),
    ]


def test_request_must_say_who_is_asking(client, me, sessions):
    assert client.get(f"{API}/pipelines").status_code == 401
    assert client.get(f"{API}/pipelines", headers={"X-Teacher-Id": "not-an-id"}).status_code == 401
    unknown = client.get(f"{API}/pipelines", headers={"X-Teacher-Id": str(uuid.uuid4())})
    assert unknown.status_code == 401
    assert unknown.json() == {"message": "преподаватель не найден", "problems": []}
    assert client.post(f"{API}/pipelines", json=THREE_FAKES).status_code == 401


def test_student_is_not_accepted_as_a_teacher(client, me, teacher, sessions):
    student = asyncio.run(UserRepository(sessions).create_student(teacher.id, name="Ученик 1"))

    refused = client.get(f"{API}/pipelines", headers={"X-Teacher-Id": str(student.id)})

    assert refused.status_code == 401


def test_pipelines_are_visible_only_to_their_teacher(client, me, stranger):
    pipeline_id = saved(client, me, THREE_FAKES)

    assert client.get(f"{API}/pipelines", headers=stranger).json() == []
    assert client.get(f"{API}/pipelines/{pipeline_id}", headers=stranger).status_code == 404
    hijacked = client.put(f"{API}/pipelines/{pipeline_id}", json=THREE_FAKES, headers=stranger)
    assert hijacked.status_code == 404
    assert client.get(f"{API}/pipelines/{pipeline_id}", headers=me).json()["latest_version"] == 1


def test_unknown_pipeline_is_not_found(client, me):
    missing = client.get(f"{API}/pipelines/{uuid.uuid4()}", headers=me)

    assert missing.status_code == 404
    assert missing.json() == {"message": "пайплайн не найден", "problems": []}
    assert client.get(f"{API}/pipelines/не-номер", headers=me).status_code == 422


def test_text_the_database_cannot_store_is_refused_not_crashed(client, me):
    """Нулевой символ встречается в тексте, скопированном из PDF; база его не записывает."""
    with_nul = {**copy.deepcopy(THREE_FAKES), "name": "Лекция\x00 1"}

    refused = client.post(f"{API}/pipelines", json=with_nul, headers=me)

    assert refused.status_code == 422
    assert "нулевой символ" in refused.json()["message"]
    assert client.get(f"{API}/pipelines", headers=me).json() == []
