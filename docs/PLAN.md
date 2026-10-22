# Bukmacherka — plan aplikacji

Prywatna aplikacja webowa, która zbiera dane piłkarskie z internetu, liczy
prawdopodobieństwa wyników modelem statystycznym, porównuje je z kursami
i na tej podstawie układa kupony z zakładów o dodatniej wartości
oczekiwanej (value bety). Na razie działa lokalnie na komputerze, a kod
jest pisany tak, żeby później dało się go łatwo przenieść na serwer.

## Ustalenia

| Obszar        | Decyzja                                                       |
|---------------|---------------------------------------------------------------|
| Sport         | Piłka nożna                                                   |
| Ligi          | Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Ekstraklasa |
| Bukmacherzy   | Superbet i STS                                                |
| Rynki         | Jak najwięcej (szczegóły niżej)                               |
| Logika        | Model statystyczny + value bety                               |
| Forma         | Aplikacja webowa w Streamlit                                  |
| Uruchamianie  | Na razie lokalnie na komputerze (Linux), serwer później       |
| Budżet na API | Tylko darmowe plany                                           |
| Odbiorcy      | Tylko ja (bez kont i płatności)                               |

## Podatek i matematyka kuponu

Superbet i STS potrącają **12% podatku od stawki kuponu**, więc wypłata to
`stawka × 0,88 × kurs`. Podatek płaci się **raz na kupon**, niezależnie od
liczby zdarzeń. Z tego wynikają reguły generatora:

- **Single:** EV = `p × kurs × 0,88 − 1`. Żeby wyjść na zero, potrzeba
  `p × kurs ≥ 1,136`, czyli ok. 14% przewagi nad kursem. Takie okazje będą
  rzadkie.
- **AKO z value betów:** EV = `(p₁ × kurs₁) × (p₂ × kurs₂) × … × 0,88 − 1`.
  Przewagi zdarzeń się mnożą, a podatek jest płacony tylko raz. Przykład:
  trzy zdarzenia, każde z 5% przewagi, dają `1,05³ × 0,88 − 1 ≈ +1,9%`,
  podczas gdy każde z nich jako single ma EV ≈ −7,6%.
- **AKO z przypadkowych zdarzeń:** marża bukmachera mnoży się tak samo jak
  przewaga, więc taki kupon ma mocno ujemne EV. Na kupon trafiają tylko
  zdarzenia, w których model widzi przewagę.
- **Ryzyko długich kuponów:** każde zdarzenie dokłada błąd modelu i obniża
  szansę trafienia. Generator ma więc limit liczby zdarzeń (np. 2–5),
  minimalne łączne prawdopodobieństwo i małe stawki (ułamkowy Kelly).
- **Wygrane powyżej 2280 zł** podlegają dodatkowo 10% podatku. Stawka
  podatku, próg i ewentualne bonusy bukmachera (np. promocje „bez
  podatku”, bonus za AKO) będą w ustawieniach.

### Kurs minimalny

Darmowe API nie dają kursów Superbetu i STS, a ich pobieranie ze stron
łamie regulaminy tych serwisów. Dlatego aplikacja przy każdym typie pokazuje
**kurs minimalny**, czyli najniższy kurs, przy którym zakład ma sens:

- jako single: `kurs_min = (1 + próg_EV) / (p × 0,88)`
- jako zdarzenie w AKO: `kurs_min = (1 + próg_przewagi) / p`

Przykład: model daje 55% na wygraną gospodarza. Kurs sprawiedliwy to 1,82,
a kurs minimalny na single przy progu EV 5% wynosi 2,17. Sprawdzasz kurs w
Superbecie i STS, wybierasz wyższy i wpisujesz go do aplikacji, a aplikacja
przelicza EV i składa kupon. Do backtestu i wstępnej selekcji służą kursy
z API i z football-data.co.uk (Pinnacle, Betfair Exchange, średnia
rynkowa).

## Rynki

