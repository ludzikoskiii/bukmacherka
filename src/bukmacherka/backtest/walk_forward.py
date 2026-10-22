"""Prognozy walk-forward: model widzi tylko mecze rozegrane przed zebraniem kursów.

football-data.co.uk zbiera kursy przed zamknięciem w piątek po południu dla
kolejki weekendowej (piątek - poniedziałek) i we wtorek po południu dla
kolejki w środku tygodnia (wtorek - czwartek). Model dla danej kolejki jest
dopasowywany na meczach rozegranych przed dniem zebrania kursów, więc wie
dokładnie tyle, ile wiedział rynek w chwili, gdy stawiamy zakład.
"""

import datetime as dt
import logging

import numpy as np
import pandas as pd

from bukmacherka.model import dixon_coles

log = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 730
MIN_TRAIN_MATCHES = 150
# Kara przy szacowaniu parametrów beniaminków na koniec sezonu.
PROMOTED_PRIOR_REG = 0.5


def odds_batch(day: dt.date) -> dt.date:
    """Dzień zebrania kursów przed zamknięciem dla meczu rozgrywanego `day`.

    Piątek - poniedziałek należy do kolejki weekendowej (kursy z piątku),
    wtorek - czwartek do kolejki w środku tygodnia (kursy z wtorku).
    """
    weekday = day.weekday()
    if weekday == 0:
        return day - dt.timedelta(days=3)
    if weekday <= 3:
        return day - dt.timedelta(days=weekday - 1)
    return day - dt.timedelta(days=weekday - 4)


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


def promoted_params(matches: pd.DataFrame) -> dict[str, list[tuple[float, float]]]:
    """Parametry (atak, obrona) beniaminków na koniec ich pierwszego sezonu.

    Klucz to sezon. Model jest dopasowywany na całym sezonie, więc wyniki
    wolno używać dopiero dla późniejszych sezonów.
    """
    promoted = promoted_teams(matches)
    result: dict[str, list[tuple[float, float]]] = {}
    for (league, season), teams in promoted.items():
        if not teams:
            continue
        games = matches[(matches.league == league) & (matches.season == season)]
        model = dixon_coles.fit(
            games.home, games.away, games.home_goals, games.away_goals, reg=PROMOTED_PRIOR_REG
        )
        params = model.params()
        result.setdefault(season, []).extend(params[team] for team in teams)
    return result


def promoted_prior(
    history: dict[str, list[tuple[float, float]]], season: str
) -> tuple[float, float]:
    """Średnie parametry beniaminków z sezonów zakończonych przed `season`.

    Bez wcześniejszych sezonów zwraca (0, 0), czyli średnią drużynę ligi.
    """
    past = [p for s, params in history.items() if s < season for p in params]
    if not past:
        return 0.0, 0.0
    attack, defence = np.mean(past, axis=0)
    return float(attack), float(defence)


def walk_forward(
    matches: pd.DataFrame,
    eval_from: dt.date,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    xi: float = dixon_coles.DEFAULT_XI,
    reg: float = dixon_coles.DEFAULT_REG,
    reg_total: float = dixon_coles.DEFAULT_REG_TOTAL,
    max_goals: int = dixon_coles.DEFAULT_MAX_GOALS,
) -> dict[int, np.ndarray]:
    """Zwraca macierz wyników dla każdego meczu od `eval_from`.

    Model jest dopasowywany od nowa dla każdej kolejki (patrz `odds_batch`)
    na meczach tej samej ligi z ostatnich `window_days` dni rozegranych
    przed dniem zebrania kursów.
    """
    promoted = promoted_teams(matches)
    history = promoted_params(matches)
    predictions: dict[int, np.ndarray] = {}
    for league, league_matches in matches.groupby("league"):
        league_matches = league_matches.sort_values("date")
        to_predict = league_matches[league_matches.date >= eval_from]
        model = None
        skipped = 0
        for batch, games in to_predict.groupby(to_predict.date.map(odds_batch)):
            train = league_matches[
                (league_matches.date < batch)
                & (league_matches.date >= batch - dt.timedelta(days=window_days))
            ]
            if len(train) < MIN_TRAIN_MATCHES:
                skipped += len(games)
                continue
            priors = {
                team: promoted_prior(history, season)
                for season in games.season.unique()
                for team in promoted.get((league, season), ())
            }
            model = dixon_coles.fit(
                train.home,
                train.away,
                train.home_goals,
                train.away_goals,
                dixon_coles.time_weights(train.date, batch, xi),
                extra_teams=set(games.home) | set(games.away),
                priors=priors,
                reg=reg,
                reg_total=reg_total,
                init=model,
            )
            for match in games.itertuples():
                predictions[match.id] = model.score_matrix(match.home, match.away, max_goals)
        if skipped:
            log.info("%s: pominięto %d meczów (za mało danych do treningu)", league, skipped)
    return predictions
