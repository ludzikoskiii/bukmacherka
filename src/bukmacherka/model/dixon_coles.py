"""Model Dixona-Colesa (1997).

Liczba goli gospodarza i gościa ma rozkład Poissona z parametrami

    log λ = intercept + home_advantage + attack[gospodarz] + defence[gość]
    log μ = intercept + attack[gość] + defence[gospodarz]

z korektą τ dla wyników 0:0, 1:0, 0:1 i 1:1 (parametr ρ). Mecze są ważone
wykładniczo według wieku, a parametry drużyn są ściągane karą L2 w stronę
wartości a priori (domyślnie 0, czyli średnia drużyna ligi). Kara zastępuje
klasyczne ograniczenie sumy parametrów do zera i stabilizuje oceny drużyn,
które mają mało meczów.
"""

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

# Waga meczu sprzed `t` dni to exp(-XI * t). 0,0019 daje połowiczny spadek
# wagi po ok. roku.
DEFAULT_XI = 0.0019
DEFAULT_REG = 2.0
DEFAULT_MAX_GOALS = 10
RHO_BOUNDS = (-0.3, 0.3)


@dataclass(frozen=True)
class DixonColes:
    teams: tuple[str, ...]
    attack: np.ndarray
    defence: np.ndarray
    intercept: float
    home_advantage: float
    rho: float

    def _index(self, team: str) -> int:
        try:
            return self.teams.index(team)
        except ValueError:
            raise KeyError(f"Drużyna {team!r} nie występuje w modelu") from None

    def expected_goals(self, home: str, away: str) -> tuple[float, float]:
        h, a = self._index(home), self._index(away)
        lam = np.exp(self.intercept + self.home_advantage + self.attack[h] + self.defence[a])
        mu = np.exp(self.intercept + self.attack[a] + self.defence[h])
        return float(lam), float(mu)

    def score_matrix(self, home: str, away: str, max_goals: int = DEFAULT_MAX_GOALS) -> np.ndarray:
        lam, mu = self.expected_goals(home, away)
        return score_matrix(lam, mu, self.rho, max_goals)

    def params(self) -> dict[str, tuple[float, float]]:
        return {
            team: (float(self.attack[i]), float(self.defence[i]))
            for i, team in enumerate(self.teams)
        }


def score_matrix(
    lam: float, mu: float, rho: float, max_goals: int = DEFAULT_MAX_GOALS
) -> np.ndarray:
    """Macierz P(gole gospodarza = wiersz, gole gościa = kolumna)."""
    goals = np.arange(max_goals + 1)
    matrix = np.outer(poisson.pmf(goals, lam), poisson.pmf(goals, mu))
    matrix[0, 0] *= max(1 - lam * mu * rho, 0.0)
    matrix[0, 1] *= max(1 + lam * rho, 0.0)
    matrix[1, 0] *= max(1 + mu * rho, 0.0)
    matrix[1, 1] *= max(1 - rho, 0.0)
    return matrix / matrix.sum()


def time_weights(dates: Iterable[dt.date], ref_date: dt.date, xi: float = DEFAULT_XI) -> np.ndarray:
    days = np.array([(ref_date - d).days for d in dates], dtype=float)
    if (days < 0).any():
        raise ValueError("Mecze do dopasowania muszą być rozegrane przed datą odniesienia")
    return np.exp(-xi * days)


