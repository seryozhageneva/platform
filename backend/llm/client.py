"""Слой ИИ-моделей — реализация интерфейса `LLMClient` из контракта (ADR 0006, ADR 0012).

Блок вызывает `context.llm.complete(...)` и не знает, какой провайдер за этим стоит. Слой:

- если блок просил ответ по схеме — добавляет в запрос просьбу ответить JSON, разбирает ответ
  и проверяет его по схеме;
- замеряет, сколько длился вызов;
- записывает каждый вызов, удачный и неудачный, в журнал вызовов.

Упавший вызов слой не повторяет: повторы делает движок (ADR 0010).
"""

import json
import logging
import re
import time
from collections.abc import Iterator
from typing import Any, Protocol
from urllib.parse import unquote

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import Unresolvable

from backend.core.contracts.interfaces import LLMMessage, LLMResponse
from backend.llm.providers import LLMError, Provider, ProviderReply

logger = logging.getLogger(__name__)

SCHEMA_REQUEST = (
    "Ответь только одним значением в формате JSON, без пояснений и без оформления кода. "
    "Ответ должен соответствовать этой JSON Schema:\n"
)

# Модель нередко оборачивает JSON в «```json ... ```», хотя её просили этого не делать.
_FENCED = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL | re.IGNORECASE)


class CallLog(Protocol):
    """Куда слой записывает вызовы. Настоящий журнал — `backend/models/llm_calls.py`.

    Слой моделей и база друг друга не подключают (правило 5 в `.importlinter`): слой знает
    только, что у журнала есть такой метод, а соединяет их слой сборки. Текста запроса и
    ответа здесь нет — только цифры.
    """

    async def record(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        error: str | None,
        run_id: str | None,
        node_id: str | None,
    ) -> None: ...


class PlatformLLM:
    def __init__(
        self,
        provider: Provider,
        *,
        call_log: CallLog | None = None,
        run_id: str | None = None,
        node_id: str | None = None,
    ) -> None:
        self._provider = provider
        self._call_log = call_log
        self._run_id = run_id
        self._node_id = node_id

    def bound(self, *, run_id: str, node_id: str | None = None) -> "PlatformLLM":
        """Тот же слой с пометкой, к какому запуску и узлу относятся его вызовы."""
        return PlatformLLM(self._provider, call_log=self._call_log, run_id=run_id, node_id=node_id)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        if schema is not None:
            messages = _with_schema_request(messages, schema)
        started = time.perf_counter()
        reply: ProviderReply | None = None
        failure: LLMError | None = None
        data: Any = None
        try:
            reply = await self._provider.chat(messages, model=model)
            if schema is not None:
                data = _parse(reply.text, schema)
        except LLMError as error:
            failure = error
        except Exception as error:
            # Чужой текст ошибки наружу не идёт: в нём могут быть адреса и подробности запроса.
            failure = LLMError("provider", f"вызов модели не удался ({type(error).__name__})")
            failure.__cause__ = error
        await self._record(
            model=reply.model if reply else model or self._provider.model,
            input_tokens=reply.input_tokens if reply else 0,
            output_tokens=reply.output_tokens if reply else 0,
            latency_ms=round((time.perf_counter() - started) * 1000),
            error=failure.kind if failure else None,
        )
        if failure is not None:
            raise failure
        assert reply is not None
        return LLMResponse(
            text=reply.text,
            data=data,
            model=reply.model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
        )

    async def aclose(self) -> None:
        """Закрывает соединения провайдера, если они у него есть."""
        close = getattr(self._provider, "aclose", None)
        if close is not None:
            await close()

    async def _record(self, **fields: Any) -> None:
        if self._call_log is None:
            return
        try:
            await self._call_log.record(
                provider=self._provider.name,
                run_id=self._run_id,
                node_id=self._node_id,
                **fields,
            )
        except Exception as error:
            # Журнал — учёт, а не часть урока: из-за него ответ модели ученику не пропадает.
            logger.warning("вызов модели не записан в журнал (%s)", type(error).__name__)


def _with_schema_request(messages: list[LLMMessage], schema: dict[str, Any]) -> list[LLMMessage]:
    """Сообщения с просьбой ответить по схеме; исходный список не меняется."""
    _check_schema(schema)
    request = SCHEMA_REQUEST + json.dumps(schema, ensure_ascii=False)
    # Системное сообщение у провайдеров одно и стоит первым, поэтому просьба дописывается в него.
    if messages and messages[0].role == "system":
        first = messages[0].model_copy(update={"content": f"{messages[0].content}\n\n{request}"})
        return [first, *messages[1:]]
    return [LLMMessage(role="system", content=request), *messages]


def _check_schema(schema: dict[str, Any]) -> None:
    """Схема проверяется до вызова модели: ошибка в схеме не должна стоить токенов."""
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise LLMError("bad_schema", f"схема ответа записана с ошибкой: {error.message}") from None
    for ref in _refs(schema):
        # Ссылка наружу заставила бы сервер скачивать схему по чужому адресу.
        if not ref.startswith("#"):
            raise LLMError(
                "bad_schema",
                f"схема ответа ссылается на другой файл или адрес («{ref}»): "
                "всё описание должно быть внутри самой схемы",
            )
        if not _resolves(schema, ref):
            raise LLMError("bad_schema", f"ссылка «{ref}» в схеме ответа никуда не ведёт")


def _refs(node: Any) -> Iterator[str]:
    """Все ссылки `$ref` в схеме, на любой глубине."""
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            yield node["$ref"]
        for value in node.values():
            yield from _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def _resolves(schema: dict[str, Any], ref: str) -> bool:
    """Ведёт ли ссылка вида «#/$defs/hint» на место внутри схемы."""
    if not ref.startswith("#/"):
        # «#» — вся схема; «#имя» — ссылка по метке, её проверит разбор ответа.
        return True
    node: Any = schema
    for part in unquote(ref[2:]).split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        else:
            return False
    return True


def _parse(text: str, schema: dict[str, Any]) -> Any:
    data = _json(text)
    # Пустой реестр: за схемами по сети библиотека не ходит.
    validator = Draft202012Validator(schema, registry=Registry())
    try:
        # Только место и нарушенное правило: сам ответ модели в текст ошибки не попадает.
        problems = sorted(
            {
                f"{error.json_path} — правило «{error.validator}»"
                for error in validator.iter_errors(data)
            }
        )
    except Unresolvable:
        raise LLMError(
            "bad_schema", "в схеме ответа есть ссылка, которая никуда не ведёт"
        ) from None
    if problems:
        raise LLMError("schema", "ответ модели не подходит под схему: " + "; ".join(problems))
    return data


def _json(text: str) -> Any:
    """JSON из ответа модели: весь ответ, блок «```json» или первое значение внутри текста."""
    candidates = [text.strip()]
    fenced = _FENCED.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    # Модель добавила слова до или после: «Ответ: {...}», «{...} Пояснение: ...».
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char in "{[":
            try:
                return decoder.raw_decode(text, start)[0]
            except json.JSONDecodeError:
                continue
    raise LLMError(
        "not_json", "модель ответила не в формате JSON, хотя её просили ответить по схеме"
    )
