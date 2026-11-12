"""Готовит данные по шаблону преподавателя и проверенной схеме результата.

Если преподаватель разрешил узлу инструменты, блок работает как агент (ADR 0035): модель
на каждом шаге отвечает по схеме — либо просит вызвать инструмент, либо отдаёт итог. Число
вызовов ограничено; когда они кончились, модели остаётся только отдать итог.
"""

import json
import re
from typing import Any

from pydantic import TypeAdapter

from backend.core.contracts.interfaces import LLMClient, LLMMessage, ToolClient, ToolInfo
from backend.core.contracts.ports import VALUE_MODELS, DataType, Task, value_problems
from backend.core.contracts.run import BlockEvent, Done, RunContext

PROMPT_FIELD = re.compile(r"\{(data|context)\}")
SUMMARY_TYPE = DataType(type="Data", of="summary")
TASKS_TYPE = DataType(type="Task", is_list=True)
DEFAULT_MAX_STEPS = 5
# Ответ инструмента целиком уходит модели: длинный журнал обрезается, чтобы не переполнить её.
MAX_TOOL_ANSWER = 20_000
AGENT_RULES = """Тебе разрешено вызывать инструменты, чтобы получить недостающие данные.
Каждый ответ — один JSON-объект одного из двух видов:
{"action": "call_tool", "tool": "<имя инструмента>", "arguments": {<аргументы>}}
{"action": "finish", "result": <итог по заданию>}
Инструменты только читают данные и ничего не меняют. Вызывай инструмент, только если без
его данных задание не выполнить.

Инструменты:"""


def _prompt(template: str, inputs: dict[str, Any]) -> str:
    values = {
        name: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for name, value in inputs.items()
    }
    fields = set(PROMPT_FIELD.findall(template))
    prompt = PROMPT_FIELD.sub(lambda match: values.get(match[1], "не передано"), template)
    for name, label in (("data", "Исходные данные"), ("context", "Дополнительные данные")):
        if name in values and name not in fields:
            prompt += f"\n\n{label}:\n{values[name]}"
    return prompt


def _only_fields(value: Any, fields: list[str]) -> Any:
    """Оставляет в записи (или в каждой записи списка) только перечисленные поля."""
    if isinstance(value, dict):
        return {name: value[name] for name in fields if name in value}
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return [_only_fields(item, fields) for item in value]
    raise ValueError("поля можно выбрать только у записи или списка записей")


def _schema(kind: DataType, preset: str | None) -> dict[str, Any]:
    if preset == "lecture_summary" and kind == SUMMARY_TYPE:
        return {
            "type": "object",
            "required": ["summary", "key_concepts"],
            "properties": {
                "summary": {"type": "string", "minLength": 1},
                "key_concepts": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
            },
            "additionalProperties": False,
        }
    if preset == "lecture_tasks" and kind == TASKS_TYPE:
        schema = TypeAdapter(list[Task]).json_schema()
        schema["minItems"] = 1
        schema["items"] = {
            "allOf": [
                schema["items"],
                {
                    "required": ["answer", "solution"],
                    "properties": {
                        "answer": {"type": "string", "minLength": 1},
                        "solution": {"type": "string", "minLength": 1},
                    },
                },
            ],
        }
        return schema
    if preset is not None:
        raise ValueError("неизвестная схема результата или схема не подходит к типу выхода")

    # Старые примеры задают только тип выхода. Data без готовой схемы принимает любой JSON.
    model = VALUE_MODELS.get(kind.type)
    if model is None:
        return {"type": "array"} if kind.is_list else {}
    return TypeAdapter(list[model] if kind.is_list else model).json_schema()


def _step_schema(result: dict[str, Any], tools: list[str] | None) -> dict[str, Any]:
    """Схема одного шага агента. `tools=None` — вызовы кончились, остаётся только итог."""
    result = dict(result)
    # Ссылки схемы результата ведут в «#/$defs/…»: определения поднимаются наверх.
    definitions = result.pop("$defs", None)
    finish = {
        "type": "object",
        "required": ["action", "result"],
        "properties": {"action": {"const": "finish"}, "result": result},
        "additionalProperties": False,
    }
    schema: dict[str, Any] = finish
    if tools is not None:
        call = {
            "type": "object",
            "required": ["action", "tool", "arguments"],
            "properties": {
                "action": {"const": "call_tool"},
                "tool": {"enum": tools},
                "arguments": {"type": "object"},
            },
            "additionalProperties": False,
        }
        schema = {"oneOf": [call, finish]}
    if definitions is not None:
        schema = {**schema, "$defs": definitions}
    return schema


