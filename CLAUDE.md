@AGENTS.md

## Только для Claude Code

- Хук форматирования, разрешения и запрет читать `.env` — в `.claude/settings.json`. Личные настройки — в `.claude/settings.local.json`, он не коммитится.
- Ревьюер вызывается как субагент `reviewer`, план задачи — скилл `/next-task`.
