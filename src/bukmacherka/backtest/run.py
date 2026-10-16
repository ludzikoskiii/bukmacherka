"""Uruchomienie backtestu i raport z wynikami."""

import datetime as dt
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import sessionmaker

from bukmacherka.backtest import simulate
from bukmacherka.backtest.data import load_matches, load_odds
from bukmacherka.backtest.walk_forward import walk_forward
from bukmacherka.model import dixon_coles

log = logging.getLogger(__name__)

ACCUMULATOR_SIZES = (2, 3, 4, 5)
MARKET_NAMES = {"1x2": "1X2", "ou": "O/U 2,5", "ah": "Handicap azjatycki"}


@dataclass
class BacktestConfig:
    leagues: list[str]
    from_season: int
    bookmaker: str = "bet365"
    closing: bool = False
    tax: float = 0.12
    min_ev: float = 0.05
    min_edge: float = 0.05
    xi: float = dixon_coles.DEFAULT_XI
    reg: float = dixon_coles.DEFAULT_REG


@dataclass
class BacktestResult:
    config: BacktestConfig
    accuracy: pd.DataFrame
    candidates: pd.DataFrame
    singles: pd.DataFrame
    singles_no_tax: pd.DataFrame
    accumulators: dict[int, pd.DataFrame] = field(default_factory=dict)


def run_backtest(session_factory: sessionmaker, config: BacktestConfig) -> BacktestResult:
    with session_factory() as session:
        matches = load_matches(session, config.leagues)
        odds = load_odds(session, set(matches.id))
    eval_from = dt.date(config.from_season, 7, 1)
    log.info("Prognozy walk-forward dla %d lig od %s...", len(config.leagues), eval_from)
    predictions = walk_forward(matches, eval_from, xi=config.xi, reg=config.reg)
    evaluated = matches[matches.id.isin(predictions)]

    cands = simulate.candidates(evaluated, predictions, odds, config.bookmaker, config.closing)
    return BacktestResult(
        config=config,
        accuracy=simulate.model_accuracy(evaluated, predictions, odds),
        candidates=cands,
        singles=simulate.single_bets(cands, config.tax, config.min_ev),
        singles_no_tax=simulate.single_bets(cands, 0.0, config.min_edge),
        accumulators={
            size: simulate.accumulators(cands, size, config.tax, config.min_edge, config.min_ev)
            for size in ACCUMULATOR_SIZES
        },
    )


def save(result: BacktestResult, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    result.candidates.to_csv(directory / "candidates.csv", index=False)
    result.singles.to_csv(directory / "singles.csv", index=False)
    pd.concat(result.accumulators.values()).to_csv(directory / "accumulators.csv", index=False)


def format_report(result: BacktestResult) -> str:
    c = result.config
    timing = "zamknięcia" if c.closing else "otwarcia"
    lines = [
        f"Backtest od sezonu {c.from_season}/{c.from_season + 1}, ligi: {', '.join(c.leagues)}",
        f"Kursy do gry: {c.bookmaker}, kursy {timing}. Podatek {_pct(c.tax, sign=False)}.",
        f"Model: Dixon-Coles, xi={c.xi}, kara L2={c.reg}.",
        "",
        "Trafność (log loss, mniej = lepiej). Rynek: kursy bez marży.",
    ]
    lines += _table(
        ["Liga", "Rynek", "Mecze", "Model", "Otwarcie", "Zamknięcie", "Model − zamkn."],
        [
            [
                league,
                MARKET_NAMES[market],
                str(len(group)),
                f"{group.model.mean():.4f}",
                f"{group.opening.mean():.4f}",
                f"{group.closing.mean():.4f}",
                f"{group.model.mean() - group.closing.mean():+.4f}",
            ]
            for (market, league), group in _with_total(result.accuracy, ["market", "league"])
        ],
    )

    lines += ["", f"Single z EV po podatku ≥ {_pct(c.min_ev, sign=False)} (stawka 1 na zakład)"]
    lines += _summary_table(result.singles, "market", MARKET_NAMES)
    lines += ["", "Te same single według lig"]
    lines += _summary_table(result.singles, "league")

    lines += [
        "",
        f"Bez podatku: zakłady z przewagą ≥ {_pct(c.min_edge, sign=False)} "
        "(czy model w ogóle wygrywa z kursem)",
    ]
    lines += _summary_table(result.singles_no_tax, "market", MARKET_NAMES)

    lines += [
        "",
        f"AKO z podatkiem: zdarzenia z przewagą ≥ {_pct(c.min_edge, sign=False)}, "
        f"EV kuponu ≥ {_pct(c.min_ev, sign=False)} (stawka 1 na kupon)",
    ]
    rows = []
    for size, coupons in result.accumulators.items():
        s = simulate.Summary.of(coupons.profit, coupons.odds, coupons.factor, coupons.clv)
        rows.append([f"AKO {size}", *_summary_cells(s)])
    lines += _table(_SUMMARY_HEADER, rows)

    lines += ["", "Dla porównania: wszystkie możliwe single bez selekcji, z podatkiem"]
    everything = simulate.single_bets(result.candidates, c.tax, -math.inf)
    lines += _summary_table(everything, "market", MARKET_NAMES)
    lines += [
        "",
        "ROI ± to 95% przedział ufności. CLV: kurs gry względem kursu sprawiedliwego",
        "z zamknięcia Pinnacle lub Betfair Exchange (dodatni = graliśmy lepiej niż rynek).",
    ]
    return "\n".join(lines)


_SUMMARY_HEADER = ["", "Zakłady", "ROI", "Śr. kurs", "Trafione", "CLV"]


def _summary_table(bets: pd.DataFrame, by: str, names: dict | None = None) -> list[str]:
    rows = []
    for key, group in _with_total(bets, [by]):
        s = simulate.Summary.of(group.profit, group.odds, group.factor, group.clv)
        label = key[0] if names is None or key[0] == "Razem" else names.get(key[0], key[0])
        rows.append([label, *_summary_cells(s)])
    return _table(_SUMMARY_HEADER, rows)


def _summary_cells(s: simulate.Summary) -> list[str]:
    if s.bets == 0:
        return ["0", "—", "—", "—", "—"]
    roi = _pct(s.roi) + (f" ± {_pct(s.roi_ci, sign=False)}" if not math.isnan(s.roi_ci) else "")
    clv = "—" if math.isnan(s.clv) else _pct(s.clv)
    avg_odds = f"{s.avg_odds:.2f}".replace(".", ",")
    return [str(s.bets), roi, avg_odds, _pct(s.hit_rate, sign=False), clv]


def _with_total(df: pd.DataFrame, by: list[str]):
    """Grupy według `by` i na końcu wiersz „Razem” dla całości (lub każdej
    wartości pierwszej kolumny, gdy grupujemy po dwóch kolumnach)."""
    if df.empty:
        return
    if len(by) == 1:
        yield from ((key, group) for key, group in df.groupby(by))
        yield ("Razem",), df
        return
    for first, outer in df.groupby(by[0]):
        for (second,), group in outer.groupby(by[1:]):
            yield (first, second), group
        yield (first, "Razem"), outer


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    all_rows = [header, *rows]
    widths = [max(len(row[i]) for row in all_rows) for i in range(len(header))]
    return [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in all_rows
    ]


def _pct(value: float, sign: bool = True) -> str:
    return (f"{value * 100:+.1f}%" if sign else f"{value * 100:.1f}%").replace(".", ",")
