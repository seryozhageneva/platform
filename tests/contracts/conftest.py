"""Общее для тестов контракта: манифесты-примеры, загруженные один раз на прогон."""

import pytest
from contract_examples import MANIFESTS

from backend.core.contracts.manifest import Manifest, load_manifest


@pytest.fixture(scope="session")
def manifests() -> dict[str, Manifest]:
    loaded = [load_manifest(path) for path in sorted(MANIFESTS.glob("*.yaml"))]
    return {manifest.id: manifest for manifest in loaded}
