"""Запуск по событию Moodle в графе пайплайна: частота опроса и блок-источник (ADR 0034).

Отдельный модуль, чтобы проверки знали и ручной запуск, и опрос Moodle.
"""

from backend.core.contracts.pipeline import BlockNode, Launch, Pipeline
from backend.core.contracts.ports import TriggerType
from backend.core.contracts.wiring import Problem

SOURCE_BLOCK = "source.moodle_submissions"
DEFAULT_POLL_MINUTES = 5
# Не чаще раза в минуту (так часто проверяет рабочий процесс) и не реже раза в сутки.
MIN_POLL_MINUTES, MAX_POLL_MINUTES = 1, 24 * 60


def moodle_launch(pipeline: Pipeline) -> Launch | None:
    return next(
        (
            launch
            for launch in pipeline.trigger().launches
            if launch.type is TriggerType.MOODLE_EVENT
        ),
        None,
    )


def poll_minutes(launch: Launch) -> int | None:
    """Как часто опрашивать Moodle; None — значение в графе не подходит."""
    value = launch.settings.get("poll_minutes", DEFAULT_POLL_MINUTES)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if MIN_POLL_MINUTES <= value <= MAX_POLL_MINUTES else None


def moodle_problems(pipeline: Pipeline) -> list[Problem]:
    """Что мешает запуску по событию Moodle в самом графе; пусто — можно опрашивать."""
    start = pipeline.trigger()
    launch = moodle_launch(pipeline)
    problems: list[Problem] = []
    if launch is not None and poll_minutes(launch) is None:
        problems.append(
            Problem(
                start.id,
                "bad_poll_minutes",
                f"частота опроса Moodle (poll_minutes) — целое число минут от "
                f"{MIN_POLL_MINUTES} до {MAX_POLL_MINUTES}",
            )
        )
    sources = [
        (node, path)
        for node, path in pipeline.walk()
        if isinstance(node, BlockNode) and node.block == SOURCE_BLOCK
    ]
    if len(sources) != 1 or sources[0][1]:
        problems.append(
            Problem(
                start.id,
                "moodle_source_needed",
                "для запуска по событию Moodle нужен ровно один блок «Источник: работы из "
                "Moodle» вне «для каждого»: из его настроек берутся курс и задание",
            )
        )
        return problems
    node = sources[0][0]
    binding = node.inputs.get("event")
    bound = binding if isinstance(binding, list) else [binding]
    if f"{start.id}.event" not in bound:
        problems.append(
            Problem(
                node.id,
                "moodle_event_not_bound",
                f"вход «event» блока нужно привязать к «{start.id}.event»: иначе запуск по "
                "событию возьмёт все сданные работы, а не только новые",
            )
        )
    return problems


def moodle_source(pipeline: Pipeline) -> BlockNode:
    return next(
        node
        for node, path in pipeline.walk()
        if isinstance(node, BlockNode) and node.block == SOURCE_BLOCK and not path
    )
