"""Общее для тестов контракта: где лежат примеры и как их загрузить."""

import json
from pathlib import Path
from typing import Any

import pytest

from backend.core.contracts.manifest import Manifest, load_manifest

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


@pytest.fixture(scope="session")
def manifests() -> dict[str, Manifest]:
    loaded = [load_manifest(path) for path in sorted(MANIFESTS.glob("*.yaml"))]
    return {manifest.id: manifest for manifest in loaded}