| Grupa | Rynki | Ligi | Źródło prawdopodobieństw |
|-------|-------|------|--------------------------|
| Gole w meczu | 1X2, podwójna szansa, DNB, Over/Under 0,5–5,5, BTTS, dokładny wynik, przedziały goli (np. 2–3), parzyste/nieparzyste, margines zwycięstwa | wszystkie | macierz wyników z modelu |
| Gole drużyny | gole gospodarza/gościa O/U, czyste konto, wygrana do zera | wszystkie | macierz wyników |
| Handicapy | handicap europejski, azjatycki (±0,5 … ±2,5, ćwiartki) | wszystkie | macierz wyników |
| Kombinacje | 1X2 + O/U, 1X2 + BTTS, BTTS + O/U, kreator zakładów z jednego meczu | wszystkie | macierz wyników (poprawnie liczy zależności w obrębie meczu) |
| Połowy | 1X2 do przerwy, do przerwy/koniec meczu, gole w połowach | top 5 (dla Ekstraklasy brak wyników do przerwy) | osobny model wyników do przerwy |
| Statystyki | rzuty rożne, kartki | top 5 | osobne modele (Poisson lub ujemny dwumianowy) |

Rynki na strzelców i zawodników są poza zakresem, bo wymagają danych o
składach i minutach gry, których darmowe źródła nie dają w wystarczającej
jakości.

## Źródła danych (darmowe)

| Co | Źródło | Limit | Uwagi |
|----|--------|-------|-------|
| Historia: wyniki, kursy zamknięcia, rożne, kartki, wyniki do przerwy, xG | football-data.co.uk (CSV) | brak | Zaimportowane w etapie 1, szczegóły niżej. |
| Nadchodzące mecze + kursy (top 5) | football-data.co.uk `fixtures.csv` | brak | Aktualizowane przed kolejkami. |
| Terminarz i wyniki (top 5) | football-data.org | darmowy plan, 10 zapytań/min | Bez Ekstraklasy. |
| Terminarz, wyniki, kontuzje, kursy (Ekstraklasa i reszta) | API-Football | 100 zapytań/dzień | Do sprawdzenia z kluczem: czy darmowy plan obejmuje bieżący sezon. |
| Kursy referencyjne (Pinnacle, rynek EU) | The Odds API | 500 kredytów/mies. | Koszt zapytania = rynki × regiony. Do sprawdzenia: czy jest Ekstraklasa. |
| xG dla starszych sezonów | Understat | brak (scraping) | Tylko top 5. Od 2026/27 xG jest już w plikach football-data.co.uk. |
| Kursy Superbetu i STS | ręcznie w aplikacji | — | Patrz „Kurs minimalny”. |

### Co jest w danych historycznych (sprawdzone w etapie 1)

Zaimportowane sezony 2019/20 – 2026/27: 14 910 meczów i ok. 770 tys.
kursów. Pełny raport pokazuje `uv run bukmacherka report`.

| | Top 5 lig | Ekstraklasa |
|---|---|---|
| Wynik | tak | tak |
| Wynik do przerwy, strzały, rożne, kartki, faule | tak | nie |
| xG | od 2026/27 | nie |
| Kursy przed zamknięciem (piątek / wtorek) | 1X2, O/U 2,5, AH | nie |
| Kursy zamknięcia | 1X2, O/U 2,5, AH | tylko 1X2 |
| Pinnacle | do ok. połowy 2025/26 | do ok. 1/3 2025/26 |
| Betfair Exchange | od 2024/25 | od 2024/25 |
| Średnia i maksimum rynku | wszystkie sezony | wszystkie sezony |
| bet365 | wszystkie sezony | od 2025/26 |

Wnioski:

- **Punkt odniesienia dla kursów:** Pinnacle do 2025/26, a od sezonu
  2026/27 Betfair Exchange (najniższa marża, ok. 0,6%). Średnia rynkowa
  jest dostępna zawsze.
- **Ekstraklasa:** backtest i CLV tylko na rynku 1X2. Pozostałe rynki dla
  Ekstraklasy da się policzyć z modelu goli, ale nie zweryfikujemy ich na
  historycznych kursach, dopóki worker nie uzbiera własnych.
