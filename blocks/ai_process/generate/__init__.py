"""Готовит данные по шаблону преподавателя и проверенной схеме результата."""

import json
import re
from typing import Any

from pydantic import TypeAdapter

from backend.core.contracts.interfaces import LLMMessage
from backend.core.contracts.ports import VALUE_MODELS, DataType, Task, value_problems
from backend.core.contracts.run import Done, RunContext

PROMPT_FIELD = re.compile(r"\{(data|context)\}")
SUMMARY_TYPE = DataType(type="Data", of="summary")
TASKS_TYPE = DataType(type="Task", is_list=True)


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


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    llm = context.llm
    if llm is None:
        raise RuntimeError("блоку не выдана модель")
    kind = DataType.model_validate(config["result"])
    schema = _schema(kind, config.get("result_schema"))
    message = LLMMessage(role="user", content=_prompt(config["prompt"], inputs))
    reply = await llm.complete([message], schema=schema, model=config.get("model"))
    # Слой модели проверяет JSON Schema. Здесь также действуют правила типа порта,
    # например требование передать текст для ответа, который не является фотографией.
    problems = value_problems(kind, reply.data)
    if problems:
        raise ValueError("ответ модели не подходит под тип результата: " + "; ".join(problems))
    return Done(outputs={"result": reply.data})
