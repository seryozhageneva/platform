"""Блоки `runtime: mcp`: вызов инструмента MCP-сервера как функции `run` (ADR 0028).

Ядро вызывает такой блок так же, как встроенный. Здесь, в слое сборки:

1. берётся подключение преподавателя запуска или общий почтовый ящик платформы;
2. MCP-клиент вызывает инструмент с настройками узла и значениями входов;
3. ответ инструмента — поля с именами выходов и `outcome` — становится результатом блока.

Файл MCP-сервер присылает содержимым (`content_base64`), потому что хранилища платформы он
не знает. Каждый такой файл сохраняется в файлы преподавателя через хранилище платформы,
а блок отдаёт дальше обычную ссылку `File` (docs/contract.md, раздел 2).
"""

import base64
import binascii
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.core.contracts.interfaces import PlatformStore
from backend.core.contracts.manifest import Manifest, McpRuntime
from backend.core.contracts.ports import FileKind, PortType, TriggerType
from backend.core.contracts.run import BlockEvent, BlockRun, Done, RunContext
from backend.mcp_client.client import (
    BUILTIN_SERVERS,
    McpToolClient,
    ToolCallError,
    builtin_server,
    email_server,
)
from backend.models.connections import ConnectionRepository
from backend.models.db import ROOT
from backend.models.tables import ConnectionKind
from backend.models.users import UserRepository

# Как у загрузки файлов платформы: один файл — до 10 МиБ. Сервер тоже проверяет, но
# платформа ему не доверяет.
MAX_FILE_SIZE = 10 * 1024 * 1024

# Инструменты MCP для преподавателя запуска и сервера с таким именем.
ToolsFor = Callable[[uuid.UUID, str], Awaitable[McpToolClient]]


class _SmtpSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="PLATFORM_", extra="ignore"
    )

    smtp_host: str = ""
    smtp_port: str = "465"
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""

    def child_environment(self) -> dict[str, str]:
        password = self.smtp_password.get_secret_value()
        if not (self.smtp_host and self.smtp_username and password):
            raise RuntimeError("не настроен почтовый ящик платформы: см. настройки PLATFORM_SMTP")
        if self.smtp_port not in ("465", "587"):
            raise RuntimeError("PLATFORM_SMTP_PORT должен быть 465 (TLS) или 587 (STARTTLS)")
        return {
            "SMTP_HOST": self.smtp_host,
            "SMTP_PORT": self.smtp_port,
            "SMTP_USERNAME": self.smtp_username,
            "SMTP_PASSWORD": password,
            "SMTP_FROM": self.smtp_from or self.smtp_username,
        }


def connection_tools(connections: ConnectionRepository) -> ToolsFor:
    """Инструменты с доступом к внешней системе для преподавателя запуска."""

    async def tools_for(owner_id: uuid.UUID, server: str) -> McpToolClient:
        if server == "email":
            return McpToolClient({server: email_server(_SmtpSettings().child_environment())})
        credentials = await connections.credentials(owner_id, ConnectionKind(server))
        if credentials is None:
            raise RuntimeError(
                f"нет подключения «{server}»: добавь адрес и токен в подключениях преподавателя"
            )
        target = builtin_server(server, url=credentials.url, token=credentials.token)
        return McpToolClient({server: target})

    return tools_for


def mcp_connector(
    tools_for: ToolsFor,
    *,
    users: UserRepository | None = None,
    servers: Iterable[str] = BUILTIN_SERVERS,
) -> Callable[[Manifest], BlockRun]:
    known = set(servers)

    def connect(manifest: Manifest) -> BlockRun:
        runtime = manifest.runtime
        assert isinstance(runtime, McpRuntime)
        if runtime.server not in known:
            raise ValueError(f"неизвестный MCP-сервер «{runtime.server}»")

        async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
            store = context.store
            if context.teacher_id is None or store is None:
                raise RuntimeError("блоку MCP нужен преподаватель запуска: чьё подключение брать")
            owner_id = uuid.UUID(context.teacher_id)
            arguments = {**config, **inputs}
            if (runtime.server, runtime.tool) in (
                ("email", "send_email"),
                ("telegram", "send_message"),
            ):
                if users is None:
                    raise RuntimeError("сборка не подключила контакты для уведомлений")
                destination = await _destination(users, owner_id, runtime.server, inputs, context)
                if destination is None:
                    return Done(outcome="skipped")
                arguments = _notification_arguments(
                    runtime.server, destination, inputs["content"], config
                )
            elif (runtime.server, runtime.tool) == ("moodle", "get_submissions"):
                arguments = _submission_arguments(config, inputs.get("event"))
            elif (runtime.server, runtime.tool) == ("moodle", "save_grade"):
                arguments = _grade_arguments(inputs)
            tools = await tools_for(owner_id, runtime.server)
            try:
                answer = await tools.call_tool(
                    runtime.server,
                    runtime.tool,
                    arguments,
                    read_only=not manifest.side_effects,
                )
            except ToolCallError as error:
                raise RuntimeError(str(error)) from None
            if (runtime.server, runtime.tool) == ("moodle", "save_grade"):
                return _grade_result(manifest, answer, arguments)
            return await _as_result(manifest, answer, store)

        return run

    return connect


