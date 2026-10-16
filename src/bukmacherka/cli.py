"""Polecenia uruchamiane z terminala: `uv run bukmacherka <polecenie>`."""

import argparse
import logging

from bukmacherka.backtest.run import BacktestConfig, format_report, run_backtest, save
from bukmacherka.config import get_settings
from bukmacherka.db import get_engine, init_db
from bukmacherka.ingest import football_data_co_uk
from bukmacherka.model import dixon_coles
from bukmacherka.report import coverage, format_coverage


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bukmacherka")
    commands = parser.add_subparsers(dest="command", required=True)

    history = commands.add_parser(
        "import-history", help="pobierz dane historyczne z football-data.co.uk"
    )
    history.add_argument("--leagues", nargs="+", help="kody lig, np. E0 POL")
    history.add_argument("--first-season", type=int, help="rok początku najstarszego sezonu")
    history.add_argument(
        "--refresh", action="store_true", help="pobierz ponownie także zakończone sezony"
    )

    commands.add_parser("report", help="pokaż, jakie dane są w bazie")

    backtest = commands.add_parser("backtest", help="sprawdź model na danych historycznych")
    backtest.add_argument("--leagues", nargs="+", help="kody lig, np. E0 POL")
    backtest.add_argument("--from-season", type=int, help="pierwszy oceniany sezon (rok początku)")
    backtest.add_argument(
        "--bookmaker",
        default="bet365",
        choices=["bet365", "market_avg", "market_max", "pinnacle", "betfair_exchange"],
        help="kursy, po których stawiamy zakłady",
    )
    backtest.add_argument(
        "--closing", action="store_true", help="graj po kursach zamknięcia zamiast otwarcia"
    )
    backtest.add_argument("--tax", type=float, help="podatek od stawki (domyślnie z ustawień)")
    backtest.add_argument("--min-ev", type=float, help="minimalne EV singla i kuponu po podatku")
    backtest.add_argument("--min-edge", type=float, help="minimalna przewaga zdarzenia w AKO")
    backtest.add_argument("--xi", type=float, default=dixon_coles.DEFAULT_XI)
    backtest.add_argument("--reg", type=float, default=dixon_coles.DEFAULT_REG)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    session_factory = init_db(get_engine(settings.database_url))

    if args.command == "import-history":
        counts = football_data_co_uk.import_history(
            session_factory,
            leagues=args.leagues or settings.leagues,
            first_season=args.first_season or settings.first_season,
            raw_dir=settings.data_dir / "raw" / "football-data.co.uk",
            refresh=args.refresh,
        )
        for league, count in counts.items():
            print(f"{league}: {count} meczów")
    elif args.command == "report":
        with session_factory() as session:
            print(format_coverage(coverage(session)))
    elif args.command == "backtest":
        config = BacktestConfig(
            leagues=args.leagues or settings.leagues,
            from_season=args.from_season or settings.first_season + 1,
            bookmaker=args.bookmaker,
            closing=args.closing,
            tax=settings.tax_rate if args.tax is None else args.tax,
            min_ev=settings.min_ev if args.min_ev is None else args.min_ev,
            min_edge=settings.min_leg_edge if args.min_edge is None else args.min_edge,
            xi=args.xi,
            reg=args.reg,
        )
        result = run_backtest(session_factory, config)
        save(result, settings.data_dir / "backtest")
        print(format_report(result))


if __name__ == "__main__":
    main()
