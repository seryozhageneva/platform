"""Правила импортов из .importlinter действительно ловят нарушения.

Каждый тест собирает во временной папке пробный мини-проект с теми же именами пакетов,
добавляет в него одно подключение и запускает lint-imports с настоящими правилами проекта.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / ".importlinter"
LINT_IMPORTS = Path(sys.executable).with_name("lint-imports")

# Пустой пробный проект: путь файла -> его содержимое.
PROBE = {
    "backend/__init__.py": "",
    "backend/core/__init__.py": "",
    "backend/core/contracts/__init__.py": "",
    "backend/core/contracts/ports.py": "",
    "backend/core/engine.py": "",
    "blocks/__init__.py": "",
    "blocks/check/__init__.py": "",
    "blocks/check/demo.py": "",
    "mcp_servers/__init__.py": "",
    "mcp_servers/moodle/__init__.py": "",
    "mcp_servers/moodle/server.py": "",
    "services/__init__.py": "",
    "services/sandbox/__init__.py": "",
}


def lint(tmp_path: Path, changed: dict[str, str]) -> subprocess.CompletedProcess:
    """Собирает пробный проект с изменёнными файлами и проверяет его правилами проекта."""
    for name, text in {**PROBE, **changed}.items():
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    return subprocess.run(
        [str(LINT_IMPORTS), "--config", str(RULES), "--no-cache"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_block_cannot_import_engine(tmp_path):
    result = lint(tmp_path, {"blocks/check/demo.py": "import backend.core.engine\n"})
    assert result.returncode != 0, result.stdout
    assert "1. Блоки видят только контракты BROKEN" in result.stdout


def test_block_cannot_import_adapter(tmp_path):
    result = lint(tmp_path, {"blocks/check/demo.py": "import mcp_servers.moodle.server\n"})
    assert result.returncode != 0, result.stdout
    assert "1. Блоки видят только контракты BROKEN" in result.stdout


def test_engine_cannot_import_block(tmp_path):
    result = lint(tmp_path, {"backend/core/engine.py": "import blocks.check.demo\n"})
    assert result.returncode != 0, result.stdout
    assert "2. Бэкенд не подключает блоки, адаптеры и сервисы BROKEN" in result.stdout


def test_contracts_import_nothing(tmp_path):
    result = lint(tmp_path, {"backend/core/contracts/ports.py": "import backend.core.engine\n"})
    assert result.returncode != 0, result.stdout
    assert "3. Контракты не подключают ничего другого из проекта BROKEN" in result.stdout


def test_adapter_cannot_import_engine(tmp_path):
    result = lint(tmp_path, {"mcp_servers/moodle/server.py": "import backend.core.engine\n"})
    assert result.returncode != 0, result.stdout
    assert "4. Адаптеры и сервисы видят только контракты BROKEN" in result.stdout


def test_adapter_cannot_import_service(tmp_path):
    result = lint(tmp_path, {"mcp_servers/moodle/server.py": "import services.sandbox\n"})
    assert result.returncode != 0, result.stdout
    assert "4. Адаптеры и сервисы видят только контракты BROKEN" in result.stdout


def test_contracts_are_allowed_everywhere(tmp_path):
    result = lint(
        tmp_path,
        {
            "blocks/check/demo.py": "from backend.core.contracts import ports\n",
            "mcp_servers/moodle/server.py": "import backend.core.contracts.ports\n",
            "backend/core/engine.py": "from backend.core.contracts import ports\n",
        },
    )
    assert result.returncode == 0, result.stdout
    assert "4 kept, 0 broken" in result.stdout
