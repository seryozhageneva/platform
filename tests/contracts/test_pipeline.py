"""Формат пайплайна: правильные графы разбираются, сломанные отклоняются с понятной ошибкой."""

import copy

import pytest
from contract_examples import SCENARIOS, scenario

from backend.core.contracts.base import ContractError
from backend.core.contracts.pipeline import (
    ForEachNode,
    ParamRef,
    Pipeline,
    param_refs,
    parse_pipeline,
)

# Самый маленький пайплайн с циклом и «для каждого».
BASE = {
    "id": "demo",
    "name": "Пример",
    "params": [
        {"name": "n", "title": "Сколько раз", "type": "integer", "default": 3},
        {"name": "topic", "title": "Тема", "type": "string"},
    ],
    "nodes": [
        {"id": "start", "type": "trigger", "launches": [{"type": "manual"}]},
        {
            "id": "take",
            "type": "block",
            "block": "source.task_bank",
            "config": {"topic": {"$param": "topic"}},
            "limit": {"max": {"$param": "n"}, "otherwise": "finish"},
        },
        {
            "id": "each",
            "type": "for_each",
            "over": "take.tasks",
            "body": {
                "start": "inner",
                "nodes": [{"id": "inner", "type": "block", "block": "sink.task_bank"}],
            },
        },
        {"id": "finish", "type": "block", "block": "sink.cabinet"},
    ],
    "transitions": [
        {"from": "start", "to": "take"},
        {"from": "take", "when": "ok", "to": "each"},
        {"from": "each", "to": "take"},
    ],
}


def test_base_is_valid():
    pipeline = parse_pipeline(BASE)
    assert pipeline.trigger().id == "start"
    assert [node.id for node, _ in pipeline.walk()] == ["start", "take", "each", "inner", "finish"]
    assert dict((node.id, path) for node, path in pipeline.walk())["inner"] == ("each",)
    assert pipeline.nodes[1].limit.max == ParamRef(param="n")


def test_pipeline_can_be_parsed_from_json_text():
    text = Pipeline.model_validate(BASE).model_dump_json(by_alias=True)
    assert parse_pipeline(text) == parse_pipeline(BASE)
    with pytest.raises(ContractError, match="это не JSON"):
        parse_pipeline("{не закрыто")


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_survives_save_and_load(name):
    pipeline = parse_pipeline(scenario(name))
    saved = pipeline.model_dump(mode="json", by_alias=True)
    assert Pipeline.model_validate(saved) == pipeline


def test_param_refs_are_found_at_any_depth():
    config = {"a": {"$param": "x"}, "b": [1, {"c": {"$param": "y"}}], "d": "текст"}
    assert sorted(param_refs(config)) == ["x", "y"]


def node(pipeline: dict, node_id: str) -> dict:
    return next(item for item in pipeline["nodes"] if item["id"] == node_id)


def extra_trigger(p):
    p["nodes"].append({"id": "again", "type": "trigger", "launches": [{"type": "manual"}]})


def no_trigger(p):
    p["nodes"] = p["nodes"][1:]
    p["transitions"] = p["transitions"][1:]


# Что сломано, как сломать, что должно быть в сообщении об ошибке.
BROKEN = [
    ("два триггера", extra_trigger, "ровно один узел-триггер, а их 2"),
    ("нет триггера", no_trigger, "ровно один узел-триггер, а их 0"),
    (
        "имя узла повторяется во вложенном теле",
        lambda p: node(p, "each")["body"]["nodes"][0].update(id="take"),
        "имя узла повторяется: take",
    ),
    (
        "переход к узлу, которого нет",
        lambda p: p["transitions"].append({"from": "finish", "to": "nowhere"}),
        "ведёт к узлу «nowhere», которого на этом уровне нет",
    ),
    (
        "переход снаружи внутрь «для каждого»",
        lambda p: p["transitions"].append({"from": "finish", "to": "inner"}),
        "ведёт к узлу «inner», которого на этом уровне нет",
    ),
    (
        "переход в триггер",
        lambda p: p["transitions"].append({"from": "finish", "to": "start"}),
        "переход не может вести в узел-триггер",
    ),
    (
        "условие у перехода из триггера",
        lambda p: p["transitions"][0].update(when="ok"),
        "у триггера нет исходов",
    ),
    (
        "два перехода с одним условием",
        lambda p: p["transitions"].append({"from": "take", "when": "ok", "to": "finish"}),
        "из узла «take» два перехода с одним условием (ok)",
    ),
    (
        "настройка ссылается на параметр, которого нет",
        lambda p: node(p, "take")["config"].update(difficulty={"$param": "level"}),
        "ссылка на параметр «level», которого нет в `params`",
    ),
    (
        "ссылка на параметр записана не именем",
        lambda p: node(p, "take")["config"].update(topic={"$param": ["topic"]}),
        "ссылка на параметр пишется как",
    ),
    (
        "значение по умолчанию не того типа",
        lambda p: p["params"][0].update(default="много"),
        "значение по умолчанию 'много' не подходит под тип integer",
    ),
    (
        "ограничитель обнуляется на узле из чужого тела",
        lambda p: node(p, "take")["limit"].update(reset_on="inner"),
        "ограничитель обнуляется на узле «inner», а он внутри «для каждого»",
    ),
    (
        "ограничитель ведёт в никуда",
        lambda p: node(p, "take")["limit"].update(otherwise="nowhere"),
        "ограничитель узла «take» ведёт к узлу «nowhere»",
    ),
    (
        "ограничитель обнуляется на узле, которого нет",
        lambda p: node(p, "take")["limit"].update(reset_on="nowhere"),
        "ограничитель обнуляется на узле «nowhere», которого нет",
    ),
    (
        "ограничитель задан текстовым параметром",
        lambda p: node(p, "take")["limit"].update(max={"$param": "topic"}),
        "нужен параметр типа integer",
    ),
    (
        "ограничитель меньше единицы",
        lambda p: node(p, "take")["limit"].update(max=0),
        "nodes.1.block.limit.max",
    ),
    (
        "расписание без cron",
        lambda p: node(p, "start").update(launches=[{"type": "schedule"}]),
        "поле `cron` нужно способу запуска `schedule` и только ему",
    ),
    (
        "триггер без способов запуска",
        lambda p: node(p, "start").update(launches=[]),
        "nodes.0.trigger.launches",
    ),
    (
        "тело начинается с узла, которого в нём нет",
        lambda p: node(p, "each")["body"].update(start="take"),
        "тело начинается с узла «take», которого в теле нет",
    ),
    (
        "запись из нескольких полей без названия",
        lambda p: node(p, "each").update(collect={"task": "each.item"}),
        "`as` (название записи) нужно тогда, когда `collect` — набор полей",
    ),
    (
        "ссылка не в виде «узел.порт»",
        lambda p: node(p, "each").update(over="take"),
        "nodes.2.for_each.over",
    ),
    (
        "неизвестный вид узла",
        lambda p: node(p, "finish").update(type="loop"),
        "nodes.3: неизвестный вид 'loop'",
    ),
    (
        "опечатка в названии поля",
        lambda p: node(p, "finish").update(inptus={}),
        "nodes.3.block.inptus: неизвестное поле",
    ),
]


