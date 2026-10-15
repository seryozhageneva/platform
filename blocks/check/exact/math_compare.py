"""Разбор короткого ответа и сравнение с эталоном как математических выражений (ADR 0017).

Строка ученика никогда не выполняется как код Python: её читает свой небольшой разборщик и
сразу строит выражение SymPy. Школьный LaTeX (`\\frac`, `\\sqrt`, `^{}`, `\\pi`, `\\sin`, `\\log_2`)
сначала переводится в обычную запись, дальше разбор общий.

Понимает: числа с точкой или запятой, `+ - * / : ^ **`, скобки, модуль `|x|`, умножение без
знака (`2x`, `2(x+1)`), функции `sqrt root sin cos tan tg cot ctg ln lg log exp abs` со скобками
и без (`sin x`, `sin^2 x`, `log_2 8`, `root_3(x)`), константы `pi` и `e`, однобуквенные переменные.
Несколько ответов разделяются `;` или запятой (`2; 3`), `x = 3` читается как `3`.

Перед вычислением выражение проверяется на размер: огромная степень или число сделали бы
из проверки одного ответа зависание сервера. По той же причине сравнение не упрощает выражения
(упрощение `(x+y+z+1)^100` не кончается и за минуту), а считает их значения в точках.
"""

import cmath
import random
import re

from sympy import (
    Abs,
    Add,
    E,
    Expr,
    Float,
    Integer,
    Max,
    Mul,
    Pow,
    Rational,
    Symbol,
    cos,
    cot,
    exp,
    log,
    pi,
    postorder_traversal,
    sign,
    sin,
    tan,
)

MAX_LENGTH = 200
MAX_EXPONENT = 100
MAX_NUMBER = 1e100
# Сколько раз степень может стоять в показателе степени: x^(x^(x^2)) — три.
MAX_TOWER = 3
# Совпадение в случайных точках: сколько точек, сколько знаков считать и какое расхождение
# считать погрешностью счёта. Ответ короче 200 символов не приблизит иррациональное число точнее
# 10^-200, так что приближённый ответ с калькулятора совпадением не сочтётся.
POINTS = 5
POINT_TRIES = 20
DIGITS = 300
TOLERANCE = Float("1e-250", DIGITS)


class Unreadable(ValueError):
    """Строку не удалось прочитать как ответ.

    Текст ошибки не цитирует саму строку: ошибка разбора эталона попадает в журнал запуска.
    """


def read(text: str | None) -> list[Expr]:
    """Ответ — список выражений: обычно одно, у уравнения с несколькими корнями — несколько."""
    if text is None or not text.strip():
        raise Unreadable("пустой ответ")
    if len(text) > MAX_LENGTH:
        raise Unreadable(f"ответ длиннее {MAX_LENGTH} символов")
    source = text.strip().strip("$")
    if "\\" in source or "{" in source or "}" in source:
        source = _from_latex(source)
    source = _normalize(source)
    return [_read_one(part) for part in _split(source)]


def same(answer: list[Expr], reference: list[Expr]) -> bool:
    """Совпадают ли ответы как наборы: порядок не важен, число ответов — важно."""
    if len(answer) != len(reference):
        return False
    rest = list(reference)
    for given in answer:
        found = next((i for i, expected in enumerate(rest) if _equal(given, expected)), None)
        if found is None:
            return False
        rest.pop(found)
    return True


# --- Сравнение -------------------------------------------------------------------------------


def _equal(given: Expr, expected: Expr) -> bool:
    difference = given - expected
    # SymPy сам сокращает простое при вычислении: x + 1 - (1 + x) — это уже 0.
    # Разность двух дробей — точная дробь: для чисел вроде 0,5 и 1/2 точки не нужны.
    if difference == 0 or difference.is_Rational:
        return difference == 0
    return _close_everywhere(given, expected)


def _close_everywhere(given: Expr, expected: Expr) -> bool:
    symbols = sorted(given.free_symbols | expected.free_symbols, key=str)
    needed = POINTS if symbols else 1
    # Одни и те же точки при каждом запуске: вердикт не должен зависеть от случая.
    rng = random.Random(0)
    checked = 0
    for _ in range(POINT_TRIES):
        point = {symbol: Rational(rng.randint(-300, 300), 100) for symbol in symbols}
        a, b = _value_at(given, point), _value_at(expected, point)
        # В этой точке выражение не определено (деление на ноль, логарифм нуля) — берём другую.
        if a is None or b is None:
            continue
        if not bool(Abs(a - b).evalf(DIGITS) <= TOLERANCE * Max(1, Abs(a), Abs(b)).evalf(DIGITS)):
            return False
        checked += 1
        if checked == needed:
            return True
    return False


