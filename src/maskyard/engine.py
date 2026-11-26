"""Database engine and schema setup."""

from collections.abc import Generator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from threading import Event, Lock, get_ident
from warnings import warn

from sqlalchemy import MetaData, event, inspect, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import object_session
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401
from .config import settings
from .models.config import CURRENT_SCHEMA_VERSION

engine = create_engine(settings.database_url)
DEFAULT_DBU = 0.001
_schema_lock = Lock()
_registration_lock = Lock()
_session_lock = Lock()
_initialized = Event()
_engine_generation = 0
_cached_sessions: dict[int, set[Session]] = {}
_config_table = SQLModel.metadata.tables["databaseconfig"]
_initial_dbu: ContextVar[float] = ContextVar("initial_dbu", default=DEFAULT_DBU)


def create_db_and_tables(*, dbu: float = DEFAULT_DBU) -> None:
    """Initialize the layout cache for the requested database unit.

    Migrate a compatible older schema and rebuild the cache if its schema or DBU is
    incompatible.

    Args:
        dbu: Size of one database unit in micrometers.

    Raises:
        ValueError: If the requested DBU is nonpositive.
    """
    if _initialized.is_set() and settings.dbu == dbu:
        return
    with _schema_lock:
        _initialized.clear()
    token = _initial_dbu.set(dbu)
    try:
        with engine.connect():
            pass
    finally:
        _initial_dbu.reset(token)


def _register_engine(cache_engine: Engine) -> None:
    """Register schema initialization and disposal hooks once per engine."""
    with _registration_lock:
        if not event.contains(cache_engine, "engine_connect", _on_engine_connect):
            event.listen(cache_engine, "engine_connect", _on_engine_connect)
            event.listen(cache_engine, "engine_disposed", _on_engine_disposed)


def _on_engine_connect(connection: Connection) -> None:
    """Initialize and commit the schema on the first connection."""
    with _schema_lock:
        if _initialized.is_set():
            return
        _initialize_schema(connection, dbu=_initial_dbu.get())
        connection.commit()
        with suppress(AttributeError):
            del settings.dbu
        _initialized.set()


def _on_engine_disposed(_engine: Engine) -> None:
    """Invalidate cached DBU and sessions when the engine is disposed."""
    global _engine_generation  # noqa: PLW0603
    with _schema_lock:
        with suppress(AttributeError):
            del settings.dbu
        _initialized.clear()
        _engine_generation += 1
    with _session_lock:
        sessions = [session for group in _cached_sessions.values() for session in group]
        _cached_sessions.clear()
    for session in sessions:
        session.close()


def _stored_schema_version(connection: Connection, tables: set[str]) -> int | None:
    """Read the schema version if the configuration table and column exist."""
    if _config_table.name not in tables:
        return None
    columns = {
        column["name"] for column in inspect(connection).get_columns(_config_table.name)
    }
    if "schema_version" not in columns:
        return None
    return connection.scalar(
        select(_config_table.c.schema_version).where(_config_table.c.id == 1)
    )


