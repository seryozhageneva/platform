"""Сборка слоя ИИ-моделей по настройкам: какой провайдер выбран в `.env`, тот и подключается."""

from backend.llm.client import CallLog, PlatformLLM
from backend.llm.gigachat import GigaChatProvider
from backend.llm.providers import LLMError, Provider, StubProvider
from backend.llm.settings import DEFAULT_MODEL, DEFAULT_SCOPE, ROOT, LLMSettings


def make_llm(
    settings: LLMSettings | None = None, *, call_log: CallLog | None = None
) -> PlatformLLM:
    """Слой моделей, готовый к передаче движку. Вызывает его слой сборки (задача 08)."""
    settings = settings or LLMSettings()
    return PlatformLLM(_provider(settings), call_log=call_log)


def _provider(settings: LLMSettings) -> Provider:
    name = settings.llm_provider.strip().lower()
    if name == "fake":
        return StubProvider()
    if name == "gigachat":
        return _gigachat(settings)
    if not name:
        raise LLMError(
            "config",
            "не выбран провайдер модели: впиши в файл .env LLM_PROVIDER=gigachat "
            "или LLM_PROVIDER=fake. Образец — в .env.example.",
        )
    raise LLMError(
        "config", f"неизвестный провайдер модели «{name}» в LLM_PROVIDER; есть gigachat и fake"
    )


def _gigachat(settings: LLMSettings) -> GigaChatProvider:
    auth_key = settings.gigachat_auth_key.get_secret_value().strip()
    if not auth_key:
        raise LLMError("config", "в файле .env не заполнен GIGACHAT_AUTH_KEY — ключ GigaChat")
    if not settings.gigachat_ca_bundle_file.strip():
        raise LLMError(
            "config",
            "в файле .env не заполнен GIGACHAT_CA_BUNDLE_FILE — путь к файлу корневого "
            "сертификата. Где его взять — в .env.example.",
        )
    ca_bundle_file = ROOT / settings.gigachat_ca_bundle_file.strip()
    if not ca_bundle_file.is_file():
        raise LLMError(
            "config",
            f"файл сертификата из GIGACHAT_CA_BUNDLE_FILE не найден: {ca_bundle_file}",
        )
    return GigaChatProvider(
        auth_key=auth_key,
        scope=settings.gigachat_scope.strip() or DEFAULT_SCOPE,
        model=settings.gigachat_model.strip() or DEFAULT_MODEL,
        ca_bundle_file=ca_bundle_file,
    )
