"""Prognozy z kursów ostrego rynku zamiast z modelu statystycznego.

Dla każdego meczu bierzemy kursy otwarcia Pinnacle (a gdy ich brak, Betfair
Exchange), usuwamy marżę i dopasowujemy do nich macierz wyników. Te kursy
były znane w chwili, gdy obstawiamy po kursach otwarcia, więc nie ma tu
wycieku informacji z przyszłości.
"""

import numpy as np
import pandas as pd

from bukmacherka.backtest.data import OddsIndex
from bukmacherka.model.market_implied import implied_matrix
from bukmacherka.value.ev import devig

SHARP_BOOKMAKERS = ("pinnacle", "betfair_exchange")


def market_predictions(
    matches: pd.DataFrame, odds: OddsIndex, *, closing: bool = False
) -> dict[int, np.ndarray]:
    predictions = {}
    for match_id in matches.id:
        for bookmaker in SHARP_BOOKMAKERS:
            result = odds.get((match_id, bookmaker, "1x2", closing))
            if result is None:
                continue
            p_1x2 = devig([result.prices[s] for s in ("home", "draw", "away")])
            totals = odds.get((match_id, bookmaker, "ou", closing))
            p_over = devig([totals.prices["over"], totals.prices["under"]])[0] if totals else None
            line = totals.line if totals else 2.5
            predictions[match_id], _ = implied_matrix(p_1x2, p_over, line)
            break
    return predictions
