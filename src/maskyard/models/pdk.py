"""Minimal decorator for persistent parametrized cells."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from functools import wraps
from hashlib import sha256
from operator import attrgetter
from pathlib import Path
from threading import RLock
from types import FunctionType, UnionType
from typing import (
    TYPE_CHECKING,
    Literal,
    TypeAliasType,
    TypedDict,
    Unpack,
    get_type_hints,
    overload,
)

from cachetools.keys import hashkey
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship, Session, SQLModel, select

from ..engine import get_context_session, get_session
from ..pcell_cache import generation_lock, identity, serialize_hashkey
from ..serialization import (
    _TO_HASHABLE,
    get_cell_name,
    kcl_cross_section_serializer,
    to_hashable,
)
from ..writer import submit_cell
from .cell import Cell, automatic_cell_name
from .cell import create_cell as _create_cell
from .cross_section import SymmetricCrossSection
from .dependency import Dependency
from .factory import PCellFactory

if TYPE_CHECKING:
    from collections.abc import Hashable, Mapping, Sequence

    from ray import ObjectRef

# Serializer inputs vary with the registered runtime type or annotation.
type _Serializer = Callable[..., object]
type _TypeSerializers = Sequence[tuple[type | UnionType, _Serializer]]
type _SerializerMap = Mapping[type | UnionType | TypeAliasType, _Serializer]


class _PCellOptions(TypedDict, total=False):
    drop_params: Sequence[str]
    type_serializers: _TypeSerializers
    type_hints_serializer: _SerializerMap | None
    use_writer: bool


def _run_remote_pcell(
    factory: Callable[..., Cell],
    pdk_name: str,
    database_url: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    drop_params: tuple[str, ...],
    type_serializers: tuple[tuple[type | UnionType, _Serializer], ...],
    type_hints_serializer: _SerializerMap | None,
) -> int:
    """Run the ordinary persistent PCell path inside a Ray worker."""
    from sqlmodel import create_engine

    from .. import engine as database

    if str(database.engine.url) != database_url:
        database.close_session()
        database.engine.dispose()
        database.engine = create_engine(database_url)
        database._initialized.clear()
        database._register_engine(database.engine)
    pdk = get_or_create_pdk(pdk_name)
    cell = pdk.pcell(
        drop_params=drop_params,
        type_serializers=type_serializers,
        type_hints_serializer=type_hints_serializer,
    )(factory)(*args, **kwargs)
    if cell.id is None:
        raise RuntimeError("Remote PCell was not persisted")
    return cell.id


class RemotePCell:
    """Cache Ray object references for equivalent PCell submissions."""

    def __init__(
        self,
        factory: Callable[..., Cell],
        pdk_name: str,
        database_url: str,
        signature: inspect.Signature,
        make_key: Callable[..., tuple[Hashable, ...]],
        drop_params: tuple[str, ...],
        type_serializers: tuple[tuple[type | UnionType, _Serializer], ...],
        type_hints_serializer: _SerializerMap | None,
    ) -> None:
        """Store factory and database configuration for remote submissions."""
        self._factory = factory
        self._pdk_name = pdk_name
        self._database_url = database_url
        self._signature = signature
        self._make_key = make_key
        self._drop_params = drop_params
        self._type_serializers = type_serializers
        self._type_hints_serializer = type_hints_serializer
        self._cache: dict[tuple[Hashable, ...], ObjectRef[int]] = {}
        self._lock = RLock()
        self.__name__ = get_function_name(factory)
        self.__signature__ = signature

    def remote(self, *args: object, **kwargs: object) -> ObjectRef[int]:
        """Reuse a matching Ray reference or submit the factory to a worker.

        A failed cached task is discarded so a subsequent call can retry it.

        Args:
            *args: Positional arguments to bind to the cell factory.
            **kwargs: Keyword arguments to bind to the cell factory.

        Returns:
            A Ray reference to the persisted cell ID.

        Raises:
            TypeError: If the arguments do not match the factory signature.
        """
        import ray

        bound = self._signature.bind(*args, **kwargs)
        bound.apply_defaults()
        params = {
            name: to_hashable(value) if isinstance(value, _TO_HASHABLE) else value
            for name, value in bound.arguments.items()
        }
        key = self._make_key(**params)
        with self._lock:
            ref = self._cache.get(key)
            if ref is not None:
                ready, _ = ray.wait([ref], timeout=0)
                if not ready:
                    return ref
                try:
                    ray.get(ref)
                except Exception:
                    del self._cache[key]
                else:
                    return ref
            ref = ray.remote(_run_remote_pcell).remote(
                self._factory,
                self._pdk_name,
                self._database_url,
                args,
                kwargs,
                self._drop_params,
                self._type_serializers,
                self._type_hints_serializer,
            )
            self._cache[key] = ref
            return ref

    def get_cell(self, ref: ObjectRef[int]) -> Cell:
        """Resolve a Ray result in the caller's database session.

        Args:
            ref: Reference to the cell ID returned by a remote submission.

        Returns:
            The persisted cell loaded in the current session.

        Raises:
            LookupError: If the task's cell is missing from the database.
        """
        import ray

        cell_id: int = ray.get(ref)
        cell = get_session().get(Cell, cell_id)
        if cell is None:
            raise LookupError(f"Remote PCell {cell_id} is missing from the database")
        return cell


class Pdk(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    name: str | None = Field(unique=True)
    pcell_factories: list[PCellFactory] = Relationship(
        sa_relationship=relationship("PCellFactory", back_populates="pdk")
    )
    cells: list[Cell] = Relationship(
        sa_relationship=relationship("Cell", back_populates="pdk")
    )

    @overload
    def pcell[**P](
        self,
        function: Callable[P, Cell],
        /,
    ) -> Callable[P, Cell]: ...

    @overload
    def pcell[**P](
        self, function: Callable[P, Cell], /, *, ray: Literal[True]
    ) -> RemotePCell: ...

    @overload
    def pcell[**P](
        self,
        function: None = None,
        /,
        *,
        ray: Literal[True],
        **kwargs: Unpack[_PCellOptions],
    ) -> Callable[[Callable[P, Cell]], RemotePCell]: ...

    @overload
    def pcell[**P](
        self,
        function: None = None,
        /,
        *,
        drop_params: Sequence[str] = ("self", "cls"),
        type_serializers: _TypeSerializers = (
            (SymmetricCrossSection, attrgetter("id")),
        ),
        type_hints_serializer: _SerializerMap | None = None,
        use_writer: bool = False,
        ray: Literal[False] = False,
    ) -> Callable[[Callable[P, Cell]], Callable[P, Cell]]: ...

    def pcell[**P](
        self,
        function: Callable[P, Cell] | None = None,
        /,
        *,
        drop_params: Sequence[str] = ("self", "cls"),
        type_serializers: _TypeSerializers = (
            (SymmetricCrossSection, attrgetter("id")),
        ),
        type_hints_serializer: _SerializerMap | None = None,
        use_writer: bool = False,
        ray: bool = False,
    ) -> (
        Callable[P, Cell]
        | RemotePCell
        | Callable[[Callable[P, Cell]], Callable[P, Cell] | RemotePCell]
    ):
        """Register a parametrized cell factory and reuse cells for matching inputs.

        Factory source changes invalidate the corresponding dependency registration.

        Args:
            function: Factory to decorate directly. Omit it to configure a decorator.
            drop_params: Parameter names excluded from cache keys.
            type_serializers: Ordered (type, serializer) pairs for matching argument
                values.
            type_hints_serializer: Serializers selected by the factory's annotations
                before runtime types are considered.
            use_writer: Whether to persist new cells through the batched writer.
            ray: Whether to expose Ray submissions instead of a synchronous factory.

        Returns:
            The wrapped factory, a remote factory handle, or a decorator for either form
            when function is omitted.

        Raises:
            ValueError: If the PDK is unnamed or Ray and the batched writer are both
                requested.
            NotImplementedError: If the database dialect does not support registration.
        """

        def decorate(
            factory: Callable[P, Cell],
        ) -> Callable[P, Cell] | RemotePCell:
            """Register a factory and build the synchronous wrapper or remote handle."""
            sig = inspect.signature(factory)
            file = _get_path(factory)
            session = get_session()
            name = get_function_name(factory)

            with file.open("rb") as f:
                file_hash = sha256(f.read()).hexdigest()
            registration_key = identity(
                str(session.get_bind().engine.url), str(file), name
            )
            with generation_lock(registration_key):
                if self.name is None:
                    raise ValueError("PCell factories require a named PDK")
                registered_pdk_id = get_or_create_pdk(self.name).id
                dependency = session.exec(
                    select(Dependency).where(Dependency.path == file)
                ).one_or_none()
                if dependency is None:
                    dependency = Dependency(path=file, file_hash=file_hash)
                    session.add(dependency)
                    session.commit()
                elif dependency.file_hash != file_hash:
                    session.delete(dependency)
                    session.commit()
                    dependency = Dependency(path=file, file_hash=file_hash)
                    session.add(dependency)
                    session.commit()
                dialect = session.get_bind().dialect.name
                if dialect == "sqlite":
                    insert_factory = sqlite_insert(PCellFactory)
                elif dialect == "postgresql":
                    insert_factory = postgresql_insert(PCellFactory)
                else:
                    raise NotImplementedError(
                        f"Unsupported database dialect: {dialect}"
                    )
                session.exec(
                    insert_factory.values(
                        name=name,
                        pdk_id=registered_pdk_id,
                        dependency_id=dependency.id,
                    ).on_conflict_do_nothing(
                        index_elements=["pdk_id", "dependency_id", "name"]
                    )
                )
                session.commit()
                pcell_factory = session.exec(
                    select(PCellFactory).where(
                        PCellFactory.name == name,
                        PCellFactory.pdk_id == registered_pdk_id,
                        PCellFactory.dependency_id == dependency.id,
                    )
                ).one()
            factory_id = pcell_factory.id

            try:
                hints = get_type_hints(factory)
            except (NameError, TypeError):
                hints = {}
            serializers: _SerializerMap | None = type_hints_serializer
            if serializers is None:
                serializers = {SymmetricCrossSection: kcl_cross_section_serializer()}
            make_key = get_keys_function(
                hints=hints,
                drop_args=drop_params,
                serialize_types=type_serializers,
                serialize_hints=serializers,
            )
            if ray:
                if use_writer:
                    raise ValueError("ray=True cannot be combined with use_writer=True")
                if self.name is None:
                    raise ValueError("Ray PCells require a named PDK")
                return RemotePCell(
                    factory,
                    self.name,
                    str(session.get_bind().engine.url),
                    sig,
                    make_key,
                    tuple(drop_params),
                    tuple(type_serializers),
                    type_hints_serializer,
                )
            cache: dict[tuple[object, Hashable], int] = {}
            lock = RLock()

            @wraps(factory)
            def wrapper_pcell(*args: P.args, **kwargs: P.kwargs) -> Cell:
                """Reuse a matching cell or build and commit a new one."""
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                params = dict(bound.arguments)
                key_params = {
                    key: (
                        to_hashable(value) if isinstance(value, _TO_HASHABLE) else value
                    )
                    for key, value in params.items()
                }
                key = make_key(**key_params)
                key_bytes = serialize_hashkey(key)
                session = get_session()
                cache_key = (session.get_bind(), key)
                with lock:
                    cell_id = cache.get(cache_key)
                    if cell_id is not None:
                        saved = session.get(Cell, cell_id)
                        if saved is not None:
                            return saved
                        del cache[cache_key]

                    name = get_cell_name(get_function_name(factory), **params)
                    pcell_key = identity(
                        str(session.get_bind().engine.url),
                        str(factory_id),
                        key_bytes.hex(),
                    )
                    with generation_lock(pcell_key):
                        with Session(session.get_bind()) as lookup:
                            existing_id = lookup.exec(
                                select(Cell.id).where(
                                    Cell.pcell_factory_id == factory_id,
                                    Cell.hashkey == key_bytes,
                                )
                            ).first()
                        if existing_id is not None:
                            saved = session.get(Cell, existing_id)
                            if saved is not None:
                                cache[cache_key] = existing_id
                                return saved

                        with automatic_cell_name.set(name):
                            cell = factory(*args, **kwargs)
                        cell.pcell_factory_id = factory_id
                        cell.hashkey = key_bytes
                        cell_info = cell.info
                        cell_settings = cell.settings
                        cell_settings.data = {**params}
                        if use_writer:
                            cell_id = submit_cell(cell, flush=True).result()
                            saved = session.get(Cell, cell_id)
                            if saved is None:
                                raise RuntimeError(
                                    "Writer committed a cell that cannot be loaded"
                                )
                            cache[cache_key] = cell_id
                            return saved
                        cell_session = get_context_session(cell)
                        cell_session.add(cell)
                        cell_info.data = {**cell_info.data}
                        cell_session.add(cell_info)
                        cell_session.add(cell_settings)
                        cell_session.commit()
                        if cell.id is not None:
                            cache[cache_key] = cell.id
                        return cell

            return wrapper_pcell

        return decorate(function) if function is not None else decorate

    def create_cell(self, name: str | None = None, *, persist: bool = True) -> Cell:
        """Create an empty cell associated with this PDK.

        Args:
            name: Explicit name, or None to use the active factory's automatic name.
            persist: Whether to add the cell to the current session for a later commit.

        Returns:
            The newly initialized cell.

        Raises:
            ValueError: If the PDK has no name.
        """
        if self.name is None:
            raise ValueError("A PDK needs a name to create cells")
        pdk = get_or_create_pdk(self.name) if self.id is None else self
        return _create_cell(name=name, pdk=pdk, persist=persist)


def get_function_name(f: Callable[..., object]) -> str:
    """Resolve a callable name, following wrapped functions such as partials.

    Args:
        f: Callable to inspect.

    Returns:
        The first available callable name.

    Raises:
        ValueError: If neither the callable nor its wrapped function has a name.
    """
    if hasattr(f, "__name__"):
        return str(f.__name__)
    if hasattr(f, "func") and callable(f.func):
        return get_function_name(f.func)
    raise ValueError(f"Function {f} has no name.")


def get_keys_function(
    hints: dict[str, type],
    drop_args: Sequence[str],
    serialize_types: _TypeSerializers,
    serialize_hints: _SerializerMap,
) -> Callable[..., tuple[Hashable, ...]]:
    """Build a function that normalizes arguments into a PCell cache key.

    Args:
        hints: Factory type hints keyed by parameter name.
        drop_args: Names to remove from keyword arguments before hashing.
        serialize_types: Ordered serializers matched against runtime value types.
        serialize_hints: Serializers matched against declared types with priority over
            runtime types.

    Returns:
        A callable that produces a key from the normalized arguments.
    """
    types_ = tuple(st[0] for st in serialize_types)

    def _keys_function(*args: object, **kwargs: object) -> tuple[Hashable, ...]:
        """Apply the configured serializers and build a cachetools key."""
        for arg in drop_args:
            kwargs.pop(arg, None)

        updates: dict[str, object] = {}
        for key, value in kwargs.items():
            if key in hints and hints[key] in serialize_hints:
                updates[key] = serialize_hints[hints[key]](value)
            elif isinstance(value, types_):
                for type_, serializer in serialize_types:
                    if isinstance(value, type_):
                        updates[key] = serializer(value)
                        break
        kwargs.update(updates)
        return hashkey(*args, **kwargs)

    return _keys_function


def _get_path(f: Callable[..., object]) -> Path:
    """Resolve a callable's source path, unwrapping partials as needed."""
    if isinstance(f, FunctionType):
        return Path(f.__code__.co_filename).expanduser().resolve()
    if isinstance(f, functools.partial):
        return _get_path(f.func)
    code = getattr(f, "__code__", None)
    if code is None:
        raise ValueError(f"Failed to retrieve path of code for function {f}")
    return Path(code.co_filename).expanduser().resolve()


def get_or_create_pdk(name: str) -> Pdk:
    """Get a named PDK, registering it first if it does not exist.

    Args:
        name: Unique PDK name in the current database.

    Returns:
        The registered PDK loaded in the current session.

    Raises:
        NotImplementedError: If the database dialect does not support registration.
    """
    session = get_session()
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        stmt = sqlite_insert(Pdk)
    elif dialect == "postgresql":
        stmt = postgresql_insert(Pdk)
    else:
        raise NotImplementedError(f"Unsupported database dialect: {dialect}")
    with generation_lock(identity(str(session.get_bind().engine.url), "pdk", name)):
        with Session(session.get_bind()) as writer:
            writer.exec(
                stmt.values(name=name).on_conflict_do_nothing(index_elements=["name"])
            )
            writer.commit()
        return session.exec(select(Pdk).where(Pdk.name == name)).one()
