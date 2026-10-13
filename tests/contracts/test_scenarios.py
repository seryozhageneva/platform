"""Четыре сценария из docs/vision.md записаны в формате контракта и стыкуются по портам.

Вторая половина файла портит сценарии по одному месту и требует, чтобы проверка это
поймала: иначе зелёный результат первой половины ничего бы не доказывал.
"""

import pytest
from contract_examples import SCENARIOS, scenario

from backend.core.contracts.manifest import Category
from backend.core.contracts.pipeline import BlockNode, parse_pipeline
from backend.core.contracts.ports import DataType
from backend.core.contracts.wiring import Wiring, check_wiring


def blocks_of(name: str) -> set[str]:
    pipeline = parse_pipeline(scenario(name))
    return {node.block for node, _ in pipeline.walk() if isinstance(node, BlockNode)}


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_is_wired_correctly(name, manifests):
    pipeline = parse_pipeline(scenario(name))
    assert blocks_of(name) <= set(manifests)
    assert [str(problem) for problem in check_wiring(pipeline, manifests)] == []


def test_scenarios_use_every_block_and_category(manifests):
    used = set().union(*(blocks_of(name) for name in SCENARIOS))
    assert used == set(manifests), "есть черновик манифеста, который не нужен ни одному сценарию"
    assert {manifests[block].category for block in used} == set(Category)


def test_computed_types_are_resolved(manifests):
    """Типы выходов универсальных блоков вычисляются для каждого узла."""
    checker = Wiring(parse_pipeline(scenario("scenario-3-materials")), manifests)
    task_list = DataType(type="Task", is_list=True)
    record_list = DataType(type="Data", of="checked_task", is_list=True)
    # ИИ-обработка: тип записан в настройке узла.
    assert checker.outputs("summarize")["result"] == DataType(type="Data", of="summary")
    assert checker.outputs("make_tasks")["result"] == task_list
    # «Для каждого»: элемент списка внутри, собранная запись снаружи.
    assert checker.outputs("each_task")["item"] == DataType(type="Task")
    assert checker.outputs("each_task")["results"] == record_list
    # Подтверждение повторяет тип того, что ему подали.
    assert checker.outputs("review")["approved"] == record_list
    # Поле записи читается с тем типом, с каким его собрали.
    assert checker.ref_type("each_approved.item.task", "to_bank") == DataType(type="Task")
    assert checker.outputs("each_approved")["results"] == task_list
    assert checker.problems == []


@pytest.mark.parametrize("name", SCENARIOS)
def test_types_do_not_depend_on_the_order_of_questions(name, manifests):
    """Редактор может спросить тип любого узла первым — ложных ошибок от этого нет."""
    pipeline = parse_pipeline(scenario(name))
    for node, _ in pipeline.walk():
        wiring = Wiring(pipeline, manifests)
        wiring.outputs(node.id)
        assert wiring.problems == [], node.id
        assert wiring.run() == [], node.id


def test_approval_may_be_repeated_in_a_loop(manifests):
    """Вход Подтверждения читает и свежий список, и то, что само же вернуло в прошлый раз."""
    data = scenario("scenario-3-materials")
    find(data["nodes"], "review")["inputs"]["items"] = ["each_task.results", "review.approved"]
    wiring = Wiring(parse_pipeline(data), manifests)
    assert wiring.run() == []
    assert wiring.outputs("review")["approved"].label() == "список Data<checked_task>"


def find(nodes: list, node_id: str) -> dict:
    for item in nodes:
        if item["id"] == node_id:
            return item
        if item["type"] == "for_each":
            try:
                return find(item["body"]["nodes"], node_id)
            except KeyError:
                pass
    raise KeyError(node_id)


def bind(node_id: str, port: str, ref):
    return lambda p: find(p["nodes"], node_id)["inputs"].__setitem__(port, ref)


def move(source: str, when: str, target: str):
    return lambda p: p["transitions"].append({"from": source, "when": when, "to": target})


