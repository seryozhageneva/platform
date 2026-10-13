"""Привязки входов: несколько ссылок на выбор и поле записи.

Несколько ссылок нужны там, где ветки сходятся: ответ пришёл либо из формы, либо после
распознавания фото. Берётся значение, записанное последним (ADR 0009).
"""

import pytest

from backend.core.contracts.run import Done
from backend.core.contracts.state import RunStatus


def text(node_id: str, value: str, **more) -> dict:
    return {
        "id": node_id,
        "type": "block",
        "block": "source.fake_text",
        "config": {"text": value},
        **more,
    }


KEEP = {
    "id": "keep",
    "type": "block",
    "block": "sink.fake_keep",
    "inputs": {"text": ["form.text", "photo.text"]},
}


@pytest.mark.parametrize(
    ("order", "taken"),
    [(["form", "photo"], "с фото"), (["photo", "form"], "из формы")],
    ids=["photo_is_later", "form_is_later"],
)
def test_the_value_written_last_is_taken(go, graph, order, taken):
    first, second = order
    nodes = {"form": text("form", "из формы"), "photo": text("photo", "с фото")}
    pipeline = graph(
        [nodes[first], nodes[second], KEEP], [(first, None, second), (second, None, "keep")]
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    assert state.ports["keep"]["report"]["text"] == taken


def test_reference_without_data_is_skipped(go, graph):
    # Узел `photo` не выполнялся: из двух ссылок данные есть только по одной.
    pipeline = graph(
        [text("form", "из формы"), text("photo", "с фото"), KEEP], [("form", None, "keep")]
    )

    state = go.start(pipeline)

    assert state.status is RunStatus.DONE
    assert state.ports["keep"]["report"]["text"] == "из формы"


def test_output_written_again_becomes_the_latest(go, graph, called):
    """В цикле `form` выполняется второй раз, уже после `photo`, — и снова самый свежий."""
    pipeline = graph(
        [
            text("form", "из формы"),
            text("photo", "с фото", limit={"max": 1, "otherwise": "keep"}),
            KEEP,
        ],
        [("form", None, "photo"), ("photo", None, "form")],
    )

    state = go.start(pipeline)

    assert called() == ["form", "photo", "form", "keep"]
    assert state.write_order[-3:] == ["photo.text", "form.text", "keep.report"]
    assert state.ports["keep"]["report"]["text"] == "из формы"


@pytest.fixture
def pair(add_block):
    """Блок с выходом-записью из двух полей."""

    async def make_pair(inputs, config, context):
        return Done(outputs={"pair": {"first": {"text": "первое"}, "second": {"text": "второе"}}})

    add_block(
        "source.fake_pair",
        make_pair,
        outputs=[{"name": "pair", "title": "Пара", "type": "Data", "of": "pair"}],
    )
    return {"id": "make", "type": "block", "block": "source.fake_pair"}


def test_field_of_a_record_is_read(go, graph, pair):
    upper = {
        "id": "upper",
        "type": "block",
        "block": "transform.fake_upper",
        "inputs": {"text": "make.pair.second"},
    }

    state = go.start(graph([pair, upper], [("make", None, "upper")]))

    assert state.status is RunStatus.DONE
    assert state.ports["upper"]["text"] == {"text": "ВТОРОЕ"}


def test_missing_field_of_a_record_is_no_data(go, graph, pair):
    upper = {
        "id": "upper",
        "type": "block",
        "block": "transform.fake_upper",
        "inputs": {"text": "make.pair.third"},
    }

    state = go.start(graph([pair, upper], [("make", None, "upper")]))

    assert state.status is RunStatus.ERROR
    assert state.error == "узел «upper»: обязательный вход остался без данных: text"
