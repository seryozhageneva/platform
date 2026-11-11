# Развёртывание платформы на сервере

Задача 24a, решения — в [ADR 0030](adr/0030-vps-deploy.md). Вся платформа запускается одним
набором контейнеров из `docker-compose.prod.yml`. Из интернета виден только Caddy: он
принимает запросы на портах 80 и 443, сам получает сертификат HTTPS и пересылает `/api/…`
серверу API. База, Redis, API, рабочий процесс и песочница видны только друг другу.

Адрес сервера, домен и пароли в репозиторий не попадают (правило 10): они записываются
только в файл `.env` на самом сервере.

## Сначала — репетиция на своём компьютере

Те же контейнеры можно запустить на Mac с адресом `https://localhost`. Так ошибки видны до
аренды сервера.

1. Допиши в `.env` строку `PLATFORM_DOMAIN=localhost`. Остальные переменные у тебя уже есть.
2. Собери образ для программ учеников и запусти платформу:

   ```bash
   docker build -t platform-code-runner:local services/sandbox
   ```

   ```bash
   docker compose -f docker-compose.prod.yml up -d --build --wait
   ```

   Первая сборка идёт несколько минут. Порты 80 и 443 на компьютере должны быть свободны.
3. Для `localhost` Caddy выпускает сертификат своим удостоверяющим центром. Достань его
   корневой сертификат, чтобы проверка ему доверяла:

   ```bash
   docker compose -f docker-compose.prod.yml cp web:/data/caddy/pki/authorities/local/root.crt tmp/caddy-root.crt
   ```

4. Заведи преподавателя в этой, отдельной от разработки, базе (шаг 6 ниже) и проверь:

   ```bash
   uv run python -m experiments.deploy_check https://localhost --ca-file tmp/caddy-root.crt --email demo.teacher@example.test
   ```

5. Остановить: `docker compose -f docker-compose.prod.yml down`. Данные остаются в томах
   Docker и вернутся при следующем запуске. Не оставляй набор запущенным после репетиции:
   порты 80 и 443 открыты для всей локальной сети (общий Wi-Fi), а не только для твоего Mac.

Все команды с `docker-compose.prod.yml`, включая `ps`, `logs` и `down`, требуют
`PLATFORM_DOMAIN` в `.env`. Без неё они останавливаются с подсказкой.

Браузер будет предупреждать о сертификате `localhost`: он не знает удостоверяющий центр
Caddy. На настоящем домене предупреждения не будет.

## Что нужно для сервера

- VPS в России: Ubuntu 24.04, от 2 ядер и 4 ГБ памяти, от 30 ГБ диска.
- Домен. В его настройках у регистратора — запись `A` с IP-адресом сервера.
- Открытые порты 22 (вход по SSH), 80 и 443.

## Шаги на сервере

Все команды — на сервере, после входа по SSH.

1. **Docker.** Поставь Docker Engine и плагин Compose по официальной инструкции для Ubuntu:
   <https://docs.docker.com/engine/install/ubuntu/>. Проверка: `docker compose version`.
2. **Код.** Репозиторий публичный, ключи для скачивания не нужны:

   ```bash
   git clone https://github.com/seryozhageneva/platform.git && cd platform
   ```

3. **Настройки.** Скопируй образец и заполни его:

   ```bash
   cp .env.example .env
   ```

   - `PLATFORM_DOMAIN` — домен сайта, без `https://`;
   - `LLM_PROVIDER`, `GIGACHAT_AUTH_KEY` — как на своём компьютере (ADR 0012);
   - `POSTGRES_PASSWORD` и `PLATFORM_SECRET_KEY` — новые, не те, что на компьютере. Команды,
     которые создают их, не показывая на экране, записаны в `.env.example`;
   - `DATABASE_URL` и `REDIS_URL` оставь пустыми: их задаёт `docker-compose.prod.yml`.

   Права на файл — только для себя: `chmod 600 .env`.
4. **Сертификат GigaChat.** Положи `Russian Trusted Root CA` в папку `certs/` (как в ADR 0012)
   и разреши его чтение контейнерам: `chmod 644 certs/*`. Это открытый сертификат, не секрет.
5. **Запуск:**

   ```bash
   docker build -t platform-code-runner:local services/sandbox
   ```

   ```bash
   docker compose -f docker-compose.prod.yml up -d --build --wait
   ```

   При запуске сами применяются миграции базы. Caddy за минуту получает сертификат
   Let's Encrypt; для этого домен уже должен указывать на сервер.
6. **Преподаватель.** Создай учётную запись. Команда дважды спросит пароль (от 12 символов);
   на экран он не выводится:

   ```bash
   docker compose -f docker-compose.prod.yml run --rm api python -m backend.api.create_teacher почта@пример --name 'Имя'
   ```

   Если запись уже есть, а пароля у неё нет, — то же с `--set-initial-password` вместо
   `--name 'Имя'` (ADR 0019).

7. **Проверка** — со своего компьютера, из папки репозитория:

   ```bash
   uv run python -m experiments.deploy_check https://домен --email почта@пример
   ```

   В выводе: «Платформа открывается по адресу: …». Это и есть гейт 2.

## Обновление версии

```bash
git pull
```

```bash
docker compose -f docker-compose.prod.yml up -d --build --wait
```

Новые миграции применяются сами. Если менялся `services/sandbox/Dockerfile` — пересобери и
образ для программ учеников (`docker build …` из шага 5).

## Полезное

- Состояние: `docker compose -f docker-compose.prod.yml ps`.
- Журнал API: `docker compose -f docker-compose.prod.yml logs api --tail 100`.
- Остановка: `docker compose -f docker-compose.prod.yml down` (данные сохраняются).

## Чего здесь пока нет

Резервных копий базы, наблюдения за сервером и автоматического обновления из GitHub. Это
записано в ADR 0030 как ограничения.