- **Jakość danych:** w kolumnach z maksimum rynku zdarzają się błędne
  kursy (suma odwrotności kursów poniżej 0,9). Przed backtestem trzeba je
  odfiltrować.
- **Nazwy drużyn:** w plikach była jedna zmiana nazwy (Górnik Zabrze),
  poprawiona słownikiem `TEAM_RENAMES`.

### Budżet zapytań (szkic)

- **The Odds API:** 6 lig × 2 rynki (h2h, totals) × 1 region = 12 kredytów
  na odświeżenie. To ok. 40 odświeżeń miesięcznie, czyli jedno dziennie
  i kilka dodatkowych przed weekendem.
- **API-Football:** codziennie terminarz i wyniki Ekstraklasy, kontuzje
  i kursy dla meczów z najbliższych 3 dni. Plan zakłada 30–60 zapytań
  dziennie, z zapasem.
- **football-data.org:** terminarz i wyniki top 5, kilka zapytań dziennie.
- **football-data.co.uk:** raz w tygodniu nowe wyniki z kursami zamknięcia
  (do CLV i ponownego trenowania modelu).

## Architektura

```
[Źródła danych] → [Worker: zadania wg harmonogramu] → [SQLite] → [Model] → [Typy + kurs minimalny]
                                                                               ↓
                                         [Streamlit] ← [Generator kuponów] ← [Kursy wpisane ręcznie]
                                                                               ↓
                                                               [Rozliczanie + statystyki]
```

### Stack

- **Python 3.12+**, zależności: `uv`
- **Baza:** SQLite + SQLAlchemy (jeden użytkownik, jeden plik, łatwy backup)
- **Dane:** `httpx`, `pandas`
- **Model:** `numpy`, `scipy`; później `scikit-learn` lub `lightgbm`
- **Harmonogram:** APScheduler w osobnym procesie (worker)
- **UI:** Streamlit
- **Jakość:** `ruff`, `pytest`, GitHub Actions
- **Uruchamianie:** lokalnie przez `uv` (panel i worker). Docker Compose
  dopiero przy przenosinach na serwer.

### Moduły (`src/bukmacherka/`)

1. **`ingest/`** — klienci źródeł danych, normalizacja nazw drużyn (tabela
   aliasów), zapis do bazy.
2. **`model/`** — model Dixona-Colesa (siła ataku i obrony, przewaga
   gospodarza, ważenie czasowe) → macierz wyników → wszystkie rynki golowe.
   Osobne modele dla połów, rzutów rożnych i kartek. Elo jako punkt
   odniesienia.
3. **`backtest/`** — symulacja na historycznych kursach zamknięcia:
   log loss i Brier score na tle kursów bez marży, ROI, yield, obsunięcie
   kapitału, CLV. Single i AKO, z podatkiem 12%.
4. **`value/`** — EV, kurs minimalny, przewaga, stawka (¼ Kelly z limitem).
5. **`coupons/`** — generator: profile ryzyka (*bezpieczny*: single i AKO
   2, *zbalansowany*: AKO 2–3, *ryzykowny*: AKO 4–5), maksymalnie jedno
   zdarzenie z meczu (poza kreatorem zakładów), filtry lig, rynków
   i kursów.
6. **`tracking/`** — zapis kuponów, automatyczne rozliczanie, historia
   bankrolla.
7. **`app/`** — panel Streamlit.
8. **`worker/`** — harmonogram zadań. Po uruchomieniu nadrabia zadania
   pominięte, kiedy komputer był wyłączony.

### Ekrany

- **Najbliższe mecze:** prawdopodobieństwa i kursy sprawiedliwe na
  wszystkich rynkach.
- **Typy:** zdarzenia z przewagą, z kursem minimalnym dla singla i dla AKO.
- **Generator kuponu:** profil, filtry, wpisanie kursów z Superbetu i STS,
  gotowe kupony z EV i stawką.
- **Historia i statystyki:** ROI, yield, skuteczność, wykres bankrolla,
  CLV, osobno dla rynków i lig.
- **Ustawienia:** bankroll, próg EV, ułamek Kelly'ego, limity, podatek,
  bonusy bukmachera.

## Model danych (szkic)

