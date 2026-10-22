"""Uruchomienie backtestu i raport z wynikami."""

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import sessionmaker

from bukmacherka.backtest import simulate
from bukmacherka.backtest.data import load_matches, load_odds
from bukmacherka.backtest.market_predictions import market_predictions
from bukmacherka.backtest.walk_forward import walk_forward
from bukmacherka.model import dixon_coles

log = logging.getLogger(__name__)

ACCUMULATOR_SIZES = (2, 3, 4, 5)
# Parametry modelu (kary L2) dobrano na sezonach rozpoczętych przed tym rokiem.
TUNED_UNTIL = 2022
MARKET_NAMES = {"1x2": "1X2", "ou": "O/U 2,5", "ah": "Handicap azjatycki"}
FAIR_SOURCES = {
    "model": "model Dixona-Colesa",
    "market": "kursy Pinnacle/Betfair Exchange bez marży",
}


@dataclass
class BacktestConfig:
    leagues: list[str]
    from_season: int
    bookmaker: str = "bet365"
    closing: bool = False
    fair: str = "model"
    tax: float = 0.12
    min_ev: float = 0.05
    min_edge: float = 0.05
    xi: float = dixon_coles.DEFAULT_XI
    reg: float = dixon_coles.DEFAULT_REG
    reg_total: float = dixon_coles.DEFAULT_REG_TOTAL


@dataclass
class BacktestResult:
    config: BacktestConfig
    accuracy: pd.DataFrame
    candidates: pd.DataFrame
    singles: pd.DataFrame
    singles_no_tax: pd.DataFrame
    accumulators: dict[int, pd.DataFrame] = field(default_factory=dict)


def run_backtest(session_factory: sessionmaker, config: BacktestConfig) -> BacktestResult:
    if config.fair not in FAIR_SOURCES:
        raise ValueError(f"Nieznane źródło wyceny: {config.fair}")
    with session_factory() as session:
        matches = load_matches(session, config.leagues)
        odds = load_odds(session, set(matches.id))
    evaluated = matches[matches.season.str[:4].astype(int) >= config.from_season]
    log.info("Prognozy (%s) dla %d meczów...", FAIR_SOURCES[config.fair], len(evaluated))
    if config.fair == "model":
        predictions = walk_forward(
            matches,
            evaluated.date.min(),
            xi=config.xi,
            reg=config.reg,
            reg_total=config.reg_total,
        )
    else:
        predictions = market_predictions(evaluated, odds, closing=config.closing)
    evaluated = evaluated[evaluated.id.isin(predictions)]

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
    timing = (
        "zamknięcia"
        if c.closing
        else "przed zamknięciem (zbierane w piątek dla kolejki weekendowej, we wtorek dla "
        "kolejki w tygodniu)"
    )
    lines = [
        f"Backtest od sezonu {c.from_season}/{c.from_season + 1}, ligi: {', '.join(c.leagues)}",
        f"Wycena: {FAIR_SOURCES[c.fair]}.",
        f"Kursy do gry: {c.bookmaker}, kursy {timing}. Podatek {_pct(c.tax, sign=False)}.",
    ]
    if c.fair == "model":
        lines.append(
            f"Model: Dixon-Coles, xi={c.xi}, kara siły={c.reg}, kara liczby goli={c.reg_total}."
        )
        if c.from_season < TUNED_UNTIL:
            lines.append(
                f"Uwaga: kary modelu dobrano na sezonach do {TUNED_UNTIL - 1}/{TUNED_UNTIL}, "
                "więc wyniki dla nich są w próbie. Czysty test: --from-season "
                f"{TUNED_UNTIL}."
            )
    missing = sorted(set(c.leagues) - set(result.candidates.league))
    if missing:
        lines.append(
            f"Brak kursów {c.bookmaker} do gry dla lig: {', '.join(missing)} "
            "(dla Ekstraklasy są tylko kursy zamknięcia: użyj --closing)."
        )

    lines += ["", "Trafność (log loss, mniej = lepiej). Rynek: kursy bez marży."]
    rows = []
    for (market, league), group in _with_total(result.accuracy, ["market", "league"]):
        pre = group[group.pre_closing.notna()]
        rows.append(
            [
                league,
                MARKET_NAMES[market],
                str(len(group)),
                f"{group.model.mean():.4f}",
                f"{group.closing.mean():.4f}",
                f"{group.model.mean() - group.closing.mean():+.4f}",
                str(len(pre)),
                f"{pre.model.mean() - pre.pre_closing.mean():+.4f}" if len(pre) else "—",
            ]
        )
    lines += _table(
        [
            "Liga",
            "Rynek",
            "Mecze",
            "Prognoza",
            "Zamknięcie",
            "Różnica",
            "Mecze*",
            "Różnica do kursów przed zamkn.*",
        ],
        rows,
    )

    lines += ["", f"Single z EV po podatku ≥ {_pct(c.min_ev, sign=False)} (stawka 1 na zakład)"]
    lines += _summary_table(result.singles, "market", MARKET_NAMES)
    lines += ["", "Te same single według lig"]
    lines += _summary_table(result.singles, "league")

    lines += [
        "",
        f"Bez podatku: zakłady z przewagą ≥ {_pct(c.min_edge, sign=False)} "
        "(czy wycena w ogóle wygrywa z kursem)",
    ]
    lines += _summary_table(result.singles_no_tax, "market", MARKET_NAMES)

    lines += [
        "",
        f"AKO z podatkiem: zdarzenia z przewagą ≥ {_pct(c.min_edge, sign=False)} z jednej partii "
        f"kursów, EV kuponu ≥ {_pct(c.min_ev, sign=False)} (stawka 1 na kupon)",
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
        "ROI ± to 95% przedział ufności (przy wysokich kursach AKO tylko orientacyjny).",
        "CLV: oczekiwany zwrot według kursów zamknięcia Pinnacle lub Betfair Exchange",
        "(dodatni = graliśmy lepiej niż rynek na zamknięciu); w nawiasie liczba zakładów z CLV.",
        "* Porównanie z kursami przed zamknięciem tylko na meczach, które je mają.",
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
    clv = "—" if math.isnan(s.clv) else f"{_pct(s.clv)} ({s.clv_bets})"
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
