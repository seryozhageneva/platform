"""Настройки слоя ИИ-моделей из файла `.env` (образец — `.env.example`)."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SCOPE = "GIGACHAT_API_PERS"
DEFAULT_MODEL = "GigaChat-2"


class LLMSettings(BaseSettings):
    """Читает переменные окружения и файл `.env`; остальные настройки из него пропускает."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # gigachat — настоящая модель; fake — заглушка без сети и без ключа.
    llm_provider: str = ""
    # SecretStr: при печати настроек и в отчётах об ошибках вместо значения — звёздочки.
    gigachat_auth_key: SecretStr = SecretStr("")
    gigachat_scope: str = ""
    gigachat_model: str = ""
    # Путь к файлу корневого сертификата; относительный отсчитывается от корня репозитория.
    gigachat_ca_bundle_file: str = ""
