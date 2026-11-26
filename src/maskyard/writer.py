"""Single-threaded, batched persistence for cells."""

from __future__ import annotations

from atexit import register
from concurrent.futures import Future
from copy import deepcopy
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Lock, Thread
from time import monotonic
from typing import TYPE_CHECKING, Self

from sqlalchemy.orm import object_session
from sqlmodel import Session

from . import engine as database
from . import kdb
from .models.cell import Cell, CellInfo, CellSettings
from .models.geometry import Geometry, Layout
from .models.instance import Instance
from .models.port import CellPort
from .models.trans import InstanceTrans, PortTrans
from .models.vector import Vector

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from .typing import JSONSerializable


@dataclass(frozen=True)
class InstanceWrite:
    """An instance whose child is saved or included in the same cell graph."""

    child: int | CellWrite
    name: str | None = None
    trans: bytes | None = None
    a: bytes | None = None
    b: bytes | None = None
    na: int = 0
    nb: int = 0
    virtual: bool = False


@dataclass(frozen=True)
class PortWrite:
    """A port referring to an already saved cross section."""

    name: str
    cross_section_id: int
    transformation: bytes


@dataclass(frozen=True)
class CellWrite:
    """Session-free snapshot of a cell and its instance relationships."""

    name: str
    geometry: bytes
    info: dict[str, JSONSerializable] = field(default_factory=dict)
    settings: dict[str, JSONSerializable] = field(default_factory=dict)
    instances: tuple[InstanceWrite, ...] = ()
    ports: tuple[PortWrite, ...] = ()
    pcell_factory_id: int | None = None
    hashkey: bytes | None = None

    @classmethod
    def from_cell(cls, cell: Cell) -> Self:
        """Snapshot an unsaved cell and its relationships for another thread.

        Args:
            cell: New cell with any unsaved child definitions available in memory.

        Returns:
            A snapshot containing serialized geometry and session-independent
            relationships.

        Raises:
            ValueError: If the cell graph cannot be snapshotted, such as when it
                contains a cycle or references an unsaved cross section.
        """
        return cls._from_cell(cell, {}, set())

    @classmethod
    def _from_cell(cls, cell: Cell, seen: dict[int, Self], visiting: set[int]) -> Self:
        """Recursively snapshot shared child cells and detect cycles."""
        if cell.id is not None:
            raise ValueError("CellWrite.from_cell requires a new, unsaved cell")
        if object_session(cell) is not None:
            raise ValueError("CellWrite.from_cell requires a session-free cell")
        identity = id(cell)
        if identity in seen:
            return seen[identity]
        if identity in visiting:
            raise ValueError("Cell instances cannot contain a cycle")
        visiting.add(identity)
        geometry = Layout().process_bind_param(
            cell.geometry.layout, database.engine.dialect
        )
        if geometry is None:
            raise ValueError("Cell geometry cannot be empty")
        instances = []
        for instance in cell.instances:
            child = instance.cell
            child_ref = (
                cls._from_cell(child, seen, visiting) if child.id is None else child.id
            )
            instances.append(
                InstanceWrite(
                    child=child_ref,
                    name=instance.name,
                    trans=InstanceTrans().process_bind_param(
                        instance.cplx_trans, database.engine.dialect
                    ),
                    a=Vector().process_bind_param(instance.a, database.engine.dialect),
                    b=Vector().process_bind_param(instance.b, database.engine.dialect),
                    na=instance.na,
                    nb=instance.nb,
                    virtual=instance.virtual,
                )
            )
        ports = []
        for port in cell.ports:
            cross_section_id = port.cross_section_id or port.cross_section.id
            if cross_section_id is None:
                raise ValueError("A port's cross section must be saved first")
            transformation = PortTrans().process_bind_param(
                port.transformation, database.engine.dialect
            )
            if transformation is None:
                raise ValueError("Port transformation cannot be empty")
            ports.append(PortWrite(port.name, cross_section_id, transformation))
        result = cls(
            name=cell.name,
            geometry=geometry,
            info=deepcopy(cell.info.data),
            settings=deepcopy(cell.settings.data),
            instances=tuple(instances),
            ports=tuple(ports),
            pcell_factory_id=cell.pcell_factory_id,
            hashkey=cell.hashkey,
        )
        seen[identity] = result
        visiting.remove(identity)
        return result


@dataclass
class _Request:
    cell: CellWrite
    future: Future[int]
    flush: bool = False


