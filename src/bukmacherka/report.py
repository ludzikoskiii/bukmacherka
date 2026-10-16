"""Raport pokrycia danych w bazie: co jest dostępne dla każdej ligi i sezonu."""

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from bukmacherka.db import Match, Odds

STAT_COLUMNS = {
    "Do przerwy": Match.home_goals_ht,
    "Rożne": Match.home_corners,
    "Kartki": Match.home_yellow,
    "xG": Match.home_xg,
}
ODDS_MARKETS = {"1X2": "1x2", "O/U 2,5": "ou", "AH": "ah"}
ODDS_BOOKMAKERS = ("pinnacle", "betfair_exchange", "market_avg")


def coverage(session: Session) -> list[dict]:
    stat_query = (
        select(
            Match.league,
            Match.season,
            func.count(Match.id),
            *(func.count(column) for column in STAT_COLUMNS.values()),
        )
        .group_by(Match.league, Match.season)
        .order_by(Match.league, Match.season)
    )
    odds_query = (
        select(
            Match.league, Match.season, Odds.market, Odds.bookmaker, func.count(distinct(Match.id))
        )
        .join(Odds, Odds.match_id == Match.id)
        .where(Odds.is_closing)
        .group_by(Match.league, Match.season, Odds.market, Odds.bookmaker)
    )
    closing = {
        (league, season, market, bookmaker): count
        for league, season, market, bookmaker, count in session.execute(odds_query)
    }

    rows = []
    for league, season, total, *stat_counts in session.execute(stat_query):
        row = {"league": league, "season": season, "matches": total}
        row |= {name: count / total for name, count in zip(STAT_COLUMNS, stat_counts, strict=True)}
        for label, market in ODDS_MARKETS.items():
            row[label] = {
                bookmaker: closing.get((league, season, market, bookmaker), 0) / total
                for bookmaker in ODDS_BOOKMAKERS
            }
        rows.append(row)
    return rows


def format_coverage(rows: list[dict]) -> str:
    if not rows:
        return "Baza jest pusta. Uruchom najpierw: bukmacherka import-history"

    def pct(value: float) -> str:
        return f"{round(value * 100)}%"

    header = ["Liga", "Sezon", "Mecze", *STAT_COLUMNS, *ODDS_MARKETS]
    lines = [header]
    for row in rows:
        lines.append(
            [
                row["league"],
                row["season"],
                str(row["matches"]),
                *(pct(row[name]) for name in STAT_COLUMNS),
                *("/".join(pct(v) for v in row[label].values()) for label in ODDS_MARKETS),
            ]
        )
    widths = [max(len(line[i]) for line in lines) for i in range(len(header))]
    table = [
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True))
        for line in lines
    ]
    legend = "Kursy zamknięcia: Pinnacle / Betfair Exchange / średnia rynkowa (% meczów)."
    return "\n".join([*table, "", legend])
