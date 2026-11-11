"""Точка входа контейнера. Получает исходник и stdin одного теста."""

import json
import os
import sys
from pathlib import Path


def main() -> None:
    payload = json.load(sys.stdin.buffer)
    code = Path("/tmp/answer.py")
    code.write_text(payload["code"], encoding="utf-8")
    stdin = Path("/tmp/stdin")
    stdin.write_text(payload["stdin"], encoding="utf-8")
    with stdin.open("rb") as stream:
        os.dup2(stream.fileno(), 0)
    # У контейнера есть собственный запасной таймер на случай остановки HTTP-сервиса.
    # Код получает только общие параметры Python, даже если Docker CLI настроил прокси.
    os.execve(
        "/usr/bin/timeout",
        ["timeout", "--foreground", "--signal=KILL", "8s", sys.executable, "-IBu", str(code)],
        {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
    )


if __name__ == "__main__":
    main()
