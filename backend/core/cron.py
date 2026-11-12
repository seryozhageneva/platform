"""Запись cron из пяти полей для расписаний по московскому времени."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from cronsim import CronSim, CronSimError

MOSCOW = ZoneInfo("Europe/Moscow")


def _parse(expression: str, start: datetime) -> CronSim:
    if len(expression) > 128 or len(expression.split()) != 5:
        raise CronSimError("ожидаются пять полей")
    return CronSim(expression, start)


def matches_cron(expression: str, minute: datetime) -> bool:
    local = minute.astimezone(MOSCOW)
    return next(_parse(expression, local - timedelta(minutes=1)), None) == local


def valid_cron(expression: str) -> bool:
    try:
        _parse(expression, datetime(2000, 1, 1, tzinfo=UTC))
    except CronSimError:
        return False
    return True