def _value_at(expr: Expr, point: dict[Symbol, Rational]) -> Expr | None:
    try:
        value = expr.evalf(DIGITS, subs=point)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None
    return value if value.is_number and value.is_finite else None


# --- Проверка размера ------------------------------------------------------------------------


def _check_size(expr: Expr) -> None:
    if _tower(expr) > MAX_TOWER:
        raise Unreadable("слишком много степеней друг в друге")
    # Снизу вверх: к узлу переходим, когда его части уже проверены и не огромны.
    for node in postorder_traversal(expr):
        if isinstance(node, Pow) and not node.exp.free_symbols:
            if abs(_constant(node.exp)) > MAX_EXPONENT:
                raise Unreadable(f"показатель степени больше {MAX_EXPONENT}")
        if isinstance(node, Expr) and not node.free_symbols:
            if abs(_constant(node)) > MAX_NUMBER:
                raise Unreadable("слишком большое число")


def _tower(expr: Expr) -> int:
    if isinstance(expr, Pow):
        return max(_tower(expr.base), 1 + _tower(expr.exp))
    if isinstance(expr, exp):
        return 1 + _tower(expr.args[0])
    return max((_tower(arg) for arg in expr.args), default=0)


def _constant(expr: Expr) -> complex:
    """Приближённое значение выражения без переменных; точное ещё не вычислено."""
    try:
        value = complex(expr.evalf(15))
    except OverflowError:
        raise Unreadable("слишком большое число") from None
    except (TypeError, ValueError, ZeroDivisionError):
        raise Unreadable("выражение не имеет числового значения") from None
    if cmath.isinf(value):
        raise Unreadable("слишком большое число")
    if not cmath.isfinite(value):
        raise Unreadable("выражение не имеет числового значения")
    return value


# --- Подготовка строки -----------------------------------------------------------------------

_SYMBOLS = {
    "−": "-",
    "–": "-",
    "·": "*",
    "∙": "*",
    "×": "*",
    "÷": "/",
    ":": "/",
    "√": " sqrt ",
    "π": " pi ",
    "²": "^2",
    "³": "^3",
}
# Левая часть `x = 3`: одна буква, возможно с номером (`x1`, `x_1`, из LaTeX — `x_(1)`).
_VARIABLE = re.compile(r"[A-Za-z](?:_?\(?\d+\)?)?")


def _normalize(source: str) -> str:
    for symbol, replacement in _SYMBOLS.items():
        source = source.replace(symbol, replacement)
    # Запятая между цифрами без пробела — десятичная: «0,5». Иначе она разделяет ответы.
    return re.sub(r"(?<=\d),(?=\d)", ".", source)


