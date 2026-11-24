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
    """Give each test a SQLite file in pytest's named temporary directory."""
    db_path = tmp_path / "test.db"
    request.node.user_properties.append(("test_db_path", str(db_path)))
    return db_path


@pytest.fixture
def test_engine(test_db_path: Path) -> Iterator[Engine]:
    """Open and dispose an engine for one test."""
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
