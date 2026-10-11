#!/bin/bash
# Хук Claude Code: после правки файла запускает форматтер и линтер.
# На вход (stdin) приходит JSON с описанием правки.
# Если нужного инструмента ещё нет (до задачи 01) — молча выходит.
# Если линтер нашёл ошибки, которые не смог исправить сам, — сообщает о них Claude (код выхода 2).

f=$(jq -r '.tool_input.file_path // (.tool_response | objects | .filePath) // empty' 2>/dev/null)
[ -n "$f" ] && [ -f "$f" ] || exit 0

root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -n "$root" ] || exit 0
case "$f" in "$root"/*) ;; *) exit 0 ;; esac

status=0

# Python: ruff format и ruff check --fix
if [[ "$f" == *.py ]]; then
  ruff=()
  if command -v ruff >/dev/null 2>&1; then
    ruff=(ruff)
  else
    # ищем ближайший pyproject.toml вверх от файла и берём ruff из окружения проекта
    dir=$(dirname "$f")
    while [[ "$dir" == "$root"* ]]; do
      if [ -f "$dir/pyproject.toml" ]; then
        if (cd "$dir" && uv run --no-sync ruff --version >/dev/null 2>&1); then
          cd "$dir" && ruff=(uv run --no-sync ruff)
        fi
        break
      fi
      [ "$dir" = "$root" ] && break
      dir=$(dirname "$dir")
    done
  fi
  if [ ${#ruff[@]} -gt 0 ]; then
    "${ruff[@]}" format --quiet "$f" >&2 || status=2
    "${ruff[@]}" check --fix --quiet "$f" >&2 || status=2
  fi
fi

# Фронтенд: prettier и eslint
if [[ "$f" == "$root"/frontend/* ]]; then
  bin=""
  for candidate in "$root/frontend/node_modules/.bin" "$root/node_modules/.bin"; do
    [ -d "$candidate" ] && bin="$candidate" && break
  done
  if [ -n "$bin" ]; then
    cd "$root/frontend" || exit 0
    if [ -x "$bin/prettier" ]; then
      "$bin/prettier" --write --ignore-unknown --log-level warn "$f" >&2 || status=2
    fi
    if [ -x "$bin/eslint" ] && [[ "$f" =~ \.(ts|tsx|js|jsx)$ ]]; then
      "$bin/eslint" --fix "$f" >&2 || status=2
    fi
  fi
fi

exit $status
