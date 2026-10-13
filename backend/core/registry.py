"""Реестр блоков: находит установленные блоки по файлам `block.yaml`.

Блок — папка с манифестом `block.yaml`. Реестр обходит папку с блоками, читает каждый
манифест и для встроенного блока находит его функцию `run` по строке `entrypoint`. Блоки он
подключает по имени-строке, а не обычным импортом: ядро не знает ни одного конкретного блока
(правило 4, ADR 0003). Решения — ADR 0011.

Сломанный блок не загружается и остальным не мешает: причина попадает в `problems`.
"""

import importlib
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core.contracts.base import ContractError
from backend.core.contracts.manifest import Manifest, PythonRuntime, load_manifest
from backend.core.contracts.run import BlockRun
from backend.core.engine import LoadedBlock
from backend.core.validator import tool_problems

MANIFEST_FILE = "block.yaml"
# Папка встроенных блоков платформы.
BUILTIN_BLOCKS = Path(__file__).resolve().parents[2] / "blocks"

# Способ вызова: по манифесту блока `mcp` или `http` даёт функцию с интерфейсом `run`.
# Ядро в сеть не ходит, поэтому способы вызова реестру передаёт слой сборки (ADR 0006).
Connector = Callable[[Manifest], BlockRun]


@dataclass(frozen=True)
class LoadProblem:
    """Почему блок не загружен: файл манифеста и причина."""

    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class _Refused(Exception):
    """Блок не берётся в реестр; текст — причина для `LoadProblem`."""


@dataclass(frozen=True)
class Registry:
    # Все исправные блоки: по ним работает валидатор и строится палитра редактора.
    manifests: dict[str, Manifest]
    # Блоки, которые можно вызвать, — таблица блоков для движка. Блока `mcp` или `http`
    # здесь нет, пока слой сборки не передал способ вызова.
    blocks: dict[str, LoadedBlock]
    problems: list[LoadProblem]


def load_registry(root: Path, connectors: Mapping[str, Connector] | None = None) -> Registry:
    """Загружает все блоки из папки `root`.

    Папка, в которой лежит `root`, должна быть в путях поиска Python: модуль блока
    подключается под именем «имя_папки.путь.к.блоку».
    """
    connectors = connectors or {}
    manifests: dict[str, Manifest] = {}
    sources: dict[str, Path] = {}
    blocks: dict[str, LoadedBlock] = {}
    problems: list[LoadProblem] = []
    # Описания уточнений `Data`: название -> (блок, схема). Порты стыкуются по названию
    # уточнения (ADR 0004), поэтому одно название — одно описание.
    shapes: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in sorted(root.rglob(MANIFEST_FILE)):
        try:
            manifest = _read(path)
            if manifest.id in manifests:
                raise _Refused(
                    f"имя блока «{manifest.id}» уже занято блоком из {sources[manifest.id]}"
                )
            described = _shapes(manifest, shapes)
            if isinstance(manifest.runtime, PythonRuntime):
                run: BlockRun | None = _find_run(root, path, manifest.runtime.entrypoint)
            else:
                run = _connect(manifest, connectors.get(manifest.runtime.type))
        except _Refused as refused:
            problems.append(LoadProblem(path, str(refused)))
            continue
        manifests[manifest.id], sources[manifest.id] = manifest, path
        shapes.update(described)
        if run is not None:
            blocks[manifest.id] = LoadedBlock(manifest, run)
    # Инструменты агента сверяются, когда известны все блоки: «с последствиями» — тот
    # инструмент, которым пользуется блок с `side_effects`.
    for block_id, found in [(name, tool_problems(m, manifests)) for name, m in manifests.items()]:
        if found:
            problems += [LoadProblem(sources[block_id], message) for message in found]
            del manifests[block_id]
            blocks.pop(block_id, None)
    return Registry(manifests, blocks, problems)


