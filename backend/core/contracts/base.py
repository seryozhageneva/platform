"""Общее для всех моделей контракта: строгая база, шаблон имён и понятные ошибки."""

from pydantic import BaseModel, ConfigDict, ValidationError

# Имена портов, узлов, исходов, параметров: латиница, цифры и подчёркивание, с буквы.
NAME = r"^[a-z][a-z0-9_]*$"


class Strict(BaseModel):
    """Незнакомое поле — ошибка, а не молчаливый пропуск: опечатка в манифесте видна сразу."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ContractError(ValueError):
    """Манифест или пайплайн не соответствует контракту. `problems` — по строке на ошибку."""

    def __init__(self, what: str, problems: list[str]):
        self.what = what
        self.problems = problems
        super().__init__(f"{what}: " + "; ".join(problems))


def explain(error: ValidationError) -> list[str]:
    """Переводит ошибки Pydantic в строки вида «поле: что не так»."""
    problems = []
    for item in error.errors():
        where = ".".join(str(part) for part in item["loc"]) or "документ"
        kind, ctx = item["type"], item.get("ctx", {})
        if kind == "missing":
            text = "обязательное поле не заполнено"
        elif kind == "extra_forbidden":
            text = "неизвестное поле"
        elif kind in ("enum", "literal_error"):
            text = f"недопустимое значение {item['input']!r}; допустимо: {ctx.get('expected')}"
        elif kind == "union_tag_invalid":
            text = f"неизвестный вид {ctx.get('tag')!r}; допустимо: {ctx.get('expected_tags')}"
        elif kind == "union_tag_not_found":
            text = f"не указано поле {ctx.get('discriminator')}"
        elif kind == "string_pattern_mismatch":
            text = f"значение {item['input']!r} не подходит под шаблон {ctx.get('pattern')}"
        elif kind == "value_error":
            text = str(ctx.get("error", item["msg"]))
        else:
            text = item["msg"]
        problems.append(f"{where}: {text}")
    return problems
