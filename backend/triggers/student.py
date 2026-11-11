"""Триггер открытия индивидуального урока."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from backend.core.contracts.pipeline import BlockNode, ParamRef, Pipeline
from backend.core.contracts.ports import AnswerForm, Event, TriggerType
from backend.core.contracts.screens import ScreenType
from backend.core.contracts.state import RunState, RunStatus
from backend.core.contracts.wiring import Problem
from backend.core.data_flow import with_params
from backend.core.validator import config_problems
from backend.models.tables import AssignmentRow
from backend.triggers.assembly import Assembly
from backend.triggers.manual import LaunchRefused, PipelineNotFound, launch_problems

BROWSER_FORMS = frozenset({AnswerForm.TEXT, AnswerForm.FORMULA, AnswerForm.CODE})


async def checked_lesson(
    assembly: Assembly, teacher_id: UUID, pipeline_id: UUID, params: dict[str, Any]
) -> tuple[Pipeline, int]:
    row = await assembly.pipelines.get(teacher_id, pipeline_id)
    graph = None if row is None else await assembly.pipelines.load(row.id, row.latest_version)
    if row is None or graph is None:
        raise PipelineNotFound("пайплайн не найден")
    problems = launch_problems(assembly, graph, TriggerType.STUDENT, params)
    if not problems:
        problems = _browser_problems(assembly, graph, params)
    if problems:
        raise LaunchRefused("урок нельзя запустить", problems)
    return graph, row.latest_version


def _browser_problems(assembly: Assembly, graph: Pipeline, params: dict[str, Any]) -> list[Problem]:
    values = {param.name: params.get(param.name, param.default) for param in graph.params}
    problems = []
    for node, _ in graph.walk():
        limit = getattr(node, "limit", None)
        if limit is not None and isinstance(limit.max, ParamRef) and values[limit.max.param] < 1:
            problems.append(
                Problem(
                    node.id, "bad_param", f"параметр «{limit.max.param}» должен быть не меньше 1"
                )
            )
        if not isinstance(node, BlockNode):
            continue
        manifest = assembly.registry.manifests[node.block]
        config = with_params(node.config, values)
        errors = config_problems(config, manifest.config, {})
        problems.extend(Problem(node.id, "bad_param", error) for error in errors)
        if manifest.screen not in (None, ScreenType.ANSWER_FORM, ScreenType.REVIEW_TABLE):
            problems.append(
                Problem(node.id, "unsupported_screen", "этот экран недоступен в кабинете ученика")
            )
        if node.block == "student.show_task" and not errors:
            forms = config.get("forms")
            if forms and BROWSER_FORMS.isdisjoint(forms):
                problems.append(
                    Problem(
                        node.id,
                        "unsupported_screen",
                        "форма должна принимать текст, формулу или код",
                    )
                )
    return problems


async def open_lesson(
    assembly: Assembly, assignment: AssignmentRow, student_id: UUID, run_id: UUID | None
) -> RunState:
    """Вызывается под блокировкой назначения."""
    if run_id is None:
        graph, version = await checked_lesson(
            assembly, assignment.teacher_id, assignment.pipeline_id, assignment.params
        )
        return await assembly.engine(assignment_id=assignment.id).start(
            graph,
            run_id=str(uuid4()),
            pipeline_id=str(assignment.pipeline_id),
            pipeline_version=version,
            event=Event(
                trigger=TriggerType.STUDENT,
                occurred_at=datetime.now(UTC),
                student_id=str(student_id),
                assignment_id=str(assignment.id),
            ),
            params=assignment.params,
            teacher_id=str(assignment.teacher_id),
            student_id=str(student_id),
        )
    state = await assembly.runs.load(str(run_id))
    if state is None:
        raise LookupError("запуск урока исчез")
    if state.status is not RunStatus.RUNNING:
        return state
    graph = await assembly.pipelines.load(assignment.pipeline_id, state.pipeline_version)
    if graph is None:
        raise LookupError("версия запуска урока исчезла")
    return await assembly.engine(assignment_id=assignment.id).resume(graph, state.run_id)