def _submission_arguments(config: dict[str, Any], event: Any) -> dict[str, Any]:
    """Запуск по событию Moodle берёт только сдачи из события, остальные — все (ADR 0034)."""
    arguments = dict(config)
    payload = event.get("payload") if isinstance(event, dict) else None
    if not (isinstance(event, dict) and event.get("trigger") == TriggerType.MOODLE_EVENT.value):
        return arguments
    if not isinstance(payload, dict):
        raise RuntimeError("в событии Moodle нет номеров сдач")
    # Опрос берёт курс и задание из настроек этого же узла, так что они совпадают.
    if (payload.get("moodle_course_id"), payload.get("moodle_assignment_id")) != (
        config.get("course_id"),
        config.get("assignment_id"),
    ):
        raise RuntimeError("событие Moodle пришло по другому курсу или заданию")
    numbers = payload.get("moodle_submission_ids")
    if not isinstance(numbers, list) or not all(_is_int(number) for number in numbers):
        raise RuntimeError("в событии Moodle нет номеров сдач")
    arguments["submission_ids"] = numbers
    return arguments


def _grade_arguments(inputs: dict[str, Any]) -> dict[str, Any]:
    """Чья работа и по какому заданию — из `meta` файла; баллы — из вердикта."""
    work = inputs.get("work")
    meta = work.get("meta") if isinstance(work, dict) else None
    keys = ("moodle_course_id", "moodle_assignment_id", "moodle_user_id")
    if not isinstance(meta, dict) or not all(_is_int(meta.get(key)) for key in keys):
        raise RuntimeError(
            "оценку в Moodle можно поставить только за работу из «Источник: работы из Moodle»"
        )
    verdict = inputs.get("verdict")
    if not isinstance(verdict, dict):
        raise RuntimeError("для оценки в Moodle нужен вердикт")
    score, max_score = verdict.get("score"), verdict.get("max_score")
    if not (_is_number(score) and _is_number(max_score)):
        # Вердикт без баллов — «верно» или «неверно»: полный балл или ноль.
        score, max_score = (1 if verdict.get("correct") else 0), 1
    comment = inputs.get("comment")
    text = comment.get("text") if isinstance(comment, dict) else comment
    if text is None:
        text = verdict.get("comment") or ""
    if not isinstance(text, str):
        raise RuntimeError("комментарий к оценке должен быть текстом")
    return {
        "course_id": meta["moodle_course_id"],
        "assignment_id": meta["moodle_assignment_id"],
        "user_id": meta["moodle_user_id"],
        "score": score,
        "max_score": max_score,
        "comment": text,
    }


def _grade_result(manifest: Manifest, answer: Any, arguments: dict[str, Any]) -> Done:
    if not isinstance(answer, dict) or answer.get("outcome") not in manifest.outcomes:
        raise RuntimeError("MCP-сервер Moodle не подтвердил оценку")
    grade = answer.get("grade")
    if not _is_number(grade):
        raise RuntimeError("MCP-сервер Moodle вернул оценку в неверном формате")
    data = {"moodle_user_id": arguments["user_id"], "grade": grade}
    event = BlockEvent(type="moodle_grade_saved", data=data)
    return Done(outcome=answer["outcome"], events=[event])


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _notification_arguments(
    server: str, destination: str | int, content: Any, config: dict[str, Any]
) -> dict[str, Any]:
    text = content.get("text") if isinstance(content, dict) else content
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("для уведомления нужен непустой текст")
    if server == "telegram":
        return {"text": text, "chat_id": destination}
    arguments = {"text": text, "email": destination}
    if "subject" in config:
        arguments["subject"] = config["subject"]
    return arguments


