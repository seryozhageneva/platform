"""«Для каждого»: тело выполняется отдельно для каждого элемента списка.

Элементы идут по очереди (ADR 0010). Перед каждым элементом тело очищается, текущий элемент
лежит на выходе `item`, а то, что названо в `collect`, собирается в выход `results`.
"""

import asyncio

import pytest

from backend.core.contracts.run import Done
from backend.core.contracts.state import RunStatus
from backend.core.contracts.wiring import check_wiring

FILE_IN = {"name": "file", "title": "Файл", "type": "File"}
TEXT = {"name": "text", "title": "Текст", "type": "Text"}
VERDICT_OUT = {"name": "verdict", "title": "Вердикт", "type": "Verdict"}

READ = {
    "id": "read",
    "type": "block",
    "block": "transform.fake_read",
    "inputs": {"file": "each.item"},
}
GRADE = {
    "id": "grade",
    "type": "block",
    "block": "check.fake_grade",
    "inputs": {"text": "read.text"},
}
COUNT = {
    "id": "count",
    "type": "block",
    "block": "sink.fake_count",
    "inputs": {"items": "each.results"},
}


@pytest.fixture(autouse=True)
def work_blocks(add_block):
    """Фейковые блоки проверки работ: прочитать файл, оценить текст, посчитать список."""
    broken = {"on": False}

    async def read(inputs, config, context):
        name = inputs["file"]["name"]
        if name.startswith("bad"):
            return Done(outcome="unreadable")
        return Done(outputs={"text": {"text": f"текст {name}"}})

    async def code(inputs, config, context):
        return Done(outputs={"text": {"text": f"код {inputs['file']['name']}"}})

    async def grade(inputs, config, context):
        if broken["on"]:
            raise RuntimeError("модель недоступна")
        return Done(outputs={"verdict": {"correct": True, "comment": inputs["text"]["text"]}})

    async def count(inputs, config, context):
        return Done(outputs={"report": {"count": len(inputs["items"])}})

    add_block(
        "transform.fake_read",
        read,
        inputs=[FILE_IN],
        outputs=[TEXT],
        outcomes=["ok", "unreadable"],
    )
    add_block("transform.fake_code", code, inputs=[FILE_IN], outputs=[TEXT])
    add_block("check.fake_grade", grade, inputs=[TEXT], outputs=[VERDICT_OUT])
    add_block(
        "sink.fake_count",
        count,
        inputs=[{"name": "items", "title": "Список", "type": "Data", "list": True}],
        outputs=[{"name": "report", "title": "Отчёт", "type": "Data", "of": "report"}],
    )
    return broken


def each(body: dict, **more) -> dict:
    return {"id": "each", "type": "for_each", "over": "get.files", "body": body, **more}


def fits_the_contract(pipeline, blocks) -> bool:
    manifests = {name: block.manifest for name, block in blocks.items()}
    return check_wiring(pipeline, manifests) == []


def test_body_runs_once_for_every_item_in_order(go, graph, files, for_each_body, blocks, calls):
    pipeline = graph(
        [
            files("a.txt", "b.txt", "c.txt"),
            each(for_each_body("read", [READ]), collect="read.text"),
            COUNT,
        ],
        [("get", None, "each"), ("each", "ok", "count")],
    )
    assert fits_the_contract(pipeline, blocks)

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    assert [node for node, *_ in calls] == ["get", "read", "read", "read", "count"]
    # Каждый вызов тела получил свой элемент — в том порядке, в каком они стоят в списке.
    assert [given["file"]["name"] for node, given, *_ in calls if node == "read"] == [
        "a.txt",
        "b.txt",
        "c.txt",
    ]
    results = [{"text": "текст a.txt"}, {"text": "текст b.txt"}, {"text": "текст c.txt"}]
    # Снаружи от узла остаётся только собранное: ни `item`, ни значений тела в состоянии нет.
    assert state.ports["each"] == {"results": results}
    assert "read" not in state.ports and state.item_index == {}
    assert calls[-1][1] == {"items": results}
    assert state.ports["count"]["report"] == {"count": 3}
    assert go.journal("item_started", "item_collected") == [
        ("each", kind, {"index": index})
        for index in range(3)
        for kind in ("item_started", "item_collected")
    ]
    assert ("each", "node_done", {"outcome": "ok"}) in go.store.journal


