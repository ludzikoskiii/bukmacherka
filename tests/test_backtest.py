import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from bukmacherka.backtest import simulate, walk_forward
from bukmacherka.backtest.data import OddsSet
from bukmacherka.model.dixon_coles import score_matrix
from bukmacherka.value.ev import devig


def make_matches(start: dt.date, days: int, league: str = "E0") -> pd.DataFrame:
    teams = ["A", "B", "C", "D"]
    rows = []
    for i in range(days):
        date = start + dt.timedelta(days=i)
        home, away = teams[i % 4], teams[(i + 1 + i // 4) % 4]
        if home == away:
            away = teams[(i + 2) % 4]
        season_year = date.year if date.month >= 7 else date.year - 1
        rows.append(
            {
                "id": i + 1,
                "league": league,
                "season": f"{season_year}/{season_year + 1}",
                "date": date,
                "home": home,
                "away": away,
                "home_goals": i % 3,
                "away_goals": (i + 1) % 2,
            }
        )
    return pd.DataFrame(rows)


def test_walk_forward_uses_only_matches_before_the_week(monkeypatch):
    matches = make_matches(dt.date(2019, 8, 1), 600)
    calls = []
    real_fit = walk_forward.dixon_coles.fit

    def recording_fit(home, away, hg, ag, weights, **kwargs):
        calls.append(len(home))
        return real_fit(home, away, hg, ag, weights, **kwargs)

    seen_weeks = {}

    def recording_weights(dates, ref_date, xi):
        seen_weeks[ref_date] = max(dates)
        return np.ones(len(list(dates)))

    monkeypatch.setattr(walk_forward.dixon_coles, "fit", recording_fit)
    monkeypatch.setattr(walk_forward.dixon_coles, "time_weights", recording_weights)
    monkeypatch.setattr(walk_forward, "MIN_TRAIN_MATCHES", 50)

    eval_from = dt.date(2020, 7, 1)
    predictions = walk_forward.walk_forward(matches, eval_from)

    assert calls
    assert all(last < week for week, last in seen_weeks.items())
    assert all(week.weekday() == 0 for week in seen_weeks)
    predicted = matches[matches.id.isin(predictions)]
    assert predicted.date.min() >= eval_from
    assert len(predicted) == len(matches[matches.date >= eval_from])


def test_promoted_teams():
    matches = pd.DataFrame(
        {
            "league": ["E0"] * 4,
            "season": ["2020/2021", "2020/2021", "2021/2022", "2021/2022"],
            "home": ["A", "B", "A", "C"],
            "away": ["B", "A", "C", "A"],
        }
    )

    assert walk_forward.promoted_teams(matches) == {("E0", "2021/2022"): {"C"}}


@pytest.fixture
def one_match():
    matches = pd.DataFrame(
        [
            {
                "id": 1,
                "league": "E0",
                "season": "2025/2026",
                "date": dt.date(2025, 9, 13),
                "home": "A",
                "away": "B",
                "home_goals": 2,
                "away_goals": 1,
            }
        ]
    )
    predictions = {1: score_matrix(1.5, 1.0, 0.0)}
    odds = {
        (1, "bet365", "1x2", False): OddsSet(None, {"home": 2.0, "draw": 3.5, "away": 4.0}),
        (1, "pinnacle", "1x2", True): OddsSet(None, {"home": 1.9, "draw": 3.6, "away": 4.4}),
        (1, "market_avg", "1x2", False): OddsSet(None, {"home": 1.95, "draw": 3.5, "away": 4.1}),
        (1, "bet365", "ah", False): OddsSet(-0.75, {"home": 2.1, "away": 1.8}),
        (1, "pinnacle", "ah", True): OddsSet(-0.5, {"home": 1.9, "away": 2.0}),
    }
    return matches, predictions, odds


def test_candidates(one_match):
    matches, predictions, odds = one_match
    cands = simulate.candidates(matches, predictions, odds, "bet365", closing=False)
    by_selection = cands.set_index(["market", "selection"])

    home = by_selection.loc[("1x2", "home")]
    assert home.factor == pytest.approx(2.0)
    assert by_selection.loc[("1x2", "draw")].factor == 0
    p_home = devig([1.9, 3.6, 4.4])[0]
    assert home.clv == pytest.approx(2.0 * p_home - 1)
    assert home.edge == pytest.approx(home.win * 2.0 - 1)

    # Wygrana 2:1 przy handicapie -0,75: połowa stawki wygrywa, połowa wraca.
    ah_home = by_selection.loc[("ah", "home")]
    assert ah_home.factor == pytest.approx(0.5 * 2.1 + 0.5)
    # Linia zamknięcia jest inna niż linia gry, więc CLV nie jest liczone.
    assert math.isnan(ah_home.clv)


def test_single_bets_apply_tax(one_match):
    matches, predictions, odds = one_match
    cands = simulate.candidates(matches, predictions, odds, "bet365", closing=False)

    bets = simulate.single_bets(cands, tax=0.12, min_ev=-math.inf)

    assert bets.profit.tolist() == pytest.approx((0.88 * cands.factor - 1).tolist())


def test_accumulators():
    cands = pd.DataFrame(
        {
            "match_id": [1, 1, 2, 3, 4, 5],
            "week": [dt.date(2025, 9, 8)] * 6,
            "edge": [0.20, 0.10, 0.15, 0.12, 0.08, 0.01],
            "odds": [2.0, 3.0, 2.5, 1.8, 2.2, 1.5],
            "factor": [2.0, 0.0, 2.5, 0.0, 2.2, 1.5],
            "clv": [0.01] * 6,
        }
    )

    coupons = simulate.accumulators(cands, size=2, tax=0.12, min_edge=0.05, min_ev=0.0)

    # Z meczu 1 bierzemy tylko lepsze zdarzenie. Mecz 5 ma za małą przewagę.
    # Kolejność: 1 (0,20), 2 (0,15), 3 (0,12), 4 (0,08).
    assert coupons.match_ids.tolist() == ["1,2", "3,4"]
    assert coupons.odds.tolist() == pytest.approx([5.0, 3.96])
    assert coupons.ev.tolist() == pytest.approx([0.88 * 1.20 * 1.15 - 1, 0.88 * 1.12 * 1.08 - 1])
    assert coupons.profit.tolist() == pytest.approx([0.88 * 5.0 - 1, -1.0])

    strict = simulate.accumulators(cands, size=2, tax=0.12, min_edge=0.05, min_ev=0.2)
    assert strict.match_ids.tolist() == ["1,2"]


def test_model_accuracy(one_match):
    matches, predictions, odds = one_match
    accuracy = simulate.model_accuracy(matches, predictions, odds)

    row = accuracy.iloc[0]
    home_win = np.tril(predictions[1], -1).sum()
    assert row.market == "1x2"
    assert row.model == pytest.approx(-math.log(home_win))
    assert row.closing == pytest.approx(-math.log(devig([1.9, 3.6, 4.4])[0]))
    assert row.opening == pytest.approx(-math.log(devig([1.95, 3.5, 4.1])[0]))