def _split(source: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for i, char in enumerate(source):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char in ";," and depth == 0:
            parts.append(source[start:i])
            start = i + 1
    parts.append(source[start:])
    return parts


def _read_one(part: str) -> Expr:
    left, equals, right = part.partition("=")
    if equals:
        if "=" in right or not _VARIABLE.fullmatch(left.strip()):
            raise Unreadable("вместо ответа записано уравнение")
        part = right
    expr = _Parser(_tokens(part)).parse()
    _check_size(expr)
    # Разборщик строит выражение «как записано»; вычисляем только после проверки размера.
    return expr.doit()


# --- LaTeX -> обычная запись -----------------------------------------------------------------

_LATEX_WORDS = {
    "cdot": "*",
    "times": "*",
    "div": "/",
    "pi": " pi ",
    "sin": " sin ",
    "cos": " cos ",
    "tan": " tan ",
    "tg": " tan ",
    "cot": " cot ",
    "ctg": " cot ",
    "ln": " ln ",
    "lg": " lg ",
    "log": " log ",
    "exp": " exp ",
    "left": "",
    "right": "",
    "lvert": "|",
    "rvert": "|",
}
_COMMAND = re.compile(r"\\([A-Za-z]+)")


def _from_latex(source: str) -> str:
    # `{,}` — так редакторы формул пишут десятичную запятую; `\,` `\;` `~` — пробелы.
    text = source.replace("{,}", ".")
    text = re.sub(r"\\[,;:! ]|~", " ", text)
    converted, _ = _latex_until(text, 0, closing=None)
    return converted


def _latex_until(s: str, i: int, closing: str | None) -> tuple[str, int]:
    out: list[str] = []
    while i < len(s):
        char = s[i]
        if char == closing:
            return "".join(out), i + 1
        if char == "}":
            raise Unreadable("лишняя закрывающая скобка")
        if char == "{":
            inner, i = _latex_until(s, i + 1, closing="}")
            out.append(f"({inner})")
        elif char in "^_":
            arg, i = _latex_arg(s, i + 1)
            out.append(f"{char}({arg})")
        elif char == "\\":
            piece, i = _latex_command(s, i)
            out.append(piece)
        else:
            out.append(char)
            i += 1
    if closing is not None:
        raise Unreadable("не закрыта скобка")
    return "".join(out), i


def _latex_command(s: str, i: int) -> tuple[str, int]:
    match = _COMMAND.match(s, i)
    if match is None:
        raise Unreadable("незнакомая команда LaTeX")
    name, i = match.group(1), match.end()
    if name in ("frac", "dfrac", "tfrac"):
        top, i = _latex_arg(s, i)
        bottom, i = _latex_arg(s, i)
        return f"(({top})/({bottom}))", i
    if name == "sqrt":
        degree = None
        if s.startswith("[", i):
            end = s.find("]", i)
            if end < 0:
                raise Unreadable("не закрыта скобка")
            degree, _ = _latex_until(s[i + 1 : end], 0, closing=None)
            i = end + 1
        radicand, i = _latex_arg(s, i)
        if degree is None:
            return f"sqrt({radicand})", i
        return f"root_({degree})({radicand})", i
    if name == "operatorname":
        word, i = _latex_arg(s, i)
        return f" {word} ", i
    if name in _LATEX_WORDS:
        return _LATEX_WORDS[name], i
    raise Unreadable("незнакомая команда LaTeX")


def _latex_arg(s: str, i: int) -> tuple[str, int]:
    """Аргумент `\\frac`, `\\sqrt`, `^`, `_`: группа в фигурных скобках или один знак."""
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        raise Unreadable("оборвана запись")
    if s[i] == "{":
        return _latex_until(s, i + 1, closing="}")
    if s[i] == "\\":
        return _latex_command(s, i)
    return s[i], i + 1


# --- Разбор обычной записи -------------------------------------------------------------------

_FUNCTIONS = (
    "sqrt",
    "root",
    "sin",
    "cos",
    "tan",
    "tg",
    "cot",
    "ctg",
    "ln",
    "lg",
    "log",
    "abs",
    "exp",
)
# Длинные имена раньше коротких: в «sinx» сначала ищем «sin».
_NAMES = sorted((*_FUNCTIONS, "pi"), key=len, reverse=True)
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z]+)|(\*\*|[-+*/^()|_]))")


class _Token:
    def __init__(self, kind: str, value: object) -> None:
        self.kind = kind  # num, var, const, func, op
        self.value = value


