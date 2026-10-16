"""Schemat bazy danych i połączenie z bazą."""

import datetime as dt
from pathlib import Path

from sqlalchemy import Engine, ForeignKey, Index, UniqueConstraint, create_engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("country", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    country: Mapped[str]
    name: Mapped[str]


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("league", "date", "home_team_id", "away_team_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Kod ligi w notacji football-data.co.uk, np. "E0" albo "POL".
    league: Mapped[str] = mapped_column(index=True)
    # Sezon w formacie "2025/2026".
    season: Mapped[str] = mapped_column(index=True)
    date: Mapped[dt.date]
    # Godzina w takiej postaci, w jakiej podaje ją źródło.
    time: Mapped[str | None]
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))

    home_goals: Mapped[int | None]
    away_goals: Mapped[int | None]
    home_goals_ht: Mapped[int | None]
    away_goals_ht: Mapped[int | None]
    home_xg: Mapped[float | None]
    away_xg: Mapped[float | None]
    home_shots: Mapped[int | None]
    away_shots: Mapped[int | None]
    home_shots_on_target: Mapped[int | None]
    away_shots_on_target: Mapped[int | None]
    home_fouls: Mapped[int | None]
    away_fouls: Mapped[int | None]
    home_corners: Mapped[int | None]
    away_corners: Mapped[int | None]
    home_yellow: Mapped[int | None]
    away_yellow: Mapped[int | None]
    home_red: Mapped[int | None]
    away_red: Mapped[int | None]
    referee: Mapped[str | None]

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])


class Odds(Base):
    __tablename__ = "odds"
    __table_args__ = (Index("ix_odds_match_source", "match_id", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    source: Mapped[str]
    # Np. "pinnacle", "bet365", "betfair_exchange", "market_avg", "market_max".
    bookmaker: Mapped[str]
    # "1x2", "ou" (over/under) albo "ah" (handicap azjatycki).
    market: Mapped[str]
    # "home", "draw", "away", "over" albo "under".
    selection: Mapped[str]
    # Linia rynku: liczba goli dla "ou", handicap gospodarza dla "ah".
    line: Mapped[float | None]
    price: Mapped[float]
    is_closing: Mapped[bool]


def get_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url)


def init_db(engine: Engine) -> sessionmaker:
    Base.metadata.create_all(engine)
    return sessionmaker(engine)