def _initialize_schema(connection: Connection, *, dbu: float) -> None:
    """Migrate or rebuild the cache to match the current schema and DBU."""
    if dbu <= 0:
        raise ValueError("DBU must be positive")
    tables = set(inspect(connection).get_table_names())
    expected_tables = set(SQLModel.metadata.tables)

    if tables:
        stored_version = _stored_schema_version(connection, tables)
        stored_dbu = (
            connection.scalar(
                select(_config_table.c.dbu).where(_config_table.c.id == 1)
            )
            if stored_version in (1, CURRENT_SCHEMA_VERSION)
            else None
        )
        if stored_version == 1 and stored_dbu == dbu and expected_tables <= tables:
            columns = {
                column["name"] for column in inspect(connection).get_columns("cell")
            }
            if "bbox" in columns:
                connection.exec_driver_sql("ALTER TABLE cell DROP COLUMN bbox")
            connection.execute(
                _config_table.update()
                .where(_config_table.c.id == 1)
                .values(schema_version=CURRENT_SCHEMA_VERSION)
            )
            stored_version = CURRENT_SCHEMA_VERSION
        if (
            stored_version != CURRENT_SCHEMA_VERSION
            or stored_dbu != dbu
            or not expected_tables <= tables
        ):
            warn(
                "Incompatible database cache configuration "
                f"(stored schema {stored_version}, DBU {stored_dbu}; "
                f"requested schema {CURRENT_SCHEMA_VERSION}, DBU {dbu}); "
                "purging the cache",
                RuntimeWarning,
                stacklevel=2,
            )
            old_schema = MetaData()
            old_schema.reflect(bind=connection)
            old_schema.drop_all(bind=connection)
        else:
            _protect_dbu(connection)
            return

    SQLModel.metadata.create_all(connection)
    connection.execute(
        _config_table.insert().values(
            id=1,
            dbu=dbu,
            schema_version=CURRENT_SCHEMA_VERSION,
        )
    )
    _protect_dbu(connection)


def _protect_dbu(connection: Connection) -> None:
    """Install SQLite triggers that guard the saved database configuration."""
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS databaseconfig_dbu_readonly "
            "BEFORE UPDATE OF dbu ON databaseconfig "
            "BEGIN SELECT RAISE(ABORT, 'database DBU is read-only'); END"
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER IF NOT EXISTS databaseconfig_delete_readonly "
            "BEFORE DELETE ON databaseconfig "
            "BEGIN SELECT RAISE(ABORT, 'database configuration is read-only'); END"
        )


_current_session: ContextVar[tuple[int, Engine, int, Session] | None] = ContextVar(
    "current_session",
    default=None,
)


def get_session() -> Session:
    """Return the current session, opening one for this thread if needed."""
    current = _current_session.get()
    thread_id = get_ident()
    if current is not None and current[0] == thread_id:
        if current[1] is engine and current[2] == _engine_generation:
            return current[3]
        close_session()

    if not _initialized.is_set():
        create_db_and_tables()
    session = Session(engine, expire_on_commit=False)
    _current_session.set((thread_id, engine, _engine_generation, session))
    with _session_lock:
        _cached_sessions.setdefault(thread_id, set()).add(session)
    return session


def close_session() -> None:
    """Close the session cached in the current thread, if any."""
    current = _current_session.get()
    if current is None or current[0] != get_ident():
        return
    _current_session.set(None)
    with _session_lock:
        sessions = _cached_sessions.get(current[0])
        if sessions is not None:
            sessions.discard(current[3])
            if not sessions:
                del _cached_sessions[current[0]]
    current[3].close()


def _close_thread_sessions(thread_ids: set[int]) -> None:
    """Close cached sessions after their worker threads have stopped."""
    with _session_lock:
        sessions = [
            session
            for thread_id in thread_ids
            for session in _cached_sessions.pop(thread_id, ())
        ]
    for session in sessions:
        session.close()


def get_context_session(model: SQLModel) -> SASession:
    """Find the session that owns a model.

    Args:
        model: ORM object whose owning session is needed.

    Returns:
        The session to which the model is attached.

    Raises:
        RuntimeError: If the model is detached or has never been added to a session.
    """
    session = object_session(model)
    if session is None:
        raise RuntimeError(f"{model.__class__} is not attached to a session")

    return session


@contextmanager
def session_context(*, expire_on_commit: bool = True) -> Generator[Session]:
    """Temporarily make a new session current for this thread.

    Args:
        expire_on_commit: Whether to expire ORM objects after each commit.

    Yields:
        The new session, which closes when the context exits.
    """
    if not _initialized.is_set():
        create_db_and_tables()
    with Session(engine, expire_on_commit=expire_on_commit) as session:
        token = _current_session.set((get_ident(), engine, _engine_generation, session))
        try:
            yield session
        finally:
            _current_session.reset(token)


_register_engine(engine)
