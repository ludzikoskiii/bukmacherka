"""Symulacja obstawiania singli i kuponów AKO na historycznych kursach."""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bukmacherka.backtest.data import OddsIndex
from bukmacherka.backtest.walk_forward import week_start
from bukmacherka.model.markets import Selection, price, settle
from bukmacherka.value.ev import devig

# Kursy zamknięcia o najmniejszej marży, w kolejności preferencji. Służą do
# CLV i porównania trafności modelu z rynkiem.
SHARP_BOOKMAKERS = ("pinnacle", "betfair_exchange")
MARKET_SELECTIONS = {
    "1x2": ("home", "draw", "away"),
    "ou": ("over", "under"),
    "ah": ("home", "away"),
}


def closing_reference(odds: OddsIndex, match_id: int, market: str):
    """Kursy zamknięcia najostrzejszego dostępnego bukmachera, inaczej średnia."""
    for bookmaker in (*SHARP_BOOKMAKERS, "market_avg"):
        odds_set = odds.get((match_id, bookmaker, market, True))
        if odds_set is not None:
            return bookmaker, odds_set
    return None, None


def candidates(
    matches: pd.DataFrame,
    predictions: dict[int, np.ndarray],
    odds: OddsIndex,
    bookmaker: str,
    closing: bool,
) -> pd.DataFrame:
    """Wszystkie zakłady, które dało się postawić u `bookmaker`, z wyceną modelu.

    Kolumny: `win`/`push` z modelu, `edge` (przewaga bez podatku), `factor`
    (faktyczny zwrot ze stawki 1 bez podatku po rozliczeniu) i `clv`
    (kurs względem kursu sprawiedliwego z zamknięcia ostrego bukmachera).
    """
    rows = []
    for match in matches.itertuples():
        matrix = predictions.get(match.id)
        if matrix is None:
            continue
        for market, selections in MARKET_SELECTIONS.items():
            bet_set = odds.get((match.id, bookmaker, market, closing))
            if bet_set is None:
                continue
            ref_name, ref_set = closing_reference(odds, match.id, market)
            fair = None
            if ref_name in SHARP_BOOKMAKERS and ref_set.line == bet_set.line:
                probabilities = devig([ref_set.prices[s] for s in selections])
                fair = {s: 1 / p for s, p in zip(selections, probabilities, strict=True)}
            for name in selections:
                selection = Selection(market, name, bet_set.line)
                model = price(matrix, selection)
                odds_value = bet_set.prices[name]
                won, pushed = settle(selection, match.home_goals, match.away_goals)
                rows.append(
                    {
                        "match_id": match.id,
                        "league": match.league,
                        "season": match.season,
                        "date": match.date,
                        "week": week_start(match.date),
                        "market": market,
                        "selection": name,
                        "line": bet_set.line,
                        "odds": odds_value,
                        "win": model.win,
                        "push": model.push,
                        "edge": model.expected_return(odds_value) - 1,
                        "factor": won * odds_value + pushed,
                        "clv": odds_value / fair[name] - 1 if fair else math.nan,
                    }
                )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class Summary:
    bets: int
    roi: float
    roi_ci: float
    avg_odds: float
    hit_rate: float
    clv: float

    @classmethod
    def of(cls, profit: pd.Series, odds: pd.Series, factor: pd.Series, clv: pd.Series):
        n = len(profit)
        if n == 0:
            return cls(0, math.nan, math.nan, math.nan, math.nan, math.nan)
        ci = 1.96 * profit.std(ddof=1) / math.sqrt(n) if n > 1 else math.nan
        return cls(
            bets=n,
            roi=float(profit.mean()),
            roi_ci=float(ci),
            avg_odds=float(odds.mean()),
            hit_rate=float((factor > 1).mean()),
            clv=float(clv.mean()) if clv.notna().any() else math.nan,
        )


def single_bets(cands: pd.DataFrame, tax: float, min_ev: float) -> pd.DataFrame:
    """Single z EV po podatku co najmniej `min_ev`, stawka 1 na zakład."""
    if cands.empty:
        return cands.assign(ev=[], profit=[])
    ev = (1 - tax) * (cands.edge + 1) - 1
    bets = cands[ev >= min_ev].copy()
    bets["ev"] = ev[ev >= min_ev]
    bets["profit"] = (1 - tax) * bets.factor - 1
    return bets


def accumulators(
    cands: pd.DataFrame, size: int, tax: float, min_edge: float, min_ev: float
) -> pd.DataFrame:
    """Kupony AKO z zakładów o przewadze co najmniej `min_edge`, stawka 1 na kupon.

    W każdym tygodniu z każdego meczu bierzemy najlepsze zdarzenie, sortujemy
    je od największej przewagi i dzielimy kolejno na kupony po `size`
    zdarzeń. Kupon trafia do gry, jeśli jego EV po podatku wynosi co
    najmniej `min_ev`. Zakładamy niezależność zdarzeń z różnych meczów.
    """
    legs = cands[cands.edge >= min_edge]
    legs = legs.sort_values("edge", ascending=False).drop_duplicates("match_id")
    coupons = []
    for week, group in legs.groupby("week"):
        group = group.sort_values("edge", ascending=False)
        for start in range(0, len(group) - size + 1, size):
            chunk = group.iloc[start : start + size]
            ev = (1 - tax) * float(np.prod(chunk.edge + 1)) - 1
            if ev < min_ev:
                continue
            coupons.append(
                {
                    "week": week,
                    "legs": size,
                    "odds": float(np.prod(chunk.odds)),
                    "ev": ev,
                    "factor": float(np.prod(chunk.factor)),
                    "profit": (1 - tax) * float(np.prod(chunk.factor)) - 1,
                    "clv": float(chunk.clv.mean()),
                    "match_ids": ",".join(str(i) for i in chunk.match_id),
                }
            )
    return pd.DataFrame(
        coupons, columns=["week", "legs", "odds", "ev", "factor", "profit", "clv", "match_ids"]
    )


def model_accuracy(
    matches: pd.DataFrame, predictions: dict[int, np.ndarray], odds: OddsIndex
) -> pd.DataFrame:
    """Log loss modelu i rynku (otwarcie: średnia, zamknięcie: ostry bukmacher).

    Liczone tylko dla meczów, które mają wszystkie trzy prognozy, żeby
    porównanie było na tym samym zbiorze.
    """
    rows = []
    for match in matches.itertuples():
        matrix = predictions.get(match.id)
        if matrix is None:
            continue
        for market, selections in (("1x2", ("home", "draw", "away")), ("ou", ("over", "under"))):
            opening = odds.get((match.id, "market_avg", market, False))
            _, closing = closing_reference(odds, match.id, market)
            if opening is None or closing is None or market == "ou" and closing.line != 2.5:
                continue
            outcome = [
                settle(Selection(market, s, 2.5 if market == "ou" else None), *_score(match))[0]
                for s in selections
            ].index(1.0)
            model = [price(matrix, Selection(market, s, opening.line)).win for s in selections]
            rows.append(
                {
                    "league": match.league,
                    "season": match.season,
                    "market": market,
                    "model": -math.log(model[outcome]),
                    "opening": -math.log(devig([opening.prices[s] for s in selections])[outcome]),
                    "closing": -math.log(devig([closing.prices[s] for s in selections])[outcome]),
                }
            )
    return pd.DataFrame(rows, columns=["league", "season", "market", "model", "opening", "closing"])


def _score(match) -> tuple[int, int]:
    return match.home_goals, match.away_goals
