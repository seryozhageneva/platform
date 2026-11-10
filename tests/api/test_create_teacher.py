"""Проверка адреса до запроса пароля и записи в базу."""

import pytest

from backend.api import create_teacher


@pytest.mark.parametrize("mode", [("--name", "Демо"), ("--set-initial-password",)])
def test_invalid_email_is_rejected_before_asking_for_password(monkeypatch, capsys, mode):
    monkeypatch.setattr("sys.argv", ["create_teacher", "bad-email", *mode])
    monkeypatch.setattr(create_teacher, "getpass", lambda _: pytest.fail("запрошен пароль"))

    with pytest.raises(SystemExit) as error:
        create_teacher.main()

    assert error.value.code == 2
    assert "укажите корректный адрес электронной почты" in capsys.readouterr().err
