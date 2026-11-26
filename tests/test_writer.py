"""Batched cell writes through a dedicated database thread."""

from __future__ import annotations

from contextlib import suppress
from threading import get_ident
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event
from sqlmodel import Session, create_engine, select

import maskyard.engine as database
from maskyard import (
    Cell,
    CellWrite,
    CellWriter,
    Enclosure,
    InstanceWrite,
    Layer,
    Pdk,
    SymmetricCrossSection,
    kdb,
    submit_cell,
)
from maskyard.models.cell import create_cell
from maskyard.models.config import DatabaseConfig
from maskyard.writer import shutdown_writer

if TYPE_CHECKING:
    from collections.abc import Iterator
    from concurrent.futures import Future
    from pathlib import Path

    from sqlalchemy.engine import Engine


@pytest.fixture
def writer_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """Install an isolated writer database and drain the writer during teardown."""
    shutdown_writer()
    engine = create_engine(f"sqlite:///{tmp_path / 'writer.db'}")
    monkeypatch.setattr(database, "engine", engine)
    database._initialized.clear()
    with suppress(AttributeError):
        del database.settings.dbu
    database._register_engine(engine)
    database.create_db_and_tables()
    try:
        yield engine
    finally:
        shutdown_writer()
        engine.dispose()
        database._initialized.clear()
        with suppress(AttributeError):
            del database.settings.dbu


def test_writer_commits_a_batch_in_one_transaction(writer_engine: Engine) -> None:
    commits: list[int] = []
    event.listen(
        writer_engine, "commit", lambda _connection: commits.append(get_ident())
    )
    writer = CellWriter(writer_engine, batch_size=3, batch_delay=1)
    try:
        futures = [
            writer.submit_cell(
                CellWrite.from_cell(create_cell(f"cell_{i}", persist=False))
            )
            for i in range(3)
        ]
        ids = [future.result(timeout=3) for future in futures]
    finally:
        writer.shutdown()

    assert len(set(ids)) == 3
    assert len(commits) == 1
    assert commits[0] != get_ident()
    with Session(writer_engine) as session:
        assert len(session.exec(select(Cell)).all()) == 3


def test_detached_parent_and_children_save_as_one_graph(writer_engine: Engine) -> None:
    child = create_cell("child", persist=False)
    child.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 100, 100))
    parent = create_cell("parent", persist=False)
    parent.add_instance(child, name="first")
    parent.add_instance(child, name="second", trans=kdb.Trans(200, 0))

    assert submit_cell(parent).result(timeout=3) > 0

    with Session(writer_engine) as session:
        saved_parent = session.exec(select(Cell).where(Cell.name == "parent")).one()
        assert len(saved_parent.instances) == 2
        assert {instance.cell.name for instance in saved_parent.instances} == {"child"}
        assert len(session.exec(select(Cell)).all()) == 2
        assert (
            saved_parent.instances[0]
            .cell.geometry.kdb_cell.shapes(kdb.LayerInfo(1, 0))
            .size()
            == 1
        )


def test_writer_rolls_back_failed_batch_and_keeps_running(
    writer_engine: Engine,
) -> None:
    writer = CellWriter(writer_engine, batch_size=2, batch_delay=1)
    try:
        good = writer.submit_cell(
            CellWrite.from_cell(create_cell("good", persist=False))
        )
        bad = writer.submit_cell(
            CellWrite(
                name="bad",
                geometry=CellWrite.from_cell(
                    create_cell("source", persist=False)
                ).geometry,
                instances=(InstanceWrite(child=9999),),
            )
        )
        with pytest.raises(LookupError):
            good.result(timeout=3)
        with pytest.raises(LookupError):
            bad.result(timeout=3)
        recovered = writer.submit_cell(
            CellWrite.from_cell(create_cell("recovered", persist=False))
        )
        assert recovered.result(timeout=3) > 0
    finally:
        writer.shutdown()
    with Session(writer_engine) as session:
        assert [cell.name for cell in session.exec(select(Cell)).all()] == ["recovered"]


