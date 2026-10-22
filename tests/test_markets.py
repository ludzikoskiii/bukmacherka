import pytest

from bukmacherka.model.dixon_coles import score_matrix
from bukmacherka.model.markets import Price, Selection, catalog, price, settle


@pytest.mark.parametrize(
    ("selection", "score", "expected"),
    [
        # Handicap azjatycki: linia to handicap gospodarza.
        (Selection("ah", "home", -0.25), (1, 1), (0.0, 0.5)),
        (Selection("ah", "home", -0.25), (2, 1), (1.0, 0.0)),
        (Selection("ah", "home", -0.75), (1, 0), (0.5, 0.5)),
        (Selection("ah", "home", -0.75), (2, 0), (1.0, 0.0)),
        (Selection("ah", "home", -0.75), (0, 0), (0.0, 0.0)),
        (Selection("ah", "home", -1.0), (1, 0), (0.0, 1.0)),
        (Selection("ah", "home", 0.25), (1, 1), (0.5, 0.5)),
        (Selection("ah", "away", -0.75), (1, 0), (0.0, 0.5)),
        (Selection("ah", "away", -0.75), (1, 1), (1.0, 0.0)),
        # Gość z linią gospodarza -1,5 gra z +1,5.
        (Selection("ah", "away", -1.5), (1, 0), (1.0, 0.0)),
        (Selection("ah", "away", -1.5), (2, 0), (0.0, 0.0)),
        (Selection("ah", "away", 1.5), (0, 2), (1.0, 0.0)),
        (Selection("ah", "away", 1.5), (3, 1), (0.0, 0.0)),
        # Gole: linie całkowite i ćwiartkowe.
        (Selection("ou", "over", 2.5), (2, 1), (1.0, 0.0)),
        (Selection("ou", "under", 2.5), (2, 1), (0.0, 0.0)),
        (Selection("ou", "over", 2.0), (1, 1), (0.0, 1.0)),
        (Selection("ou", "over", 2.25), (1, 1), (0.0, 0.5)),
        (Selection("ou", "over", 2.75), (2, 1), (0.5, 0.5)),
        (Selection("ou", "under", 2.75), (2, 1), (0.0, 0.5)),
        (Selection("ou", "under", 2.25), (1, 1), (0.5, 0.5)),
        (Selection("home_total", "over", 1.5), (2, 0), (1.0, 0.0)),
        (Selection("away_total", "under", 0.5), (2, 0), (1.0, 0.0)),
        (Selection("draw_no_bet", "home"), (1, 1), (0.0, 1.0)),
        (Selection("draw_no_bet", "away"), (0, 1), (1.0, 0.0)),
        # Handicap europejski: remis po handicapie to osobny wynik.
        (Selection("eh", "draw", -1.0), (2, 1), (1.0, 0.0)),
        (Selection("eh", "home", -1.0), (2, 1), (0.0, 0.0)),
        (Selection("eh", "away", -2.0), (1, 0), (1.0, 0.0)),
        (Selection("eh", "home", 2.0), (0, 1), (1.0, 0.0)),
        (Selection("1x2", "draw"), (2, 2), (1.0, 0.0)),
        (Selection("double_chance", "X2"), (0, 0), (1.0, 0.0)),
        (Selection("btts", "yes"), (1, 1), (1.0, 0.0)),
        (Selection("btts", "no"), (2, 0), (1.0, 0.0)),
        (Selection("cs", "2:1"), (2, 1), (1.0, 0.0)),
        (Selection("total_exact", "6+"), (4, 3), (1.0, 0.0)),
        (Selection("goals_range", "2-3"), (1, 1), (1.0, 0.0)),
        (Selection("goals_range", "2-3"), (2, 2), (0.0, 0.0)),
        (Selection("goals_range", "4+"), (2, 2), (1.0, 0.0)),
        (Selection("odd_even", "odd"), (1, 2), (1.0, 0.0)),
        (Selection("margin", "home_2"), (3, 1), (1.0, 0.0)),
        (Selection("margin", "home_3+"), (4, 1), (1.0, 0.0)),
        (Selection("margin", "away_1"), (0, 1), (1.0, 0.0)),
        (Selection("clean_sheet", "home"), (0, 0), (1.0, 0.0)),
        (Selection("win_to_nil", "away"), (0, 2), (1.0, 0.0)),
        (Selection("win_to_nil", "away"), (1, 2), (0.0, 0.0)),
        (Selection("1x2_ou", "home&over", 2.5), (2, 1), (1.0, 0.0)),
        (Selection("1x2_ou", "home&over", 2.5), (1, 0), (0.0, 0.0)),
        (Selection("dc_ou", "X2&under", 2.5), (1, 1), (1.0, 0.0)),
        (Selection("1x2_btts", "away&yes"), (1, 2), (1.0, 0.0)),
        (Selection("btts_ou", "no&under", 2.5), (2, 0), (1.0, 0.0)),
    ],
)
def test_settle(selection, score, expected):
    assert settle(selection, *score) == expected


