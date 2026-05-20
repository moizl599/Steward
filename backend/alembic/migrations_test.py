"""End-to-end tests for the Alembic migration history.

We run ``alembic upgrade head`` and ``alembic downgrade base`` against a fresh
on-disk SQLite file in ``tmp_path``. Subprocess invocation matches what a real
deploy job runs — testing it any other way (programmatic ``command.upgrade``)
would skip a layer that breaks in production (env var loading, working
directory, etc.).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, inspect

EXPECTED_TABLES = {"environments", "scans", "reports"}
ALEMBIC_TABLE = "alembic_version"


def _run_alembic(args: list[str], db_url: str, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, "DATABASE_URL": db_url}
    return subprocess.run(
        ["alembic", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
    )


def _backend_root() -> Path:
    # tests run from /app inside the container; the alembic dir lives there.
    return Path("/app")


def test_alembic_upgrade_head_creates_all_tables(tmp_path: Path) -> None:
    db_file = tmp_path / "upgrade.db"
    db_url_async = f"sqlite+aiosqlite:///{db_file}"
    db_url_sync = f"sqlite:///{db_file}"

    _run_alembic(["upgrade", "head"], db_url_async, _backend_root())

    engine = create_engine(db_url_sync)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()
    assert EXPECTED_TABLES.issubset(tables), tables
    assert ALEMBIC_TABLE in tables


def test_alembic_downgrade_base_drops_all_app_tables(tmp_path: Path) -> None:
    db_file = tmp_path / "downgrade.db"
    db_url_async = f"sqlite+aiosqlite:///{db_file}"
    db_url_sync = f"sqlite:///{db_file}"

    _run_alembic(["upgrade", "head"], db_url_async, _backend_root())
    _run_alembic(["downgrade", "base"], db_url_async, _backend_root())

    engine = create_engine(db_url_sync)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()
    # Application tables are gone; alembic_version stays around (Alembic owns it).
    assert EXPECTED_TABLES.isdisjoint(tables), tables


def test_alembic_round_trips_upgrade_downgrade_upgrade(tmp_path: Path) -> None:
    db_file = tmp_path / "roundtrip.db"
    db_url_async = f"sqlite+aiosqlite:///{db_file}"
    db_url_sync = f"sqlite:///{db_file}"

    _run_alembic(["upgrade", "head"], db_url_async, _backend_root())
    _run_alembic(["downgrade", "base"], db_url_async, _backend_root())
    _run_alembic(["upgrade", "head"], db_url_async, _backend_root())

    engine = create_engine(db_url_sync)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()
    assert EXPECTED_TABLES.issubset(tables)