def _tool_list(tools: list[ToolInfo], fixed: dict[str, Any]) -> str:
    lines = []
    for tool in tools:
        lines.append(f"- {tool.server}.{tool.name}: {tool.description}")
        lines.append(
            "  аргументы (JSON Schema): " + json.dumps(tool.input_schema, ensure_ascii=False)
        )
    if fixed:
        given = json.dumps(fixed, ensure_ascii=False)
        lines.append(f"Эти аргументы задал преподаватель, они подставятся сами: {given}")
    return "\n".join(lines)


def _tool_answer(name: str, answer: Any, left: int) -> str:
    text = json.dumps(answer, ensure_ascii=False)
    if len(text) > MAX_TOOL_ANSWER:
        text = text[:MAX_TOOL_ANSWER] + " … (ответ обрезан)"
    if left:
        more = f"Вызовов инструментов осталось: {left}."
    else:
        more = "Вызовы инструментов кончились: отдай итог."
    return f"Ответ инструмента {name}:\n{text}\n\n{more}"


async def _available(tools: ToolClient, chosen: list[str]) -> list[ToolInfo]:
    """Инструменты узла в порядке настроек; недоступный или с последствиями — ошибка."""
    found = {f"{tool.server}.{tool.name}": tool for tool in await tools.list_tools()}
    missing = [name for name in chosen if name not in found or not found[name].read_only]
    if missing:
        raise RuntimeError("агенту недоступны инструменты: " + ", ".join(missing))
    return [found[name] for name in chosen]


async def _agent(
    llm: LLMClient,
    tools: ToolClient,
    prompt: str,
    schema: dict[str, Any],
    config: dict[str, Any],
) -> tuple[Any, list[BlockEvent]]:
    """Шаги агента до итога. Возвращает итог и записи журнала о вызовах инструментов."""
    available = await _available(tools, config["tools"])
    # Аргументы, которые задал преподаватель; они перекрывают аргументы модели.
    fixed: dict[str, Any] = {"course_id": config["course_id"]} if "course_id" in config else {}
    left: int = config.get("max_steps", DEFAULT_MAX_STEPS)
    by_name = {f"{tool.server}.{tool.name}": tool for tool in available}
    names = list(by_name)
    messages = [
        LLMMessage(role="system", content=AGENT_RULES + "\n" + _tool_list(available, fixed)),
        LLMMessage(role="user", content=prompt),
    ]
    events: list[BlockEvent] = []
    while True:
        step_schema = _step_schema(schema, names if left else None)
        reply = await llm.complete(messages, schema=step_schema, model=config.get("model"))
        step = reply.data
        if step["action"] == "finish":
            return step["result"], events
        left -= 1
        server, tool = step["tool"].split(".", 1)
        # Только аргументы из схемы инструмента: лишнее поле модели могло бы унести в журнал
        # данные учеников из промпта.
        accepted = by_name[step["tool"]].input_schema.get("properties", {})
        arguments = {
            name: value
            for name, value in {**step["arguments"], **fixed}.items()
            if name in accepted
        }
        ok = True
        try:
            answer = await tools.call(server, tool, arguments)
        except Exception as error:
            # Ошибку видит модель: она может поправить аргументы или обойтись без данных.
            ok, answer = False, {"error": str(error)}
        # В журнал — что спросили, но не сам ответ: в нём данные учеников.
        events.append(
            BlockEvent(
                type="tool_called", data={"tool": step["tool"], "arguments": arguments, "ok": ok}
            )
        )
        messages += [
            LLMMessage(role="assistant", content=json.dumps(step, ensure_ascii=False)),
            LLMMessage(role="user", content=_tool_answer(step["tool"], answer, left)),
        ]


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    llm = context.llm
    if llm is None:
        raise RuntimeError("блоку не выдана модель")
    kind = DataType.model_validate(config["result"])
    schema = _schema(kind, config.get("result_schema"))
    if "data_fields" in config:
        inputs = {**inputs, "data": _only_fields(inputs["data"], config["data_fields"])}
    prompt = _prompt(config["prompt"], inputs)
    events: list[BlockEvent] = []
    if config.get("tools"):
        if context.tools is None:
            raise RuntimeError("блоку не выданы инструменты")
        data, events = await _agent(llm, context.tools, prompt, schema, config)
    else:
        message = LLMMessage(role="user", content=prompt)
        data = (await llm.complete([message], schema=schema, model=config.get("model"))).data
    # Слой модели проверяет JSON Schema. Здесь также действуют правила типа порта,
    # например требование передать текст для ответа, который не является фотографией.
    problems = value_problems(kind, data)
    if problems:
        raise ValueError("ответ модели не подходит под тип результата: " + "; ".join(problems))
    return Done(outputs={"result": data}, events=events)