def test_record_of_several_fields_is_collected_and_read_by_field(
    go, graph, files, for_each_body, blocks, calls, file_of
):
    """Как в сценарии 2: развилка в теле, запись из нескольких полей, второе «для каждого»."""
    by_kind = {"id": "by_kind", "type": "switch", "value": "each.item", "field": "kind"}
    code = {**READ, "id": "code", "block": "transform.fake_code"}
    grade = {**GRADE, "inputs": {"text": ["read.text", "code.text"]}}
    check_all = each(
        for_each_body(
            "by_kind",
            [by_kind, READ, code, grade],
            [
                ("by_kind", "document", "read"),
                ("by_kind", "code", "code"),
                ("read", "ok", "grade"),
                ("code", None, "grade"),
            ],
        ),
        collect={
            "work": "each.item",
            "text": ["read.text", "code.text"],
            "verdict": "grade.verdict",
        },
        **{"as": "graded_work"},
    )
    send = {
        "id": "send",
        "type": "block",
        "block": "sink.fake_keep",
        "inputs": {"text": "each_graded.item.text"},
    }
    send_all = {
        "id": "each_graded",
        "type": "for_each",
        "over": "each.results",
        "body": for_each_body("send", [send]),
    }
    pipeline = graph(
        [files("a.txt", "b.py"), check_all, send_all],
        [("get", None, "each"), ("each", "ok", "each_graded")],
    )
    assert fits_the_contract(pipeline, blocks)

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    assert [node for node, *_ in calls] == ["get", "read", "grade", "code", "grade", "send", "send"]
    assert state.ports["each"]["results"] == [
        {
            "work": file_of("a.txt"),
            "text": {"text": "текст a.txt"},
            "verdict": {"correct": True, "comment": "текст a.txt"},
        },
        # У второй работы своя ветка: в запись попал её текст, а не оставшийся от первой.
        {
            "work": file_of("b.py"),
            "text": {"text": "код b.py"},
            "verdict": {"correct": True, "comment": "код b.py"},
        },
    ]
    assert [given["text"]["text"] for node, given, *_ in calls if node == "send"] == [
        "текст a.txt",
        "код b.py",
    ]
    # Второе «для каждого» ничего не собирает: выхода `results` у него нет.
    assert "each_graded" not in state.ports