- `teams`, `team_aliases`
- `matches` (liga, sezon, data, drużyny, wynik, wynik do przerwy, xG,
  rożne, kartki, status)
- `odds` (mecz, źródło/bukmacher, rynek, wybór, linia, kurs, czas, czy
  zamknięcie)
- `predictions` (mecz, wersja modelu, rynek, wybór, linia,
  prawdopodobieństwo)
- `coupons`, `coupon_legs` (kurs wpisany, bukmacher, rozliczenie)
- `bankroll_log`
- `job_runs` (które zadanie, kiedy, ile zapytań zużyło, czy się udało)

## Etapy

| Etap | Zakres | Kryterium ukończenia |
|------|--------|----------------------|
| 0 ✅ | Szkielet: `uv`, `ruff`, `pytest`, CI, konfiguracja | Lint i testy przechodzą lokalnie i w CI |
| 1 ✅ | Import historii z football-data.co.uk | 5+ sezonów każdej ligi w bazie, raport dostępnych kolumn |
| 2 ✅ | Dixon-Coles, rynki z macierzy wyników, backtest single i AKO | Raport: kalibracja, ROI i CLV na kursach zamknięcia z podatkiem (wyniki niżej) |
| 3 | Bieżące dane: klienci API, aliasy nazw drużyn między źródłami, worker z harmonogramem | Mecze z najbliższych 3 dni z kursami odświeżają się same |
| 4 | Uruchamianie lokalne: panel i worker jednym poleceniem, autostart workera jako usługa użytkownika systemd, nadrabianie zaległych zadań, backup bazy | Po włączeniu komputera dane same się aktualizują |
| 5 | Value, kurs minimalny, generator kuponów, rozliczanie | Kupony generują się i rozliczają automatycznie |
| 6 | Panel Streamlit | Wszystkie ekrany działają lokalnie |
| 7 | Połowy, rożne, kartki, xG, kontuzje | Nowe rynki przechodzą backtest |

**Etap 2 jest punktem decyzyjnym:** jeśli model nie pokazuje przewagi nad
kursami zamknięcia, wracamy do modelu i danych.

**Worker ruszy przed panelem:** football-data.co.uk daje za darmo kursy
tylko na trzy rynki (1X2, O/U 2,5, handicap azjatycki) i tylko z dwóch
momentów: przed kolejką (piątek lub wtorek) i na zamknięciu. Kursów na
pozostałych rynkach ani z innych momentów nie da się później pobrać wstecz,
więc im wcześniej worker zacznie je zbierać, tym więcej danych do oceny. Przy pracy lokalnej kursy zbierają się tylko wtedy, gdy
komputer jest włączony. Luki w kursach zamknięcia uzupełni cotygodniowy
import z football-data.co.uk.

## Wyniki etapu 2

Backtest walk-forward na sezonach 2022/23 – 2026/27 (top 5 lig, 7379
meczów; Ekstraklasa tylko na kursach zamknięcia). Parametry modelu dobrano
wcześniej, na sezonach 2020/21 – 2021/22, więc to uczciwy test poza próbą.
Polecenie: `uv run bukmacherka backtest --from-season 2022`.

### Model statystyczny (Dixon-Coles): brak przewagi

| | Model | Rynek przed zamkn. | Rynek na zamkn. |
|---|---|---|---|
| Log loss 1X2 (mniej = lepiej) | 0,988 | 0,968 | 0,966 |
| Log loss O/U 2,5 | 0,676 | 0,669 | 0,666 |

- Model jest wyraźnie gorszy od kursów. W mieszance model + rynek
  optymalna waga modelu wychodzi ujemna: tam, gdzie model nie zgadza się
  z rynkiem, częściej rację ma rynek.
- „Okazje” modelu są gorsze od zakładów losowych: CLV −8%, ROI singli po
  podatku −27% (wszystkie zakłady bez selekcji: −17%).
- Wniosek: sam model z goli nie nadaje się do szukania value. Zostaje jako
  zapas dla meczów bez kursów ostrego rynku.

### Wycena z kursów ostrego rynku: działa, ale okazji jest mało