def test_submit_rejects_session_bound_cells(writer_engine: Engine) -> None:
    cell = create_cell("bound")
    with pytest.raises(ValueError, match="session-free"):
        submit_cell(cell)
    database.close_session()


def test_writer_shutdown_drains_requests(writer_engine: Engine) -> None:
    writer = CellWriter(writer_engine, batch_delay=1)
    future: Future[int] = writer.submit_cell(
        CellWrite.from_cell(create_cell("last", persist=False))
    )
    writer.shutdown()
    assert future.result(timeout=1) > 0
    with pytest.raises(RuntimeError, match="closed"):
        writer.submit_cell(CellWrite.from_cell(create_cell("late", persist=False)))


def test_flush_request_skips_batch_delay(writer_engine: Engine) -> None:
    writer = CellWriter(writer_engine, batch_delay=1)
    try:
        future = writer.submit_cell(
            CellWrite.from_cell(create_cell("urgent", persist=False)), flush=True
        )
        assert future.result(timeout=0.5) > 0
    finally:
        writer.shutdown()


def test_pcell_can_opt_into_writer(writer_engine: Engine) -> None:
    pdk = Pdk(name="writer_test")
    calls = 0

    @pdk.pcell(use_writer=True)
    def component(width: int) -> Cell:
        nonlocal calls
        calls += 1
        return pdk.create_cell(name=f"component_{width}", persist=False)

    first = component(7)
    assert first.id is not None
    assert component(7) is first
    assert calls == 1
    with Session(writer_engine) as session:
        saved = session.get(Cell, first.id)
        assert saved is not None
        assert saved.name == "component_7"


def test_writer_saves_ports_and_info(writer_engine: Engine) -> None:
    with Session(writer_engine) as session:
        layer = Layer(layer=1, datatype=0)
        enclosure = Enclosure(
            name="empty",
            definition={"bands": [], "bboxes": []},
        )
        cross_section = SymmetricCrossSection(
            canonical_name="strip", width=1000, layer=layer, enclosure=enclosure
        )
        session.add(cross_section)
        session.commit()
        cross_section_id = cross_section.id

    cell = create_cell("with_port", persist=False)
    cell.info.data = {"purpose": "test"}
    cell.attach_port("o1", cross_section, trans=kdb.Trans(100, 0))
    cell_id = submit_cell(cell).result(timeout=3)

    with Session(writer_engine) as session:
        saved = session.get(Cell, cell_id)
        assert saved is not None
        assert saved.info.data == {"purpose": "test"}
        assert len(saved.ports) == 1
        assert saved.ports[0].cross_section_id == cross_section_id
        assert saved.ports[0].trans.disp.x == 100


def test_existing_insert_still_commits_one_instance(writer_engine: Engine) -> None:
    parent = create_cell("parent")
    child = create_cell("child")
    instance = parent.insert(child, name="child_instance")
    assert instance.id is not None
    assert len(parent.instances) == 1
    with Session(writer_engine) as session:
        saved = session.get(Cell, parent.id)
        assert saved is not None
        assert [item.name for item in saved.instances] == ["child_instance"]
    database.close_session()


def test_parent_can_reference_a_committed_child(writer_engine: Engine) -> None:
    child_id = submit_cell(create_cell("child", persist=False)).result(timeout=3)
    with Session(writer_engine) as session:
        child = session.get(Cell, child_id)
        assert child is not None
        parent = create_cell("parent", persist=False)
        parent.add_instance(child, name="child_instance")
        parent_id = submit_cell(parent).result(timeout=3)
    with Session(writer_engine) as session:
        saved = session.get(Cell, parent_id)
        assert saved is not None
        assert saved.instances[0].cell_id == child_id


def test_writer_keeps_configured_dbu(writer_engine: Engine) -> None:
    with pytest.warns(RuntimeWarning, match="purging the cache"):
        database.create_db_and_tables(dbu=0.002)
    cell = create_cell("custom_dbu", persist=False)
    assert cell.geometry.layout.dbu == 0.002
    assert submit_cell(cell).result(timeout=3) > 0
    with Session(writer_engine) as session:
        config = session.get(DatabaseConfig, 1)
        assert config is not None
        assert config.dbu == 0.002