def fit(
    home: Sequence[str],
    away: Sequence[str],
    home_goals: Sequence[int],
    away_goals: Sequence[int],
    weights: Sequence[float] | None = None,
    *,
    extra_teams: Iterable[str] = (),
    priors: Mapping[str, tuple[float, float]] | None = None,
    reg: float = DEFAULT_REG,
    init: DixonColes | None = None,
) -> DixonColes:
    """Dopasowuje model metodą największej wiarygodności z karą L2.

    `extra_teams` to drużyny bez meczów w danych (np. beniaminkowie przed
    pierwszą kolejką), dla których model przyjmie wartości a priori.
    `priors` podaje dla wybranych drużyn (atak, obrona), w stronę których
    ściągane są parametry. `init` przyspiesza dopasowanie, startując
    z parametrów poprzedniego modelu.
    """
    if reg <= 0:
        raise ValueError("Kara L2 musi być dodatnia, bo zapewnia identyfikowalność modelu")
    teams = tuple(sorted(set(home) | set(away) | set(extra_teams)))
    index = {team: i for i, team in enumerate(teams)}
    n = len(teams)
    hi = np.array([index[t] for t in home], dtype=np.intp)
    ai = np.array([index[t] for t in away], dtype=np.intp)
    x = np.asarray(home_goals, dtype=float)
    y = np.asarray(away_goals, dtype=float)
    w = np.ones_like(x) if weights is None else np.asarray(weights, dtype=float)

    priors = priors or {}
    prior_att = np.array([priors.get(t, (0.0, 0.0))[0] for t in teams])
    prior_def = np.array([priors.get(t, (0.0, 0.0))[1] for t in teams])

    theta0 = np.concatenate(
        [[np.log(max((x.mean() + y.mean()) / 2, 0.1)), 0.25, -0.05], prior_att, prior_def]
    )
    if init is not None:
        theta0[:3] = [init.intercept, init.home_advantage, init.rho]
        previous = init.params()
        for team, i in index.items():
            if team in previous:
                theta0[3 + i], theta0[3 + n + i] = previous[team]

    masks = ((x == 0) & (y == 0), (x == 0) & (y == 1), (x == 1) & (y == 0), (x == 1) & (y == 1))
    result = minimize(
        _objective,
        theta0,
        args=(hi, ai, x, y, w, n, prior_att, prior_def, reg, masks),
        jac=True,
        method="L-BFGS-B",
        bounds=[(None, None), (None, None), RHO_BOUNDS] + [(None, None)] * (2 * n),
    )
    theta = result.x
    return DixonColes(
        teams=teams,
        attack=theta[3 : 3 + n].copy(),
        defence=theta[3 + n :].copy(),
        intercept=float(theta[0]),
        home_advantage=float(theta[1]),
        rho=float(theta[2]),
    )


def _objective(theta, hi, ai, x, y, w, n, prior_att, prior_def, reg, masks):
    """Ujemna ważona log-wiarygodność z karą L2 oraz jej gradient."""
    intercept, home_adv, rho = theta[0], theta[1], theta[2]
    att = theta[3 : 3 + n]
    dfc = theta[3 + n :]

    a = intercept + home_adv + att[hi] + dfc[ai]
    b = intercept + att[ai] + dfc[hi]
    lam = np.exp(a)
    mu = np.exp(b)

    # Log-wiarygodność Poissona bez stałych log(x!) i log(y!).
    ll = x * a - lam + y * b - mu
    grad_a = x - lam
    grad_b = y - mu
    grad_rho = np.zeros_like(x)
    tau = np.ones_like(x)

    m00, m01, m10, m11 = masks
    t = 1 - lam[m00] * mu[m00] * rho
    tau[m00] = t
    grad_a[m00] -= lam[m00] * mu[m00] * rho / t
    grad_b[m00] -= lam[m00] * mu[m00] * rho / t
    grad_rho[m00] = -lam[m00] * mu[m00] / t

    t = 1 + lam[m01] * rho
    tau[m01] = t
    grad_a[m01] += lam[m01] * rho / t
    grad_rho[m01] = lam[m01] / t

    t = 1 + mu[m10] * rho
    tau[m10] = t
    grad_b[m10] += mu[m10] * rho / t
    grad_rho[m10] = mu[m10] / t

    tau[m11] = 1 - rho
    grad_rho[m11] = -1 / (1 - rho)

    ll += np.log(np.maximum(tau, 1e-12))

    wa = w * grad_a
    wb = w * grad_b
    d_att = att - prior_att
    d_def = dfc - prior_def

    value = -np.dot(w, ll) + 0.5 * reg * (d_att @ d_att + d_def @ d_def)
    grad = np.empty_like(theta)
    grad[0] = -(wa.sum() + wb.sum())
    grad[1] = -wa.sum()
    grad[2] = -np.dot(w, grad_rho)
    grad[3 : 3 + n] = -(np.bincount(hi, wa, n) + np.bincount(ai, wb, n)) + reg * d_att
    grad[3 + n :] = -(np.bincount(ai, wa, n) + np.bincount(hi, wb, n)) + reg * d_def
    return value, grad