Macierz wyników dopasowana do kursów Pinnacle/Betfair (1X2 + O/U) wycenia
inne rynki zgodnie z rynkiem: handicap azjatycki różni się od kursów
Pinnacle średnio o 0,7%, choć macierz nie widziała tych kursów.

Gra u bet365 po kursach z piątku/wtorku, gdy kurs jest wyższy od
sprawiedliwego z Pinnacle/Betfair:

| | Zakłady (4+ sezony, 5 lig) | CLV (bez podatku) |
|---|---|---|
| Zdarzenia z przewagą ≥ 2% | 533 (ok. 3 tygodniowo) | +2,3% |
| Single z EV po podatku ≥ 5% | 12 | — |
| AKO 3 z takich zdarzeń | 31 | +14,8% (po podatku ok. +1%) |
| AKO 4 | 30 | +15,9% (po podatku ok. +2%) |

- Dodatnie CLV potwierdza, że to prawdziwe pomyłki bukmachera, a nie szum.
- Po podatku 12% single praktycznie nie istnieją, a AKO wychodzą w okolicy
  zera na plus przy ogromnej zmienności (kilka kuponów na sezon, średni kurs
  kuponu od 14 przy AKO 3 do 91 przy AKO 5). Faktyczne ROI w backteście to
  szum: za mało kuponów.
- Wynik dotyczy bet365. Superbet i STS mogą być miększe albo twardsze; tego
  nie sprawdzimy bez ich kursów. Promocje „bez podatku” zmieniają rachunek
  radykalnie (przewaga 2% przestaje być zjadana przez 12%).

### Poprawki po niezależnym przeglądzie

Przegląd (4 recenzentów + weryfikacja) potwierdził poprawność wiarygodności
i gradientu modelu, rozliczania wszystkich 274 rynków i mapowania kolumn
z football-data.co.uk. Poprawione zostały: AKO łączące kursy z różnych dni,
CLV kuponu (iloczyn, nie średnia), CLV przy przesuniętej linii handicapu,
wyrównanie treningu z dniem zebrania kursów, prior beniaminków liczony tylko
z wcześniejszych sezonów, usuwanie marży metodą potęgową zamiast
proporcjonalnej (proporcjonalna zawyżała szanse outsiderów), osobna kara dla
kierunku „liczba goli” (model był zbyt pewny na O/U), Ekstraklasa w tabeli
trafności, etykiety handicapu europejskiego. Podatek od wygranych powyżej
2280 zł wejdzie w etapie 5, razem ze stawkami.

### Decyzja po etapie 2 (do ustalenia)

Rekomendacja: oprzeć wycenę na kursach ostrego rynku zamiast na modelu.
Aplikacja pobiera kursy Pinnacle/Betfair (The Odds API, region EU), wylicza
kursy sprawiedliwe i kursy minimalne na wszystkich rynkach, a użytkownik
porównuje je z ofertą Superbetu i STS. Generator składa AKO z wpisanych
zdarzeń z przewagą. Model Dixona-Colesa zostaje tylko jako zapas.

## Na później: serwer

Na razie wszystko działa lokalnie. Przy przenosinach na serwer trzeba
będzie wybrać:

1. **Serwer:** darmowy Oracle Cloud Always Free (0 zł, ale trudniejsza
   rejestracja) albo tani VPS (np. Hetzner, mikr.us, kilkanaście zł
   miesięcznie).
2. **Dostęp do panelu:** Tailscale (prywatna sieć, nic nie jest publicznie
   wystawione) albo hasło przez przeglądarkę (reverse proxy Caddy z HTTPS).

Przeniesienie sprowadzi się do dodania Docker Compose, bo konfiguracja
i baza są już oddzielone od kodu.

## Odpowiedzialna gra

Aplikacja ma wbudowane limity: maksymalna stawka jako % bankrolla, dzienny
limit kuponów i widoczny bilans. Celem jest mierzalne podejmowanie decyzji,
a nie gwarancja wygranej. Model może się mylić, a bukmacherzy mają przewagę
w postaci marży, a w Polsce dodatkowo podatku.
