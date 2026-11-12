from copy import deepcopy

from api_fakes import THREE_FAKES, saved

API = "/api/v1/pipelines"
CRON = "0 18 * * 5"


def test_teacher_can_configure_only_own_saved_pipeline(client, me, stranger):
    graph = deepcopy(THREE_FAKES)
    graph["nodes"][0]["launches"].append({"type": "schedule", "cron": CRON})
    pipeline_id = saved(client, me, graph)
    path = f"{API}/{pipeline_id}/schedule"
    settings = {"enabled": True, "params": {"phrase": "неделя"}, "expected_version": 1}

    initial = client.get(path, headers=me)
    assert initial.json() == {"cron": CRON, "enabled": False, "params": {}, "last_fired_at": None}
    assert client.get(path, headers=stranger).status_code == 404
    assert client.put(path, headers=stranger, json=settings).status_code == 404

    enabled = client.put(path, headers=me, json=settings)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enabled"] is True
    assert client.get(path, headers=me).json()["params"] == {"phrase": "неделя"}

    bad = client.put(path, headers=me, json={**settings, "params": {"phrase": 123}})
    assert bad.status_code == 422, bad.text
    assert bad.json()["problems"][0]["code"] == "bad_param"
    assert client.get(path, headers=me).json() == enabled.json()

    assert client.put(f"{API}/{pipeline_id}", headers=me, json=graph).status_code == 200
    assert client.put(path, headers=me, json=settings).status_code == 409
    disabled = client.put(
        path, headers=me, json={**settings, "enabled": False, "expected_version": 2}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False


def test_enabling_pipeline_without_schedule_is_refused(client, me):
    pipeline_id = saved(client, me, THREE_FAKES)
    response = client.put(
        f"{API}/{pipeline_id}/schedule", headers=me, json={"enabled": True, "expected_version": 1}
    )
    assert response.status_code == 422, response.text
    assert response.json()["problems"][0]["code"] == "launch_not_allowed"


def test_removing_schedule_from_graph_disables_it(client, me):
    graph = deepcopy(THREE_FAKES)
    graph["nodes"][0]["launches"].append({"type": "schedule", "cron": CRON})
    pipeline_id = saved(client, me, graph)
    path = f"{API}/{pipeline_id}/schedule"
    response = client.put(path, headers=me, json={"enabled": True, "expected_version": 1})
    assert response.status_code == 200, response.text

    assert client.put(f"{API}/{pipeline_id}", headers=me, json=THREE_FAKES).status_code == 200
    assert client.put(f"{API}/{pipeline_id}", headers=me, json=graph).status_code == 200
    assert client.get(path, headers=me).json()["enabled"] is False
