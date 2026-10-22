"""Symulacja obstawiania singli i kuponów AKO na historycznych kursach."""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bukmacherka.backtest.data import OddsIndex, OddsSet
from bukmacherka.backtest.walk_forward import odds_batch
from bukmacherka.model.market_implied import implied_matrix
from bukmacherka.model.markets import Selection, price, settle
from bukmacherka.value.ev import devig

# Kursy o najmniejszej marży, w kolejności preferencji. Ich kursy zamknięcia
# służą do CLV i do oceny trafności modelu.
SHARP_BOOKMAKERS = ("pinnacle", "betfair_exchange")
MARKET_SELECTIONS = {
    "1x2": ("home", "draw", "away"),
    "ou": ("over", "under"),
    "ah": ("home", "away"),
}
CANDIDATE_COLUMNS = [
    "match_id",
    "league",
    "season",
    "date",
    "batch",
    "market",
    "selection",
    "line",
    "odds",
    "win",
    "push",
    "edge",
    "factor",
    "clv",
]
COUPON_COLUMNS = ["batch", "legs", "odds", "ev", "factor", "profit", "clv", "match_ids"]


def reference(
    odds: OddsIndex, match_id: int, market: str, closing: bool, sharp_only: bool = False
) -> tuple[str | None, OddsSet | None]:
    """Kursy najostrzejszego dostępnego bukmachera, inaczej średnia rynkowa."""
    bookmakers = SHARP_BOOKMAKERS if sharp_only else (*SHARP_BOOKMAKERS, "market_avg")
    for bookmaker in bookmakers:
        odds_set = odds.get((match_id, bookmaker, market, closing))
        if odds_set is not None:
            return bookmaker, odds_set
    return None, None


class _ClosingFair:
    """Sprawiedliwa wycena zakładu według kursów zamknięcia ostrego bukmachera.

    Gdy linia zakładu jest taka sama jak linia zamknięcia, używamy kursów
    zamknięcia bezpośrednio. Gdy linia się przesunęła (częste przy handicapie
    azjatyckim), wyceniamy zakład z macierzy wyników dopasowanej do kursów
    zamknięcia 1X2 i Over/Under.
    """

    def __init__(self, odds: OddsIndex, match_id: int):
        self.odds = odds
        self.match_id = match_id
        self._matrix: np.ndarray | None = None
        self._matrix_done = False

    def expected_return(self, selection: Selection, odds_value: float) -> float:
        _, ref = reference(self.odds, self.match_id, selection.market, True, sharp_only=True)
        if ref is not None and ref.line == selection.line and not _can_push(selection):
            names = MARKET_SELECTIONS[selection.market]
            fair = dict(zip(names, devig([ref.prices[s] for s in names]), strict=True))
            return fair[selection.selection] * odds_value
        matrix = self._closing_matrix()
        if matrix is None:
            return math.nan
        return price(matrix, selection).expected_return(odds_value)

    def _closing_matrix(self) -> np.ndarray | None:
        if not self._matrix_done:
            self._matrix_done = True
            _, result = reference(self.odds, self.match_id, "1x2", True, sharp_only=True)
            if result is not None:
                p_1x2 = devig([result.prices[s] for s in ("home", "draw", "away")])
                _, totals = reference(self.odds, self.match_id, "ou", True, sharp_only=True)
                p_over = (
                    devig([totals.prices["over"], totals.prices["under"]])[0] if totals else None
                )
                line = totals.line if totals else 2.5
                self._matrix, _ = implied_matrix(p_1x2, p_over, line)
        return self._matrix


def _can_push(selection: Selection) -> bool:
    """Czy zakład może skończyć się zwrotem (linia całkowita lub ćwiartkowa).

    Dla takich linii kurs sprawiedliwy z dwudrogowego rynku nie wystarcza do
    policzenia oczekiwanego zwrotu, bo nie znamy prawdopodobieństwa zwrotu.
    """
    return selection.line is not None and (selection.line * 2) % 2 != 1


def candidates(
    matches: pd.DataFrame,
    predictions: dict[int, np.ndarray],
    odds: OddsIndex,
    bookmaker: str,
    closing: bool,
) -> pd.DataFrame:
    """Wszystkie zakłady, które dało się postawić u `bookmaker`, z wyceną.

    Kolumny: `win`/`push` z prognozy, `edge` (przewaga bez podatku), `factor`
    (faktyczny zwrot ze stawki 1 bez podatku po rozliczeniu), `clv`
    (oczekiwany zwrot według kursów zamknięcia ostrego bukmachera minus 1)
    i `batch` (dzień zebrania kursów; przy kursach zamknięcia dzień meczu).
    """
    rows = []
    for match in matches.itertuples():
        matrix = predictions.get(match.id)
        if matrix is None:
            continue
        closing_fair = _ClosingFair(odds, match.id)
        for market, selections in MARKET_SELECTIONS.items():
            bet_set = odds.get((match.id, bookmaker, market, closing))
            if bet_set is None:
                continue
            for name in selections:
                selection = Selection(market, name, bet_set.line)
                forecast = price(matrix, selection)
                odds_value = bet_set.prices[name]
                won, pushed = settle(selection, match.home_goals, match.away_goals)
                rows.append(
                    {
                        "match_id": match.id,
                        "league": match.league,
                        "season": match.season,
                        "date": match.date,
                        "batch": match.date if closing else odds_batch(match.date),
                        "market": market,
                        "selection": name,
                        "line": bet_set.line,
                        "odds": odds_value,
                        "win": forecast.win,
                        "push": forecast.push,
                        "edge": forecast.expected_return(odds_value) - 1,
                        "factor": won * odds_value + pushed,
                        "clv": closing_fair.expected_return(selection, odds_value) - 1,
                    }
                )
    return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)


