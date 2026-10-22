"""Rynki zakładów liczone z macierzy wyników meczu.

Każdy zakład jest opisany przez to, jaka część stawki wygrywa (`win`), a jaka
jest zwracana (`push`) przy danym wyniku. Pozwala to jednolicie liczyć
zwykłe zakłady, zwroty (np. handicap azjatycki 0, linia 2,0) i ćwiartki
(np. -0,25, gdzie połowa stawki gra na linii 0, a połowa na -0,5).

Dla kursu `k` oczekiwany zwrot ze stawki 1 (bez podatku) wynosi
`win * k + push`, a kurs sprawiedliwy to `(1 - push) / win`.
"""

import math
from dataclasses import dataclass
from functools import cache

import numpy as np


@dataclass(frozen=True)
class Selection:
    market: str
    selection: str
    line: float | None = None

    def label(self) -> str:
        """Opis zakładu z linią widzianą od strony typowanej drużyny.

        W handicapach linia jest zapisana jako handicap gospodarza, więc dla
        gościa odwracamy znak. Remis w handicapie europejskim opisujemy
        handicapem gospodarza, bo nie ma „swojej” strony.
        """
        if self.line is None:
            return self.selection
        if self.market == "eh" and self.selection == "draw":
            return f"draw (home {_signed(self.line)})"
        handicap = self.market in ("ah", "eh") and self.selection == "away"
        return f"{self.selection} {_signed(-self.line if handicap else self.line)}"


def _signed(line: float) -> str:
    return "0" if line == 0 else f"{line:+g}"


@dataclass(frozen=True)
class Price:
    selection: Selection
    win: float
    push: float

    @property
    def fair_odds(self) -> float:
        return (1 - self.push) / self.win if self.win > 0 else math.inf

    def expected_return(self, odds: float) -> float:
        """Oczekiwany zwrot ze stawki 1 przy kursie `odds`, bez podatku."""
        return self.win * odds + self.push


def settle(selection: Selection, home_goals: int, away_goals: int) -> tuple[float, float]:
    """Rozliczenie zakładu dla wyniku: (część stawki wygrana, część zwrócona)."""
    win, push = _grids(selection, max(home_goals, away_goals) + 1)
    return float(win[home_goals, away_goals]), float(push[home_goals, away_goals])


def price(matrix: np.ndarray, selection: Selection) -> Price:
    win, push = _grids(selection, matrix.shape[0])
    return Price(selection, float((matrix * win).sum()), float((matrix * push).sum()))


def price_all(matrix: np.ndarray) -> list[Price]:
    return [price(matrix, selection) for selection in catalog()]


@cache
def catalog() -> tuple[Selection, ...]:
    """Wszystkie rynki, które model wycenia dla każdego meczu."""
    s: list[Selection] = []
    s += [Selection("1x2", v) for v in ("home", "draw", "away")]
    s += [Selection("double_chance", v) for v in ("1X", "12", "X2")]
    s += [Selection("draw_no_bet", v) for v in ("home", "away")]
    for line in _lines(0.5, 6.5, 0.25):
        s += [Selection("ou", "over", line), Selection("ou", "under", line)]
    for team in ("home", "away"):
        for line in _lines(0.5, 4.5, 0.5):
            s += [Selection(f"{team}_total", side, line) for side in ("over", "under")]
    s += [Selection("btts", v) for v in ("yes", "no")]
    for line in _lines(-3.5, 3.5, 0.25):
        s += [Selection("ah", "home", line), Selection("ah", "away", line)]
    for line in (-3.0, -2.0, -1.0, 1.0, 2.0, 3.0):
        s += [Selection("eh", v, line) for v in ("home", "draw", "away")]
    s += [Selection("cs", f"{h}:{a}") for h in range(6) for a in range(6)]
    s += [Selection("total_exact", str(g)) for g in range(6)] + [Selection("total_exact", "6+")]
    s += [Selection("goals_range", r) for r in GOAL_RANGES]
    s += [Selection("odd_even", v) for v in ("odd", "even")]
    s += [Selection("margin", v) for v in MARGINS]
    s += [Selection("clean_sheet", v) for v in ("home", "away")]
    s += [Selection("win_to_nil", v) for v in ("home", "away")]
    for line in (1.5, 2.5, 3.5):
        for result in ("home", "draw", "away"):
            s += [Selection("1x2_ou", f"{result}&{side}", line) for side in ("over", "under")]
    for result in ("1X", "12", "X2"):
        s += [Selection("dc_ou", f"{result}&{side}", 2.5) for side in ("over", "under")]
    for result in ("home", "draw", "away"):
        s += [Selection("1x2_btts", f"{result}&{b}") for b in ("yes", "no")]
    for b in ("yes", "no"):
        s += [Selection("btts_ou", f"{b}&{side}", 2.5) for side in ("over", "under")]
    return tuple(s)


