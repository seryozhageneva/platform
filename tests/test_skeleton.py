"""Каркас: пакеты целевой структуры на месте и видны проверке импортов."""

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOT_PACKAGES = ["backend", "blocks", "mcp_servers", "services"]

PACKAGES = [
    "backend",
    "backend.core",
    "backend.core.contracts",
    "backend.triggers",
    "backend.api",
    "backend.llm",
    "backend.mcp_client",
    "backend.models",
    "blocks",
    "blocks.source",
    "blocks.transform",
    "blocks.student",
    "blocks.check",
    "blocks.ai_process",
    "blocks.approval",
    "blocks.sink",
    "mcp_servers",
    "mcp_servers.moodle",
    "mcp_servers.cloud",
    "mcp_servers.email",
    "mcp_servers.telegram",
    "services",
    "services.sandbox",
]


def test_packages_importable():
    for name in PACKAGES:
        importlib.import_module(name)


def test_every_code_folder_is_a_package():
    """Папку с кодом без __init__.py проверка импортов не видит — таких быть не должно."""
    missing = set()
    for package in ROOT_PACKAGES:
        for file in (ROOT / package).rglob("*.py"):
            folder = file.parent
            while folder != ROOT:
                if not (folder / "__init__.py").exists():
                    missing.add(str(folder.relative_to(ROOT)))
                folder = folder.parent
    assert not missing, f"Нет __init__.py в папках: {sorted(missing)}"


def test_top_level_init_files_are_empty():
    """Код в этих файлах загружается вместе с контрактами в обход правил импортов."""
    for name in ["backend/__init__.py", "backend/core/__init__.py"]:
        assert (ROOT / name).read_text().strip() == "", f"{name} должен оставаться пустым"


def test_tests_do_not_import_conftest_by_name():
    """Файлов `conftest.py` несколько, и по имени подключается тот, что загружен последним.

    Поэтому `from conftest import ...` работает только при удачном порядке запуска. Общее
    для тестов лежит в файле со своим именем — как `tests/llm/llm_doubles.py`.
    """
    guilty = [
        str(file.relative_to(ROOT))
        for file in (ROOT / "tests").rglob("*.py")
        if any(
            line.strip().startswith(("from conftest import", "import conftest"))
            for line in file.read_text(encoding="utf-8").splitlines()
        )
    ]
    assert not guilty, f"Подключают conftest по имени: {guilty}"
