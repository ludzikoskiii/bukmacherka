"""Import wyników, statystyk i kursów historycznych z football-data.co.uk."""

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, sessionmaker

from bukmacherka.db import Match, Odds, Team

log = logging.getLogger(__name__)

SOURCE = "football-data.co.uk"
BASE_URL = "https://football-data.co.uk"

# Ligi z osobnym plikiem na każdy sezon: mmz4281/<sezon>/<kod>.csv.
MAIN_LEAGUES = {
    "E0": "England",
    "SP1": "Spain",
    "I1": "Italy",
    "D1": "Germany",
    "F1": "France",
}
# Ligi z jednym plikiem na wszystkie sezony: new/<kod>.csv. Mają tylko wynik
# i kursy zamknięcia 1X2.
EXTRA_LEAGUES = {
    "POL": "Poland",
}
EXTRA_COLUMNS = {"Home": "HomeTeam", "Away": "AwayTeam", "HG": "FTHG", "AG": "FTAG"}

# Drużyny, których nazwa zmieniła się w plikach między sezonami.
TEAM_RENAMES = {
    ("Poland", "Gornik Z."): "Gornik Zabrze",
}

# Prefiksy kolumn z kursami. Pinnacle ma inny prefiks dla 1X2 niż dla
# Over/Under i handicapu azjatyckiego.
BOOKMAKERS_1X2 = {
    "PS": "pinnacle",
    "B365": "bet365",
    "BFE": "betfair_exchange",
    "Avg": "market_avg",
    "Max": "market_max",
}
BOOKMAKERS_LINES = {**{k: v for k, v in BOOKMAKERS_1X2.items() if k != "PS"}, "P": "pinnacle"}

INT_COLUMNS = {
    "FTHG": "home_goals",
    "FTAG": "away_goals",
    "HTHG": "home_goals_ht",
    "HTAG": "away_goals_ht",
    "HS": "home_shots",
    "AS": "away_shots",
    "HST": "home_shots_on_target",
    "AST": "away_shots_on_target",
    "HF": "home_fouls",
    "AF": "away_fouls",
    "HC": "home_corners",
    "AC": "away_corners",
    "HY": "home_yellow",
    "AY": "away_yellow",
    "HR": "home_red",
    "AR": "away_red",
}
FLOAT_COLUMNS = {"HxG": "home_xg", "AxG": "away_xg"}


@dataclass
class ParsedMatch:
    league: str
    season: str
    date: dt.date
    time: str | None
    home: str
    away: str
    stats: dict[str, int | float | str | None]
    odds: list[dict] = field(default_factory=list)


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def season_name(start_year: int) -> str:
    return f"{start_year}/{start_year + 1}"


def current_season_start(today: dt.date) -> int:
    return today.year if today.month >= 7 else today.year - 1


def read_csv(path: Path) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="latin-1")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def parse_frame(df: pd.DataFrame, league: str, season: str | None = None) -> list[ParsedMatch]:
    """Zamienia plik CSV na listę meczów.

    Dla lig z `MAIN_LEAGUES` trzeba podać sezon. Pliki z `EXTRA_LEAGUES` mają
    sezon w kolumnie `Season`.
    """
    if league in EXTRA_LEAGUES:
        df = df.rename(columns=EXTRA_COLUMNS)
    elif season is None:
        raise ValueError(f"Liga {league} wymaga podania sezonu")

    country = _country(league)

    def team(value) -> str:
        name = str(value).strip()
        return TEAM_RENAMES.get((country, name), name)

    matches = []
    for row in df.to_dict("records"):
        if _is_missing(row.get("HomeTeam")) or _is_missing(row.get("Date")):
            continue
        stats: dict[str, int | float | str | None] = {
            attr: _int(row.get(col)) for col, attr in INT_COLUMNS.items()
        }
        stats |= {attr: _float(row.get(col)) for col, attr in FLOAT_COLUMNS.items()}
        stats["referee"] = _str(row.get("Referee"))
        matches.append(
            ParsedMatch(
                league=league,
                season=season or str(row["Season"]),
                date=_parse_date(str(row["Date"])),
                time=_str(row.get("Time")),
                home=team(row["HomeTeam"]),
                away=team(row["AwayTeam"]),
                stats=stats,
                odds=_parse_odds(row),
            )
        )
    return matches


def _parse_odds(row: dict) -> list[dict]:
    odds = []

    def add(column, bookmaker, market, selection, line, is_closing):
        price = _float(row.get(column))
        if price is not None and price > 1:
            odds.append(
                {
                    "bookmaker": bookmaker,
                    "market": market,
                    "selection": selection,
                    "line": line,
                    "price": price,
                    "is_closing": is_closing,
                }
            )

    for is_closing in (False, True):
        c = "C" if is_closing else ""
        for prefix, bookmaker in BOOKMAKERS_1X2.items():
            for code, selection in (("H", "home"), ("D", "draw"), ("A", "away")):
                add(f"{prefix}{c}{code}", bookmaker, "1x2", selection, None, is_closing)

        ah_line = _float(row.get(f"AH{c}h"))
        for prefix, bookmaker in BOOKMAKERS_LINES.items():
            add(f"{prefix}{c}>2.5", bookmaker, "ou", "over", 2.5, is_closing)
            add(f"{prefix}{c}<2.5", bookmaker, "ou", "under", 2.5, is_closing)
            if ah_line is not None:
                add(f"{prefix}{c}AHH", bookmaker, "ah", "home", ah_line, is_closing)
                add(f"{prefix}{c}AHA", bookmaker, "ah", "away", ah_line, is_closing)
    return odds