GOAL_RANGES = ("0-1", "1-2", "1-3", "2-3", "2-4", "3-4", "3-5", "4-5", "4-6", "4+", "5+", "6+")
MARGINS = ("home_3+", "home_2", "home_1", "draw", "away_1", "away_2", "away_3+")


def _lines(start: float, stop: float, step: float) -> list[float]:
    count = round((stop - start) / step) + 1
    return [round(start + i * step, 2) for i in range(count)]


@cache
def _grids(selection: Selection, size: int) -> tuple[np.ndarray, np.ndarray]:
    x, y = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
    win, push = _settlement(selection, x, y)
    win = np.broadcast_to(np.asarray(win, dtype=float), x.shape)
    push = np.broadcast_to(np.asarray(push, dtype=float), x.shape)
    win.flags.writeable = False
    push.flags.writeable = False
    return win, push


def _asian(margin: np.ndarray, line: float) -> tuple[np.ndarray, np.ndarray]:
    """Rozliczenie linii azjatyckiej: wynik zakładu to `margin + line`.

    Linie ćwiartkowe (np. -0,75) dzielą stawkę na dwie połowy grające na
    sąsiednich liniach (-0,5 i -1,0).
    """
    lines = [line - 0.25, line + 0.25] if (line * 4) % 2 == 1 else [line]
    win = sum((margin + sub > 0).astype(float) for sub in lines) / len(lines)
    push = sum((margin + sub == 0).astype(float) for sub in lines) / len(lines)
    return win, push


def _binary(condition: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return condition.astype(float), np.zeros(condition.shape)


def _outcome(name: str, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return {
        "home": x > y,
        "draw": x == y,
        "away": x < y,
        "1X": x >= y,
        "12": x != y,
        "X2": x <= y,
    }[name]


def _settlement(sel: Selection, x: np.ndarray, y: np.ndarray):
    market, value, line = sel.market, sel.selection, sel.line
    total = x + y

    if market in ("1x2", "double_chance"):
        return _binary(_outcome(value, x, y))
    if market == "draw_no_bet":
        return _asian(x - y if value == "home" else y - x, 0.0)
    if market == "ou":
        return _asian(total if value == "over" else -total, -line if value == "over" else line)
    if market in ("home_total", "away_total"):
        goals = x if market == "home_total" else y
        return _asian(goals if value == "over" else -goals, -line if value == "over" else line)
    if market == "btts":
        both = (x > 0) & (y > 0)
        return _binary(both if value == "yes" else ~both)
    if market == "ah":
        # Linia jest handicapem gospodarza; zakład na gościa gra z linią przeciwną.
        return _asian(x - y, line) if value == "home" else _asian(y - x, -line)
    if market == "eh":
        margin = x - y + line
        return _binary({"home": margin > 0, "draw": margin == 0, "away": margin < 0}[value])
    if market == "cs":
        h, a = (int(v) for v in value.split(":"))
        return _binary((x == h) & (y == a))
    if market == "total_exact":
        return _binary(total >= 6 if value == "6+" else total == int(value))
    if market == "goals_range":
        if value.endswith("+"):
            return _binary(total >= int(value[:-1]))
        low, high = (int(v) for v in value.split("-"))
        return _binary((total >= low) & (total <= high))
    if market == "odd_even":
        return _binary(total % 2 == (1 if value == "odd" else 0))
    if market == "margin":
        if value == "draw":
            return _binary(x == y)
        side, size = value.split("_")
        diff = x - y if side == "home" else y - x
        return _binary(diff >= 3 if size == "3+" else diff == int(size))
    if market == "clean_sheet":
        return _binary(y == 0 if value == "home" else x == 0)
    if market == "win_to_nil":
        return _binary((x > y) & (y == 0) if value == "home" else (y > x) & (x == 0))
    if market in ("1x2_ou", "dc_ou", "btts_ou", "1x2_btts"):
        first, second = value.split("&")
        if market == "btts_ou":
            both = (x > 0) & (y > 0)
            left = both if first == "yes" else ~both
        else:
            left = _outcome(first, x, y)
        if market == "1x2_btts":
            both = (x > 0) & (y > 0)
            right = both if second == "yes" else ~both
        else:
            right = total > line if second == "over" else total < line
        return _binary(left & right)
    raise ValueError(f"Nieznany rynek: {sel}")
