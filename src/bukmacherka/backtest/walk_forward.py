"""Prognozy walk-forward: dla każdego tygodnia model widzi tylko wcześniejsze mecze."""

import datetime as dt
import logging

import numpy as np
import pandas as pd

from bukmacherka.model import dixon_coles

log = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 730
# Średnie parametry (atak, obrona) beniaminków na koniec ich pierwszego
# sezonu w lidze, oszacowane na sezonach 2020/21 – 2025/26 wszystkich lig.
# To jedna stała wyznaczona na tych samych sezonach, na których działa
# backtest; jej wpływ słabnie z każdą kolejką, bo dane szybko przeważają.
PROMOTED_PRIOR = (-0.2, 0.2)
MIN_TRAIN_MATCHES = 150


def week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def promoted_teams(matches: pd.DataFrame) -> dict[tuple[str, str], set[str]]:
    """Beniaminkowie: drużyny, których nie było w lidze w poprzednim sezonie.

    Skład ligi jest znany przed startem sezonu, więc nie ma tu wycieku
    informacji z przyszłości. Dla pierwszego sezonu w danych zbiór jest pusty.
    """
    result: dict[tuple[str, str], set[str]] = {}
    for league, league_matches in matches.groupby("league"):
        teams_by_season = {
            season: set(group.home) | set(group.away)
            for season, group in league_matches.groupby("season")
        }
        seasons = sorted(teams_by_season)
        for previous, current in zip(seasons, seasons[1:], strict=False):
            result[(league, current)] = teams_by_season[current] - teams_by_season[previous]
    return result


def walk_forward(
    matches: pd.DataFrame,
    eval_from: dt.date,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    xi: float = dixon_coles.DEFAULT_XI,
    reg: float = dixon_coles.DEFAULT_REG,
    promoted_prior: tuple[float, float] = PROMOTED_PRIOR,
    max_goals: int = dixon_coles.DEFAULT_MAX_GOALS,
) -> dict[int, np.ndarray]:
    """Zwraca macierz wyników dla każdego meczu od `eval_from`.

    Model jest dopasowywany od nowa co tydzień (od poniedziałku) na meczach
    tej samej ligi z ostatnich `window_days` dni rozegranych przed tym
    poniedziałkiem.
    """
    promoted = promoted_teams(matches)
    predictions: dict[int, np.ndarray] = {}
    for league, league_matches in matches.groupby("league"):
        league_matches = league_matches.sort_values("date")
        to_predict = league_matches[league_matches.date >= eval_from]
        model = None
        skipped = 0
        for start, week in to_predict.groupby(to_predict.date.map(week_start)):
            train = league_matches[
                (league_matches.date < start)
                & (league_matches.date >= start - dt.timedelta(days=window_days))
            ]
            if len(train) < MIN_TRAIN_MATCHES:
                skipped += len(week)
                continue
            priors = {
                team: promoted_prior
                for season in week.season.unique()
                for team in promoted.get((league, season), ())
            }
            model = dixon_coles.fit(
                train.home,
                train.away,
                train.home_goals,
                train.away_goals,
                dixon_coles.time_weights(train.date, start, xi),
                extra_teams=set(week.home) | set(week.away),
                priors=priors,
                reg=reg,
                init=model,
            )
            for match in week.itertuples():
                predictions[match.id] = model.score_matrix(match.home, match.away, max_goals)
        if skipped:
            log.info("%s: pominięto %d meczów (za mało danych do treningu)", league, skipped)
    return predictions
