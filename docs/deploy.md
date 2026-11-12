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
- Журнал очереди и расписаний: `docker compose -f docker-compose.prod.yml logs worker --tail 100`.
- Остановка: `docker compose -f docker-compose.prod.yml down` (данные сохраняются).

Сервис `worker` каждую минуту проверяет включённые расписания (ADR 0032).
В редакторе у стартового узла можно указать, например, `0 18 * * 5` для запуска
по пятницам в 18:00 по Москве. После сохранения графа включи запуск в панели
«Расписание». После перезапуска рабочий процесс проверяет текущую минуту.

Тот же сервис `worker` раз в минуту смотрит включённые запуски по событию Moodle (ADR 0034).
Moodle каждого такого пайплайна он опрашивает раз в `poll_minutes` минут и создаёт один запуск
на все новые сданные работы. У стартового узла отметь «Запускать, когда в Moodle сдали работу»,
сохрани граф и включи запуск в панели «Событие Moodle». Там же видно время последней проверки
и ошибку, если Moodle не ответил. Токену Moodle нужны права на чтение работ и выставление
оценок. Новых переменных в `.env` и новых сервисов нет.

## Уведомления по почте и в Telegram

Отправители работают внутри образа платформы. Для почты укажи в локальном `.env` параметры
`PLATFORM_SMTP_HOST`, `PLATFORM_SMTP_USERNAME` и `PLATFORM_SMTP_PASSWORD`. Если почтовый сервис
требует пароль приложения, используй его. Порт по умолчанию — 465 с TLS. Для сервиса с
STARTTLS укажи `PLATFORM_SMTP_PORT=587`. Адрес отправителя `PLATFORM_SMTP_FROM` можно
оставить пустым, если почтовый логин совпадает с разрешённым адресом. Для работы MCP-блоков
также нужен `PLATFORM_SECRET_KEY`. На сервере API и worker получают эти параметры из
`env_file` в `docker-compose.prod.yml`. Для доставки нужен исходящий доступ к SMTP и
к `https://api.telegram.org`.

### Ручная проверка на своём компьютере

Используй отдельного демонстрационного преподавателя, выдуманных учеников, свой тестовый
ящик и личный чат со своим тестовым ботом. В чате сначала нажми «Старт». Номер личного чата
берётся из `message.chat.id` в ответе метода `getUpdates` тестового бота.
[Документация Telegram](https://core.telegram.org/bots/api#getupdates)

1. Примени миграции командой `uv run --locked --no-sync alembic upgrade head`. В отдельных
   терминалах запусти `uv run --locked --no-sync python -m backend.api` и
   `uv run --locked --no-sync arq backend.triggers.worker.WorkerSettings`.
   Для этого примера достаточно `LLM_PROVIDER=fake`.
2. В локальном `http://127.0.0.1:8000/docs` войди через `POST /api/v1/auth/teacher`. Сохрани
   токен тестового бота через `PUT /api/v1/connections/telegram`, передав только поле
   `token`. Используй токен только локально.
3. Создай двух тестовых учеников через `POST /api/v1/students`. Через
   `PUT /api/v1/students/{student_id}/notification-contacts` укажи одному только
   `telegram_id`, второму только `email`. Пропущенное поле или `null` очищает контакт.
4. Загрузи DOCX с коротким тестовым текстом через `POST /api/v1/files`. Сохрани граф
   [notifications-demo.json](examples/pipelines/notifications-demo.json) через
   `POST /api/v1/pipelines`. Запусти его через `POST /api/v1/pipelines/{pipeline_id}/runs`
   с телом `{"params": {"file_id": "<id файла>"}}`.
5. Через `GET /api/v1/runs/{run_id}` проверь статус `waiting`. Ящик и чат пока пусты.
   Подтверди обе тестовые строки в кабинете преподавателя. Через API то же действие
   выполняет `POST /api/v1/runs/{run_id}/responses`: передай `node_id` и `approval_id` из
   `waiting`, а в `response.rows` — по записи с `index` для каждой строки. Для любой лишней
   строки укажи `keep: false`.
6. Проверь статус `done`, письмо в ящике и сообщение в личном чате. Если сервис вернул
   ошибку или истёк таймаут, сначала проверь оба канала. Платформа показывает сбой в журнале
   и не повторяет отправку автоматически.

## Облако: Яндекс Диск

Блок «Источник: файл из облака» берёт файл с Яндекс Диска преподавателя (ADR 0036). Сервер
облака работает внутри образа платформы, новых переменных в `.env` и новых сервисов нет. Нужен
`PLATFORM_SECRET_KEY` и исходящий доступ к `https://cloud-api.yandex.net` и серверам
скачивания Диска (`*.yandex.ru`, `*.yandex.net`).

### Как получить токен

1. Зарегистрируй своё приложение на `https://oauth.yandex.ru` и дай ему только доступ на
   чтение Диска (`cloud_api:disk.read`, «Чтение всего Диска»). Запись не нужна: платформа
   Диск не меняет.
2. Получи отладочный токен для своего аккаунта по ссылке
   `https://oauth.yandex.ru/authorize?response_type=token&client_id=<ID приложения>`.
   [Документация Яндекса](https://yandex.ru/dev/id/doc/ru/tokens/debug-token)
3. Проверь токен без платформы: `uv run python -m experiments.cloud_check /путь/к/файлу.pdf`.
   Скрипт спросит токен и не покажет его на экране.

### Ручная проверка на своём компьютере

Положи на Диск выдуманную лекцию в DOCX или PDF, не работы учеников.

1. Запусти API и worker, как в разделе про уведомления, с `LLM_PROVIDER=fake`.
2. В `http://127.0.0.1:8000/docs` войди как демонстрационный преподаватель и сохрани токен
   через `PUT /api/v1/connections/cloud`, передав только поле `token`.
3. Сохрани граф [cloud-lecture-demo.json](examples/pipelines/cloud-lecture-demo.json) и запусти
   его с телом `{"params": {"lecture_path": "/Лекции/лекция.docx"}}`.
4. Конспект появится в кабинете преподавателя, а лекция — в его файлах. Если файла по пути
   нет, запуск закончится исходом `missing` у первого блока, без обращения к модели.

## Чего здесь пока нет

Резервных копий базы, наблюдения за сервером и автоматического обновления из GitHub. Это
записано в ADR 0030 как ограничения.
