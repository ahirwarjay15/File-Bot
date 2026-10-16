import pytest
from pydantic import ValidationError

from app.config import Settings


def set_required_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123456:fake-token")
    monkeypatch.setenv("OWNER_ID", "12345")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017")


@pytest.mark.parametrize("role", ["all", "main", "worker", " MAIN ", "Worker"])
def test_app_role_is_normalized(monkeypatch, role):
    set_required_env(monkeypatch)
    monkeypatch.setenv("APP_ROLE", role)
    settings = Settings(_env_file=None)
    assert settings.app_role == role.strip().lower()


def test_app_role_defaults_to_legacy_all_in_one_mode(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.delenv("APP_ROLE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_role == "all"


def test_invalid_app_role_is_rejected(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("APP_ROLE", "manager")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
