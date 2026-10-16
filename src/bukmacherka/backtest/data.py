"""Wczytywanie meczów i kursów z bazy do backtestu."""

import logging
from collections import Counter
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from bukmacherka.db import Match, Odds, Team

log = logging.getLogger(__name__)

SET_SIZES = {"1x2": 3, "ou": 2, "ah": 2}
# Komplet kursów, którego suma odwrotności wypada poza ten zakres, uznajemy
# za błąd w danych. Dolna granica dopuszcza drobny arbitraż w kolumnach
# z maksimum rynku.
OVERROUND_RANGE = (0.95, 1.25)


@dataclass(frozen=True)
class OddsSet:
    line: float | None
    prices: dict[str, float]

    @property
    def overround(self) -> float:
        return sum(1 / k for k in self.prices.values())


# Klucz: (match_id, bookmaker, market, is_closing).
OddsIndex = dict[tuple[int, str, str, bool], OddsSet]


def load_matches(session: Session, leagues: list[str]) -> pd.DataFrame:
    home, away = aliased(Team), aliased(Team)
    query = (
        select(
            Match.id,
            Match.league,
            Match.season,
            Match.date,
            home.name,
            away.name,
            Match.home_goals,
            Match.away_goals,
        )
        .join(home, Match.home_team_id == home.id)
        .join(away, Match.away_team_id == away.id)
        .where(
            Match.league.in_(leagues),
            Match.home_goals.is_not(None),
            Match.away_goals.is_not(None),
        )
        .order_by(Match.date, Match.id)
    )
    columns = ["id", "league", "season", "date", "home", "away", "home_goals", "away_goals"]
    return pd.DataFrame(session.execute(query).all(), columns=columns)


def load_odds(session: Session, match_ids: set[int]) -> OddsIndex:
    """Wczytuje komplety kursów i odrzuca niekompletne lub z błędną marżą."""
    query = select(
        Odds.match_id,
        Odds.bookmaker,
        Odds.market,
        Odds.is_closing,
        Odds.selection,
        Odds.line,
        Odds.price,
    )
    grouped: dict[tuple[int, str, str, bool], tuple[float | None, dict[str, float]]] = {}
    for match_id, bookmaker, market, is_closing, selection, line, price in session.execute(query):
        if match_id not in match_ids:
            continue
        key = (match_id, bookmaker, market, is_closing)
        _, prices = grouped.setdefault(key, (line, {}))
        prices[selection] = price

    index: OddsIndex = {}
    dropped: Counter = Counter()
    low, high = OVERROUND_RANGE
    for key, (line, prices) in grouped.items():
        odds_set = OddsSet(line, prices)
        if len(prices) != SET_SIZES[key[2]]:
            dropped["niekompletne"] += 1
        elif not low <= odds_set.overround <= high:
            dropped["błędna marża"] += 1
        else:
            index[key] = odds_set
    if dropped:
        log.info(
            "Odrzucone komplety kursów: %s (z %d)",
            ", ".join(f"{reason}: {count}" for reason, count in dropped.items()),
            len(grouped),
        )
    return index
