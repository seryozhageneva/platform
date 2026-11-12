# Образы платформы для сервера (задача 24a, ADR 0030). Собираются командой
#   docker compose -f docker-compose.prod.yml build
# Три готовых образа из одного файла:
#   platform — API и рабочий процесс очереди (один код, разные команды запуска);
#   sandbox  — песочница для кода: тот же код плюс программа docker, чтобы запускать
#              одноразовые контейнеры с программами учеников;
#   web      — Caddy с собранным фронтендом: принимает запросы из интернета и включает HTTPS.
# Секреты в образ не попадают: .env и certs/ исключены в .dockerignore и подключаются при запуске.

# --- Сборка фронтенда -------------------------------------------------------------------
FROM node:24-slim AS frontend
WORKDIR /src/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
# Только сборка, без проверки типов (`pnpm build` = tsc + vite): tsc проверяет и тесты, а они
# берут примеры из docs/, которых в образе нет. Типы проверяет CI на каждом pull request.
RUN pnpm exec vite build

# --- API и рабочий процесс --------------------------------------------------------------
FROM python:3.12-slim AS platform
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /app
# Сначала только библиотеки: этот слой пересобирается, лишь когда меняется uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project \
    && python -c "from zoneinfo import ZoneInfo; ZoneInfo('Europe/Moscow')"
COPY alembic.ini ./
COPY backend backend
COPY blocks blocks
COPY mcp_servers mcp_servers
COPY services services
# Проверяем, что адаптеры уведомлений загружаются из собранного образа.
RUN python -c "import mcp_servers.email.server; import mcp_servers.telegram.server; import mcp_servers.cloud.server"
# Сервер работает не от имени администратора контейнера.
USER 10001:10001
CMD ["python", "-m", "backend.api"]

# --- Песочница --------------------------------------------------------------------------
FROM platform AS sandbox
COPY --from=docker:29-cli /usr/local/bin/docker /usr/local/bin/docker
# Песочнице нужен доступ к Docker сервера, а файл доступа (docker.sock) принадлежит
# администратору. Поэтому она работает от его имени (ограничение записано в ADR 0030).
USER root
CMD ["uvicorn", "services.sandbox.app:app", "--host", "0.0.0.0", "--port", "8001"]

# --- Caddy и фронтенд -------------------------------------------------------------------
FROM caddy:2 AS web
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /src/frontend/dist /srv