def _tokens(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    while i < len(source):
        if source[i:].isspace():
            break
        match = _TOKEN.match(source, i)
        if match is None:
            raise Unreadable("в ответе есть непонятный знак")
        number, letters, op = match.groups()
        if number is not None:
            value = Rational(number) if "." in number else Integer(number)
            tokens.append(_Token("num", value))
        elif letters is not None:
            tokens.extend(_words(letters))
        else:
            tokens.append(_Token("op", "^" if op == "**" else op))
        i = match.end()
    return tokens


def _words(letters: str) -> list[_Token]:
    """Буквы подряд: имена функций и констант, остальное — однобуквенные переменные."""
    tokens: list[_Token] = []
    i = 0
    while i < len(letters):
        name = next((name for name in _NAMES if letters.startswith(name, i)), None)
        if name == "pi":
            tokens.append(_Token("const", pi))
        elif name is not None:
            tokens.append(_Token("func", name))
        elif letters[i] == "e":
            tokens.append(_Token("const", E))
            name = "e"
        else:
            tokens.append(_Token("var", Symbol(letters[i])))
            name = letters[i]
        i += len(name)
    return tokens


def _negative(expr: Expr) -> Expr:
    return Mul(Integer(-1), expr, evaluate=False)


def _apply(name: str, arg: Expr, base: Expr | None) -> Expr:
    if name == "sqrt":
        return Pow(arg, Rational(1, 2), evaluate=False)
    if name == "root":
        if base is None:
            raise Unreadable("у корня не указана степень")
        inverse = Pow(base, Integer(-1), evaluate=False)
        # Корень нечётной степени — школьный, действительный: корень 3-й степени из -8 равен -2.
        # Без этого SymPy берёт комплексный корень.
        if base.is_Integer and base.is_odd:
            real = Pow(Abs(arg, evaluate=False), inverse, evaluate=False)
            return Mul(sign(arg, evaluate=False), real, evaluate=False)
        return Pow(arg, inverse, evaluate=False)
    if name in ("ln", "lg", "log"):
        if name == "lg":
            base = Integer(10)
        if base is None:
            return log(arg, evaluate=False)
        inverse = Pow(log(base, evaluate=False), Integer(-1), evaluate=False)
        return Mul(log(arg, evaluate=False), inverse, evaluate=False)
    function = {
        "sin": sin,
        "cos": cos,
        "tan": tan,
        "tg": tan,
        "cot": cot,
        "ctg": cot,
        "abs": Abs,
        "exp": exp,
    }[name]
    return function(arg, evaluate=False)


class _Parser:
    """Разбор сверху вниз: сумма → произведение → знак → степень → атом.

    Выражение строится с `evaluate=False` — «как записано», без вычислений.
    """

    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.i = 0

    def parse(self) -> Expr:
        if not self.tokens:
            raise Unreadable("пустой ответ")
        expr = self.sum()
        if self.i != len(self.tokens):
            raise Unreadable("лишние знаки в ответе")
        return expr

    def peek(self) -> _Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> _Token:
        token = self.peek()
        if token is None:
            raise Unreadable("оборвана запись")
        self.i += 1
        return token

    def is_op(self, *ops: str) -> bool:
        token = self.peek()
        return token is not None and token.kind == "op" and token.value in ops

    def expect(self, op: str) -> None:
        if not self.is_op(op):
            raise Unreadable("не закрыта скобка")
        self.i += 1

    def starts_factor(self) -> bool:
        """Может ли здесь начаться множитель без знака умножения: `2x`, `2(x+1)`, `x sin x`.

        Число после множителя не начинает новый — «2 3» не читается как 6. Черта модуля
        тоже: иначе закрывающую черту не отличить от открывающей.
        """
        token = self.peek()
        if token is None:
            return False
        return token.kind in ("var", "const", "func") or self.is_op("(")

    def sum(self) -> Expr:
        expr = self.product()
        while self.is_op("+", "-"):
            sign = self.take().value
            term = self.product()
            expr = Add(expr, term if sign == "+" else _negative(term), evaluate=False)
        return expr

    def product(self) -> Expr:
        expr = self.signed()
        while True:
            if self.is_op("*", "/"):
                op = self.take().value
                factor = self.signed()
                if op == "/":
                    factor = Pow(factor, Integer(-1), evaluate=False)
                expr = Mul(expr, factor, evaluate=False)
            elif self.starts_factor():
                expr = Mul(expr, self.power(), evaluate=False)
            else:
                return expr

    def signed(self) -> Expr:
        if self.is_op("-"):
            self.take()
            return _negative(self.signed())
        if self.is_op("+"):
            self.take()
            return self.signed()
        return self.power()

    def power(self) -> Expr:
        base = self.atom()
        if self.is_op("^"):
            self.take()
            # Справа налево: 2^3^2 — это 2^9; -x^2 — это -(x^2).
            return Pow(base, self.signed(), evaluate=False)
        return base

    def atom(self) -> Expr:
        token = self.take()
        if token.kind in ("num", "var", "const"):
            return token.value  # type: ignore[return-value]
        if token.kind == "func":
            return self.function(str(token.value))
        if token.value == "(":
            expr = self.sum()
            self.expect(")")
            return expr
        if token.value == "|":
            expr = self.sum()
            self.expect("|")
            return Abs(expr, evaluate=False)
        raise Unreadable("оборвана запись")

    def function(self, name: str) -> Expr:
        base = None
        if name in ("log", "root") and self.is_op("_"):
            self.take()
            base = self.atom()
        power = None
        if self.is_op("^"):
            self.take()
            power = self.signed()
        if self.is_op("("):
            self.take()
            arg = self.sum()
            self.expect(")")
        else:
            arg = self.bare_argument(single=name in ("sqrt", "root"))
        result = _apply(name, arg, base)
        # sin^2 x — это (sin x)^2.
        return result if power is None else Pow(result, power, evaluate=False)

    def bare_argument(self, single: bool) -> Expr:
        """Аргумент без скобок: `sin 2x` — это sin(2x), а `√2x` — это √2·x, как в учебнике."""
        token = self.peek()
        if token is None or token.kind not in ("num", "var", "const"):
            raise Unreadable("у функции нет аргумента")
        arg = self.power()
        while not single and (token := self.peek()) is not None and token.kind in ("var", "const"):
            arg = Mul(arg, self.power(), evaluate=False)
        return arg
