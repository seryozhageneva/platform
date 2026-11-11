"""Блок «Источник: файл» возвращает ссылку на загруженный документ."""

from typing import Any

from backend.core.contracts.run import BlockEvent, Done, RunContext


async def run(inputs: dict[str, Any], config: dict[str, Any], context: RunContext) -> Done:
    store = context.store
    if store is None:
        raise RuntimeError("блоку не выдано хранилище платформы")

    file = await store.get_file(config["file_id"])
    if file is None:
        return Done(
            outcome="missing",
            events=[
                BlockEvent(
                    type="file_missing",
                    data={"message": "Проверьте номер файла в настройках блока."},
                )
            ],
        )
    return Done(outputs={"file": file.model_dump(mode="json")})
