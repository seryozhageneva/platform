"""Готовые экраны платформы для блоков, которые ждут человека.

Блок не приносит свой интерфейс: он называет один из экранов и передаёт для него данные.
У каждого экрана своя форма данных (что показать) и своя форма ответа (что человек решил).
"""

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from backend.core.contracts.base import Strict
from backend.core.contracts.ports import Answer, AnswerForm, FileRef, Hint


class ScreenType(StrEnum):
    ANSWER_FORM = "answer_form"
    CONFIRM_RECOGNIZED = "confirm_recognized"
    REVIEW_TABLE = "review_table"
    REVIEW_DOCUMENT = "review_document"


class AnswerFormData(Strict):
    """Условие задачи без ответа и эталонного решения: в браузер ученика они не попадают."""

    task_id: str
    statement: str
    forms: list[AnswerForm] = Field(min_length=1)
    hint: Hint | None = None
    can_ask_hint: bool = True


class AnswerFormResponse(Strict):
    """Свободного чата нет: ученик либо отвечает, либо просит подсказку."""

    action: Literal["answer", "hint"]
    answer: Answer | None = None

    @model_validator(mode="after")
    def _answer_is_given(self) -> Self:
        if self.action == "answer" and self.answer is None:
            raise ValueError("при действии «answer» нужен сам ответ")
        return self


class ConfirmRecognizedData(Strict):
    file: FileRef
    recognized: str


class ConfirmRecognizedResponse(Strict):
    confirmed: bool
    corrected: str | None = None


class Column(Strict):
    key: str
    title: str
    editable: bool = False


class ReviewTableData(Strict):
    columns: list[Column] = Field(min_length=1)
    rows: list[dict[str, Any]]


class RowDecision(Strict):
    """Решение по одной строке: оставить (с правками или без) или пропустить."""

    index: int = Field(ge=0)
    keep: bool = True
    values: dict[str, Any] = {}


class ReviewTableResponse(Strict):
    rows: list[RowDecision]


class ReviewDocumentData(Strict):
    title: str
    content: Any
    editable: bool = True


class ReviewDocumentResponse(Strict):
    approved: bool
    content: Any = None


SCREEN_DATA: dict[ScreenType, type[Strict]] = {
    ScreenType.ANSWER_FORM: AnswerFormData,
    ScreenType.CONFIRM_RECOGNIZED: ConfirmRecognizedData,
    ScreenType.REVIEW_TABLE: ReviewTableData,
    ScreenType.REVIEW_DOCUMENT: ReviewDocumentData,
}

SCREEN_RESPONSE: dict[ScreenType, type[Strict]] = {
    ScreenType.ANSWER_FORM: AnswerFormResponse,
    ScreenType.CONFIRM_RECOGNIZED: ConfirmRecognizedResponse,
    ScreenType.REVIEW_TABLE: ReviewTableResponse,
    ScreenType.REVIEW_DOCUMENT: ReviewDocumentResponse,
}
