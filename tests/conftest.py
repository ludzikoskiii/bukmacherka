import datetime as dt
from pathlib import Path

import httpx
import pytest

from bukmacherka.db import get_engine, init_db
from bukmacherka.ingest import football_data_co_uk

FIXTURES = Path(__file__).parent / "fixtures" / "football_data_co_uk"
FIXTURE_URLS = {
    "/mmz4281/2526/E0.csv": "E0_2526.csv",
    "/mmz4281/2627/E0.csv": "E0_2627.csv",
    "/new/POL.csv": "POL.csv",
}


@pytest.fixture
def session_factory(tmp_path):
    return init_db(get_engine(f"sqlite:///{tmp_path}/db/test.db"))


@pytest.fixture
def fake_site():
    """Udaje football-data.co.uk, serwując pliki z katalogu fixtures."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        name = FIXTURE_URLS.get(request.url.path)
        if name is None:
            return httpx.Response(404)
        return httpx.Response(200, content=(FIXTURES / name).read_bytes())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    yield client, requested
    client.close()


@pytest.fixture
def run_import(session_factory, fake_site, tmp_path):
    client, requested = fake_site

    def run(leagues=("E0", "POL"), first_season=2025):
        return football_data_co_uk.import_history(
            session_factory,
            list(leagues),
            first_season,
            tmp_path / "raw",
            today=dt.date(2026, 10, 16),
            client=client,
        )

    run.requested = requested
    return run
