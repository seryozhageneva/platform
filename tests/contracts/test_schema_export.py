"""Выгруженные JSON Schema в docs/schemas/ не отстают от моделей контракта."""

import json

import pytest
import yaml
from contract_examples import MANIFESTS, ROOT, SCENARIOS, scenario
from jsonschema import Draft202012Validator

from backend.core.contracts.schema_export import SCHEMAS, render

HOW_TO_UPDATE = "обнови схемы: uv run python -m backend.core.contracts.schema_export"


@pytest.mark.parametrize("name", SCHEMAS)
def test_schema_file_is_up_to_date(name):
    saved = (ROOT / "docs" / "schemas" / name).read_text(encoding="utf-8")
    assert saved == render(SCHEMAS[name]), HOW_TO_UPDATE


def schema(name: str) -> Draft202012Validator:
    data = json.loads((ROOT / "docs" / "schemas" / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(data)
    return Draft202012Validator(data)


def test_examples_fit_the_exported_schemas():
    """Схемой можно пользоваться без Python: примеры проходят и по ней."""
    blocks = schema("block.schema.json")
    for path in MANIFESTS.glob("*.yaml"):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert list(blocks.iter_errors(manifest)) == [], path.name
    pipelines = schema("pipeline.schema.json")
    for name in SCENARIOS:
        assert list(pipelines.iter_errors(scenario(name))) == [], name
