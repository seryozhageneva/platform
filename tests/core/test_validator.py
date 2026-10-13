"""Валидатор: четыре сценария проходят, а сломанные пайплайны отклоняются с понятной ошибкой.

Сломанный пайплайн — настоящий сценарий из `docs/examples/pipelines/`, испорченный в одном
месте. Мелкие случаи (тело «для каждого», взаимное обнуление счётчиков) собраны из фейковых
блоков. Модели и базы здесь нет.
"""

import pytest

from backend.core.contracts.manifest import ToolRef
from backend.core.contracts.pipeline import Param, parse_pipeline
from backend.core.validator import Report, config_problems, validate

# --- Сценарии из примеров ------------------------------------------------------------------


@pytest.mark.parametrize("number", [1, 2, 3, 4])
def test_scenario_has_no_errors(number, scenario, example_manifests):
    report = validate(parse_pipeline(scenario(number)), example_manifests)
    assert [str(problem) for problem in report.errors] == []
    assert report.ok


def test_only_scenario_1_sends_without_approval(scenario, example_manifests):
    """Итог урока уходит ученику в Telegram без Подтверждения — это предупреждение."""
    warnings = {
        number: validate(parse_pipeline(scenario(number)), example_manifests).warnings
        for number in (1, 2, 3, 4)
    }
    assert [(w.node, w.code) for w in warnings[1]] == [("to_telegram", "no_approval")]
    assert "минуя Подтверждение преподавателя" in warnings[1][0].message
    assert warnings[2] == warnings[3] == warnings[4] == []


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


def drop_move(source: str, target: str):
    def change(p, manifests):
        p["transitions"] = [
            move for move in p["transitions"] if (move["from"], move["to"]) != (source, target)
        ]

    return change


def set_limit(node_id: str, **fields):
    return lambda p, manifests: find(p["nodes"], node_id)["limit"].update(fields)


def set_config(node_id: str, **fields):
    return lambda p, manifests: find(p["nodes"], node_id)["config"].update(fields)


def bind(node_id: str, port: str, ref):
    return lambda p, manifests: find(p["nodes"], node_id)["inputs"].__setitem__(port, ref)


def let_agent_send_email(p, manifests):
    agent = manifests["ai_process.generate"]
    tools = [*agent.tools, ToolRef(server="email", tool="send_email")]
    manifests["ai_process.generate"] = agent.model_copy(update={"tools": tools})


# Что испортить, в каком сценарии, как; на каком узле ошибка, её код, что есть в сообщении.
BROKEN = [
    (
        "в узел не ведёт ни один переход",
        3,
        drop_move("summarize", "save_summary"),
        ("save_summary", "unreachable", "нельзя дойти от старта: в него не ведёт ни один переход"),
    ),
    (
        "у тьютора снят ограничитель",
        1,
        lambda p, manifests: find(p["nodes"], "tutor").pop("limit"),
        (
            "show",
            "unbounded_loop",
            "круг show → tutor → show может повторяться без конца: "
            "ни у одного узла в нём нет ограничителя",
        ),
    ),
    (
        "ограничитель тьютора обнуляется внутри своего круга",
        1,
        set_limit("tutor", reset_on="show"),
        (
            "show",
            "unbounded_loop",
            "счётчик ограничителя узла «tutor» обнуляется на узле «show», "
            "а он стоит в этом же круге",
        ),
    ),
    (
        "круг из переходов «попытки кончились»",
        1,
        set_limit("take_task", otherwise="tutor"),
        (
            "take_task",
            "unbounded_loop",
            "круг take_task → tutor → take_task может повторяться без конца: "
            "когда попытки у «take_task», «tutor» кончаются",
        ),
    ),
    (
        "обязательный вход читает узел, который идёт позже",
        3,
        bind("summarize", "data", "make_tasks.result"),
        (
            "summarize",
            "never_written",
            "обязательный вход «data» читает «make_tasks.result», "
            "но узел «make_tasks» не выполняется раньше этого узла",
        ),
    ),
    (
        "сложность задана словом вместо числа",
        1,
        set_config("take_task", difficulty="высокая"),
        ("take_task", "bad_config", "настройка «difficulty»: нужно целое число"),
    ),
    (
        "не заполнена обязательная настройка",
        3,
        lambda p, manifests: find(p["nodes"], "summarize")["config"].pop("prompt"),
        ("summarize", "bad_config", "не заполнена обязательная настройка «prompt»"),
    ),
    (
        "в числовую настройку подставлен текстовый параметр",
        1,
        set_config("take_task", difficulty={"$param": "topic"}),
        (
            "take_task",
            "bad_config",
            "настройка «difficulty»: сюда подставляется параметр «topic» (текст), "
            "а нужно: целое число",
        ),
    ),
    (
        "агенту разрешён инструмент отправки письма",
        4,
        let_agent_send_email,
        (
            "analyze",
            "tool_with_side_effects",
            "агенту разрешён инструмент «email.send_email», а он действует во внешнем мире: "
            "им пользуется блок «sink.email»",
        ),
    ),
    (
        "ошибка стыковки: ответ подан во вход «задача»",
        1,
        bind("show", "task", "recognize.answer"),
        ("show", "incompatible", "вход «task» ждёт Task, а «recognize.answer» выдаёт Answer"),
    ),
]