def _read(path: Path) -> Manifest:
    try:
        return load_manifest(path)
    except ContractError as error:
        raise _Refused("; ".join(error.problems)) from error
    except UnicodeDecodeError as error:
        raise _Refused("файл не читается: сохрани его в кодировке UTF-8") from error
    except OSError as error:
        raise _Refused(f"файл не читается: {type(error).__name__}: {error}") from error


def _connect(manifest: Manifest, connect: Connector | None) -> BlockRun | None:
    """Функция блока `mcp` или `http`; None — способа вызова пока нет."""
    if connect is None:
        return None
    try:
        return connect(manifest)
    except Exception as error:
        raise _Refused(
            f"способ вызова «{manifest.runtime.type}» не подключил блок: "
            f"{type(error).__name__}: {error}"
        ) from error


def _shapes(
    manifest: Manifest, known: Mapping[str, tuple[str, dict[str, Any]]]
) -> dict[str, tuple[str, dict[str, Any]]]:
    """Описания уточнений из манифеста; отказ, если название уже описано по-другому."""
    found: dict[str, tuple[str, dict[str, Any]]] = {}
    for port in (*manifest.inputs, *manifest.outputs):
        if port.of is None or port.json_schema is None:
            continue
        owner, schema = found.get(port.of) or known.get(port.of) or (manifest.id, port.json_schema)
        if schema != port.json_schema:
            where = (
                "в другом порту этого же блока" if owner == manifest.id else f"в блоке «{owner}»"
            )
            raise _Refused(
                f"порт «{port.name}»: данные «{port.of}» описаны иначе, чем {where}. "
                "Порты стыкуются по названию данных, поэтому разные данные называются по-разному"
            )
        found[port.of] = (owner, schema)
    return found


def _find_run(root: Path, path: Path, entrypoint: str) -> BlockRun:
    """Функция блока по строке «модуль:функция» из манифеста."""
    module_name, function_name = entrypoint.split(":")
    # Манифест указывает только на код своего блока: чужую функцию назвать блоком нельзя.
    package = ".".join([root.name, *path.parent.relative_to(root).parts])
    if module_name != package and not module_name.startswith(package + "."):
        raise _Refused(
            f"`entrypoint` указывает на модуль «{module_name}», а код блока лежит в «{package}»"
        )
    # Папка внутри папки блока может быть отдельным блоком со своим манифестом.
    folder = path.parent
    for part in module_name.split(".")[len(package.split(".")) :]:
        folder = folder / part
        if (folder / MANIFEST_FILE).exists():
            raise _Refused(
                f"`entrypoint` указывает на модуль «{module_name}», а это код другого блока: "
                f"у него свой манифест {folder / MANIFEST_FILE}"
            )
    try:
        module = importlib.import_module(module_name)
    # SystemExit — не Exception: блок, который при загрузке завершает программу,
    # не должен остановить платформу.
    except (Exception, SystemExit) as error:
        raise _Refused(
            f"модуль «{module_name}» не загрузился: {type(error).__name__}: {error}"
        ) from error
    origin = getattr(module, "__file__", None)
    if origin is None:
        # Папка без файлов Python подключается как пустой модуль.
        raise _Refused(f"в модуле «{module_name}» нет кода: в папке блока нет файла `__init__.py`")
    if path.parent.resolve() not in Path(origin).resolve().parents:
        raise _Refused(
            f"модуль «{module_name}» загрузился не из папки блока, а из {origin}: "
            "проверь, что папка с блоками есть в путях поиска Python и имя не занято"
        )
    run = getattr(module, function_name, None)
    if run is None:
        raise _Refused(f"в модуле «{module_name}» нет функции «{function_name}»")
    if not inspect.iscoroutinefunction(run):
        raise _Refused(
            f"«{module_name}:{function_name}» должна быть объявлена как `async def`: "
            "движок ждёт результат блока, не останавливая остальные запуски"
        )
    return run
