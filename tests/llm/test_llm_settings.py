"""Настройки и сборка слоя: какой провайдер выбран, тот и подключается; чего не хватает — сказано.

Настоящий файл `.env` здесь не читается: значения передаются прямо в тесте.
"""

import asyncio

import pytest

from backend.core.contracts.interfaces import LLMClient, LLMMessage
from backend.llm import factory
from backend.llm.factory import make_llm
from backend.llm.providers import LLMError
from backend.llm.settings import LLMSettings

AUTH_KEY = "выдуманный-ключ-для-теста"


def settings(**values) -> LLMSettings:
    defaults = {
        "llm_provider": "",
        "gigachat_auth_key": "",
        "gigachat_scope": "",
        "gigachat_model": "",
        "gigachat_ca_bundle_file": "",
    }
    return LLMSettings(_env_file=None, **{**defaults, **values})


@pytest.fixture
def certificate(tmp_path):
    """Файл на месте сертификата: сборке важно только, что он существует."""
    file = tmp_path / "root_ca.cer"
    file.write_text("выдуманный сертификат")
    return file


@pytest.fixture
def built(monkeypatch):
    """Вместо настоящего провайдера GigaChat — запись того, с чем его собирали."""
    made = {}

    class Recorded:
        name = "gigachat"

        def __init__(self, **options) -> None:
            made.update(options)
            self.model = options["model"]

    monkeypatch.setattr(factory, "GigaChatProvider", Recorded)
    return made


def test_fake_provider_works_without_a_key(call_log):
    llm = make_llm(settings(llm_provider="fake"), call_log=call_log)

    reply = asyncio.run(llm.complete([LLMMessage(role="user", content="Привет")]))

    assert isinstance(llm, LLMClient)
    assert reply.model == "fake"
    assert call_log.records[0]["provider"] == "fake"


def test_provider_name_ignores_case_and_spaces():
    assert isinstance(make_llm(settings(llm_provider=" Fake ")), LLMClient)


def test_missing_provider_is_explained():
    with pytest.raises(LLMError, match="LLM_PROVIDER=gigachat") as caught:
        make_llm(settings())

    assert caught.value.kind == "config"


def test_unknown_provider_is_explained():
    with pytest.raises(LLMError, match="неизвестный провайдер модели «openai»"):
        make_llm(settings(llm_provider="openai"))


def test_gigachat_without_a_key_is_explained(certificate):
    with pytest.raises(LLMError, match="не заполнен GIGACHAT_AUTH_KEY"):
        make_llm(settings(llm_provider="gigachat", gigachat_ca_bundle_file=str(certificate)))


def test_gigachat_without_a_certificate_is_explained():
    with pytest.raises(LLMError, match="не заполнен GIGACHAT_CA_BUNDLE_FILE"):
        make_llm(settings(llm_provider="gigachat", gigachat_auth_key=AUTH_KEY))


def test_gigachat_with_a_missing_certificate_file_is_explained(tmp_path):
    with pytest.raises(LLMError, match="файл сертификата из GIGACHAT_CA_BUNDLE_FILE не найден"):
        make_llm(
            settings(
                llm_provider="gigachat",
                gigachat_auth_key=AUTH_KEY,
                gigachat_ca_bundle_file=str(tmp_path / "нет-такого-файла.cer"),
            )
        )


def test_gigachat_is_built_from_settings(built, certificate):
    make_llm(
        settings(
            llm_provider="gigachat",
            gigachat_auth_key=AUTH_KEY,
            gigachat_scope="GIGACHAT_API_B2B",
            gigachat_model="GigaChat-2-Max",
            gigachat_ca_bundle_file=str(certificate),
        )
    )

    assert built == {
        "auth_key": AUTH_KEY,
        "scope": "GIGACHAT_API_B2B",
        "model": "GigaChat-2-Max",
        "ca_bundle_file": certificate,
    }


def test_empty_scope_and_model_fall_back_to_defaults(built, certificate):
    """В `.env.example` эти строки пустые: пустое значение не должно ломать подключение."""
    make_llm(
        settings(
            llm_provider="gigachat",
            gigachat_auth_key=AUTH_KEY,
            gigachat_ca_bundle_file=str(certificate),
        )
    )

    assert (built["scope"], built["model"]) == ("GIGACHAT_API_PERS", "GigaChat-2")


def test_key_is_hidden_when_settings_are_printed():
    printed = repr(settings(llm_provider="gigachat", gigachat_auth_key=AUTH_KEY))

    assert AUTH_KEY not in printed
    assert "**********" in printed


def test_real_library_client_checks_certificates_and_does_not_retry(certificate, monkeypatch):
    """Проверка сертификатов включена всегда, даже если окружение просит её отключить."""
    monkeypatch.setenv("GIGACHAT_VERIFY_SSL_CERTS", "false")
    monkeypatch.setenv("GIGACHAT_MAX_RETRIES", "5")
    llm = make_llm(
        settings(
            llm_provider="gigachat",
            gigachat_auth_key=AUTH_KEY,
            gigachat_ca_bundle_file=str(certificate),
        )
    )

    sdk_settings = llm._provider._client._settings
    assert sdk_settings.verify_ssl_certs is True
    assert sdk_settings.ca_bundle_file == str(certificate)
    assert sdk_settings.max_retries == 0
