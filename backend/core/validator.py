"""Валидатор пайплайнов: проверка схемы урока до сохранения и до запуска.

Начинает с проверки стыковки портов из контракта (`check_wiring`) и добавляет то, чего она
не делает: достижимость узлов, ограничитель в каждом круге, чтение ещё не записанного
выхода, настройки узла по схеме блока, инструменты агента и Подтверждение перед блоком с
последствиями. Решения — ADR 0011.

Чистая функция: ни базы, ни сети, ни самих блоков — только пайплайн и манифесты.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from backend.core.contracts.manifest import Kind, Manifest, McpRuntime
from backend.core.contracts.pipeline import (
    BlockNode,
    ForEachNode,
    Param,
    ParamType,
    Pipeline,
    SwitchNode,
    Transition,
)
from backend.core.contracts.wiring import Problem, check_wiring


@dataclass(frozen=True)
class Report:
    """Отчёт валидатора. С ошибкой пайплайн не сохраняется, с предупреждением — сохраняется."""

    errors: list[Problem]
    warnings: list[Problem]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(pipeline: Pipeline, manifests: Mapping[str, Manifest]) -> Report:
    """Проверяет пайплайн по манифестам установленных блоков."""
    return _Validator(pipeline, manifests).run()


def tool_problems(manifest: Manifest, manifests: Mapping[str, Manifest]) -> list[str]:
    """Инструменты с последствиями среди разрешённых агенту блока; пусто — всё в порядке.

    Инструмент считается действующим во внешнем мире, если им пользуется блок с
    `side_effects`. Пометки самого MCP-сервера сверяются при подключении к нему (задача 23).
    """
    acting = {
        (other.runtime.server, other.runtime.tool): other.id
        for other in manifests.values()
        if isinstance(other.runtime, McpRuntime) and other.side_effects
    }
    return [
        f"агенту разрешён инструмент «{ref.server}.{ref.tool}», а он действует во внешнем "
        f"мире: им пользуется блок «{acting[ref.server, ref.tool]}». Агенту доступны только "
        "инструменты чтения"
        for ref in manifest.tools
        if (ref.server, ref.tool) in acting
    ]


@dataclass(frozen=True)
class _Level:
    """Один уровень графа: весь пайплайн или тело одного «для каждого»."""

    # «Для каждого», чьё это тело; None — верхний уровень.
    owner: str | None
    start: str
    nodes: dict[str, Any]
    # Обычные переходы: узел отработал и по исходу пошёл дальше.
    moves: dict[str, list[str]]
    # Переходы «попытки кончились»: узел не выполнялся, сработал его ограничитель.
    otherwise: dict[str, str]
    # Такие же переходы, которые сработать не могут: попытки узла никогда не кончатся.
    dead: dict[str, str]

    def steps(self, node_id: str, *, exhausted: bool = False) -> list[str]:
        """Куда можно попасть из узла за один шаг.

        `exhausted` — попытки узла кончились навсегда: остаётся только переход «иначе».
        """
        targets = [] if exhausted else list(self.moves.get(node_id, []))
        if node_id in self.otherwise:
            targets.append(self.otherwise[node_id])
        return targets

    def reach(self, starts: Iterable[str], stop: Iterable[str] = ()) -> set[str]:
        """Узлы, до которых можно дойти от `starts`, не выполнив ни одного узла из `stop`.

        Мимо узла из `stop` путь идёт только переходом «иначе»: он срабатывает как раз
        тогда, когда узел не выполнялся.
        """
        stop = set(stop)
        return _reach(lambda node_id: self.steps(node_id, exhausted=node_id in stop), starts)

    def limit(self, node_id: str) -> Any:
        return getattr(self.nodes[node_id], "limit", None)


def _level(owner: str | None, start: str, nodes: list[Any], moves: list[Transition]) -> _Level:
    by_id = {node.id: node for node in nodes}
    targets: dict[str, list[str]] = {}
    for move in moves:
        if move.target not in targets.setdefault(move.source, []):
            targets[move.source].append(move.target)
    wanted = {
        node.id: node.limit.otherwise
        for node in nodes
        if getattr(node, "limit", None) is not None and node.limit.otherwise
    }
    # Переход «иначе» срабатывает, когда в узел пришли с потраченными попытками. Для этого
    # из узла нужно суметь вернуться в него же, не выполнив по дороге узел, который
    # обнуляет его счётчик. Возвращаться можно и чужими переходами «иначе», поэтому
    # множество растёт, пока находится новое.
    live: dict[str, str] = {}
    while True:
        level = _Level(owner, start, by_id, targets, dict(live), {})
        found = {
            node_id: target
            for node_id, target in wanted.items()
            if by_id[node_id].limit.reset_on != node_id
            and node_id
            in level.reach(targets.get(node_id, []), stop=[by_id[node_id].limit.reset_on])
        }
        if found.keys() <= live.keys():
            dead = {node_id: target for node_id, target in wanted.items() if node_id not in live}
            return _Level(owner, start, by_id, targets, live, dead)
        live |= found


class _Validator:
    def __init__(self, pipeline: Pipeline, manifests: Mapping[str, Manifest]) -> None:
        self.pipeline = pipeline
        self.manifests = manifests
        self.params = {param.name: param for param in pipeline.params}
        self.errors: list[Problem] = []
        self.warnings: list[Problem] = []
        # Уровни графа: верхний и по одному на тело каждого «для каждого».
        self.levels: dict[str | None, _Level] = {
            None: _level(None, pipeline.trigger().id, pipeline.nodes, pipeline.transitions)
        }
        # На каком уровне стоит узел: None — на верхнем, иначе имя «для каждого».
        self.home: dict[str, str | None] = {}
        for node, path in pipeline.walk():
            self.home[node.id] = path[-1] if path else None
            if isinstance(node, ForEachNode):
                body = node.body
                self.levels[node.id] = _level(node.id, body.start, body.nodes, body.transitions)
        self.reachable = {owner: level.reach([level.start]) for owner, level in self.levels.items()}
        # Узлы каждого уровня, до которых можно дойти от его начала, минуя Подтверждение.
        self.unguarded = {
            owner: level.reach(
                [level.start], stop=[n.id for n in level.nodes.values() if self._is_approval(n)]
            )
            for owner, level in self.levels.items()
        }

    def run(self) -> Report:
        self.errors += check_wiring(self.pipeline, self.manifests)
        for level in self.levels.values():
            self._check_reachable(level)
            self._check_loops(level)
        for node, _ in self.pipeline.walk():
            if node.id not in self.reachable[self.home[node.id]]:
                continue  # о недостижимом узле уже сообщено, остальное о нём — шум
            if isinstance(node, SwitchNode):
                self._check_written(node.id, "развилка", node.value)
            elif isinstance(node, ForEachNode):
                self._check_written(node.id, "«для каждого»", node.over)
            elif isinstance(node, BlockNode) and node.block in self.manifests:
                self._check_block(node, self.manifests[node.block])
        return Report(self.errors, self.warnings)

    def _error(self, node: str, code: str, message: str) -> None:
        self.errors.append(Problem(node, code, message))

    # --- Достижимость --------------------------------------------------------------------

    def _check_reachable(self, level: _Level) -> None:
        where = "от старта" if level.owner is None else f"от первого узла тела «{level.owner}»"
        entered = {target for node_id in level.nodes for target in level.steps(node_id)}
        for node_id in level.nodes:
            if node_id in self.reachable[level.owner]:
                continue
            unused = [source for source, target in level.dead.items() if target == node_id]
            if node_id in entered:
                why = "переходы в него ведут только из таких же недостижимых узлов"
            elif unused:
                why = (
                    f"в него ведёт только переход «иначе» узла «{unused[0]}», а он не "
                    f"сработает: попытки узла «{unused[0]}» не кончаются"
                )
            else:
                why = "в него не ведёт ни один переход"
            self._error(node_id, "unreachable", f"до узла нельзя дойти {where}: {why}")

    # --- Круги и ограничители ------------------------------------------------------------

    def _check_loops(self, level: _Level) -> None:
        """Каждый круг должен когда-нибудь кончиться.

        Сначала ищутся узлы, которые за запуск выполняются конечное число раз: у них есть
        ограничитель, счётчик которого не обнуляется, либо они не стоят ни в одном круге.
        Обычные переходы из таких узлов рано или поздно перестают срабатывать и из графа
        убираются. Так повторяется, пока находится что-то новое. Круг, который остался, —
        бесконечный.
        """
        nodes = [node_id for node_id in level.nodes if node_id in self.reachable[level.owner]]
        finite: set[str] = set()

        def steps(node_id: str) -> list[str]:
            return level.steps(node_id, exhausted=node_id in finite)

        def meet(a: str, b: str) -> bool:
            """Можно ли ходить от `a` к `b` и обратно сколько угодно раз."""
            return b in _reach(steps, steps(a)) and a in _reach(steps, steps(b))

        while True:
            looping = {node_id for node_id in nodes if meet(node_id, node_id)}
            found = {node_id for node_id in nodes if node_id not in looping}
            for node_id in looping:
                limit = level.limit(node_id)
                if limit is None:
                    continue
                # Обнуление мешает ограничителю, только если узел, который обнуляет, может
                # выполняться между проходами этого узла снова и снова. Узел снаружи тела
                # «для каждого» внутри одного элемента не выполняется вовсе.
                resets = limit.reset_on if limit.reset_on in nodes else None
                if resets is None or resets in finite or not meet(node_id, resets):
                    found.add(node_id)
            if found <= finite:
                break
            finite |= found

        reported: set[str] = set()
        for node_id in nodes:
            if node_id not in looping or node_id in reported:
                continue
            circle = _circle(steps, node_id)
            reported |= {
                other
                for other in looping
                if other in _reach(steps, [node_id]) and node_id in _reach(steps, [other])
            }
            self._error(node_id, "unbounded_loop", self._explain_loop(level, circle, finite))

    def _explain_loop(self, level: _Level, circle: list[str], finite: set[str]) -> str:
        path = " → ".join([*circle, circle[0]])
        head = f"круг {path} может повторяться без конца"
        pairs = list(zip(circle, [*circle[1:], circle[0]], strict=True))
        limited = [node_id for node_id in circle if level.limit(node_id) is not None]
        # Ограничитель считает только тогда, когда узел выполняется и идёт дальше по кругу.
        # Узел из `finite` свои попытки рано или поздно тратит и дальше ходит только «иначе».
        counting = [
            a for a, b in pairs if a in limited and a not in finite and b in level.moves.get(a, [])
        ]
        if not limited:
            return f"{head}: ни у одного узла в нём нет ограничителя. Поставь ограничитель"
        if not counting:
            names = ", ".join(f"«{node_id}»" for node_id in limited)
            return (
                f"{head}: когда попытки у {names} кончаются, переход «иначе» ведёт по тому же "
                "кругу, и ни один узел с ограничителем в нём уже не выполняется"
            )
        node_id = counting[0]
        resets = level.limit(node_id).reset_on
        where = (
            "а он стоит в этом же круге"
            if resets in circle
            else "а он сам может выполняться без конца"
        )
        return (
            f"{head}: счётчик ограничителя узла «{node_id}» обнуляется на узле «{resets}», {where}"
        )

    # --- Чтение ещё не записанного -------------------------------------------------------

    def _check_written(self, node_id: str, what: str, bound: str | list[str]) -> None:
        """Хотя бы один из источников должен выполняться раньше узла, который его читает."""
        refs = bound if isinstance(bound, list) else [bound]
        sources = [ref.split(".")[0] for ref in refs]
        if any(self._may_run_before(source, node_id) for source in sources):
            return
        read = ", ".join(f"«{ref}»" for ref in refs)
        if len(refs) == 1:
            why = f"узел «{sources[0]}» не выполняется раньше этого узла"
        else:
            names = ", ".join(f"«{source}»" for source in dict.fromkeys(sources))
            why = f"ни один из узлов {names} не выполняется раньше этого узла"
        self._error(node_id, "never_written", f"{what} читает {read}, но {why}")

    def _may_run_before(self, source: str, reader: str) -> bool:
        """Есть ли путь, на котором `source` выполняется раньше `reader`.

        Ссылки, которые никуда не ведут или нарушают видимость, уже названы проверкой
        стыковки — здесь они пропускаются.
        """
        if source not in self.home:
            return True
        # Поднимаемся от читающего узла к уровню, на котором стоит источник.
        anchor: str | None = reader
        while anchor is not None and self.home[anchor] != self.home[source]:
            anchor = self.home[anchor]
        if anchor is None:
            return True
        if anchor == source and anchor != reader:
            # Источник — «для каждого», в теле которого стоит читающий узел: `item` там есть.
            return True
        level = self.levels[self.home[source]]
        return anchor in level.reach(level.steps(source))

    # --- Блок: настройки, инструменты, Подтверждение -------------------------------------

    def _check_block(self, node: BlockNode, manifest: Manifest) -> None:
        for port in manifest.inputs:
            if port.required and port.name in node.inputs:
                self._check_written(
                    node.id, f"обязательный вход «{port.name}»", node.inputs[port.name]
                )
        for message in config_problems(node.config, manifest.config, self.params):
            self._error(node.id, "bad_config", message)
        for message in tool_problems(manifest, self.manifests):
            self._error(node.id, "tool_with_side_effects", f"блок «{manifest.id}»: {message}")
        if manifest.side_effects and self._is_unguarded(node.id):
            self.warnings.append(
                Problem(
                    node.id,
                    "no_approval",
                    f"блок «{manifest.id}» действует во внешнем мире, а до узла можно дойти, "
                    "минуя Подтверждение преподавателя",
                )
            )

    def _is_approval(self, node: Any) -> bool:
        manifest = self.manifests.get(node.block) if isinstance(node, BlockNode) else None
        return manifest is not None and manifest.kind is Kind.APPROVAL

    def _is_unguarded(self, node_id: str) -> bool:
        """Можно ли дойти до узла от старта, не пройдя ни одного Подтверждения.

        Узел в теле «для каждого» защищён и тогда, когда Подтверждение стоит перед самим
        «для каждого».
        """
        home = self.home[node_id]
        if node_id not in self.unguarded[home]:
            return False
        return home is None or self._is_unguarded(home)


def _reach(steps: Any, starts: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    queue = list(starts)
    while queue:
        node_id = queue.pop()
        if node_id not in seen:
            seen.add(node_id)
            queue += steps(node_id)
    return seen


def _circle(steps: Any, start: str) -> list[str]:
    """Кратчайший круг через узел `start`: список узлов без повтора первого в конце."""
    paths = [[start]]
    seen = {start}
    while paths:
        path = paths.pop(0)
        for target in steps(path[-1]):
            if target == start:
                return path
            if target not in seen:
                seen.add(target)
                paths.append([*path, target])
    return [start]


# --- Настройки узла по схеме блока -------------------------------------------------------

_TYPE_NAMES = {
    "string": "текст",
    "integer": "целое число",
    "number": "число",
    "boolean": "да или нет",
    "array": "список",
    "object": "набор полей",
    "null": "пустое значение",
}
_PARAM_NAMES = {
    ParamType.STRING: "текст",
    ParamType.INTEGER: "целое число",
    ParamType.NUMBER: "число",
    ParamType.BOOLEAN: "да или нет",
}
# Какому типу из схемы настроек подходит параметр: целое годится и там, где ждут число.
_PARAM_FITS = {
    ParamType.STRING: {"string"},
    ParamType.INTEGER: {"integer", "number"},
    ParamType.NUMBER: {"number"},
    ParamType.BOOLEAN: {"boolean"},
}
_BOUNDS = {
    "minimum": "меньше допустимого",
    "exclusiveMinimum": "должно быть больше",
    "maximum": "больше допустимого",
    "exclusiveMaximum": "должно быть меньше",
}

# Проверки, которым нужно само значение. Если внутри настройки стоит параметр пайплайна,
# значение узнаем только при назначении — такие проверки пропускаются.
_NEEDS_VALUE = {"anyOf", "oneOf", "not", "contains", "uniqueItems", "const", "enum"}

Path = tuple[str | int, ...]


def config_problems(
    config: dict[str, Any], schema: dict[str, Any], params: Mapping[str, Param]
) -> list[str]:
    """Чем настройки узла расходятся со схемой `config` блока; пусто — всё в порядке.

    Значение параметра пайплайна известно только при назначении, поэтому там, где стоит
    ссылка `{"$param": "имя"}`, сверяется тип параметра, а не значение.
    """
    refs: dict[Path, str] = {}
    plain = _without_params(config, (), refs)
    problems = []
    try:
        errors = list(Draft202012Validator(schema).iter_errors(plain))
    except Exception as error:
        # Схему пишет автор блока. Ссылка `$ref` в никуда проверку манифеста проходит и
        # обнаруживается только здесь.
        return [f"схема настроек блока неисправна: {type(error).__name__}: {error}"]
    for error in errors:
        path = tuple(error.absolute_path)
        inside = any(ref[: len(path)] == path for ref in refs)
        if path in refs or (inside and error.validator in _NEEDS_VALUE):
            continue
        problems.append(_explain(error, path))
    for path, name in refs.items():
        param, expected = params.get(name), _schema_at(schema, path).get("type")
        if param is None or expected is None:
            continue
        allowed = set(expected) if isinstance(expected, list) else {expected}
        if not allowed & _PARAM_FITS[param.type]:
            wanted = " или ".join(_TYPE_NAMES.get(kind, kind) for kind in sorted(allowed))
            problems.append(
                f"{_setting(path)}: сюда подставляется параметр «{name}» "
                f"({_PARAM_NAMES[param.type]}), а нужно: {wanted}"
            )
    return list(dict.fromkeys(problems))


def _without_params(value: Any, path: Path, refs: dict[Path, str]) -> Any:
    """Копия настроек, где на месте ссылок на параметры пусто; сами ссылки — в `refs`."""
    if isinstance(value, dict):
        if set(value) == {"$param"}:
            refs[path] = value["$param"]
            return None
        return {key: _without_params(item, (*path, key), refs) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_params(item, (*path, index), refs) for index, item in enumerate(value)]
    return value


def _schema_at(schema: dict[str, Any], path: Path) -> dict[str, Any]:
    """Часть схемы, которая описывает значение по пути; пусто — если схема о нём молчит."""
    for key in path:
        inner = (
            schema.get("items") if isinstance(key, int) else schema.get("properties", {}).get(key)
        )
        if not isinstance(inner, dict):
            return {}
        schema = inner
    return schema


def _setting(path: Path) -> str:
    return "настройка «" + ".".join(str(part) for part in path) + "»" if path else "настройки"


def _explain(error: ValidationError, path: Path) -> str:
    """Ошибка JSON Schema по-русски: какая настройка и что с ней не так."""
    kind, expected, value = error.validator, error.validator_value, error.instance
    if kind == "required":
        missing = ", ".join(f"«{name}»" for name in expected if name not in value)
        if path:
            return f"{_setting(path)}: не заполнено обязательное поле {missing}"
        return f"не заполнена обязательная настройка {missing}"
    where = _setting(path)
    if kind == "type":
        kinds = expected if isinstance(expected, list) else [expected]
        wanted = " или ".join(_TYPE_NAMES.get(item, item) for item in kinds)
        return f"{where}: нужно {wanted}, а записано {value!r}"
    if kind == "enum":
        allowed = ", ".join(str(item) for item in expected)
        return f"{where}: значение {value!r} не из списка; допустимо: {allowed}"
    if kind in _BOUNDS:
        return f"{where}: значение {value!r} {_BOUNDS[kind]} {expected}"
    if kind == "additionalProperties":
        known = set(error.schema.get("properties", {}))
        extra = ", ".join(f"«{name}»" for name in value if name not in known)
        return f"{where}: у блока нет настройки {extra}"
    return f"{where}: не подходит под схему настроек блока ({error.message})"
