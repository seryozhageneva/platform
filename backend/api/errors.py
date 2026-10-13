"""Отказ API: код ответа, текст по-русски и список причин."""

from backend.core.contracts.wiring import Problem


class ApiError(Exception):
    def __init__(self, status: int, message: str, problems: list[Problem] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.problems = problems or []
