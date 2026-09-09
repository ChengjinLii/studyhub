from sqlalchemy import create_engine, text

from app.core.query_timing import QueryTiming, instrument_engine, query_timing


def test_query_timing_is_scoped_and_records_no_sql():
    engine = create_engine("sqlite://")
    instrument_engine(engine)
    timing = QueryTiming()
    token = query_timing.set(timing)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT :secret"), {"secret": "never-log-this"})
        assert timing.count == 1
        assert timing.seconds >= 0
        assert "never-log-this" not in repr(timing)
    finally:
        query_timing.reset(token)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    assert timing.count == 1
    engine.dispose()
