"""Basic persistence and lookup behavior for cells."""

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

import maskyard.engine as database
from maskyard import Cell, CellPort, Layer, SymmetricCrossSection, kdb
from maskyard.engine import create_db_and_tables
from maskyard.models.enclosure import get_or_create_enclosure


def test_cell_can_be_saved_and_loaded(test_engine: Engine) -> None:
    create_db_and_tables()

    with Session(test_engine) as session:
        cell = Cell(name="top")
        session.add(cell)
        session.commit()
        cell_id = cell.id

    with Session(test_engine) as session:
        loaded = session.exec(select(Cell).where(Cell.id == cell_id)).one()
        assert loaded.name == "top"
        assert isinstance(loaded.bbox(), kdb.Box)
        assert loaded.bbox().empty()
        assert loaded.dbu == 0.001


def test_cell_uses_database_dbu(
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_db_and_tables(dbu=0.002)

    with Session(test_engine) as session:
        cell = Cell(name="top")
        session.add(cell)
        session.commit()
        assert cell.dbu == 0.002

    with Session(test_engine) as session:
        loaded = session.exec(select(Cell).where(Cell.name == "top")).one()
        assert loaded.dbu == 0.002

    monkeypatch.setattr(database, "engine", test_engine)
    with database.session_context():
        assert Cell(name="not-yet-added").dbu == 0.002


def test_port_conversion_uses_database_dbu(
    test_engine: Engine,
) -> None:
    create_db_and_tables(dbu=0.002)

    with Session(test_engine) as session:
        cell = Cell(name="top")
        session.add(cell)
        session.commit()
        layer = Layer(layer=1, datatype=0)
        session.add(layer)
        enclosure = get_or_create_enclosure(
            session, main_layer=layer, definition={}, name="EXAMPLE"
        )
        session.add(enclosure)
        cross_section = SymmetricCrossSection(
            enclosure=enclosure,
            canonical_name="abc",
            width=1000,
            layer=layer,
        )
        session.add(cross_section)
        port = CellPort(
            name="p",
            transformation=kdb.DCplxTrans(1, 0, False, 0.004, 0.006),
            cell=cell,
            cross_section=cross_section,
        )
        session.add(port)
        session.commit()

    with Session(test_engine) as session:
        loaded = session.exec(select(CellPort)).one()
        assert loaded.trans.disp == kdb.Vector(2, 3)


def test_cell_finds_layer_by_number_or_name(test_engine: Engine) -> None:
    create_db_and_tables()

    with Session(test_engine) as session:
        cell = Cell(name="top")
        session.add_all([cell, Layer(layer=1, datatype=0, name="metal")])
        session.commit()

        by_number = cell.layer(1, 0)
        by_name = cell.layer(name="metal")
        assert (by_number.layer, by_number.datatype, by_number.name) == (
            1,
            0,
            "metal",
        )
        assert (by_name.layer, by_name.datatype, by_name.name) == (
            1,
            0,
            "metal",
        )


def test_cell_layer_rejects_incomplete_or_missing_lookup(test_engine: Engine) -> None:
    create_db_and_tables()

    with Session(test_engine) as session:
        cell = Cell(name="top")
        session.add(cell)
        session.commit()

        with pytest.raises(ValueError, match="both layer and datatype"):
            cell.layer(layer=1)  # ty: ignore[no-matching-overload]
        with pytest.raises(LookupError, match="not found"):
            cell.layer(name="missing")
