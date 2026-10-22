"""Macierz wyników dopasowana do kursów rynku.

Dla meczu z kursami ostrego bukmachera (Pinnacle, Betfair Exchange) szukamy
oczekiwanej liczby goli gospodarza i gościa, przy których macierz
Dixona-Colesa odtwarza prawdopodobieństwa z kursów 1X2 i (jeśli są)
Over/Under. Z tej macierzy wyceniamy potem wszystkie pozostałe rynki.

Na danych historycznych tak wyznaczone kursy handicapu azjatyckiego różnią
się od kursów Pinnacle na tym rynku średnio o 0,7%, choć macierz nie
widziała tych kursów.
"""

import math
from collections.abc import Sequence

import numpy as np
from scipy.optimize import minimize

from bukmacherka.model.dixon_coles import DEFAULT_MAX_GOALS, score_matrix
from bukmacherka.model.markets import Selection, price

DEFAULT_RHO = -0.05


def implied_matrix(
    p_1x2: Sequence[float],
    p_over: float | None = None,
    line: float = 2.5,
    *,
    rho: float = DEFAULT_RHO,
    max_goals: int = DEFAULT_MAX_GOALS,
) -> tuple[np.ndarray, float]:
    """Zwraca macierz wyników i błąd dopasowania (RMSE prawdopodobieństw).

    `p_1x2` to prawdopodobieństwa (gospodarz, remis, gość) z kursów bez
    marży. `p_over` to prawdopodobieństwo powyżej `line` goli; dla linii ze
    zwrotem (np. 2,0 albo 2,25) chodzi o prawdopodobieństwo wygranej pod
    warunkiem, że zakład nie skończył się zwrotem, bo tak je zwraca usunięcie
    marży z dwudrogowego rynku.
    """
    targets = [*p_1x2] + ([p_over] if p_over is not None else [])
    over = Selection("ou", "over", line)

    def implied(log_rates: np.ndarray) -> list[float]:
        matrix = score_matrix(math.exp(log_rates[0]), math.exp(log_rates[1]), rho, max_goals)
        probs = [np.tril(matrix, -1).sum(), np.trace(matrix), np.triu(matrix, 1).sum()]
        if p_over is not None:
            p = price(matrix, over)
            probs.append(p.win / (1 - p.push))
        return probs

    def loss(log_rates: np.ndarray) -> float:
        return sum((a - b) ** 2 for a, b in zip(implied(log_rates), targets, strict=True))

    start = _initial_guess(p_1x2)
    result = minimize(loss, start, method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-12})
    lam, mu = math.exp(result.x[0]), math.exp(result.x[1])
    return score_matrix(lam, mu, rho, max_goals), math.sqrt(result.fun / len(targets))


def _initial_guess(p_1x2: Sequence[float]) -> np.ndarray:
    # Przy ok. 2,7 golach na mecz różnica szans gospodarza i gościa przekłada
    # się mniej więcej liniowo na różnicę logarytmów oczekiwanych goli.
    diff = 1.6 * (p_1x2[0] - p_1x2[2])
    return np.array([math.log(1.35) + diff / 2, math.log(1.35) - diff / 2])
