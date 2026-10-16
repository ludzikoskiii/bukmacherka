from bukmacherka.report import coverage, format_coverage


def test_coverage(run_import, session_factory):
    run_import()
    with session_factory() as session:
        rows = {(row["league"], row["season"]): row for row in coverage(session)}

    e0_old = rows[("E0", "2025/2026")]
    assert e0_old["matches"] == 3
    assert e0_old["Do przerwy"] == 1
    assert e0_old["xG"] == 0
    assert e0_old["1X2"]["pinnacle"] == 1

    e0_new = rows[("E0", "2026/2027")]
    assert e0_new["xG"] == 1
    assert e0_new["1X2"]["pinnacle"] == 0
    assert e0_new["1X2"]["betfair_exchange"] == 1

    pol = rows[("POL", "2025/2026")]
    assert pol["Do przerwy"] == 0
    assert pol["1X2"]["pinnacle"] == 1
    assert pol["O/U 2,5"]["market_avg"] == 0


def test_format_coverage(run_import, session_factory):
    assert "import-history" in format_coverage([])

    run_import()
    with session_factory() as session:
        text = format_coverage(coverage(session))

    assert "POL" in text
    assert "2026/2027" in text