def test_empty_list_gives_the_outcome_empty(go, graph, files, for_each_body, called):
    nothing = {
        "id": "nothing",
        "type": "block",
        "block": "source.fake_text",
        "config": {"text": "—"},
    }
    pipeline = graph(
        [files(), each(for_each_body("read", [READ]), collect="read.text"), COUNT, nothing],
        [("get", None, "each"), ("each", "ok", "count"), ("each", "empty", "nothing")],
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    assert called() == ["get", "nothing"]
    assert state.ports["each"] == {"results": []}


def test_item_whose_branch_did_not_finish_is_not_collected(go, graph, files, for_each_body):
    pipeline = graph(
        [
            files("a.txt", "bad.txt", "c.txt"),
            each(
                for_each_body("read", [READ, GRADE], [("read", "ok", "grade")]),
                collect={"work": "each.item", "verdict": "grade.verdict"},
                **{"as": "graded_work"},
            ),
        ],
        [("get", None, "each")],
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    # Второй файл не прочитан: до оценки его ветка не дошла. Вердикт первой работы,
    # оставшийся бы от прошлого элемента, ему не достался — тело очищается.
    assert [record["work"]["name"] for record in state.ports["each"]["results"]] == [
        "a.txt",
        "c.txt",
    ]
    assert [record["verdict"]["comment"] for record in state.ports["each"]["results"]] == [
        "текст a.txt",
        "текст c.txt",
    ]
    assert go.journal("item_skipped") == [
        ("each", "item_skipped", {"index": 1, "missing": ["verdict"]})
    ]


@pytest.fixture
def two_works(graph, files, for_each_body):
    """Две работы; в теле два узла: прочитать и оценить."""
    return graph(
        [
            files("a.txt", "b.txt"),
            each(
                for_each_body("read", [READ, GRADE], [("read", "ok", "grade")]),
                collect="grade.verdict",
            ),
        ],
        [("get", None, "each")],
    )


def test_state_is_saved_after_every_node_of_the_body(go, two_works):
    go.start(two_works)

    assert [(saved.current, saved.item_index) for saved in go.store.saved] == [
        (["get"], {}),
        (["each"], {}),
        (["read"], {"each": 0}),
        (["grade"], {"each": 0}),
        (["read"], {"each": 1}),
        (["grade"], {"each": 1}),
        ([], {}),
    ]
    # Собранное копится по мере прохода списка.
    assert [len(saved.ports.get("each", {}).get("results", [])) for saved in go.store.saved] == [
        0,
        0,
        0,
        0,
        1,
        1,
        2,
    ]


def test_run_continues_from_the_same_item_after_a_server_restart(go, two_works, called, file_of):
    first = {"correct": True, "comment": "текст a.txt"}
    go.interrupted(
        current=["grade"],
        item_index={"each": 1},
        ports={
            "get": {"files": [file_of("a.txt"), file_of("b.txt")]},
            "each": {"results": [first], "item": file_of("b.txt")},
            "read": {"text": {"text": "текст b.txt"}},
        },
        write_order=["get.files", "each.results", "each.item", "read.text"],
    )

    state = go.resume(two_works)

    assert state.status is RunStatus.DONE
    # Первая работа второй раз не проверялась, у второй вызван только оставшийся узел.
    assert called() == ["grade"]
    assert state.ports["each"]["results"] == [first, {"correct": True, "comment": "текст b.txt"}]


def test_failure_inside_the_body_stops_the_run_on_that_item(
    go, two_works, work_blocks, calls, file_of
):
    work_blocks["on"] = True
    failed = go.start(two_works)

    assert failed.status is RunStatus.ERROR
    assert failed.error.startswith("узел «grade»: блок «check.fake_grade» упал")
    assert failed.current == ["grade"] and failed.item_index == {"each": 0}
    assert failed.ports["each"] == {"results": [], "item": file_of("a.txt")}

    work_blocks["on"] = False
    calls.clear()
    state = go.resume(two_works)

    assert state.status is RunStatus.DONE
    assert [node for node, *_ in calls] == ["grade", "read", "grade"]
    assert len(state.ports["each"]["results"]) == 2


def test_pause_inside_the_body(go, graph, files, for_each_body, ask, answer_with):
    question = {"id": "ask", "type": "block", "block": "student.fake_ask"}
    pipeline = graph(
        [files("a.txt", "b.txt"), each(for_each_body("ask", [question]), collect="ask.answer")],
        [("get", None, "each")],
    )

    state = go.start(pipeline)
    assert state.status is RunStatus.WAITING and state.item_index == {"each": 0}

    state = go.respond(pipeline, "ask", answer_with("первый"))
    # Ответ по первому элементу собран, запуск ждёт ответа по второму.
    assert state.status is RunStatus.WAITING and state.item_index == {"each": 1}
    assert [given["text"] for given in state.ports["each"]["results"]] == ["первый"]

    state = go.respond(pipeline, "ask", answer_with("второй"))
    assert state.status is RunStatus.DONE
    assert [given["text"] for given in state.ports["each"]["results"]] == ["первый", "второй"]
    assert asyncio.run(go.store.load("run-1")) == state


def test_for_each_inside_for_each(go, graph, files, for_each_body, add_block, blocks, called):
    async def split(inputs, config, context):
        name = inputs["file"]["name"]
        return Done(outputs={"parts": [{"text": f"{name}:1"}, {"text": f"{name}:2"}]})

    add_block(
        "transform.fake_split",
        split,
        inputs=[FILE_IN],
        outputs=[{**TEXT, "name": "parts", "list": True}],
    )
    upper = {
        "id": "upper",
        "type": "block",
        "block": "transform.fake_upper",
        "inputs": {"text": "each_part.item"},
    }
    parts = {
        "id": "each_part",
        "type": "for_each",
        "over": "split.parts",
        "body": for_each_body("upper", [upper]),
        "collect": "upper.text",
    }
    pipeline = graph(
        [
            files("a", "b"),
            each(
                for_each_body(
                    "split",
                    [
                        {**READ, "id": "split", "block": "transform.fake_split"},
                        parts,
                        {**COUNT, "inputs": {"items": "each_part.results"}},
                    ],
                    [("split", None, "each_part"), ("each_part", "ok", "count")],
                ),
                collect="count.report",
            ),
        ],
        [("get", None, "each")],
    )
    assert fits_the_contract(pipeline, blocks)

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    assert called() == ["get", *["split", "upper", "upper", "count"] * 2]
    assert state.ports["each"] == {"results": [{"count": 2}, {"count": 2}]}
    # От вложенного «для каждого» в состоянии ничего не осталось.
    assert sorted(state.ports) == ["each", "get", "start"]
    assert state.item_index == {} and state.write_order == [
        "start.event",
        "get.files",
        "each.results",
    ]


def test_limit_inside_the_body_counts_for_each_item(go, graph, files, for_each_body, called):
    again = {**READ, "limit": {"max": 2}}
    pipeline = graph(
        [files("a.txt", "b.txt"), each(for_each_body("read", [again], [("read", None, "read")]))],
        [("get", None, "each")],
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    # По два прохода на каждую работу: счётчик тела обнуляется перед каждым элементом.
    assert called() == ["get", "read", "read", "read", "read"]
    assert state.counters == {}


def test_for_each_over_something_that_is_not_a_list_stops_the_run(go, graph, for_each_body, called):
    make = {"id": "get", "type": "block", "block": "source.fake_text", "config": {"text": "а"}}
    pipeline = graph(
        [make, {**each(for_each_body("read", [READ])), "over": "get.text"}],
        [("get", None, "each")],
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.ERROR
    assert state.error == "узел «each»: «для каждого»: по ссылке «get.text» нет списка"
    assert called() == ["get"]
