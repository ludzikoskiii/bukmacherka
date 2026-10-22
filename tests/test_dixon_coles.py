import datetime as dt

import numpy as np
import pytest
from scipy.stats import poisson

from bukmacherka.model import dixon_coles as dc


def test_score_matrix_without_correction_is_poisson():
    matrix = dc.score_matrix(1.4, 0.9, 0.0, max_goals=15)

    expected = np.outer(poisson.pmf(np.arange(16), 1.4), poisson.pmf(np.arange(16), 0.9))
    np.testing.assert_allclose(matrix, expected / expected.sum())


def test_score_matrix_low_score_correction():
    plain = dc.score_matrix(1.4, 0.9, 0.0)
    corrected = dc.score_matrix(1.4, 0.9, -0.1)

    assert corrected.sum() == pytest.approx(1)
    # Ujemne ρ podbija remisy 0:0 i 1:1 kosztem 1:0 i 0:1.
    assert corrected[0, 0] > plain[0, 0]
    assert corrected[1, 1] > plain[1, 1]
    assert corrected[1, 0] < plain[1, 0]
    assert corrected[0, 1] < plain[0, 1]


def test_time_weights():
    ref = dt.date(2025, 1, 1)
    weights = dc.time_weights([ref, ref - dt.timedelta(days=365)], ref, xi=0.0019)

    np.testing.assert_allclose(weights, [1.0, np.exp(-0.0019 * 365)])
    with pytest.raises(ValueError):
        dc.time_weights([ref + dt.timedelta(days=1)], ref)


def test_fit_recovers_parameters_from_simulated_matches():
    rng = np.random.default_rng(0)
    teams = [f"T{i}" for i in range(8)]
    attack = np.array([0.4, 0.25, 0.1, 0.0, -0.05, -0.15, -0.25, -0.3])
    defence = np.array([-0.35, -0.2, -0.1, 0.0, 0.05, 0.15, 0.2, 0.25])
    intercept, home_adv, rho = 0.1, 0.3, -0.1

    home, away, hg, ag = [], [], [], []
    for _ in range(150):
        for h in range(8):
            for a in range(8):
                if h == a:
                    continue
                lam = np.exp(intercept + home_adv + attack[h] + defence[a])
                mu = np.exp(intercept + attack[a] + defence[h])
                matrix = dc.score_matrix(lam, mu, rho, max_goals=12)
                cell = rng.choice(matrix.size, p=matrix.ravel())
                home.append(teams[h])
                away.append(teams[a])
                hg.append(cell // 13)
                ag.append(cell % 13)

    model = dc.fit(home, away, hg, ag, reg=0.01)

    assert model.home_advantage == pytest.approx(home_adv, abs=0.03)
    assert model.rho == pytest.approx(rho, abs=0.04)
    # Parametry są wyznaczone z dokładnością do stałej przesuniętej do intercept.
    np.testing.assert_allclose(
        model.attack - model.attack.mean(), attack - attack.mean(), atol=0.06
    )
    np.testing.assert_allclose(
        model.defence - model.defence.mean(), defence - defence.mean(), atol=0.06
    )


def test_team_without_matches_gets_prior():
    model = dc.fit(
        ["A", "B", "A", "B"],
        ["B", "A", "B", "A"],
        [1, 0, 2, 1],
        [0, 1, 2, 1],
        extra_teams=["New"],
        priors={"New": (-0.2, 0.2)},
    )

    assert model.params()["New"] == pytest.approx((-0.2, 0.2), abs=1e-4)
    lam, mu = model.expected_goals("New", "A")
    assert lam > 0 and mu > 0
    with pytest.raises(KeyError):
        model.expected_goals("Unknown", "A")


def test_fit_requires_positive_regularisation():
    with pytest.raises(ValueError):
        dc.fit(["A"], ["B"], [1], [0], reg=0)


def test_gradient_matches_finite_differences_also_where_tau_is_not_positive():
    from scipy.optimize import approx_fprime

    rng = np.random.default_rng(1)
    n = 4
    hi = rng.integers(0, n, 40)
    ai = (hi + rng.integers(1, n, 40)) % n
    x = rng.integers(0, 3, 40).astype(float)
    y = rng.integers(0, 3, 40).astype(float)
    x[:5], y[:5] = 0, 0
    w = rng.uniform(0.3, 1, 40)
    masks = ((x == 0) & (y == 0), (x == 0) & (y == 1), (x == 1) & (y == 0), (x == 1) & (y == 1))
    prior = np.zeros(n)
    args = (hi, ai, x, y, w, n, prior, prior, 3.0, 7.0, masks)
    for rho in (-0.25, 0.0, 0.1, 0.29):
        # Duże oczekiwane gole sprawiają, że przy dodatnim ρ τ(0:0) spada poniżej zera.
        theta = np.concatenate([[1.0, 0.3, rho], rng.normal(0, 0.3, 2 * n)])
        numeric = approx_fprime(theta, lambda t: dc._objective(t, *args)[0], 1e-7)
        analytic = dc._objective(theta, *args)[1]
        np.testing.assert_allclose(analytic, numeric, rtol=1e-4, atol=1e-3)


def test_separate_penalty_for_goal_volume():
    rng = np.random.default_rng(3)
    home, away, hg, ag = [], [], [], []
    for _ in range(30):
        for h, a in (("A", "B"), ("B", "A"), ("A", "C"), ("C", "A"), ("B", "C"), ("C", "B")):
            home.append(h)
            away.append(a)
            # A gra mecze z dużą liczbą goli po obu stronach.
            boost = 1.0 if "A" in (h, a) else 0.0
            hg.append(rng.poisson(1.3 + boost))
            ag.append(rng.poisson(1.0 + boost))

    loose = dc.fit(home, away, hg, ag, reg=1.0, reg_total=1.0)
    strict = dc.fit(home, away, hg, ag, reg=1.0, reg_total=1e6)

    a_loose = loose.params()["A"]
    a_strict = strict.params()["A"]
    assert a_loose[0] + a_loose[1] > 0.3
    # Przy ogromnej karze na kierunek liczby goli suma atak + obrona znika.
    assert a_strict[0] + a_strict[1] == pytest.approx(0, abs=1e-3)
