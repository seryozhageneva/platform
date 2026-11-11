"""Наполнение тестового Moodle выдуманными данными (задача 23, ADR 0028).

Сначала подними тестовый Moodle (первый раз — несколько минут):
    docker compose -f docker-compose.moodle.yml up -d --wait
Затем:
    uv run python -m experiments.moodle_setup

Скрипт создаёт выдуманные файлы работ (PDF, DOCX и код на Python), копирует их в контейнер
и запускает там `experiments/moodle_seed.php`. Повторный запуск ничего не дублирует.
Печатает адрес Moodle и номера курса и задания — их вводят в настройки блока
«Источник: работы из Moodle». Токен на экран не выводится: его берёт `seed_test_moodle()`,
которой пользуются ручная проверка и тесты на настоящем Moodle.
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from docx import Document
from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.moodle.yml")]
FONT = ROOT / "blocks" / "sink" / "file" / "fonts" / "DejaVuSans.ttf"
SEED = Path(__file__).with_name("moodle_seed.php")
IN_CONTAINER = "/tmp/platform_seed"


@dataclass(frozen=True)
class TestMoodle:
    url: str
    course_id: int
    assignment_id: int
    token: str

    def __repr__(self) -> str:
        # Токен — секрет: в журнал и в сообщения об ошибках он попадать не должен.
        return (
            f"TestMoodle(url={self.url!r}, course_id={self.course_id}, "
            f"assignment_id={self.assignment_id}, token=***)"
        )


def _pdf(lines: list[str]) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", FONT)
    pdf.set_font("DejaVu", size=12)
    for line in lines:
        pdf.multi_cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _docx(lines: list[str]) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def work_files() -> dict[str, bytes]:
    """Выдуманные работы студентов: имя файла → содержимое."""
    return {
        "work1.pdf": _pdf(
            [
                "Контрольная работа. Студент 1.",
                "Задача: найти производную функции f(x) = x^2 + 3x.",
                "Решение: f'(x) = 2x + 3.",
            ]
        ),
        "work2.docx": _docx(
            [
                "Контрольная работа. Студент 2.",
                "Производная суммы равна сумме производных, поэтому f'(x) = 2x + 3.",
            ]
        ),
        "solution.py": b"def derivative(x):\n    return 2 * x + 3\n",
        "draft.pdf": _pdf(["Черновик: решение ещё не готово."]),
    }


def _compose(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        [*COMPOSE, *args], check=False, capture_output=True, text=True, cwd=ROOT
    )
    if result.returncode != 0:
        # Вывод PHP может содержать токен только в последней строке успешного запуска,
        # а здесь запуск не удался — показываем ошибку как есть.
        raise RuntimeError(
            f"docker compose {' '.join(args[:2])} не удался: {result.stderr.strip()}"
            f"\n{result.stdout.strip()}"
        )
    return result.stdout if capture else ""


def seed_test_moodle() -> TestMoodle:
    """Наполняет тестовый Moodle и возвращает адрес, номера курса и задания и токен."""
    with tempfile.TemporaryDirectory() as folder:
        for name, content in work_files().items():
            (Path(folder) / name).write_bytes(content)
        _compose("exec", "-T", "-u", "root", "moodle", "rm", "-rf", IN_CONTAINER)
        _compose("cp", folder, f"moodle:{IN_CONTAINER}")
    _compose("cp", str(SEED), f"moodle:{IN_CONTAINER}/seed.php")
    # Moodle в контейнере работает не от root: файлы должны быть ему доступны на чтение.
    _compose("exec", "-T", "-u", "root", "moodle", "chmod", "-R", "a+rX", IN_CONTAINER)
    output = _compose(
        "exec",
        "-T",
        "moodle",
        "php",
        f"{IN_CONTAINER}/seed.php",
        f"--files={IN_CONTAINER}",
        capture=True,
    )
    data = json.loads(output.strip().splitlines()[-1])
    return TestMoodle(
        url=data["url"],
        course_id=data["course_id"],
        assignment_id=data["assignment_id"],
        token=data["token"],
    )


def main() -> None:
    moodle = seed_test_moodle()
    print(f"Тестовый Moodle: {moodle.url}")
    print(f"Курс: {moodle.course_id}, задание: {moodle.assignment_id}")
    print("Сданы три работы (PDF, DOCX, код на Python), у четвёртого студента черновик.")


if __name__ == "__main__":
    main()
