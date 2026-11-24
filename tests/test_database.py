"""Smoke test for creating and reopening the database."""

import sqlite3
import warnings

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session
from sqlmodel import Session, SQLModel, select

import maskyard as oas
import maskyard.engine as database
from maskyard.models.config import CURRENT_SCHEMA_VERSION, DatabaseConfig


def test_create_and_load_database(test_engine: Engine) -> None:
    database.create_db_and_tables()
    test_engine.dispose()
    tables = set(inspect(test_engine).get_table_names())
    assert tables == set(SQLModel.metadata.tables)


def test_database_config_stores_schema_version(test_engine: Engine) -> None:
    database.create_db_and_tables()

    with Session(test_engine) as session:
        config = session.get(DatabaseConfig, 1)
        assert config is not None
        assert config.schema_version == CURRENT_SCHEMA_VERSION


def test_dbu_mismatch_rebuilds_database_and_dispose_clears_cache(
    test_engine: Engine,
) -> None:
    database.create_db_and_tables(dbu=0.002)
    assert database.settings.dbu == 0.002

    with Session(test_engine) as session:
        assert database.settings.dbu == 0.002
        session.add(oas.Cell(name="old"))
        session.commit()

    with pytest.warns(RuntimeWarning, match="purging the cache"):
        database.create_db_and_tables(dbu=0.005)
    assert database.settings.dbu == 0.005
    with Session(test_engine) as session:
        assert session.exec(select(oas.Cell)).all() == []
    test_engine.dispose()
    assert "dbu" not in database.settings.__dict__
    database.create_db_and_tables(dbu=0.005)
    assert database.settings.dbu == 0.005
    with (
        pytest.raises(IntegrityError, match="database DBU is read-only"),
        test_engine.begin() as connection,
    ):
        connection.execute(text("UPDATE databaseconfig SET dbu = 0.002"))


def test_first_package_session_initializes_empty_cache(
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database, "engine", test_engine)

    with database.session_context() as session:
        config = session.get(DatabaseConfig, 1)
        assert config is not None
        assert config.schema_version == CURRENT_SCHEMA_VERSION


def test_lazy_session_is_replaced_after_engine_dispose(test_engine: Engine) -> None:
    session = database.get_session()
    cell = oas.Cell(name="cached")
    session.add(cell)
    session.commit()
    assert database.get_session() is session

    test_engine.dispose()

    assert object_session(cell) is None
    assert database.get_session() is not session


def test_registered_engine_initializes_on_connection(test_engine: Engine) -> None:
    database._register_engine(test_engine)

    with test_engine.connect() as connection:
        assert inspect(connection).has_table("databaseconfig")
        assert (
            connection.execute(
                select(SQLModel.metadata.tables["databaseconfig"].c.schema_version)
            ).scalar_one()
            == CURRENT_SCHEMA_VERSION
        )


def test_outdated_cache_warns_and_is_purged(
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database.create_db_and_tables()
    with Session(test_engine) as session:
        session.add(oas.Cell(name="stale"))
        config = session.get(DatabaseConfig, 1)
        assert config is not None
        config.schema_version = 0
        session.commit()
    with test_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE stale_table (id INTEGER)")

    test_engine.dispose()

    def open_cache() -> None:
        with database.session_context() as session:
            assert session.exec(select(oas.Cell)).all() == []

    with pytest.warns(RuntimeWarning, match="purging the cache"):
        open_cache()
    with Session(test_engine) as session:
        config = session.get(DatabaseConfig, 1)
        assert config is not None
        assert config.schema_version == CURRENT_SCHEMA_VERSION
    assert "stale_table" not in inspect(test_engine).get_table_names()


def test_cache_without_version_column_is_purged(test_engine: Engine) -> None:
    database_path = test_engine.url.database
    assert database_path is not None
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE databaseconfig (id INTEGER PRIMARY KEY, dbu FLOAT)"
        )
        connection.execute("INSERT INTO databaseconfig (id, dbu) VALUES (1, 0.001)")

    with pytest.warns(RuntimeWarning, match="purging the cache"):
        database.create_db_and_tables()

    with Session(test_engine) as session:
        config = session.get(DatabaseConfig, 1)
        assert config is not None
        assert config.schema_version == CURRENT_SCHEMA_VERSION


def test_matching_cache_keeps_existing_cells(test_engine: Engine) -> None:
    database.create_db_and_tables()
    with Session(test_engine) as session:
        session.add(oas.Cell(name="keep"))
        session.commit()

    test_engine.dispose()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        database.create_db_and_tables()
    assert not caught
    with Session(test_engine) as session:
        assert len(session.exec(select(oas.Cell)).all()) == 1


def test_bbox_column_upgrade_keeps_existing_cells(test_engine: Engine) -> None:
    database.create_db_and_tables()
    with Session(test_engine) as session:
        session.add(oas.Cell(name="keep"))
        session.commit()
    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE cell ADD COLUMN bbox BLOB NOT NULL DEFAULT X'00'"
        )
        connection.exec_driver_sql("UPDATE databaseconfig SET schema_version = 1")

    test_engine.dispose()
    database.create_db_and_tables()

    assert "bbox" not in {
        column["name"] for column in inspect(test_engine).get_columns("cell")
    }
    with Session(test_engine) as session:
        assert [cell.name for cell in session.exec(select(oas.Cell)).all()] == ["keep"]
