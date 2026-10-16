# Bukmacherka — plan aplikacji (wersja robocza)

Prywatna aplikacja webowa, która zbiera dane piłkarskie z internetu, liczy
prawdopodobieństwa wyników modelem statystycznym, porównuje je z kursami
bukmacherów i na tej podstawie układa kupony z zakładów o dodatniej wartości
oczekiwanej (value bety).

## Ustalenia

| Obszar     | Decyzja                                        |
|------------|------------------------------------------------|
| Sport      | Tylko piłka nożna (inne sporty ewentualnie później) |
| Forma      | Aplikacja webowa                               |
| Logika     | Model statystyczny + value bety                |
| Odbiorcy   | Tylko ja (bez kont, bez płatności)             |

## Założenia, o których trzeba pamiętać

- **Podatek 12% od stawki.** U legalnych polskich bukmacherów od stawki
  potrąca się 12% podatku, więc efektywny kurs to `kurs × 0,88`. Przez to
  zakład musi mieć ok. 14% przewagi nad kursem, żeby w ogóle wyjść na zero.
  Model musi liczyć wartość oczekiwaną (EV) na kursie efektywnym, a nie
  nominalnym. Wygrane powyżej 2280 zł są dodatkowo opodatkowane stawką 10%.
- **Marża w kuponach AKO się mnoży.** Każde zdarzenie dokłada marżę
  bukmachera, więc długie kupony prawie zawsze mają ujemne EV. Generator
  powinien preferować single i krótkie AKO (2–3 zdarzenia) złożone wyłącznie
  z value betów.
- **Najpierw backtest, potem interfejs.** Zanim powstanie UI, model musi
  pokazać na danych historycznych, że wygrywa z kursami zamknięcia. Jeśli nie
  wygrywa, poprawiamy model, a nie wygląd aplikacji.

## Źródła danych

| Co                              | Źródło                         | Koszt / limit                     | Uwagi |
|---------------------------------|--------------------------------|-----------------------------------|-------|
| Historyczne wyniki + kursy      | football-data.co.uk (CSV)      | darmowe                           | Zawiera kursy zamknięcia (m.in. Pinnacle). Idealne do treningu i backtestu. |
| Terminarz, wyniki, kontuzje     | API-Football (api-sports.io)   | darmowy plan: 100 zapytań/dzień    | Ma też składy i kursy. Free plan ograniczony do części sezonów. |
| Terminarz (alternatywa)         | football-data.org              | darmowy plan, kilkanaście lig     | Prosty, stabilny. |
| Aktualne kursy                  | The Odds API                   | darmowo 500 kredytów/mies.        | Koszt zapytania = liczba rynków × liczba regionów. Polscy bukmacherzy raczej niedostępni. |
| xG (expected goals)             | Understat                      | darmowe (scraping)                | Top 5 lig + liga rosyjska. Na FBref od stycznia 2026 nie ma już zaawansowanych statystyk Opta. |
| Kursy mojego bukmachera         | Ręczne wpisanie w aplikacji    | —                                 | Scrapowanie STS/Fortuny/Superbetu łamie ich regulaminy, więc na start wpisujemy kursy ręcznie. |

## Architektura

```
[Źródła danych] → [Zbieracze (jobs)] → [Baza danych] → [Model] → [Value bety] → [Generator kuponów] → [Web UI]
                                                                                        ↓
                                                                        [Rozliczanie + statystyki]
```

Proponowany stack (do potwierdzenia):

- **Python 3.12**, zarządzanie zależnościami: `uv`
- **Baza:** SQLite (wystarczy dla jednej osoby), ORM: SQLAlchemy
- **Zbieranie danych:** `httpx`, `pandas`, harmonogram: APScheduler albo cron
- **Model:** `numpy`, `scipy`, `statsmodels`; później `scikit-learn` lub `lightgbm`
- **UI:** Streamlit (najszybsza droga do panelu dla jednej osoby). Gdyby
  aplikacja miała urosnąć, można przejść na FastAPI + React.
- **Jakość:** `ruff`, `pytest`

### Moduły

1. **`ingest/`** — pobieranie danych z każdego źródła, normalizacja nazw
   drużyn (różne źródła różnie je zapisują, więc potrzebna jest tabela
   aliasów), zapis do bazy.
2. **`model/`**
   - Model Dixona-Colesa (Poisson z korektą niskich wyników i ważeniem
     czasowym): siła ataku i obrony każdej drużyny, przewaga gospodarza.
   - Z macierzy prawdopodobieństw wyników liczymy rynki 1X2, Over/Under 2.5,
     BTTS i podwójną szansę.
   - Elo jako punkt odniesienia i dodatkowa cecha.
   - Później: cechy z xG, kontuzji i zmęczenia (terminarz).
