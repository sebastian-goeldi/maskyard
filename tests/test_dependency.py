from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as SASession
from sqlmodel import Session, col, select

from maskyard import Cell, Instance, Pdk
from maskyard.engine import get_context_session, session_context
from maskyard.models.cell import CellInfo, CellSettings, create_cell
from maskyard.models.dependency import Dependency, find_and_clean_changed_dependencies
from maskyard.models.geometry import Geometry
from maskyard.models.instance import InstanceInfo
from maskyard.models.pcell import PCell


@pytest.mark.parametrize("foreign_keys", [False, True])
def test_changed_dependency_evicts_generated_cells_and_ancestors(
    test_engine: Engine, tmp_path: Path, foreign_keys: bool
) -> None:
    source = tmp_path / "component.py"
    source.write_bytes(b"old")
    with test_engine.connect() as connection:
        if foreign_keys:
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
            connection.commit()
        with Session(connection) as session:
            dependency = Dependency(path=source, file_hash=sha256(b"old").hexdigest())
            pcell = PCell(name="component", dependency=dependency, pdk=Pdk(name="test"))
            first = create_cell("first", persist=False)
            second = create_cell("second", persist=False)
            first.pcell = second.pcell = pcell
            parent = create_cell("parent", persist=False)
            top = create_cell("top", persist=False)
            unrelated = create_cell("unrelated", persist=False)
            parent.add_instance(first).info = InstanceInfo(id=None)
            parent.add_instance(second)
            top.add_instance(parent)
            top.add_instance(unrelated)
            session.add(top)
            session.commit()
            unrelated_id = unrelated.id
            pcell_id = pcell.id

            find_and_clean_changed_dependencies(session)
            assert len(session.exec(select(Cell)).all()) == 5

            source.write_bytes(b"new")
            find_and_clean_changed_dependencies(session)
            session.rollback()
            assert len(session.exec(select(Cell)).all()) == 5
            assert dependency.file_hash == sha256(b"old").hexdigest()

            find_and_clean_changed_dependencies(session)
            session.commit()
            find_and_clean_changed_dependencies(session)
            assert session.exec(select(col(Cell.id))).all() == [unrelated_id]
            assert session.exec(select(col(Geometry.id))).all() == [unrelated_id]
            assert session.exec(select(col(CellInfo.id))).all() == [unrelated_id]
            assert session.exec(select(col(CellSettings.id))).all() == [unrelated_id]
            assert session.exec(select(col(Instance.id))).all() == []
            assert session.exec(select(col(InstanceInfo.id))).all() == []
            assert session.get(PCell, pcell_id) is pcell
            assert dependency.file_hash == sha256(b"new").hexdigest()


@pytest.mark.parametrize("use_context", [False, True])
def test_session_delete_cascades_to_ancestors(
    test_engine: Engine, use_context: bool
) -> None:
    session_manager = session_context() if use_context else SASession(test_engine)
    with session_manager as session:
        leaf = Cell(name="leaf")
        parent = Cell(name="parent")
        top = Cell(name="top")
        sibling = Cell(name="sibling")
        parent.add_instance(leaf).info = InstanceInfo(id=None)
        top.add_instance(parent)
        top.add_instance(sibling)
        session.add(top)
        session.commit()

        attached_session = get_context_session(leaf)
        assert attached_session is session
        attached_session.delete(leaf)
        assert session.scalars(select(Cell)).all() == [sibling]
        session.rollback()
        assert len(session.scalars(select(Cell)).all()) == 4

        attached_session.delete(leaf)
        session.commit()

    with Session(test_engine) as session:
        assert session.exec(select(col(Cell.name))).all() == ["sibling"]
        assert session.exec(select(Instance)).all() == []
        assert session.exec(select(InstanceInfo)).all() == []
