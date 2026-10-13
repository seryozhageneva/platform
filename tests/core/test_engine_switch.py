"""Развилка: узел, исход которого — значение поля у данных.

Пример из сценария 2: что сдано — документ или код — записано в самом файле работы, и
развилка читает его поле `kind`.
"""

import pytest

from backend.core.contracts.run import Done
from backend.core.contracts.state import RunStatus
from backend.core.contracts.wiring import check_wiring

FILE_OUT = {"name": "file", "title": "Файл", "type": "File"}
VERDICT_OUT = {"name": "verdict", "title": "Вердикт", "type": "Verdict"}


def leaf(node_id: str) -> dict:
    """Узел-лист: по тому, вызван ли он, видно, куда свернула развилка."""
    return {"id": node_id, "type": "block", "block": "source.fake_text", "config": {"text": "а"}}


@pytest.fixture
def by_kind(graph, add_block):
    """Пайплайн «взять файл → развилка по виду файла → одна из веток»."""

    async def get_file(inputs, config, context):
        file = {"id": "f1", "name": "работа", "kind": config["kind"], "media_type": "text/plain"}
        return Done(outputs={"file": file})

    add_block("source.fake_file", get_file, outputs=[FILE_OUT])

    def build(kind: str, transitions: list[tuple]):
        return graph(
            [
                {
                    "id": "get",
                    "type": "block",
                    "block": "source.fake_file",
                    "config": {"kind": kind},
                },
                {"id": "by_kind", "type": "switch", "value": "get.file", "field": "kind"},
                leaf("as_document"),
                leaf("as_code"),
                leaf("other"),
            ],
            [("get", None, "by_kind"), *transitions],
        )

    return build


BRANCHES = [("by_kind", "document", "as_document"), ("by_kind", "code", "as_code")]


@pytest.mark.parametrize(("kind", "branch"), [("document", "as_document"), ("code", "as_code")])
def test_switch_goes_by_the_value_of_a_field(go, by_kind, blocks, called, kind, branch):
    pipeline = by_kind(kind, BRANCHES)
    manifests = {name: block.manifest for name, block in blocks.items()}
    assert check_wiring(pipeline, manifests) == []

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    assert called() == ["get", branch]
    # Развилка — обычный шаг: её исход виден в журнале, своих выходов у неё нет.
    assert ("by_kind", "node_done", {"outcome": kind}) in go.store.journal
    assert "by_kind" not in state.ports


def test_value_without_its_own_transition_goes_by_the_any_outcome_transition(go, by_kind, called):
    state = go.start(by_kind("image", [*BRANCHES, ("by_kind", None, "other")]))

    assert state.status is RunStatus.DONE
    assert called() == ["get", "other"]


def test_value_without_any_transition_ends_the_branch(go, by_kind, called):
    state = go.start(by_kind("image", BRANCHES))

    assert state.status is RunStatus.DONE
    assert called() == ["get"]


@pytest.mark.parametrize(("correct", "branch"), [(True, "right"), (False, "wrong")])
def test_yes_or_no_field_gives_true_or_false(go, graph, add_block, called, correct, branch):
    async def check(inputs, config, context):
        return Done(outputs={"verdict": {"correct": correct}})

    add_block("check.fake_verdict", check, outputs=[VERDICT_OUT])
    pipeline = graph(
        [
            {"id": "check", "type": "block", "block": "check.fake_verdict"},
            {"id": "is_correct", "type": "switch", "value": "check.verdict", "field": "correct"},
            leaf("right"),
            leaf("wrong"),
        ],
        [
            ("check", None, "is_correct"),
            ("is_correct", "true", "right"),
            ("is_correct", "false", "wrong"),
        ],
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    assert called() == ["check", branch]


def test_switch_without_data_stops_the_run(go, graph, called):
    # Развилка стоит первой: узел `make`, на который она смотрит, ещё не выполнялся.
    pipeline = graph(
        [
            {"id": "by_text", "type": "switch", "value": "make.text", "field": "text"},
            {**leaf("make")},
        ],
        [("by_text", None, "make")],
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.ERROR
    assert state.error == "узел «by_text»: развилка: по ссылке «make.text» нет данных"
    assert state.current == ["by_text"] and called() == []


def test_switch_on_an_empty_field_stops_the_run(go, graph, add_block, called):
    async def check(inputs, config, context):
        return Done(outputs={"verdict": {"correct": True}})

    add_block("check.fake_verdict", check, outputs=[VERDICT_OUT])
    # Комментария в вердикте нет: по пустому полю выбрать ветку нельзя.
    pipeline = graph(
        [
            {"id": "check", "type": "block", "block": "check.fake_verdict"},
            {"id": "by_comment", "type": "switch", "value": "check.verdict", "field": "comment"},
            leaf("next"),
        ],
        [("check", None, "by_comment"), ("by_comment", None, "next")],
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.ERROR
    assert state.error == (
        "узел «by_comment»: развилка: у данных «check.verdict» нет значения в поле «comment»"
    )
    assert called() == ["check"]
