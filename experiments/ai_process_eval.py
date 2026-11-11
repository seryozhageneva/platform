"""Ручной замер на выдуманных лекциях: python -m experiments.ai_process_eval."""

import asyncio
import json
from pathlib import Path
from time import perf_counter

from backend.core.contracts.ports import Text
from backend.core.contracts.run import RunContext
from backend.llm.factory import make_llm
from backend.llm.providers import LLMError
from backend.llm.settings import DEFAULT_MODEL, LLMSettings
from blocks.ai_process.generate import run

SCENARIO = Path(__file__).resolve().parents[1] / "docs/examples/pipelines/scenario-3-materials.json"
LECTURES = {
    "fractions": (
        "В дроби числитель показывает, сколько долей взяли, а знаменатель — "
        "на сколько равных долей разделили целое. Чтобы сложить дроби с одинаковым "
        "знаменателем, сложи их числители и сохрани знаменатель. Например, 1/5 + 2/5 = 3/5."
    ),
    "rectangle": (
        "Площадь прямоугольника равна произведению его длины и ширины. "
        "Периметр равен удвоенной сумме этих сторон. Для сторон 3 см и 4 см "
        "площадь равна 12 квадратным сантиметрам, а периметр равен 14 сантиметрам."
    ),
    "mean": (
        "Среднее арифметическое равно сумме значений, делённой на их количество. "
        "У чисел 2, 4 и 9 сумма 15, поэтому их среднее равно 5. "
        "Повторяющиеся числа учитываются столько раз, сколько встречаются в списке."
    ),
}


async def main() -> int:
    settings = LLMSettings()
    if settings.llm_provider.strip().lower() != "gigachat":
        print("Для замера требуется LLM_PROVIDER=gigachat.")
        return 1
    try:
        llm = make_llm(settings)
    except LLMError as error:
        print(f"Модель не подключена ({error.kind}).")
        return 1

    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    stages = ("summarize", "make_tasks")
    configs = {node["id"]: node["config"] for node in scenario["nodes"] if node["id"] in stages}
    print(f"Модель: {settings.gigachat_model.strip() or DEFAULT_MODEL}", flush=True)
    accepted = 0
    try:
        for lecture, text in LECTURES.items():
            inputs = {"data": Text(text=text).model_dump(mode="json", exclude_none=True)}
            for stage in stages:
                context = RunContext(
                    run_id=f"eval-{lecture}", node_id=stage, pipeline_id=scenario["id"], llm=llm
                )
                row = {"lecture": lecture, "stage": stage}
                started = perf_counter()
                try:
                    output = (await run(inputs, configs[stage], context)).outputs["result"]
                except LLMError as error:
                    row.update(error=error.kind, detail=str(error))
                except ValueError as error:
                    row.update(error="result_type", detail=str(error))
                else:
                    accepted += 1
                    row["result"] = output
                    if stage == "summarize":
                        inputs["context"] = output
                row["latency_ms"] = round((perf_counter() - started) * 1000)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        await llm.aclose()
    total = len(LECTURES) * len(stages)
    print(f"Прошли проверку формы: {accepted} из {total}.")
    return int(accepted != total)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