def store(session: Session, matches: list[ParsedMatch]) -> None:
    """Zapisuje mecze w bazie. Ponowny import aktualizuje istniejące rekordy."""
    if not matches:
        return
    team_ids: dict[tuple[str, str], int] = {}
    existing: dict[tuple, Match] = {}
    for league, season in {(m.league, m.season) for m in matches}:
        query = select(Match).where(Match.league == league, Match.season == season)
        for match in session.scalars(query):
            existing[(league, match.date, match.home_team_id, match.away_team_id)] = match

    stored: list[tuple[Match, ParsedMatch]] = []
    for parsed in matches:
        country = _country(parsed.league)
        home_id = _team_id(session, team_ids, country, parsed.home)
        away_id = _team_id(session, team_ids, country, parsed.away)
        key = (parsed.league, parsed.date, home_id, away_id)
        match = existing.get(key)
        if match is None:
            match = Match(
                league=parsed.league, date=parsed.date, home_team_id=home_id, away_team_id=away_id
            )
            session.add(match)
            existing[key] = match
        match.season = parsed.season
        match.time = parsed.time
        for attr, value in parsed.stats.items():
            setattr(match, attr, value)
        stored.append((match, parsed))
    session.flush()

    match_ids = [match.id for match, _ in stored]
    session.execute(delete(Odds).where(Odds.source == SOURCE, Odds.match_id.in_(match_ids)))
    rows = [
        {"match_id": match.id, "source": SOURCE, **odds}
        for match, parsed in stored
        for odds in parsed.odds
    ]
    if rows:
        session.execute(insert(Odds), rows)


def import_history(
    session_factory: sessionmaker,
    leagues: list[str],
    first_season: int,
    raw_dir: Path,
    *,
    today: dt.date | None = None,
    refresh: bool = False,
    client: httpx.Client | None = None,
) -> dict[str, int]:
    """Pobiera pliki CSV (z lokalną pamięcią podręczną) i zapisuje je w bazie.

    Pliki z zakończonych sezonów pobierają się tylko raz. Plik bieżącego
    sezonu jest pobierany za każdym razem, bo dochodzą do niego nowe mecze.
    Zwraca liczbę zaimportowanych meczów dla każdej ligi.
    """
    unknown = [lg for lg in leagues if lg not in MAIN_LEAGUES and lg not in EXTRA_LEAGUES]
    if unknown:
        raise ValueError(f"Nieznane ligi: {', '.join(unknown)}")

    current = current_season_start(today or dt.date.today())
    own_client = client is None
    client = client or httpx.Client(
        follow_redirects=True, timeout=60, headers={"User-Agent": "bukmacherka/0.1"}
    )
    counts: dict[str, int] = {}
    try:
        for league in leagues:
            counts[league] = 0
            if league in EXTRA_LEAGUES:
                path = _download(
                    client, f"{BASE_URL}/new/{league}.csv", raw_dir / "new" / f"{league}.csv", True
                )
                if path is None:
                    continue
                by_season: dict[str, list[ParsedMatch]] = {}
                for match in parse_frame(read_csv(path), league):
                    if _start_year(match) >= first_season:
                        by_season.setdefault(match.season, []).append(match)
                for matches in by_season.values():
                    counts[league] += _store_batch(session_factory, matches)
                continue

            for start in range(first_season, current + 1):
                code = season_code(start)
                path = _download(
                    client,
                    f"{BASE_URL}/mmz4281/{code}/{league}.csv",
                    raw_dir / "mmz4281" / code / f"{league}.csv",
                    refresh or start == current,
                )
                if path is None:
                    continue
                matches = parse_frame(read_csv(path), league, season_name(start))
                counts[league] += _store_batch(session_factory, matches)
    finally:
        if own_client:
            client.close()
    return counts


def _store_batch(session_factory: sessionmaker, matches: list[ParsedMatch]) -> int:
    with session_factory.begin() as session:
        store(session, matches)
    if matches:
        log.info("%s %s: %d meczów", matches[0].league, matches[0].season, len(matches))
    return len(matches)


def _download(client: httpx.Client, url: str, dest: Path, refresh: bool) -> Path | None:
    if dest.exists() and not refresh:
        return dest
    response = client.get(url)
    if response.status_code == 404:
        log.warning("Brak pliku: %s", url)
        return None
    response.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    return dest


def _team_id(session: Session, cache: dict, country: str, name: str) -> int:
    key = (country, name)
    if key not in cache:
        team = session.scalar(select(Team).where(Team.country == country, Team.name == name))
        if team is None:
            team = Team(country=country, name=name)
            session.add(team)
            session.flush()
        cache[key] = team.id
    return cache[key]


def _country(league: str) -> str:
    return MAIN_LEAGUES.get(league) or EXTRA_LEAGUES[league]


def _start_year(match: ParsedMatch) -> int:
    return int(match.season[:4])


def _parse_date(value: str) -> dt.date:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Nieznany format daty: {value!r}")


def _is_missing(value) -> bool:
    return value is None or (not isinstance(value, str) and pd.isna(value)) or value == ""


def _float(value) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value) -> int | None:
    number = _float(value)
    return None if number is None else int(number)


def _str(value) -> str | None:
    return None if _is_missing(value) else str(value).strip()