@pytest.mark.parametrize(("title", "change", "message"), BROKEN, ids=[b[0] for b in BROKEN])
def test_broken_pipeline_is_rejected(title, change, message):
    pipeline = copy.deepcopy(BASE)
    change(pipeline)
    with pytest.raises(ContractError) as error:
        parse_pipeline(pipeline)
    assert message in str(error.value)


def test_scenario_2_has_one_trigger_with_two_launches():
    """Открытый вопрос 9: узел-триггер один, способов запуска может быть несколько."""
    trigger = parse_pipeline(scenario("scenario-2-grading")).trigger()
    assert [launch.type for launch in trigger.launches] == ["moodle_event", "schedule"]


def test_limit_inside_body_may_reset_on_outer_node():
    pipeline = copy.deepcopy(BASE)
    node(pipeline, "each")["body"]["nodes"][0]["limit"] = {"max": 2, "reset_on": "take"}
    parse_pipeline(pipeline)


def has_cycle(nodes: set[str], edges: set[tuple[str, str]]) -> bool:
    """Есть ли цикл: убираем узлы без входящих стрелок, пока получается."""
    nodes, edges = set(nodes), {(a, b) for a, b in edges if a in nodes and b in nodes}
    while nodes:
        free = nodes - {target for _, target in edges}
        if not free:
            return True
        nodes -= free
        edges = {(a, b) for a, b in edges if a in nodes}
    return False


@pytest.mark.parametrize("name", SCENARIOS)
def test_every_loop_in_scenario_has_a_limit(name):
    """Если убрать узлы с ограничителем, циклов в графе не остаётся."""
    pipeline = parse_pipeline(scenario(name))
    levels = [(pipeline.nodes, pipeline.transitions)]
    levels += [
        (n.body.nodes, n.body.transitions) for n, _ in pipeline.walk() if isinstance(n, ForEachNode)
    ]
    for nodes, transitions in levels:
        edges = {(move.source, move.target) for move in transitions}
        unlimited = {n.id for n in nodes if getattr(n, "limit", None) is None}
        assert has_cycle({n.id for n in nodes}, edges) is (name == "scenario-1-training")
        assert not has_cycle(unlimited, edges)


def test_scenario_1_loops_have_limits():
    pipeline = parse_pipeline(scenario("scenario-1-training"))
    limits = {n.id: n.limit for n, _ in pipeline.walk() if getattr(n, "limit", None)}
    assert limits["take_task"].max == ParamRef(param="n_tasks")
    assert limits["take_task"].otherwise == "collect_results"
    assert limits["tutor"].max == ParamRef(param="max_hints")
    assert limits["tutor"].reset_on == "take_task"
    # Цикл «фото не читается → показать снова» тоже ограничен.
    assert limits["recognize"].max == 3 and limits["recognize"].reset_on == "take_task"


def test_for_each_collects_a_record():
    pipeline = parse_pipeline(scenario("scenario-2-grading"))
    each = next(n for n, _ in pipeline.walk() if n.id == "each_work")
    assert isinstance(each, ForEachNode)
    assert each.record == "graded_work" and set(each.collect) == {"work", "verdict", "comment"}