def add_switch(body_of: str, value: str, field: str):
    """Добавляет развилку `probe` в тело указанного «для каждого»."""
    probe = {"id": "probe", "type": "switch", "value": value, "field": field}
    return lambda p: find(p["nodes"], body_of)["body"]["nodes"].append(probe)


def two_reviews_feed_each_other(p):
    again = {"id": "review_again", "type": "block", "block": "approval.review_table"}
    p["nodes"].append({**again, "inputs": {"items": "review.approved"}})
    find(p["nodes"], "review")["inputs"]["items"] = "review_again.approved"


def collect_a_list(p):
    each = find(p["nodes"], "each_task")
    each.pop("as")
    each["collect"] = "make_tasks.result"


S1, S2, S3, S4 = SCENARIOS

# Сценарий, что испортить, на каком узле ошибка, её код, что должно быть в сообщении.
BROKEN = [
    (
        "ответ подан во вход «задача»",
        S1,
        bind("show", "task", "recognize.answer"),
        ("show", "incompatible", "вход «task» ждёт Task, а «recognize.answer» выдаёт Answer"),
    ),
    (
        "один из нескольких источников не подходит",
        S1,
        bind("check_exact", "answer", ["show.answer", "tutor.hint"]),
        ("check_exact", "incompatible", "вход «answer» ждёт Answer, а «tutor.hint» выдаёт Hint"),
    ),
    (
        "обязательный вход не привязан",
        S1,
        lambda p: find(p["nodes"], "check_exact")["inputs"].pop("answer"),
        ("check_exact", "missing_input", "обязательный вход «answer» ни к чему не привязан"),
    ),
    (
        "блока нет среди манифестов",
        S1,
        lambda p: find(p["nodes"], "check_exact").update(block="check.magic"),
        ("check_exact", "unknown_block", "блок «check.magic» не найден"),
    ),
    (
        "привязан вход, которого у блока нет",
        S1,
        bind("show", "teacher", "take_task.task"),
        ("show", "unknown_input", "у блока «student.show_task» нет входа «teacher»"),
    ),
    (
        "ссылка на выход, которого нет",
        S1,
        bind("show", "task", "take_task.problem"),
        ("show", "unknown_port", "у узла нет выхода «problem»"),
    ),
    (
        "ссылка на узел, которого нет",
        S1,
        bind("show", "task", "bank.task"),
        ("show", "unknown_ref", "узла «bank» нет"),
    ),
    (
        "переход по исходу, которого у блока нет",
        S1,
        move("check_exact", "almost", "tutor"),
        ("check_exact", "unknown_outcome", "бывают только: correct, wrong"),
    ),
    (
        "развилка по полю, которого нет у задачи",
        S1,
        lambda p: find(p["nodes"], "by_method").update(field="colour"),
        ("by_method", "unknown_field", "у типа Task нет поля «colour»"),
    ),
    (
        "развилка: переход по значению, которого не бывает",
        S1,
        move("by_method", "essay", "check_rubric"),
        ("by_method", "unknown_outcome", "бывают только: code, long_answer, short_answer"),
    ),
    (
        "«для каждого» перебирает не список",
        S2,
        lambda p: find(p["nodes"], "each_work").update(over="start.event"),
        ("each_work", "not_a_list", "«start.event» выдаёт Event"),
    ),
    (
        "снаружи читается узел из тела «для каждого»",
        S2,
        bind("review", "items", "check_text.verdict"),
        ("review", "out_of_scope", "узел «check_text» находится внутри «для каждого»"),
    ),
    (
        "текущий элемент читается снаружи тела",
        S2,
        bind("review", "items", "each_work.item"),
        ("review", "out_of_scope", "`item` доступен только внутри тела «each_work»"),
    ),
    (
        "в поле записи собраны значения разных типов",
        S2,
        lambda p: find(p["nodes"], "each_work")["collect"].update(
            verdict=["check_text.verdict", "extract.text"]
        ),
        ("each_work", "mixed_types", "«check_text.verdict» — Verdict, «extract.text» — Text"),
    ),
    (
        "развилка по виду файла: значения «архив» не бывает",
        S2,
        lambda p: find(p["nodes"], "each_work")["body"]["transitions"].append(
            {"from": "by_kind", "when": "archive", "to": "extract"}
        ),
        ("by_kind", "unknown_outcome", "бывают только: code, document, image, other"),
    ),
    (
        "у записи нет такого поля",
        S2,
        bind("to_moodle", "work", "each_approved.item.student"),
        ("to_moodle", "unknown_field", "Data<graded_work> без поля «student»"),
    ),
    (
        "поле записи не того типа",
        S2,
        bind("to_moodle", "work", "each_approved.item.verdict"),
        ("to_moodle", "incompatible", "вход «work» ждёт File"),
    ),
    (
        "запись целиком подана во вход «задача»",
        S3,
        bind("to_bank", "task", "each_approved.item"),
        ("to_bank", "incompatible", "ждёт Task, а «each_approved.item» выдаёт Data<checked_task>"),
    ),
    (
        "одно значение подано во вход-список",
        S3,
        bind("export", "content", "summarize.result"),
        ("export", "incompatible", "ждёт список Data, а «summarize.result» выдаёт Data<summary>"),
    ),
    (
        "список подан во вход «один элемент»",
        S3,
        bind("verify", "task", "make_tasks.result"),
        ("verify", "incompatible", "ждёт Task, а «make_tasks.result» выдаёт список Task"),
    ),
    (
        "тип результата ИИ-обработки задан параметром",
        S3,
        lambda p: find(p["nodes"], "make_tasks")["config"].update(
            result={"$param": "lecture_file"}
        ),
        ("make_tasks", "bad_config_type", "должен быть записан тип результата"),
    ),
    (
        "развилка по полю, которого нет у записи",
        S2,
        add_switch("each_approved", "each_approved.item", "student"),
        ("probe", "unknown_field", "у записи «graded_work» нет поля «student»"),
    ),
    (
        "развилка смотрит на список",
        S3,
        add_switch("each_task", "make_tasks.result", "id"),
        ("probe", "not_a_value", "развилка смотрит на одно значение, а не на список Task"),
    ),
    (
        "с каждого элемента собирается список",
        S3,
        collect_a_list,
        ("each_task", "nested_list", "собрать можно значение, но не список"),
    ),
    (
        "тип выхода зависит сам от себя",
        S2,
        two_reviews_feed_each_other,
        ("review_again", "type_cycle", "тип выхода зависит сам от себя"),
    ),
    (
        "запись названа так же, как данные блока",
        S4,
        lambda p: find(p["nodes"], "each_student").update({"as": "student_result"}),
        ("each_student", "record_name_taken", "название записи «student_result» занято"),
    ),
    (
        "запись названа так же, как результат ИИ-обработки",
        S4,
        lambda p: find(p["nodes"], "each_student").update({"as": "digest"}),
        ("each_student", "record_name_taken", "данные блока «ai_process.generate»"),
    ),
    (
        "переход по исходу, которого нет у Подтверждения",
        S4,
        move("review", "maybe", "to_teacher"),
        ("review", "unknown_outcome", "бывают только: approved, rejected"),
    ),
]


@pytest.mark.parametrize(
    ("title", "name", "change", "expected"), BROKEN, ids=[case[0] for case in BROKEN]
)
def test_broken_wiring_is_caught(title, name, change, expected, manifests):
    data = scenario(name)
    change(data)
    problems = check_wiring(parse_pipeline(data), manifests)
    node, code, message = expected
    found = [p for p in problems if p.node == node and p.code == code and message in p.message]
    assert found, [f"{p.code}: {p}" for p in problems]
    assert str(found[0]).startswith(f"узел «{node}»: ")
