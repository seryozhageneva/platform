"""Ручная проверка развёрнутой платформы (задача 24a, гейт 2; ADR 0030).

Запуск:
    uv run python -m experiments.deploy_check https://адрес-платформы
    uv run python -m experiments.deploy_check https://localhost --ca-file tmp/caddy-root.crt
    uv run python -m experiments.deploy_check https://адрес-платформы --email почта@преподавателя

Что проверяется:
1. по https:// открывается страница платформы;
2. API отвечает на /api/v1/health;
3. адрес http:// перенаправляет на https://;
4. служебные страницы API (/docs, /openapi.json) снаружи не видны;
5. с --email: вход преподавателя проходит, а cookie входа помечена Secure и HttpOnly.
   Пароль спрашивается в терминале и на экран не выводится.

Проверка сертификата не отключается. Для localhost Caddy выпускает сертификат своим
удостоверяющим центром; его корневой сертификат передаётся через --ca-file (см. docs/deploy.md).
"""

import argparse
import ssl
import sys
from getpass import getpass
from urllib.parse import urlsplit

import httpx


def _client(ca_file: str | None) -> httpx.Client:
    verify: ssl.SSLContext | bool = True
    if ca_file:
        verify = ssl.create_default_context(cafile=ca_file)
    return httpx.Client(verify=verify, timeout=15, follow_redirects=False)


def check(site: str, ca_file: str | None, email: str | None) -> list[str]:
    """Список провалов; пустой — всё в порядке."""
    failures: list[str] = []
    parts = urlsplit(site)
    if parts.scheme != "https" or not parts.hostname:
        return ["адрес должен начинаться с https://"]
    site = f"https://{parts.netloc}"

    with _client(ca_file) as client:
        try:
            page = client.get(f"{site}/")
        except httpx.ConnectError as error:
            return [f"не удалось подключиться по HTTPS: {error}"]
        if page.status_code != 200 or '<div id="root">' not in page.text:
            failures.append(f"страница платформы: ответ {page.status_code}")

        health = client.get(f"{site}/api/v1/health")
        if health.status_code != 200 or health.json() != {"status": "ok"}:
            failures.append(f"/api/v1/health: ответ {health.status_code}")

        plain = client.get(f"http://{parts.hostname}/")
        location = plain.headers.get("location", "")
        if plain.status_code not in {301, 302, 307, 308} or not location.startswith("https://"):
            failures.append(f"http:// не перенаправляет на https:// (ответ {plain.status_code})")

        for hidden in ("/docs", "/openapi.json"):
            if client.get(f"{site}{hidden}").status_code == 200:
                failures.append(f"{hidden} виден из интернета")

        if email:
            password = getpass(f"Пароль {email}: ")
            login = client.post(
                f"{site}/api/v1/auth/teacher",
                json={"email": email, "password": password},
                headers={"Origin": site},
            )
            cookie = login.headers.get("set-cookie", "")
            if login.status_code != 200:
                failures.append(f"вход преподавателя: ответ {login.status_code}")
            elif "Secure" not in cookie or "HttpOnly" not in cookie:
                failures.append("cookie входа без пометок Secure и HttpOnly")
            else:
                client.post(f"{site}/api/v1/auth/logout", headers={"Origin": site})
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка развёрнутой платформы")
    parser.add_argument("site", help="адрес платформы, например https://localhost")
    parser.add_argument("--ca-file", help="корневой сертификат, если он не общеизвестный")
    parser.add_argument("--email", help="почта преподавателя для проверки входа")
    arguments = parser.parse_args()

    failures = check(arguments.site, arguments.ca_file, arguments.email)
    if failures:
        print("Проверка не пройдена:")
        for failure in failures:
            print(f"  — {failure}")
        return 1
    checked = "страница, API, HTTPS, служебные страницы скрыты"
    if arguments.email:
        checked += ", вход и cookie Secure"
    print(f"Платформа открывается по адресу: {checked}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
