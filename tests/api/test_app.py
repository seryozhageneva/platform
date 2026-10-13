"""Само приложение: сервер отвечает, а описание OpenAPI строится и называет все эндпоинты.

Из описания OpenAPI фронтенд получит свои типы (задача 13), поэтому оно проверяется уже здесь.
"""

API = "/api/v1"


def test_server_is_alive(client):
    response = client.get(f"{API}/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_describes_every_endpoint(client):
    schema = client.get("/openapi.json")

    assert schema.status_code == 200
    found = {
        (method.upper(), path)
        for path, methods in schema.json()["paths"].items()
        for method in methods
    }
    assert found == {
        ("GET", f"{API}/health"),
        ("POST", f"{API}/pipelines"),
        ("GET", f"{API}/pipelines"),
        ("GET", f"{API}/pipelines/{{pipeline_id}}"),
        ("PUT", f"{API}/pipelines/{{pipeline_id}}"),
        ("POST", f"{API}/pipelines/{{pipeline_id}}/runs"),
        ("GET", f"{API}/runs/{{run_id}}"),
        ("GET", f"{API}/runs/{{run_id}}/events"),
    }
    # Граф пайплайна описан моделью контракта, а не «любым JSON».
    assert "Pipeline" in schema.json()["components"]["schemas"]


def test_refusals_of_the_server_itself_look_like_all_the_others(client, me):
    """Неизвестный адрес, неверный метод и тело не в JSON — тот же вид: текст и причины."""
    unknown = client.get(f"{API}/no_such_address")
    assert unknown.status_code == 404
    assert unknown.json() == {"message": "такого адреса у API нет", "problems": []}

    wrong_method = client.delete(f"{API}/pipelines", headers=me)
    assert wrong_method.status_code == 405
    assert wrong_method.json() == {
        "message": "этот адрес не принимает такой запрос",
        "problems": [],
    }

    not_json = client.post(
        f"{API}/pipelines", content="{", headers={**me, "Content-Type": "application/json"}
    )
    assert not_json.status_code == 422
    assert not_json.json() == {"message": "тело запроса — не JSON", "problems": []}
