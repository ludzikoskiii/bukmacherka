# Bukmacherka

Prywatna aplikacja webowa do typowania zakładów piłkarskich. Zbiera dane
z darmowych źródeł, liczy prawdopodobieństwa wyników modelem statystycznym
i układa kupony z value betów, z uwzględnieniem polskiego podatku od stawki.

Pełny plan: [`docs/PLAN.md`](docs/PLAN.md).

## Uruchomienie lokalne

Wymagany [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # uzupełnij klucze API
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Dane

```bash
uv run bukmacherka import-history   # pobierz historię do data/bukmacherka.db
uv run bukmacherka report           # pokaż, co jest w bazie
```

## Backtest

```bash
uv run bukmacherka backtest --from-season 2022                 # model statystyczny
uv run bukmacherka backtest --from-season 2022 --fair market   # wycena z kursów Pinnacle/Betfair
uv run bukmacherka backtest --leagues POL --closing --bookmaker market_avg
```

Opcje: `--bookmaker` (bet365, market_avg, market_max, ...), `--closing`,
`--min-ev`, `--min-edge`, `--tax`. Raport trafia na ekran, a szczegóły
zakładów do `data/backtest/`.

Pobrane pliki CSV trafiają do `data/raw/`. Zakończone sezony pobierają się
tylko raz, a bieżący przy każdym uruchomieniu. Opcje: `--leagues E0 POL`,
`--first-season 2021`, `--refresh`.

## Struktura

```
src/bukmacherka/
  config.py   ustawienia (zmienne BUKMACHERKA_* lub plik .env)
  ingest/     pobieranie danych ze źródeł
  model/      model wyników i rynki
  backtest/   testy na danych historycznych
  value/      EV, kurs minimalny, stawki
  coupons/    generator kuponów
  tracking/   rozliczanie i bankroll
  worker/     harmonogram zadań na serwerze
  app/        panel Streamlit
tests/
docs/PLAN.md
```