@dataclass(frozen=True)
class Summary:
    bets: int
    roi: float
    roi_ci: float
    avg_odds: float
    hit_rate: float
    clv: float
    clv_bets: int

    @classmethod
    def of(cls, profit: pd.Series, odds: pd.Series, factor: pd.Series, clv: pd.Series):
        n = len(profit)
        if n == 0:
            return cls(0, math.nan, math.nan, math.nan, math.nan, math.nan, 0)
        ci = 1.96 * profit.std(ddof=1) / math.sqrt(n) if n > 1 else math.nan
        return cls(
            bets=n,
            roi=float(profit.mean()),
            roi_ci=float(ci),
            avg_odds=float(odds.mean()),
            hit_rate=float((factor > 1).mean()),
            clv=float(clv.mean()) if clv.notna().any() else math.nan,
            clv_bets=int(clv.notna().sum()),
        )


def single_bets(cands: pd.DataFrame, tax: float, min_ev: float) -> pd.DataFrame:
    """Single z EV po podatku co najmniej `min_ev`, stawka 1 na zakład."""
    ev = (1 - tax) * (cands.edge + 1) - 1
    bets = cands[ev >= min_ev].copy()
    bets["ev"] = ev[ev >= min_ev]
    bets["profit"] = (1 - tax) * bets.factor - 1
    return bets


def accumulators(
    cands: pd.DataFrame, size: int, tax: float, min_edge: float, min_ev: float
) -> pd.DataFrame:
    """Kupony AKO z zakładów o przewadze co najmniej `min_edge`, stawka 1 na kupon.

    Kupon łączy tylko zdarzenia z jednej partii kursów (`batch`), czyli takie,
    których kursy były znane jednocześnie przed pierwszym meczem kuponu.
    W partii z każdego meczu bierzemy najlepsze zdarzenie, sortujemy je od
    największej przewagi i dzielimy kolejno na kupony po `size` zdarzeń.
    Kupon trafia do gry, jeśli jego EV po podatku wynosi co najmniej
    `min_ev`. Zakładamy niezależność zdarzeń z różnych meczów.
    """
    legs = cands[cands.edge >= min_edge]
    if legs.empty:
        return pd.DataFrame(columns=COUPON_COLUMNS)
    legs = legs.sort_values("edge", ascending=False).drop_duplicates("match_id")
    coupons = []
    for batch, group in legs.groupby("batch"):
        group = group.sort_values("edge", ascending=False)
        for start in range(0, len(group) - size + 1, size):
            chunk = group.iloc[start : start + size]
            # np.prod na tablicach numpy, bo prod() z pandas pomija NaN.
            factor = float(np.prod(chunk.factor.to_numpy()))
            ev = (1 - tax) * float(np.prod(chunk.edge.to_numpy() + 1)) - 1
            if ev < min_ev:
                continue
            coupons.append(
                {
                    "batch": batch,
                    "legs": size,
                    "odds": float(np.prod(chunk.odds.to_numpy())),
                    "ev": ev,
                    "factor": factor,
                    "profit": (1 - tax) * factor - 1,
                    # CLV kuponu narasta z każdym zdarzeniem; brak CLV jednego
                    # zdarzenia oznacza brak CLV całego kuponu.
                    "clv": float(np.prod(chunk.clv.to_numpy() + 1)) - 1,
                    "match_ids": ",".join(str(i) for i in chunk.match_id),
                }
            )
    return pd.DataFrame(coupons, columns=COUPON_COLUMNS)


def model_accuracy(
    matches: pd.DataFrame, predictions: dict[int, np.ndarray], odds: OddsIndex
) -> pd.DataFrame:
    """Log loss prognozy i rynku na tych samych meczach.

    `closing`: kursy zamknięcia (Pinnacle, Betfair Exchange albo średnia).
    `pre_closing`: kursy przed zamknięciem z tego samego źródła; NaN, gdy ich
    nie ma (np. Ekstraklasa). Rynek: kursy po usunięciu marży.
    """
    rows = []
    for match in matches.itertuples():
        matrix = predictions.get(match.id)
        if matrix is None:
            continue
        for market, selections in (("1x2", ("home", "draw", "away")), ("ou", ("over", "under"))):
            _, closing = reference(odds, match.id, market, True)
            if closing is None or market == "ou" and closing.line != 2.5:
                continue
            line = 2.5 if market == "ou" else None
            outcome = [
                settle(Selection(market, s, line), match.home_goals, match.away_goals)[0]
                for s in selections
            ].index(1.0)
            forecast = price(matrix, Selection(market, selections[outcome], line)).win
            _, pre = reference(odds, match.id, market, False)
            pre_ok = pre is not None and pre.line == closing.line
            rows.append(
                {
                    "league": match.league,
                    "season": match.season,
                    "market": market,
                    "model": -math.log(forecast),
                    "pre_closing": _log_loss(pre, selections, outcome) if pre_ok else math.nan,
                    "closing": _log_loss(closing, selections, outcome),
                }
            )
    return pd.DataFrame(
        rows, columns=["league", "season", "market", "model", "pre_closing", "closing"]
    )


def _log_loss(odds_set: OddsSet, selections: tuple[str, ...], outcome: int) -> float:
    return -math.log(devig([odds_set.prices[s] for s in selections])[outcome])
