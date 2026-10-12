"""Манифест блока: примеры проходят проверку, сломанные манифесты отклоняются с понятной ошибкой."""

import copy

import pytest
import yaml
from conftest import MANIFESTS

from backend.core.contracts.base import ContractError
from backend.core.contracts.manifest import Category, Kind, load_manifest, parse_manifest
from backend.core.contracts.ports import PortType
from backend.core.contracts.screens import ScreenType

# Три полных примера — по одному на способ запуска.
FULL = {
    "student.show_task": "python",
    "source.moodle_submissions": "mcp",
    "check.code_tests": "http",
}


@pytest.mark.parametrize(("block_id", "runtime"), FULL.items())
def test_full_example_is_valid(block_id, runtime):
    manifest = load_manifest(MANIFESTS / f"{block_id}.yaml")
    assert manifest.id == block_id
    assert manifest.runtime.type == runtime


def test_show_task_example_in_detail():
    manifest = load_manifest(MANIFESTS / "student.show_task.yaml")
    assert manifest.kind is Kind.INTERACTIVE
    assert manifest.screen is ScreenType.ANSWER_FORM
    assert manifest.outcomes == ["answer", "photo", "hint_requested"]
    assert manifest.input("task").required is True
    assert manifest.input("hint").required is False
    assert manifest.output("answer").type is PortType.ANSWER
    assert manifest.side_effects is False


def test_all_drafts_are_valid(manifests):
    assert len(manifests) == len(list(MANIFESTS.glob("*.yaml"))) >= 20
    for path in MANIFESTS.glob("*.yaml"):
        assert path.stem in manifests, f"имя файла {path.name} не совпадает с id блока"
    assert {manifest.category for manifest in manifests.values()} == set(Category)
    assert {manifest.runtime.type for manifest in manifests.values()} == {"python", "mcp", "http"}


def test_defaults():
    manifest = parse_manifest(
        {
            "id": "sink.demo",
            "version": "1.0.0",
            "name": "Пример",
            "description": "Самый короткий манифест.",
            "author": "platform",
            "category": "sink",
            "runtime": {"type": "python", "entrypoint": "blocks.sink.demo:run"},
        }
    )
    assert manifest.kind is Kind.AUTO
    assert manifest.outcomes == ["ok"]
    assert manifest.config == {"type": "object", "properties": {}}
    assert manifest.side_effects is False and manifest.tools == []


def broken(change) -> dict:
    """Правильный манифест «показать задачу», испорченный функцией `change`."""
    text = (MANIFESTS / "student.show_task.yaml").read_text(encoding="utf-8")
    data = copy.deepcopy(yaml.safe_load(text))
    change(data)
    return data


def port(**fields) -> dict:
    return {"name": "extra", "title": "Лишний", "type": "Data", **fields}


# Что сломано, как сломать, что должно быть в сообщении об ошибке.
BROKEN = [
    ("нет id", lambda m: m.pop("id"), "id: обязательное поле не заполнено"),
    (
        "неизвестная категория",
        lambda m: m.update(category="logic"),
        "category: недопустимое значение 'logic'",
    ),
    ("ждёт человека без экрана", lambda m: m.pop("screen"), "ждёт человека: укажи `screen`"),
    (
        "экран у автоматического блока",
        lambda m: m.update(kind="auto"),
        "человека не ждёт",
    ),
    (
        "экран преподавателя у блока для ученика",
        lambda m: m.update(screen="review_table"),
        "экран `review_table` не подходит для `kind: interactive`",
    ),
    (
        "два входа с одним именем",
        lambda m: m["inputs"].append(dict(m["inputs"][0])),
        "имя входа повторяется: task",
    ),
    (
        "неизвестный способ запуска",
        lambda m: m.update(runtime={"type": "grpc", "url": "http://x"}),
        "runtime: неизвестный вид 'grpc'",
    ),
    ("опечатка в названии поля", lambda m: m.update(colour="red"), "colour: неизвестное поле"),
    ("версия не из трёх чисел", lambda m: m.update(version="1.0"), "version: значение '1.0'"),
    (
        "same_as на вход, которого нет",
        lambda m: m["outputs"].append(port(same_as="items")),
        "`same_as` ссылается на вход «items», которого нет",
    ),
    (
        "from_config на настройку, которой нет",
        lambda m: m["outputs"].append(port(from_config="result")),
        "`from_config` ссылается на настройку «result»",
    ),
    (
        "уточнение не у Data",
        lambda m: m["inputs"][0].update(of="summary"),
        "inputs.0: уточнение `of` бывает только у типа Data",
    ),
    (
        "настройки не описаны схемой",
        lambda m: m.update(config={"forms": ["text"]}),
        "config: настройки описываются как JSON Schema",
    ),
    (
        "исход с пробелом",
        lambda m: m.update(outcomes=["answer", "не знаю"]),
        "outcomes.1: значение 'не знаю'",
    ),
]


@pytest.mark.parametrize(("title", "change", "message"), BROKEN, ids=[b[0] for b in BROKEN])
def test_broken_manifest_is_rejected(title, change, message):
    with pytest.raises(ContractError) as error:
        parse_manifest(broken(change))
    assert message in str(error.value)


def test_not_a_mapping_is_rejected():
    with pytest.raises(ContractError, match="ожидался набор полей"):
        parse_manifest("- id: x\n- id: y\n")
    with pytest.raises(ContractError, match="это не YAML"):
        parse_manifest("id: [не закрыто")