@pytest.mark.parametrize(
    ("title", "number", "change", "expected"), BROKEN, ids=[case[0] for case in BROKEN]
)
def test_broken_pipeline_is_rejected(title, number, change, expected, scenario, example_manifests):
    data = scenario(number)
    change(data, example_manifests)
    report = validate(parse_pipeline(data), example_manifests)
    node, code, message = expected
    found = [p for p in report.errors if p.node == node and p.code == code and message in p.message]
    assert not report.ok
    assert found, [f"{p.code}: {p}" for p in report.errors]
    assert str(found[0]).startswith(f"узел «{node}»: ")


def test_bypassing_approval_is_a_warning_not_an_error(scenario, example_manifests):
    """Пустой список работ ведёт мимо Подтверждения прямо к выставлению оценок."""
    data = scenario(2)
    data["transitions"].append({"from": "each_work", "when": "empty", "to": "each_approved"})
    report = validate(parse_pipeline(data), example_manifests)
    assert report.ok and report.errors == []
    assert [(w.node, w.code) for w in report.warnings] == [
        ("to_moodle", "no_approval"),
        ("to_email", "no_approval"),
    ]
    assert "блок «sink.moodle_grades» действует во внешнем мире" in report.warnings[0].message


# --- Мелкие случаи на фейковых блоках ------------------------------------------------------


def block(node_id: str, block_id: str = "source.fake_text", **fields) -> dict:
    return {"id": node_id, "type": "block", "block": block_id, **fields}


@pytest.fixture
def check(blocks, graph):
    """Проверяет пайплайн из фейковых блоков; возвращает отчёт."""

    def run(nodes, transitions=(), **manifests) -> Report:
        known = {name: loaded.manifest for name, loaded in blocks.items()} | manifests
        return validate(graph(nodes, transitions), known)

    return run


def codes(report: Report) -> list[tuple[str, str]]:
    return [(problem.node, problem.code) for problem in report.errors]


def test_optional_input_may_read_a_node_that_runs_later(check, manifest_for):
    """Подсказки при первом показе задачи ещё нет — это не ошибка."""
    text = {"name": "text", "title": "Текст", "type": "Text"}
    optional = manifest_for(
        "transform.fake_optional", inputs=[{**text, "required": False}], outputs=[text]
    )
    nodes = [
        block("first", "transform.fake_optional", inputs={"text": "second.text"}),
        block("second"),
    ]
    assert check(nodes, [("first", None, "second")], **{optional.id: optional}).errors == []

    nodes[0] = block("first", "transform.fake_upper", inputs={"text": "second.text"})
    assert codes(check(nodes, [("first", None, "second")])) == [("first", "never_written")]


