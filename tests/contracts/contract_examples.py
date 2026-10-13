"""Примеры для тестов контракта: где лежат манифесты и сценарии и как их загрузить.

Лежит отдельно от `conftest.py`: файлов с таким именем в тестах несколько, и подключить
по имени «тот самый» нельзя — Python отдаёт тот, что загружен последним.
"""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ROOT / "docs" / "examples" / "manifests"
PIPELINES = ROOT / "docs" / "examples" / "pipelines"

SCENARIOS = [
    "scenario-1-training",
    "scenario-2-grading",
    "scenario-3-materials",
    "scenario-4-analytics",
]


def scenario(name: str) -> dict[str, Any]:
    """Сценарий как словарь — свежая копия, которую тест может портить."""
    return json.loads((PIPELINES / f"{name}.json").read_text(encoding="utf-8"))
