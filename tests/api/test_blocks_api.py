"""Каталог берётся из реестра и доступен только преподавателю."""

from uuid import uuid4

from test_lessons_api import student_session

BLOCKS = "/api/v1/blocks"


def test_catalog_uses_installed_manifests(client_of, registry_of, me, teacher):
    registry = registry_of("source.fake_text")
    client = client_of(registry)

    response = client.get(BLOCKS, headers={**me, "X-Expected-Account": str(teacher.id)})

    assert response.status_code == 200, response.text
    (item,) = response.json()
    manifest = registry.manifests[item["id"]]
    fields = {
        "id",
        "name",
        "description",
        "category",
        "inputs",
        "outputs",
        "outcomes",
        "config",
        "side_effects",
    }
    assert item == manifest.model_dump(mode="json", by_alias=True, include=fields)


def test_catalog_checks_teacher_session(client, me):
    assert client.get(BLOCKS).status_code == 401
    assert client.get(BLOCKS, headers={**me, "X-Expected-Account": str(uuid4())}).status_code == 409
    _, student, _ = student_session(client, me, "Лис")
    assert client.get(BLOCKS, headers=student).status_code == 403
