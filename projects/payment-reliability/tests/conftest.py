"""Shared fixtures for Product 01 tests."""

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from synthetic_generator.ingest import connect, init_db


@pytest.fixture
def db() -> Iterator[psycopg.Connection]:
    """A fresh schema with tables and KPI views; skipped when PostgreSQL is not running."""
    try:
        conn = connect()
    except psycopg.OperationalError as err:
        if os.environ.get("REQUIRE_DB") == "1":  # CI (ADR 0010): a missing database is a failure
            pytest.fail(f"REQUIRE_DB=1 but PostgreSQL is not reachable: {err}")
        pytest.skip(f"PostgreSQL not reachable (start it with `make up`): {err}")
    conn.autocommit = True
    schema = f"test_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    init_db(conn)
    try:
        yield conn
    finally:
        conn.execute(f"DROP SCHEMA {schema} CASCADE")
        conn.close()
