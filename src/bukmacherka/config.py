"""Ustawienia aplikacji wczytywane ze zmiennych środowiskowych i pliku `.env`."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BUKMACHERKA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///data/bukmacherka.db"
    data_dir: Path = Path("data")

    # Kody lig w notacji football-data.co.uk.
    leagues: list[str] = ["E0", "SP1", "I1", "D1", "F1", "POL"]
    # Rok rozpoczęcia najstarszego importowanego sezonu (2019 = sezon 2019/2020).
    # Od tego sezonu pliki mają kursy zamknięcia średniej i maksimum rynku.
    first_season: int = Field(default=2019, ge=2000)

    # Podatek od stawki kuponu w Polsce, pobierany raz na kupon.
    tax_rate: float = Field(default=0.12, ge=0, lt=1)
    # Wygrana powyżej progu jest dodatkowo opodatkowana.
    winnings_tax_threshold: float = Field(default=2280.0, ge=0)
    winnings_tax_rate: float = Field(default=0.10, ge=0, lt=1)

    min_ev: float = Field(default=0.05, ge=0)
    kelly_fraction: float = Field(default=0.25, gt=0, le=1)
    max_stake_pct: float = Field(default=0.02, gt=0, le=1)

    football_data_org_key: str | None = None
    api_football_key: str | None = None
    odds_api_key: str | None = None


def get_settings() -> Settings:
    return Settings()
