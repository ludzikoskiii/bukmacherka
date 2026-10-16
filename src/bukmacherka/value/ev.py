"""Wartość oczekiwana zakładów z uwzględnieniem polskiego podatku od stawki.

Podatek `tax` jest pobierany raz od stawki kuponu, więc ze stawki 1 do gry
trafia `1 - tax`. Dla kuponu AKO oczekiwany zwrot to iloczyn oczekiwanych
zwrotów zdarzeń (zakładamy niezależność zdarzeń z różnych meczów) razy
`1 - tax`.
"""

import math
from collections.abc import Iterable, Sequence

from bukmacherka.model.markets import Price


def single_ev(price: Price, odds: float, tax: float) -> float:
    """EV singla na jednostkę stawki (przed podatkiem)."""
    return (1 - tax) * price.expected_return(odds) - 1


def edge(price: Price, odds: float) -> float:
    """Przewaga zdarzenia nad kursem, bez podatku."""
    return price.expected_return(odds) - 1


def accumulator_ev(legs: Iterable[tuple[Price, float]], tax: float) -> float:
    """EV kuponu AKO złożonego z par (wycena zdarzenia, kurs)."""
    return (1 - tax) * math.prod(price.expected_return(odds) for price, odds in legs) - 1


def min_odds_single(price: Price, tax: float, min_ev: float) -> float:
    """Najniższy kurs, przy którym single ma EV co najmniej `min_ev`."""
    if price.win <= 0:
        return math.inf
    return ((1 + min_ev) / (1 - tax) - price.push) / price.win


def min_odds_leg(price: Price, min_edge: float) -> float:
    """Najniższy kurs, przy którym zdarzenie ma przewagę co najmniej `min_edge`."""
    if price.win <= 0:
        return math.inf
    return (1 + min_edge - price.push) / price.win


def devig(odds: Sequence[float]) -> list[float]:
    """Prawdopodobieństwa z kursów po usunięciu marży (metoda proporcjonalna)."""
    implied = [1 / k for k in odds]
    total = sum(implied)
    return [p / total for p in implied]
