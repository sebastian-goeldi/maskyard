"""Fixtures for isolated test databases."""

from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

import pytest
from _pytest.terminal import TerminalReporter
from sqlalchemy.engine import Engine
from sqlmodel import create_engine


@pytest.fixture
def test_db_path(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """Allocate a test database path and record it for failure reports.

    Args:
        tmp_path: Temporary directory assigned by pytest.
        request: Fixture request for the active test.

    Returns:
        The SQLite database path for the test.
    """
    db_path = tmp_path / "test.db"
    request.node.user_properties.append(("test_db_path", str(db_path)))
    return db_path


@pytest.fixture
def test_engine(test_db_path: Path) -> Iterator[Engine]:
    """Install a temporary database engine for one test.

    Args:
        test_db_path: Path to the test's SQLite database file.

    Yields:
        The isolated engine, which is disposed before restoring the original engine.
    """
    import maskyard.engine as database

    engine = create_engine(f"sqlite:///{test_db_path}")
    original_engine = database.engine
    database.engine = engine
    database._initialized.clear()
    with suppress(AttributeError):
        del database.settings.dbu
    database._register_engine(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        database.engine = original_engine
        database._initialized.clear()
        with suppress(AttributeError):
            del database.settings.dbu


def pytest_terminal_summary(terminalreporter: TerminalReporter) -> None:
    """Show database paths once at the end when tests fail."""
    failed_paths = {
        report.nodeid: value
        for status in ("failed", "error")
        for report in terminalreporter.stats.get(status, [])
        for key, value in getattr(report, "user_properties", ())
        if key == "test_db_path"
    }
    if failed_paths:
        terminalreporter.section("Failed test databases")
        for nodeid, path in failed_paths.items():
            terminalreporter.write_line(f"{nodeid}: {path}")