async def _destination(
    users: UserRepository,
    owner_id: uuid.UUID,
    server: str,
    inputs: dict[str, Any],
    context: RunContext,
) -> str | int | None:
    if "recipient" in inputs:
        recipient = inputs["recipient"]
        student_id = recipient.get("student_id") if isinstance(recipient, dict) else None
    else:
        student_id = context.student_id
    try:
        if not isinstance(student_id, str):
            raise ValueError
        identifier = uuid.UUID(student_id)
    except ValueError:
        raise RuntimeError("в получателе уведомления нужен номер ученика (student_id)") from None
    student = await users.get_student(owner_id, identifier)
    if student is None:
        raise RuntimeError("ученик для уведомления не найден у преподавателя запуска")
    return student.notification_email if server == "email" else student.telegram_id


async def _as_result(manifest: Manifest, answer: Any, store: PlatformStore) -> Done:
    if not isinstance(answer, dict):
        raise RuntimeError("MCP-сервер ответил без полей выходов")
    outcome = answer.get("outcome", "ok")
    if outcome not in manifest.outcomes:
        raise RuntimeError(f"MCP-сервер вернул неизвестный исход «{outcome}»")
    ports = {port.name: port for port in manifest.outputs}
    extra = sorted(set(answer) - set(ports) - {"outcome"})
    if extra:
        raise RuntimeError(f"MCP-сервер вернул поля, которых нет среди выходов: {', '.join(extra)}")
    outputs: dict[str, Any] = {}
    for name, value in answer.items():
        if name == "outcome":
            continue
        # Пустое поле — выхода нет, но только при исходе не ok: например, файла нет при
        # missing. При ok пустой выход — ошибка сервера, она ловится ниже (ADR 0036).
        if value is None and outcome != "ok":
            continue
        port = ports[name]
        if port.type is PortType.FILE:
            items = value if port.is_list and isinstance(value, list) else [value]
            saved = [await _save_file(store, name, item) for item in items]
            outputs[name] = saved if port.is_list else saved[0]
        else:
            outputs[name] = value
    return Done(outcome=outcome, outputs=outputs)


async def _save_file(store: PlatformStore, port: str, item: Any) -> dict[str, Any]:
    """Файл из ответа сервера — в файлы преподавателя; дальше по пайплайну идёт ссылка."""
    if not isinstance(item, dict) or "content_base64" not in item:
        raise RuntimeError(f"выход «{port}»: MCP-сервер прислал файл без содержимого")
    try:
        content = base64.b64decode(item["content_base64"], validate=True)
        kind = FileKind(item.get("kind", "other"))
    except (binascii.Error, TypeError, ValueError):
        raise RuntimeError(f"выход «{port}»: MCP-сервер прислал файл в неверном формате") from None
    if len(content) > MAX_FILE_SIZE:
        raise RuntimeError(f"выход «{port}»: файл больше 10 МиБ")
    name = str(item.get("name") or "file")
    media_type = str(item.get("media_type") or "application/octet-stream")
    meta = item.get("meta") or {}
    if not isinstance(meta, dict):
        raise RuntimeError(f"выход «{port}»: описание файла в неверном формате")
    # Повтор блока в том же запуске и узле с тем же файлом не создаёт второй копии (ADR 0026).
    fingerprint = hashlib.sha256(
        json.dumps([port, name, meta], sort_keys=True, ensure_ascii=False).encode() + content
    ).hexdigest()
    try:
        ref = await store.save_file(
            key=f"mcp:{fingerprint}",
            name=name,
            kind=kind,
            media_type=media_type,
            content=content,
        )
    except ValidationError:
        raise RuntimeError(f"выход «{port}»: файл не сохранён") from None
    # Номер работы во внешней системе нужен дальше (оценка в Moodle — ADR 0034), а в
    # таблице файлов его нет: он едет в описании ссылки внутри запуска.
    return ref.model_copy(update={"meta": {**ref.meta, **meta}}).model_dump(mode="json")
