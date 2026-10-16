import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import func, select

from bukmacherka.db import Match, Odds, Team
from bukmacherka.ingest import football_data_co_uk as fd

FIXTURES = Path(__file__).parent / "fixtures" / "football_data_co_uk"


def price(match, bookmaker, market, selection, is_closing):
    [odds] = [
        o
        for o in match.odds
        if (o["bookmaker"], o["market"], o["selection"], o["is_closing"])
        == (bookmaker, market, selection, is_closing)
    ]
    return odds["price"], odds["line"]


def count(session_factory, model):
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_season_helpers():
    assert fd.season_code(2025) == "2526"
    assert fd.season_code(1999) == "9900"
    assert fd.season_name(2025) == "2025/2026"
    assert fd.current_season_start(dt.date(2026, 10, 16)) == 2026
    assert fd.current_season_start(dt.date(2026, 6, 30)) == 2025


def test_parse_main_league():
    matches = fd.parse_frame(fd.read_csv(FIXTURES / "E0_2526.csv"), "E0", "2025/2026")

    assert len(matches) == 3
    match = matches[0]
    assert (match.date, match.time) == (dt.date(2025, 8, 15), "20:00")
    assert (match.home, match.away) == ("Liverpool", "Bournemouth")
    assert match.stats["home_goals"] == 4
    assert match.stats["away_goals"] == 2
    assert match.stats["home_goals_ht"] == 1
    assert match.stats["home_corners"] == 6
    assert match.stats["away_yellow"] == 2
    assert match.stats["home_xg"] is None
    assert match.stats["referee"] == "A Taylor"

    # 5 bukmacherów × (3 wybory 1X2 + 2 O/U + 2 AH) × kursy otwarcia i zamknięcia.
    assert len(match.odds) == 70
    assert price(match, "pinnacle", "1x2", "home", True) == (1.29, None)
    assert price(match, "pinnacle", "1x2", "away", False) == (9.07, None)
    assert price(match, "pinnacle", "ou", "under", True) == (2.95, 2.5)
    assert price(match, "pinnacle", "ah", "home", True) == (2.07, -1.75)
    assert price(match, "pinnacle", "ah", "home", False) == (1.9, -1.5)


def test_parse_season_with_xg_and_without_pinnacle():
    matches = fd.parse_frame(fd.read_csv(FIXTURES / "E0_2627.csv"), "E0", "2026/2027")

    match = matches[0]
    assert (match.stats["home_xg"], match.stats["away_xg"]) == (1.88, 0.2)
    assert not [o for o in match.odds if o["bookmaker"] == "pinnacle"]
    assert price(match, "betfair_exchange", "1x2", "home", True)[0] > 1


def test_parse_extra_league():
    matches = fd.parse_frame(fd.read_csv(FIXTURES / "POL.csv"), "POL")

    assert [m.season for m in matches] == [
        "2018/2019",
        "2025/2026",
        "2025/2026",
        "2026/2027",
        "2026/2027",
    ]
    match = matches[1]
    assert (match.home, match.away) == ("Jagiellonia", "Termalica B-B.")
    assert (match.stats["home_goals"], match.stats["away_goals"]) == (0, 4)
    assert match.stats["home_goals_ht"] is None
    assert all(o["is_closing"] and o["market"] == "1x2" for o in match.odds)
    assert price(match, "pinnacle", "1x2", "home", True) == (1.64, None)
    assert not [o for o in matches[3].odds if o["bookmaker"] == "pinnacle"]


def test_team_renames():
    df = fd.read_csv(FIXTURES / "POL.csv")
    df.loc[0, "Home"] = "Gornik Z."

    assert fd.parse_frame(df, "POL")[0].home == "Gornik Zabrze"


def test_main_league_requires_season():
    with pytest.raises(ValueError):
        fd.parse_frame(fd.read_csv(FIXTURES / "E0_2526.csv"), "E0")


def test_import_history(run_import, session_factory):
    counts = run_import()

    # E0: 3 mecze z 2025/26 i 2 z 2026/27. POL: 4 mecze od sezonu 2025/26.
    assert counts == {"E0": 5, "POL": 4}
    assert count(session_factory, Match) == 9
    with session_factory() as session:
        match = session.scalar(select(Match).join(Match.home_team).where(Team.name == "Liverpool"))
        assert match.season == "2025/2026"
        assert match.away_team.name == "Bournemouth"
        assert match.home_team.country == "England"


def test_reimport_updates_instead_of_duplicating(run_import, session_factory):
    run_import()
    odds_before = count(session_factory, Odds)
    teams_before = count(session_factory, Team)
    run_import.requested.clear()

    run_import()

    assert count(session_factory, Match) == 9
    assert count(session_factory, Odds) == odds_before
    assert count(session_factory, Team) == teams_before
    # Zakończony sezon jest brany z pamięci podręcznej, bieżący pobierany ponownie.
    assert run_import.requested == ["/mmz4281/2627/E0.csv", "/new/POL.csv"]


def test_missing_file_is_skipped(run_import):
    assert run_import(leagues=["E0"], first_season=2024) == {"E0": 5}
    assert "/mmz4281/2425/E0.csv" in run_import.requested


def test_unknown_league(run_import):
    with pytest.raises(ValueError, match="XX"):
        run_import(leagues=["XX"])