3. **`backtest/`** — symulacja obstawiania na historycznych kursach.
   Metryki: log loss i Brier score modelu na tle kursów bez marży, ROI,
   yield, maksymalne obsunięcie kapitału i CLV (czy łapiemy lepsze kursy
   niż kurs zamknięcia).
4. **`value/`** — EV = `p_model × kurs × 0,88 − 1`; próg np. EV > 5%.
   Stawka: ułamkowe kryterium Kelly'ego (np. ¼ Kelly) z limitem % bankrolla.
5. **`coupons/`** — generator kuponów:
   - profile ryzyka: *bezpieczny* (single, niskie kursy),
     *zbalansowany* (AKO 2–3), *ryzykowny* (wyższe kursy);
   - ograniczenia: maksymalnie jedno zdarzenie z danego meczu, zakres kursów,
     wybrane ligi i rynki;
   - dla każdego kuponu: łączne prawdopodobieństwo, kurs, EV i sugerowana
     stawka.
6. **`tracking/`** — zapis każdego kuponu, automatyczne rozliczanie po
   wynikach, historia bankrolla.
7. **`app/`** — interfejs webowy.

### Ekrany aplikacji

- **Dziś / Najbliższe mecze:** lista meczów z prawdopodobieństwami modelu
  i kursami.
- **Value bety:** zdarzenia z EV powyżej progu, posortowane.
- **Generator kuponu:** wybór profilu i ograniczeń, wygenerowane kupony,
  możliwość ręcznego wpisania kursu z mojego bukmachera.
- **Historia i statystyki:** ROI, yield, skuteczność, wykres bankrolla, CLV.
- **Ustawienia:** bankroll, ligi, próg EV, ułamek Kelly'ego, limity stawek.

## Model danych (szkic)

- `teams` (id, nazwa, liga) + `team_aliases` (alias, źródło, team_id)
- `matches` (id, liga, sezon, data, gospodarz, gość, gole, xG, status)
- `odds` (match_id, bukmacher, rynek, wybór, kurs, czas pobrania, czy zamknięcie)
- `predictions` (match_id, wersja modelu, rynek, wybór, prawdopodobieństwo)
- `coupons` (id, data, profil, stawka, kurs łączny, EV, status, wynik)
- `coupon_legs` (coupon_id, match_id, rynek, wybór, kurs, rozliczenie)
- `bankroll_log` (data, saldo, zmiana, powód)

## Etapy

| Etap | Zakres | Kryterium ukończenia |
|------|--------|----------------------|
| 0 | Szkielet repo: `uv`, `ruff`, `pytest`, struktura katalogów | Testy i lint przechodzą |
| 1 | Import historycznych CSV z football-data.co.uk do SQLite | Kilka sezonów wybranych lig w bazie |
| 2 | Model Dixona-Colesa + backtest | Raport: kalibracja, ROI na kursach zamknięcia (z podatkiem 12%) |
| 3 | Bieżące dane: terminarz + kursy (API-Football / The Odds API), codzienny job | Jutrzejsze mecze z kursami w bazie |
| 4 | Value bety + generator kuponów + rozliczanie | Kupony generują się i rozliczają automatycznie |
| 5 | Interfejs webowy (Streamlit) | Wszystkie ekrany działają lokalnie |
| 6 | Ulepszenia: xG, kontuzje, więcej rynków, ewentualnie opis kuponu generowany przez AI | Lepsze wyniki w backteście niż wersja z etapu 2 |

Etap 2 jest punktem decyzyjnym: jeśli backtest nie pokazuje przewagi nad
kursami, wracamy do modelu i danych, zanim zaczniemy etapy 3–5.

## Otwarte pytania

1. Które ligi na start? (propozycja: Premier League, La Liga, Serie A,
   Bundesliga, Ligue 1 i Ekstraklasa)
2. U którego bukmachera grasz? To decyduje, skąd brać kursy i czy dotyczy
   Cię podatek 12%.
3. Budżet na API: zostajemy przy darmowych planach czy dopuszczamy ok. 20 USD
   miesięcznie (np. API-Football Pro)?
4. Rynki na start: tylko 1X2, czy od razu też Over/Under i BTTS?
5. Uruchamianie: lokalnie na komputerze czy na małym serwerze (VPS), żeby
   kursy pobierały się same?
6. UI: Streamlit wystarczy, czy od początku chcesz FastAPI + React?

## Odpowiedzialna gra

Aplikacja ma wbudowane limity: maksymalna stawka jako % bankrolla, dzienny
limit kuponów i widoczny bilans. Celem jest mierzalne podejmowanie decyzji,
a nie gwarancja wygranej. Model może się mylić, a bukmacherzy mają przewagę
w postaci marży i podatku.