@pytest.fixture
def matrix():
    return score_matrix(1.6, 1.1, -0.08)


def test_complementary_markets_sum_to_one(matrix):
    def total(market, names, line=None):
        return sum(price(matrix, Selection(market, n, line)).win for n in names)

    assert total("1x2", ("home", "draw", "away")) == pytest.approx(1)
    assert total("btts", ("yes", "no")) == pytest.approx(1)
    assert total("odd_even", ("odd", "even")) == pytest.approx(1)
    assert total("total_exact", ("0", "1", "2", "3", "4", "5", "6+")) == pytest.approx(1)
    assert total("margin", ("home_3+", "home_2", "home_1", "draw")) + total(
        "margin", ("away_1", "away_2", "away_3+")
    ) == pytest.approx(1)
    for line in (-1.0, 1.0):
        assert total("eh", ("home", "draw", "away"), line) == pytest.approx(1)


@pytest.mark.parametrize("line", [-2.5, -1.75, -1.0, -0.25, 0.0, 0.5, 1.25, 2.0])
def test_asian_handicap_sides_are_mirrored(matrix, line):
    home = price(matrix, Selection("ah", "home", line))
    away = price(matrix, Selection("ah", "away", line))

    assert home.push == pytest.approx(away.push)
    assert home.win + home.push + away.win == pytest.approx(1)


@pytest.mark.parametrize("line", [1.5, 2.0, 2.25, 2.75, 3.0])
def test_totals_sides_are_mirrored(matrix, line):
    over = price(matrix, Selection("ou", "over", line))
    under = price(matrix, Selection("ou", "under", line))

    assert over.win + over.push + under.win == pytest.approx(1)


def test_label_shows_line_from_the_bettors_side():
    assert Selection("ah", "home", -0.75).label() == "home -0.75"
    assert Selection("ah", "away", -0.75).label() == "away +0.75"
    assert Selection("ah", "away", 0.0).label() == "away 0"
    assert Selection("eh", "away", -1.0).label() == "away +1"
    assert Selection("eh", "home", -1.0).label() == "home -1"
    assert Selection("eh", "draw", -1.0).label() == "draw (home -1)"
    assert Selection("ou", "over", 2.5).label() == "over +2.5"
    assert Selection("1x2", "draw").label() == "draw"


def test_fair_odds():
    selection = Selection("ah", "home", 0.0)
    assert Price(selection, win=0.5, push=0.0).fair_odds == pytest.approx(2.0)
    # Z prawdopodobieństwem zwrotu 0,2 kurs sprawiedliwy to (1 - 0,2) / 0,4.
    assert Price(selection, win=0.4, push=0.2).fair_odds == pytest.approx(2.0)
    assert Price(selection, win=0.4, push=0.2).expected_return(2.0) == pytest.approx(1.0)


def test_catalog_has_no_duplicates_and_prices_every_selection(matrix):
    selections = catalog()
    assert len(selections) == len(set(selections))
    for selection in selections:
        p = price(matrix, selection)
        assert 0 <= p.win <= 1
        assert 0 <= p.push <= 1
        assert p.win + p.push <= 1 + 1e-9
