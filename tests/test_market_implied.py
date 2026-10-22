import numpy as np
import pytest

from bukmacherka.model.dixon_coles import score_matrix
from bukmacherka.model.market_implied import implied_matrix
from bukmacherka.model.markets import Selection, price


def probabilities(matrix):
    return [np.tril(matrix, -1).sum(), np.trace(matrix), np.triu(matrix, 1).sum()]


@pytest.mark.parametrize(("lam", "mu"), [(1.5, 1.1), (2.6, 0.6), (0.8, 1.9), (1.2, 1.2)])
def test_recovers_matrix_from_its_own_prices(lam, mu):
    truth = score_matrix(lam, mu, -0.05)
    over = price(truth, Selection("ou", "over", 2.5)).win

    matrix, error = implied_matrix(probabilities(truth), over)

    assert error < 1e-4
    np.testing.assert_allclose(matrix, truth, atol=1e-4)


def test_works_without_totals():
    truth = score_matrix(1.7, 0.9, -0.05)

    matrix, error = implied_matrix(probabilities(truth))

    assert error < 1e-4
    assert probabilities(matrix) == pytest.approx(probabilities(truth), abs=1e-4)


def test_total_line_with_push_uses_conditional_probability():
    truth = score_matrix(1.4, 1.3, -0.05)
    p = price(truth, Selection("ou", "over", 2.0))

    matrix, error = implied_matrix(probabilities(truth), p.win / (1 - p.push), line=2.0)

    assert error < 1e-4
    np.testing.assert_allclose(matrix, truth, atol=1e-4)
