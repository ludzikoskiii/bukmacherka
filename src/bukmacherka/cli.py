"""Polecenia uruchamiane z terminala: `uv run bukmacherka <polecenie>`."""

import argparse
import logging

from bukmacherka.config import get_settings
from bukmacherka.db import get_engine, init_db
from bukmacherka.ingest import football_data_co_uk
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


if __name__ == "__main__":
    main()
