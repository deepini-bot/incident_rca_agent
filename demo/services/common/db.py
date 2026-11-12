"""SQLAlchemy engine with a deliberately small pool (so pool exhaustion is reproducible)."""
import os
import time
from contextlib import contextmanager

from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_client import Gauge, Histogram
from sqlalchemy import create_engine, text

from . import faults

SERVICE = os.getenv("SERVICE_NAME", "unknown")
DB_LAT = Histogram(
    "db_query_duration_seconds", "Time a DB connection is held per operation", ["service"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


def make_engine():
    engine = create_engine(
        os.environ["DATABASE_URL"],
        pool_size=5, max_overflow=2, pool_timeout=3, pool_recycle=300, pool_pre_ping=True,
    )
    SQLAlchemyInstrumentor().instrument(engine=engine)
    Gauge("db_pool_checked_out", "Connections checked out of the pool", ["service"]) \
        .labels(SERVICE).set_function(lambda: engine.pool.checkedout())
    return engine


@contextmanager
def connection(engine):
    """Transactional connection. The slow_db fault holds the connection with SELECT SLEEP,
    which is what a genuinely slow query does (and it is what exhausts the pool)."""
    start = time.perf_counter()
    try:
        with engine.begin() as conn:
            ms = faults.state.slow_db_ms
            if ms > 0:
                conn.execute(text("SELECT SLEEP(:s)"), {"s": ms / 1000})
            yield conn
    finally:
        DB_LAT.labels(SERVICE).observe(time.perf_counter() - start)
