import pytest
from pydantic import ValidationError

from bukmacherka.config import Settings


def test_defaults():
    settings = Settings(_env_file=None)

    assert settings.tax_rate == 0.12
    assert settings.leagues == ["E0", "SP1", "I1", "D1", "F1", "POL"]
    assert settings.odds_api_key is None


def test_env_override(monkeypatch):
    monkeypatch.setenv("BUKMACHERKA_TAX_RATE", "0")
    monkeypatch.setenv("BUKMACHERKA_LEAGUES", '["E0", "POL"]')
    settings = Settings(_env_file=None)

    assert settings.tax_rate == 0
    assert settings.leagues == ["E0", "POL"]


def test_rejects_invalid_tax_rate(monkeypatch):
    monkeypatch.setenv("BUKMACHERKA_TAX_RATE", "1.5")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
