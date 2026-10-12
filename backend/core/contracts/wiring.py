"""Проверка стыковки портов: каждая привязка входа ведёт к совместимому выходу.

Чистая функция без обращений к базе и сети. Валидатор пайплайнов (задача 06) вызывает её
и добавляет свои проверки: достижимость узлов, ограничители циклов, Подтверждение перед
блоками с последствиями.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import ValidationError

from backend.core.contracts.manifest import Manifest
from backend.core.contracts.pipeline import (
    BlockNode,
    ForEachNode,
    Pipeline,
    SwitchNode,
    Transition,
    TriggerNode,
)
from backend.core.contracts.ports import VALUE_MODELS, DataType, PortType, can_connect


@dataclass(frozen=True)
class Problem:
    node: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"узел «{self.node}»: {self.message}"


# Исходы узла «для каждого»: список обработан или оказался пустым.
FOR_EACH_OUTCOMES = ("ok", "empty")


def check_wiring(pipeline: Pipeline, manifests: Mapping[str, Manifest]) -> list[Problem]:
    """Возвращает список ошибок стыковки; пустой список — всё стыкуется."""
    return Wiring(pipeline, manifests).run()


class Wiring:
    """Типы всех выходов пайплайна и найденные ошибки стыковки.

    `outputs(узел)` и `ref_type(ссылка, узел)` пригодятся редактору: показать тип на порту
    и предложить для входа только подходящие выходы.
    """

    def __init__(self, pipeline: Pipeline, manifests: Mapping[str, Manifest]):
        self.pipeline = pipeline
        self.manifests = manifests
        self.nodes: dict[str, Any] = {}
        # Путь узла — «для каждого», в которые он вложен, от внешнего к внутреннему.
        self.paths: dict[str, tuple[str, ...]] = {}
        for node, path in pipeline.walk():
            self.nodes[node.id] = node
            self.paths[node.id] = path
        # Записи, собранные узлами «для каждого»: название -> узел, который её собирает.
        self.records = {
            node.record: node
            for node in self.nodes.values()
            if isinstance(node, ForEachNode) and node.record
        }
        self.problems: list[Problem] = []
        self._outputs: dict[str, dict[str, DataType]] = {}
        self._items: dict[str, DataType | None] = {}
        self._resolving: set[str] = set()

    def run(self) -> list[Problem]:
        for node in self.nodes.values():
            if isinstance(node, BlockNode):
                self._check_block(node)
            elif isinstance(node, SwitchNode):
                self._switch_outcomes(node)
            elif isinstance(node, ForEachNode):
                self.outputs(node.id)
        self._check_record_names()
        self._check_transitions(self.pipeline.transitions)
        for node in self.nodes.values():
            if isinstance(node, ForEachNode):
                self._check_transitions(node.body.transitions)
        return self.problems

    def _report(self, node: str, code: str, message: str) -> None:
        problem = Problem(node, code, message)
        if problem not in self.problems:
            self.problems.append(problem)

    # --- Типы выходов узла ---------------------------------------------------------------

    def outputs(self, node_id: str) -> dict[str, DataType]:
        """Типы выходов узла. Вычисляемые типы (`same_as`, `from_config`) уже раскрыты."""
        if node_id in self._outputs:
            return self._outputs[node_id]
        if node_id in self._resolving:
            self._report(
                node_id,
                "type_cycle",
                "тип выхода зависит сам от себя: проверь привязки входов с `same_as`",
            )
            return {}
        self._resolving.add(node_id)
        node = self.nodes[node_id]
        if isinstance(node, TriggerNode):
            result = {"event": DataType(type=PortType.EVENT)}
        elif isinstance(node, BlockNode):
            result = self._block_outputs(node)
        elif isinstance(node, ForEachNode):
            result = self._for_each_outputs(node)
        else:
            result = {}
        self._resolving.discard(node_id)
        self._outputs[node_id] = result
        return result

    def _block_outputs(self, node: BlockNode) -> dict[str, DataType]:
        manifest = self.manifests.get(node.block)
        if manifest is None:
            return {}
        result = {}
        for port in manifest.outputs:
            if port.from_config:
                kind = self._type_from_config(node, port.from_config)
            elif port.same_as:
                bound = node.inputs.get(port.same_as) or []
                refs = bound if isinstance(bound, list) else [bound]
                # Ссылка на собственный такой же выход («то, что вышло в прошлый раз»)
                # тип не определяет — его задают остальные ссылки.
                own = {f"{node.id}.{out.name}" for out in manifest.outputs if out.same_as}
                refs = [ref for ref in refs if ref not in own]
                kind = self.binding_type(refs, node.id) if refs else None
            else:
                kind = port.element().as_list() if port.is_list else port.element()
            if kind is not None:
                result[port.name] = kind
        return result

    def _type_from_config(self, node: BlockNode, setting: str) -> DataType | None:
        try:
            return DataType.model_validate(node.config.get(setting))
        except ValidationError:
            self._report(
                node.id,
                "bad_config_type",
                f"в настройке «{setting}» должен быть записан тип результата, например "
                '{"type": "Data", "of": "summary"}; параметром пайплайна его задать нельзя',
            )
            return None

    def item_type(self, node: ForEachNode) -> DataType | None:
        """Тип одного элемента списка, который перебирает «для каждого».

        Считается отдельно от `results`: телу он нужен раньше, чем известно, что собрано.
        """
        if node.id not in self._items:
            self._items[node.id] = None
            over = self.ref_type(node.over, node.id)
            if over is not None and over.is_list:
                self._items[node.id] = over.element()
            elif over is not None:
                self._report(
                    node.id,
                    "not_a_list",
                    f"«для каждого» перебирает список, а «{node.over}» выдаёт {over.label()}",
                )
        return self._items[node.id]

    def _for_each_outputs(self, node: ForEachNode) -> dict[str, DataType]:
        result = {}
        item = self.item_type(node)
        if item is not None:
            result["item"] = item
        inside = (*self.paths[node.id], node.id)
        if isinstance(node.collect, str):
            kind = self.ref_type(node.collect, node.id, inside)
            if kind is not None and not kind.is_list:
                result["results"] = kind.as_list()
            elif kind is not None:
                self._report(node.id, "nested_list", "собрать можно значение, но не список")
        elif isinstance(node.collect, dict):
            for bound in node.collect.values():
                self.binding_type(bound, node.id, inside)
            result["results"] = DataType(type=PortType.DATA, of=node.record, is_list=True)
        return result

    # --- Тип по ссылке -------------------------------------------------------------------

    def ref_type(
        self, ref: str, user: str, user_path: tuple[str, ...] | None = None
    ) -> DataType | None:
        """Тип значения по ссылке «узел.порт[.поле]», как его видит узел `user`.

        Сообщает об ошибке и возвращает None, если ссылка никуда не ведёт.
        """
        target, port, *rest = ref.split(".")
        path = self.paths[user] if user_path is None else user_path
        if target not in self.nodes:
            self._report(user, "unknown_ref", f"ссылка «{ref}»: узла «{target}» нет")
            return None
        target_node = self.nodes[target]
        inside_target = target in path
        if self.paths[target] != path[: len(self.paths[target])]:
            self._report(
                user,
                "out_of_scope",
                f"ссылка «{ref}»: узел «{target}» находится внутри «для каждого», снаружи "
                "виден только выход `results` самого узла «для каждого»",
            )
            return None
        if isinstance(target_node, ForEachNode) and (port == "item") != inside_target:
            self._report(
                user,
                "out_of_scope",
                f"ссылка «{ref}»: `item` доступен только внутри тела «{target}», "
                "а `results` — только снаружи",
            )
            return None
        if isinstance(target_node, BlockNode) and target_node.block not in self.manifests:
            return None  # о неизвестном блоке уже сообщено
        if isinstance(target_node, ForEachNode) and port == "item":
            kind = self.item_type(target_node)
        else:
            kind = self.outputs(target).get(port)
        if kind is None:
            if target not in self._resolving and not self._has_problem(target):
                self._report(user, "unknown_port", f"ссылка «{ref}»: у узла нет выхода «{port}»")
            return None
        if not rest:
            return kind
        owner = self.records.get(kind.of or "")
        if kind.is_list or owner is None or rest[0] not in owner.collect:
            self._report(
                user,
                "unknown_field",
                f"ссылка «{ref}»: поле читается только у записи, собранной узлом "
                f"«для каждого», а здесь {kind.label()}"
                + (f" без поля «{rest[0]}»" if owner is not None else ""),
            )
            return None
        return self.binding_type(
            owner.collect[rest[0]], owner.id, (*self.paths[owner.id], owner.id)
        )

    def binding_type(
        self, bound: str | list[str], user: str, user_path: tuple[str, ...] | None = None
    ) -> DataType | None:
        """Тип привязки. У нескольких ссылок на выбор тип обязан быть один и тот же."""
        refs = bound if isinstance(bound, list) else [bound]
        kinds = [self.ref_type(ref, user, user_path) for ref in refs]
        if None in kinds:
            return None
        if any(kind != kinds[0] for kind in kinds):
            self._report(
                user,
                "mixed_types",
                "ссылки на выбор выдают разное: "
                + ", ".join(
                    f"«{ref}» — {kind.label()}" for ref, kind in zip(refs, kinds, strict=True)
                ),
            )
            return None
        return kinds[0]

    def _has_problem(self, node: str) -> bool:
        return any(problem.node == node for problem in self.problems)

    # --- Узлы ----------------------------------------------------------------------------

    def _check_block(self, node: BlockNode) -> None:
        manifest = self.manifests.get(node.block)
        if manifest is None:
            self._report(node.id, "unknown_block", f"блок «{node.block}» не найден")
            return
        for name, bound in node.inputs.items():
            port = manifest.input(name)
            if port is None:
                self._report(node.id, "unknown_input", f"у блока «{node.block}» нет входа «{name}»")
                continue
            for ref in bound if isinstance(bound, list) else [bound]:
                kind = self.ref_type(ref, node.id)
                if kind is not None and not can_connect(kind, port):
                    self._report(
                        node.id,
                        "incompatible",
                        f"вход «{name}» ждёт {port.label()}, а «{ref}» выдаёт {kind.label()}",
                    )
        for port in manifest.inputs:
            if port.required and port.name not in node.inputs:
                self._report(
                    node.id,
                    "missing_input",
                    f"обязательный вход «{port.name}» ни к чему не привязан",
                )
        self.outputs(node.id)

    def _switch_outcomes(self, node: SwitchNode) -> set[str] | None:
        """Возможные исходы развилки; None — любые (значение поля заранее неизвестно)."""
        kind = self.ref_type(node.value, node.id)
        if kind is None:
            return None
        if kind.is_list:
            self._report(
                node.id, "not_a_value", f"развилка смотрит на одно значение, а не на {kind.label()}"
            )
            return None
        model = VALUE_MODELS.get(kind.type)
        if model is None:
            owner = self.records.get(kind.of or "")
            if owner is not None and node.field not in owner.collect:
                self._report(
                    node.id, "unknown_field", f"у записи «{kind.of}» нет поля «{node.field}»"
                )
            return None
        field = model.model_fields.get(node.field)
        if field is None:
            self._report(node.id, "unknown_field", f"у типа {kind.label()} нет поля «{node.field}»")
            return None
        if isinstance(field.annotation, type) and issubclass(field.annotation, Enum):
            return {item.value for item in field.annotation}
        if field.annotation is bool:
            return {"true", "false"}
        return None

    def _check_record_names(self) -> None:
        """Название записи не совпадает с уточнением данных какого-нибудь блока.

        Поля записи ищутся по её названию. При совпадении данные блока были бы приняты за
        запись, и ссылка на несуществующее поле прошла бы проверку.
        """
        for node in self.nodes.values():
            manifest = self.manifests.get(node.block) if isinstance(node, BlockNode) else None
            if manifest is None:
                continue
            taken = {port.of for port in (*manifest.inputs, *manifest.outputs)}
            for port in manifest.outputs:
                if port.from_config:
                    taken.add(self.outputs(node.id).get(port.name, port).of)
            for name in sorted(taken & set(self.records)):
                self._report(
                    self.records[name].id,
                    "record_name_taken",
                    f"название записи «{name}» занято: так называются данные блока "
                    f"«{node.block}». Выбери для `as` другое название",
                )

    def _check_transitions(self, transitions: list[Transition]) -> None:
        for move in transitions:
            if move.when is None:
                continue
            node = self.nodes[move.source]
            if isinstance(node, BlockNode):
                manifest = self.manifests.get(node.block)
                allowed = set(manifest.outcomes) if manifest else None
            elif isinstance(node, SwitchNode):
                allowed = self._switch_outcomes(node)
            else:
                allowed = set(FOR_EACH_OUTCOMES)
            if allowed is not None and move.when not in allowed:
                self._report(
                    node.id,
                    "unknown_outcome",
                    f"переход по исходу «{move.when}», а у узла бывают только: "
                    f"{', '.join(sorted(allowed))}",
                )
