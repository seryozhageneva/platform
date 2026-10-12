"""Состояние запуска: порядок записи выходов (ADR 0009)."""

import pytest
from pydantic import ValidationError

from backend.core.contracts.state import RunState


def new_state(**fields) -> RunState:
    return RunState(run_id="run-1", pipeline_id="pipeline-1", pipeline_version=1, **fields)


def test_new_state_has_no_outputs_and_no_order():
    state = new_state()
    assert state.ports == {} and state.write_order == [] and state.item_index == {}


def test_written_output_becomes_the_freshest():
    state = new_state()
    state.write("show", {"answer": {"text": "8"}})
    state.write("recognize", {"answer": {"text": "3"}, "photo": {"id": "f1"}})

    assert state.ports == {
        "show": {"answer": {"text": "8"}},
        "recognize": {"answer": {"text": "3"}, "photo": {"id": "f1"}},
    }
    assert state.write_order == ["show.answer", "recognize.answer", "recognize.photo"]


def test_writing_again_moves_the_output_to_the_end():
    state = new_state()
    state.write("show", {"answer": 1})
    state.write("recognize", {"answer": 2})
    state.write("show", {"answer": 3})

    assert state.write_order == ["recognize.answer", "show.answer"]
    assert state.ports["show"] == {"answer": 3}


def test_writing_one_output_keeps_the_other_outputs_of_the_node():
    state = new_state()
    state.write("check", {"verdict": {"correct": False}, "note": "первая попытка"})
    state.write("check", {"verdict": {"correct": True}})

    assert state.ports["check"] == {"verdict": {"correct": True}, "note": "первая попытка"}
    assert state.write_order == ["check.note", "check.verdict"]


def test_latest_picks_the_reference_written_last():
    """Ответ пришёл либо из формы, либо после распознавания фото — берётся последний."""
    state = new_state()
    state.write("show", {"answer": "из формы"})
    state.write("recognize", {"answer": "с фото"})
    assert state.latest(["show.answer", "recognize.answer"]) == "recognize.answer"

    state.write("show", {"answer": "снова из формы"})
    # Порядок ссылок в привязке на выбор не влияет.
    assert state.latest(["show.answer", "recognize.answer"]) == "show.answer"
    assert state.latest(["recognize.answer", "show.answer"]) == "show.answer"


def test_latest_skips_outputs_that_were_never_written():
    state = new_state()
    assert state.latest(["show.answer", "recognize.answer"]) is None

    state.write("show", {"answer": "из формы"})
    assert state.latest(["show.answer", "recognize.answer"]) == "show.answer"
    assert state.latest(["recognize.answer", "show.photo"]) is None


def test_latest_looks_at_the_output_behind_a_field_reference():
    """Ссылка «узел.порт.поле» — это поле записи; свежесть считается по выходу «узел.порт»."""
    state = new_state()
    state.write("show", {"answer": "из формы"})
    state.write("each", {"item": {"task": {"id": "t1"}}})

    assert state.latest(["each.item.task"]) == "each.item.task"
    assert state.latest(["each.item.task", "show.answer"]) == "each.item.task"

    state.write("show", {"answer": "снова из формы"})
    assert state.latest(["each.item.task", "show.answer"]) == "show.answer"
    assert state.latest(["each.results.task"]) is None


def test_order_survives_json_even_when_the_keys_are_reordered():
    """Суть вопроса 27: база перемешивает ключи `ports`, а список порядок сохраняет."""
    state = new_state()
    state.write("zeta", {"out": 1})
    state.write("alpha", {"out": 2})
    state.write("zeta", {"out": 3})

    dumped = state.model_dump(mode="json")
    dumped["ports"] = dict(sorted(dumped["ports"].items()))
    loaded = RunState.model_validate(dumped)

    assert loaded == state
    assert list(loaded.ports) == ["alpha", "zeta"]
    assert loaded.latest(["alpha.out", "zeta.out"]) == "zeta.out"


def test_state_saved_before_the_order_existed_is_still_read():
    """В порядке записи выхода нет — он считается самым старым."""
    old = new_state(ports={"show": {"answer": 1}, "recognize": {"answer": 2}})
    assert old.write_order == []
    assert old.latest(["recognize.answer"]) == "recognize.answer"

    old.write("show", {"answer": 3})
    assert old.latest(["recognize.answer", "show.answer"]) == "show.answer"


@pytest.mark.parametrize(
    ("order", "problem"),
    [
        (["show.answer", "show.answer"], "выход повторяется в порядке записи: show.answer"),
        (["show.photo"], "в порядке записи есть выход, которого нет в `ports`: show.photo"),
        (["tutor.hint"], "в порядке записи есть выход, которого нет в `ports`: tutor.hint"),
        # В порядке записи стоят только выходы «узел.порт», без поля.
        (["show.answer.text"], "которого нет в `ports`: show.answer.text"),
    ],
    ids=["repeated", "unknown_port", "unknown_node", "field_reference"],
)
def test_order_that_disagrees_with_ports_is_rejected(order, problem):
    with pytest.raises(ValidationError, match=problem):
        new_state(ports={"show": {"answer": 1}}, write_order=order)


def test_item_index_is_kept_per_for_each_node():
    state = new_state(item_index={"each_work": 3})
    assert RunState.model_validate_json(state.model_dump_json()) == state

    with pytest.raises(ValidationError):
        new_state(item_index={"each_work": -1})