class CellWriter:
    """Own one session on one thread and commit queued cells in batches."""

    def __init__(
        self,
        engine: Engine,
        *,
        batch_size: int = 64,
        batch_delay: float = 0.005,
        queue_size: int = 1024,
    ) -> None:
        """Start a dedicated database writer thread.

        Args:
            engine: Database engine used by the worker's session.
            batch_size: Maximum number of requests in one batch.
            batch_delay: Maximum time in seconds spent waiting for more requests.
            queue_size: Maximum number of requests waiting in the queue.

        Raises:
            ValueError: If either size is below one or the delay is negative.
        """
        if batch_size < 1 or batch_delay < 0 or queue_size < 1:
            raise ValueError("Invalid writer batch or queue size")
        self._engine = engine
        self._batch_size = batch_size
        self._batch_delay = batch_delay
        self._requests: Queue[_Request | None] = Queue(maxsize=queue_size)
        self._lock = Lock()
        self._closed = False
        self._thread = Thread(target=self._run, name="maskyard-writer", daemon=True)
        self._thread.start()

    def submit_cell(self, cell: CellWrite, *, flush: bool = False) -> Future[int]:
        """Queue a snapshot for the writer thread.

        Args:
            cell: Session-independent snapshot to persist.
            flush: Whether to end the current batch at this request.

        Returns:
            A future that resolves to the cell ID after its transaction commits.

        Raises:
            RuntimeError: If the writer has been shut down.
        """
        future: Future[int] = Future()
        with self._lock:
            if self._closed:
                raise RuntimeError("Cell writer is closed")
            self._requests.put(_Request(cell, future, flush))
        return future

    def shutdown(self) -> None:
        """Commit queued requests and stop the writer thread."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._requests.put(None)
        self._thread.join()

    def _run(self) -> None:
        """Drain the queue into batches using one session on the writer thread."""
        with Session(self._engine, expire_on_commit=False) as session:
            while True:
                first = self._requests.get()
                if first is None:
                    return
                batch = [first]
                deadline = monotonic() + self._batch_delay
                closing = False
                while len(batch) < self._batch_size and not batch[-1].flush:
                    try:
                        next_request = self._requests.get(
                            timeout=max(0, deadline - monotonic())
                        )
                    except Empty:
                        break
                    if next_request is None:
                        closing = True
                        break
                    batch.append(next_request)
                self._commit_batch(session, batch)
                if closing:
                    return

    def _commit_batch(self, session: Session, batch: list[_Request]) -> None:
        """Commit active requests together and resolve their futures."""
        active = [
            request
            for request in batch
            if request.future.set_running_or_notify_cancel()
        ]
        if not active:
            return
        try:
            cells: list[Cell] = []
            for request in active:
                cell = self._make_cell(session, request.cell, {})
                session.add(cell)
                cells.append(cell)
            session.flush()
            ids = [self._cell_id(cell) for cell in cells]
            session.commit()
            for request, cell_id in zip(active, ids, strict=True):
                request.future.set_result(cell_id)
        except BaseException as error:
            session.rollback()
            for request in active:
                if not request.future.done():
                    request.future.set_exception(error)
        finally:
            session.expunge_all()

    @staticmethod
    def _cell_id(cell: Cell) -> int:
        """Read a flushed cell's ID and fail if the flush did not assign one."""
        if cell.id is None:
            raise RuntimeError("Flushed cell has no ID")
        return cell.id

    def _make_cell(
        self, session: Session, data: CellWrite, seen: dict[int, Cell]
    ) -> Cell:
        """Rebuild a snapshot as ORM objects, reusing shared children."""
        identity = id(data)
        if identity in seen:
            return seen[identity]
        layout = kdb.Layout()
        layout.read_bytes(data.geometry)
        cell = Cell(
            name=data.name,
            pcell_factory_id=data.pcell_factory_id,
            hashkey=data.hashkey,
        )
        cell.geometry = Geometry(id=None, layout=layout)
        cell.info = CellInfo(id=None, data=deepcopy(data.info))
        cell.settings = CellSettings(id=None, data=deepcopy(data.settings))
        for spec in data.ports:
            transformation = PortTrans().process_result_value(
                spec.transformation, session.get_bind().dialect
            )
            cell.ports.append(
                CellPort(
                    name=spec.name,
                    cross_section_id=spec.cross_section_id,
                    transformation=transformation,
                )
            )
        seen[identity] = cell
        for spec in data.instances:
            child = (
                self._make_cell(session, spec.child, seen)
                if isinstance(spec.child, CellWrite)
                else session.get(Cell, spec.child)
            )
            if child is None:
                raise LookupError(f"Child cell {spec.child} does not exist")
            cell.instances.append(
                Instance(
                    name=spec.name,
                    cplx_trans=(
                        InstanceTrans().process_result_value(
                            spec.trans, session.get_bind().dialect
                        )
                        if spec.trans is not None
                        else kdb.ICplxTrans()
                    ),
                    a=(
                        Vector().process_result_value(
                            spec.a, session.get_bind().dialect
                        )
                        if spec.a is not None
                        else kdb.Vector()
                    ),
                    b=(
                        Vector().process_result_value(
                            spec.b, session.get_bind().dialect
                        )
                        if spec.b is not None
                        else kdb.Vector()
                    ),
                    na=spec.na,
                    nb=spec.nb,
                    virtual=spec.virtual,
                    cell=child,
                )
            )
        return cell


_writer_lock = Lock()
_writer: CellWriter | None = None


def get_writer() -> CellWriter:
    """Return the writer for the current database engine."""
    global _writer  # noqa: PLW0603
    with _writer_lock:
        if _writer is None or _writer._engine is not database.engine:
            if _writer is not None:
                _writer.shutdown()
            if not database._initialized.is_set():
                database.create_db_and_tables()
            _writer = CellWriter(database.engine)
        return _writer


def submit_cell(cell: Cell | CellWrite, *, flush: bool = False) -> Future[int]:
    """Queue a new cell for the process-wide writer.

    Args:
        cell: Unsaved cell to snapshot, or an existing snapshot to queue directly.
        flush: Whether to end the writer's batch at this request.

    Returns:
        A future that resolves to the committed cell ID.
    """
    data = CellWrite.from_cell(cell) if isinstance(cell, Cell) else cell
    return get_writer().submit_cell(data, flush=flush)


def shutdown_writer() -> None:
    """Drain and close the process-wide writer."""
    global _writer  # noqa: PLW0603
    with _writer_lock:
        if _writer is not None:
            _writer.shutdown()
            _writer = None


register(shutdown_writer)