def test_several_sources_and_none_runs_before(check):
    nodes = [
        block("first", "transform.fake_upper", inputs={"text": ["second.text", "third.text"]}),
        block("second"),
        block("third"),
    ]
    report = check(nodes, [("first", None, "second"), ("second", None, "third")])
    assert codes(report) == [("first", "never_written")]
    assert "ни один из узлов «second», «third» не выполняется раньше" in report.errors[0].message


def test_node_in_a_loop_may_read_its_own_previous_output(check):
    nodes = [
        block("again", "transform.fake_upper", inputs={"text": "again.text"}, limit={"max": 3})
    ]
    assert check(nodes, [("again", None, "again")]).errors == []
    # Без круга «прошлого раза» у узла не бывает.
    assert codes(check(nodes)) == [("again", "never_written")]


def test_body_of_for_each_is_checked_like_a_small_graph(check, files, for_each_body):
    def each(body: dict) -> dict:
        return {"id": "each", "type": "for_each", "over": "get.files", "body": body}

    def run(body: dict) -> Report:
        nodes = [files("a.txt"), each(body), block("later")]
        return check(nodes, [("get", None, "each"), ("each", None, "later")])

    lost = run(for_each_body("a", [block("a"), block("b")]))
    assert codes(lost) == [("b", "unreachable")]
    assert "нельзя дойти от первого узла тела «each»" in lost.errors[0].message

    circle = [("a", None, "b"), ("b", None, "a")]
    endless = run(for_each_body("a", [block("a"), block("b")], circle))
    assert codes(endless) == [("a", "unbounded_loop")]

    limited = run(for_each_body("a", [block("a"), block("b", limit={"max": 2})], circle))
    assert limited.errors == []

    # Счётчик обнуляется на узле снаружи тела — внутри одного элемента он не обнуляется.
    outer = {"max": 2, "reset_on": "get"}
    assert run(for_each_body("a", [block("a"), block("b", limit=outer)], circle)).errors == []

    # Узел тела читает узел, который выполняется уже после «для каждого».
    reads_later = block("a", "transform.fake_upper", inputs={"text": "later.text"})
    assert codes(run(for_each_body("a", [reads_later]))) == [("a", "never_written")]


def test_for_each_over_a_list_that_is_not_ready_yet(check, files, for_each_body):
    each = {
        "id": "each",
        "type": "for_each",
        "over": "get.files",
        "body": for_each_body("a", [block("a")]),
    }
    report = check([each, files("a.txt")], [("each", None, "get")])
    assert codes(report) == [("each", "never_written")]
    assert "«для каждого» читает «get.files»" in report.errors[0].message


def test_limiters_that_reset_each_other_do_not_stop_a_loop(check):
    """«a» обнуляет счётчик «b», а «b» — счётчик «a»: ни один не дойдёт до предела."""
    nodes = [
        block("a", limit={"max": 2, "reset_on": "b"}),
        block("b", limit={"max": 2, "reset_on": "a"}),
    ]
    report = check(nodes, [("a", None, "b"), ("b", None, "a")])
    assert codes(report) == [("a", "unbounded_loop")]
    assert "счётчик ограничителя узла «a» обнуляется на узле «b»" in report.errors[0].message

    nodes[1] = block("b", limit={"max": 2})
    assert check(nodes, [("a", None, "b"), ("b", None, "a")]).errors == []


def test_limiter_that_resets_itself_does_not_stop_a_loop(check):
    nodes = [block("a", limit={"max": 2, "reset_on": "a"})]
    assert codes(check(nodes, [("a", None, "a")])) == [("a", "unbounded_loop")]


