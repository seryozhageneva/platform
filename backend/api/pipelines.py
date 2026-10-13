"""Эндпоинты пайплайнов: сохранить, сохранить новой версией, список, прочитать.

Перед сохранением пайплайн проверяет валидатор (ADR 0011): с ошибкой он не сохраняется,
с предупреждением — сохраняется, и предупреждения уходят в ответе.
"""

import uuid

from fastapi import APIRouter

from backend.api.deps import REFUSALS, Assembled, Teacher
from backend.api.errors import ApiError
from backend.api.schemas import PipelineDetail, PipelineSaved, PipelineSummary, ProblemOut
from backend.core.contracts.pipeline import Pipeline
from backend.core.validator import validate
from backend.triggers.assembly import Assembly

router = APIRouter(prefix="/pipelines", tags=["Пайплайны"], responses=REFUSALS)


def _warnings(assembly: Assembly, pipeline: Pipeline) -> list[ProblemOut]:
    """Предупреждения валидатора; с ошибками — отказ, пайплайн не сохраняется."""
    report = validate(pipeline, assembly.registry.manifests)
    if not report.ok:
        raise ApiError(422, "пайплайн не прошёл проверку и не сохранён", report.errors)
    return [ProblemOut.of(warning) for warning in report.warnings]


@router.post("", status_code=201, summary="Сохранить новый пайплайн")
async def create_pipeline(
    pipeline: Pipeline, teacher: Teacher, assembly: Assembled
) -> PipelineSaved:
    warnings = _warnings(assembly, pipeline)
    row = await assembly.pipelines.create(teacher.id, pipeline)
    return PipelineSaved(id=row.id, version=row.latest_version, warnings=warnings)


@router.put("/{pipeline_id}", summary="Сохранить пайплайн новой версией")
async def save_pipeline_version(
    pipeline_id: uuid.UUID, pipeline: Pipeline, teacher: Teacher, assembly: Assembled
) -> PipelineSaved:
    warnings = _warnings(assembly, pipeline)
    try:
        version = await assembly.pipelines.save_version(teacher.id, pipeline_id, pipeline)
    except LookupError as error:
        raise ApiError(404, str(error)) from None
    return PipelineSaved(id=pipeline_id, version=version, warnings=warnings)


@router.get("", summary="Свои пайплайны")
async def list_pipelines(teacher: Teacher, assembly: Assembled) -> list[PipelineSummary]:
    return [PipelineSummary.of(row) for row in await assembly.pipelines.list_pipelines(teacher.id)]


@router.get("/{pipeline_id}", summary="Пайплайн с графом последней версии")
async def get_pipeline(
    pipeline_id: uuid.UUID, teacher: Teacher, assembly: Assembled
) -> PipelineDetail:
    row = await assembly.pipelines.get(teacher.id, pipeline_id)
    graph = None if row is None else await assembly.pipelines.load(row.id, row.latest_version)
    if row is None or graph is None:
        raise ApiError(404, "пайплайн не найден")
    return PipelineDetail(**PipelineSummary.of(row).model_dump(), graph=graph)
