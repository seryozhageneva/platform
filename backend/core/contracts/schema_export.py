"""Выгрузка JSON Schema манифеста и пайплайна в docs/schemas/.

Схемы нужны автору стороннего блока и редактору: по ним проверяется `block.yaml` и файл
пайплайна. Запуск: uv run python -m backend.core.contracts.schema_export
"""

import json
from pathlib import Path

from pydantic import BaseModel

from backend.core.contracts.manifest import Manifest
from backend.core.contracts.pipeline import Pipeline

SCHEMAS: dict[str, type[BaseModel]] = {
    "block.schema.json": Manifest,
    "pipeline.schema.json": Pipeline,
}
TARGET = Path(__file__).resolve().parents[3] / "docs" / "schemas"


def render(model: type[BaseModel]) -> str:
    schema = model.model_json_schema(by_alias=True)
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMAS.items():
        (TARGET / name).write_text(render(model), encoding="utf-8")
        print(f"записано: docs/schemas/{name}")


if __name__ == "__main__":
    main()
