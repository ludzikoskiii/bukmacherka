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
