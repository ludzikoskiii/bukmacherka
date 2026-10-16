import pytest

from bukmacherka.model.markets import Price, Selection
from bukmacherka.value import ev

HOME = Selection("1x2", "home")


def binary(p: float) -> Price:
    return Price(HOME, win=p, push=0.0)


def test_single_ev_includes_stake_tax():
    # 0,88 × 0,5 × 2,5 − 1 = 0,1
    assert ev.single_ev(binary(0.5), 2.5, tax=0.12) == pytest.approx(0.10)
    assert ev.single_ev(binary(0.5), 2.5, tax=0.0) == pytest.approx(0.25)


def test_accumulator_pays_tax_once():
    legs = [(binary(0.5), 2.1)] * 3  # każde zdarzenie: przewaga 5%

    assert ev.accumulator_ev(legs, tax=0.12) == pytest.approx(0.88 * 1.05**3 - 1)
    assert ev.single_ev(binary(0.5), 2.1, tax=0.12) == pytest.approx(0.88 * 1.05 - 1)


def test_min_odds_single_matches_plan_example():
    price = binary(0.55)

    assert ev.min_odds_single(price, tax=0.12, min_ev=0.05) == pytest.approx(2.1694, abs=1e-4)
    assert price.fair_odds == pytest.approx(1.818, abs=1e-3)


@pytest.mark.parametrize("price", [binary(0.55), Price(HOME, win=0.4, push=0.2)])
def test_min_odds_are_break_even_points(price):
    single = ev.min_odds_single(price, tax=0.12, min_ev=0.05)
    leg = ev.min_odds_leg(price, min_edge=0.03)

    assert ev.single_ev(price, single, tax=0.12) == pytest.approx(0.05)
    assert ev.edge(price, leg) == pytest.approx(0.03)


def test_min_odds_for_impossible_outcome():
    assert ev.min_odds_single(binary(0.0), 0.12, 0.05) == float("inf")
    assert ev.min_odds_leg(binary(0.0), 0.05) == float("inf")


def test_devig():
    assert ev.devig([2.0, 2.0]) == pytest.approx([0.5, 0.5])
    assert ev.devig([1.9, 1.9]) == pytest.approx([0.5, 0.5])
    assert sum(ev.devig([2.1, 3.4, 3.6])) == pytest.approx(1)