def test_two_separate_endless_circles_are_reported_separately(check, manifest_for):
    fork = manifest_for("source.fake_fork", outcomes=["left", "right"])
    nodes = [
        block("fork", "source.fake_fork"),
        block("a"),
        block("b"),
        block("c"),
        block("d"),
    ]
    moves = [
        ("fork", "left", "a"),
        ("fork", "right", "c"),
        ("a", None, "b"),
        ("b", None, "a"),
        ("c", None, "d"),
        ("d", None, "c"),
    ]
    assert codes(check(nodes, moves, **{fork.id: fork})) == [
        ("a", "unbounded_loop"),
        ("c", "unbounded_loop"),
    ]


def test_approval_on_the_way_guards_a_block_with_side_effects(check, manifest_for):
    text = {"name": "text", "title": "Текст", "type": "Text"}
    send = manifest_for("sink.fake_send", inputs=[text], side_effects=True)
    review = manifest_for(
        "approval.fake_review",
        kind="approval",
        screen="review_document",
        inputs=[text],
        outputs=[text],
    )
    extra = {send.id: send, review.id: review}
    make = block("make")
    ask = block("review", "approval.fake_review", inputs={"text": "make.text"})

    guarded = [make, ask, block("send", "sink.fake_send", inputs={"text": "review.text"})]
    report = check(guarded, [("make", None, "review"), ("review", None, "send")], **extra)
    assert (report.errors, report.warnings) == ([], [])

    unguarded = [make, block("send", "sink.fake_send", inputs={"text": "make.text"})]
    report = check(unguarded, [("make", None, "send")], **extra)
    assert report.errors == []
    assert [(w.node, w.code) for w in report.warnings] == [("send", "no_approval")]


def test_approval_skipped_by_its_limit_does_not_guard(check, manifest_for):
    """Попытки Подтверждения кончились — переход «иначе» ведёт к отправке мимо него."""
    text = {"name": "text", "title": "Текст", "type": "Text"}
    send = manifest_for("sink.fake_send", inputs=[text], side_effects=True)
    review = manifest_for(
        "approval.fake_review",
        kind="approval",
        screen="review_document",
        inputs=[text],
        outputs=[text],
        outcomes=["approved", "rejected"],
    )
    extra = {send.id: send, review.id: review}
    moves = [("make", None, "review"), ("review", "rejected", "make")]

    def nodes(**limit) -> list[dict]:
        return [
            block("make"),
            block("review", "approval.fake_review", inputs={"text": "make.text"}, limit=limit),
            block("send", "sink.fake_send", inputs={"text": "make.text"}),
        ]

    report = check(
        nodes(max=2, otherwise="send"), [*moves, ("review", "approved", "send")], **extra
    )
    assert report.errors == []
    assert [(w.node, w.code) for w in report.warnings] == [("send", "no_approval")]

    # Без «иначе» круг «отклонил — переделай» просто кончается: отправки мимо нет.
    report = check(nodes(max=2), [*moves, ("review", "approved", "send")], **extra)
    assert (report.errors, report.warnings) == ([], [])


def test_otherwise_that_can_never_fire_is_not_a_circle(check):
    """В «b» нельзя вернуться, его попытки не кончатся — «иначе» не сработает."""
    nodes = [block("a"), block("b", limit={"max": 2, "otherwise": "a"})]
    assert check(nodes, [("a", None, "b")]).errors == []

    # Узел, в который ведёт только такой переход, недостижим.
    nodes = [block("a", limit={"max": 1, "otherwise": "b"}), block("b")]
    report = check(nodes)
    assert codes(report) == [("b", "unreachable")]
    assert "только переход «иначе» узла «a», а он не сработает" in report.errors[0].message

    # Счётчик обнуляется при каждом выполнении самого узла — попытки не кончаются никогда.
    nodes = [block("a", limit={"max": 1, "otherwise": "b", "reset_on": "a"}), block("b")]
    assert codes(check(nodes, [("a", None, "a")])) == [
        ("b", "unreachable"),
        ("a", "unbounded_loop"),
    ]


