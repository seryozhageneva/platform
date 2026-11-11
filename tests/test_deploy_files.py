"""Файлы для сервера (ADR 0030): что видно из интернета и что попадает в образ.

Docker здесь не нужен: проверяется сам текст файлов. Тест ловит ошибки, которые на сервере
стоили бы дорого: открытую наружу базу, секреты внутри образа, лишний доступ к Docker.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


def test_only_caddy_is_reachable_from_outside():
    published = {name for name, service in SERVICES.items() if service.get("ports")}

    assert published == {"web"}
    assert SERVICES["web"]["ports"] == ["80:80", "443:443", "443:443/udp"]


def test_only_sandbox_gets_docker_access():
    with_socket = {
        name
        for name, service in SERVICES.items()
        if any("docker.sock" in volume for volume in service.get("volumes", []))
    }

    assert with_socket == {"sandbox"}


def test_api_trusts_forwarded_headers_and_listens_inside_docker():
    environment = SERVICES["api"]["environment"]

    assert environment["PLATFORM_API_HOST"] == "0.0.0.0"
    assert environment["PLATFORM_TRUSTED_PROXIES"] == "*"
    assert environment["PLATFORM_SANDBOX_URL"] == "http://sandbox:8001"
    assert SERVICES["worker"]["environment"]["PLATFORM_SANDBOX_URL"] == "http://sandbox:8001"


def test_secrets_stay_out_of_images():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()

    assert {".env", ".env.*", "certs/", ".git/"} <= set(ignored)


def test_caddy_opens_only_api_and_frontend():
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")

    assert "{$PLATFORM_DOMAIN}" in caddyfile
    assert "handle /api/*" in caddyfile
    # К API ведёт ровно одно правило — только для /api/…; /docs и /openapi.json не открыты.
    assert caddyfile.count("reverse_proxy") == 1
