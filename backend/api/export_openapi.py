"""Записать OpenAPI в stdout без подключения к базе."""

import json

from backend.api.app import create_app

if __name__ == "__main__":
    print(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2))