def test_reset_from_a_node_that_cannot_come_back_does_not_matter(check, manifest_for):
    """Два круга подряд: из второго в первый пути нет, взаимное обнуление не мешает."""
    fork = manifest_for("source.fake_fork", outcomes=["again", "next"])
    nodes = [
        block("a", "source.fake_fork", limit={"max": 1, "reset_on": "b"}),
        block("b", "source.fake_fork", limit={"max": 2, "reset_on": "a"}),
    ]
    moves = [("a", "again", "a"), ("a", "next", "b"), ("b", "again", "b")]
    assert check(nodes, moves, **{fork.id: fork}).errors == []


# --- Настройки узла по схеме блока ---------------------------------------------------------

SCHEMA = {
    "type": "object",
    "required": ["title"],
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "to": {"enum": ["teacher", "student"]},
        "days": {"type": "integer", "minimum": 1},
        "share": {"type": "number"},
        "forms": {"type": "array", "items": {"type": "string"}},
        "result": {"type": "object", "required": ["type"]},
        "tags": {"type": "array", "uniqueItems": True},
        "shape": {
            "anyOf": [
                {"type": "string"},
                {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}},
            ]
        },
    },
}
PARAMS = {
    "topic": Param(name="topic", title="Тема", type="string"),
    "count": Param(name="count", title="Сколько", type="integer"),
}


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"title": "Итог"}, []),
        ({"title": "Итог", "to": "parent"}, ["настройка «to»: значение 'parent' не из списка"]),
        ({"title": "Итог", "days": 0}, ["настройка «days»: значение 0 меньше допустимого 1"]),
        ({"title": 5}, ["настройка «title»: нужно текст, а записано 5"]),
        ({"title": "Итог", "colour": "red"}, ["настройки: у блока нет настройки «colour»"]),
        ({"title": "Итог", "result": {}}, ["настройка «result»: не заполнено обязательное поле"]),
        ({"title": "Итог", "forms": ["text", 7]}, ["настройка «forms.1»: нужно текст"]),
        # Параметр подходит по типу: значение узнаем только при назначении.
        ({"title": {"$param": "topic"}, "days": {"$param": "count"}}, []),
        ({"title": "Итог", "share": {"$param": "count"}}, []),
        ({"title": "Итог", "forms": [{"$param": "topic"}]}, []),
        (
            {"title": {"$param": "count"}},
            ["настройка «title»: сюда подставляется параметр «count» (целое число)"],
        ),
        (
            {"title": "Итог", "forms": [{"$param": "count"}]},
            ["настройка «forms.0»: сюда подставляется параметр «count»"],
        ),
        # У настройки со списком значений тип не записан — параметр сверить не с чем.
        ({"title": "Итог", "to": {"$param": "topic"}}, []),
        # Проверки, которым нужно само значение, с параметром внутри пропускаются.
        ({"title": "Итог", "tags": [{"$param": "topic"}, {"$param": "count"}]}, []),
        ({"title": "Итог", "shape": {"n": {"$param": "count"}}}, []),
        ({"title": "Итог", "tags": ["a", "a"]}, ["настройка «tags»: не подходит под схему"]),
        ({"title": "Итог", "shape": 5}, ["настройка «shape»: не подходит под схему"]),
    ],
)
def test_config_is_checked_against_block_schema(config, expected):
    problems = config_problems(config, SCHEMA, PARAMS)
    assert len(problems) == len(expected), problems
    for problem, part in zip(problems, expected, strict=True):
        assert part in problem


def test_broken_block_schema_is_a_problem_not_a_crash():
    """Ссылка в никуда в схеме настроек: манифест её принимает, а проверка — уже нет."""
    schema = {"type": "object", "properties": {"x": {"$ref": "#/$defs/missing"}}}
    (problem,) = config_problems({"x": 1}, schema, {})
    assert problem.startswith("схема настроек блока неисправна: ")
