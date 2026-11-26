"""Regression tests for in-place layout transforms."""

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from maskyard import Cell, CellPort, InstancePort, Layer, SymmetricCrossSection, kdb
from maskyard.engine import create_db_and_tables
from maskyard.models.cell import create_cell
from maskyard.models.enclosure import get_or_create_enclosure


def test_port_transform_methods(test_engine: Engine) -> None:
    create_db_and_tables(dbu=0.002)
    port = CellPort(name="p", transformation=kdb.Trans(3, 4))

    assert port.move((1, 2), (2, 4)).movex(3).movey(7, 2) is port
    assert port.center == (7, 1)
    port.rotate(1, center=(2, 1)).mirror_x(4).mirror_y(3)
    assert port.center == (6, 0)
    port.mirror((0, 4), (4, 8))
    assert port.dcenter == pytest.approx((-0.008, 0.020))
    assert port.mirrored
    port.mirrored = False
    assert port.mirrored is False

    port.dmove((0.002, 0.002), (0.005, 0.003)).dmovex(0.001).dmovey(0.002, 0.006)
    assert port.dcenter == pytest.approx((-0.004, 0.025))
    port.drotate(90, center=(0.001, 0.025))
    assert port.dcenter == pytest.approx((0.001, 0.020))
    port.dmirror_x(0.003).dmirror_y(0.005).dmirror()
    assert port.dcenter == pytest.approx((-0.005, -0.010))

    with pytest.raises(ValueError, match="two distinct points"):
        port.mirror((0, 0), (0, 0))
    with pytest.raises(ValueError, match="two distinct points"):
        port.dmirror((0, 0), (0, 0))


def test_instance_transform_moves_array_in_parent_coordinates(
    test_engine: Engine,
) -> None:
    create_db_and_tables(dbu=0.002)
    child = create_cell("child", persist=False)
    child.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 2, 3))
    parent = Cell(name="parent")
    instance = parent.add_instance(
        child,
        a=kdb.Vector(10, 0),
        b=kdb.Vector(0, 5),
        na=2,
        nb=3,
        trans=kdb.Trans(4, 6),
    )
    assert instance.mirrored is False
    assert instance.rotate(1).dmirror_x(0.002).move((3, 2)) is instance
    assert instance.mirrored
    assert instance.cplx_trans.disp == kdb.Vector(11, 6)
    assert instance.a == kdb.Vector(0, 10)
    assert instance.b == kdb.Vector(5, 0)
    assert instance.bbox() == kdb.Box(11, 6, 24, 18)
    assert child.bbox() == kdb.Box(0, 0, 2, 3)

    port = CellPort(name="p", transformation=kdb.Trans(1, 2))
    derived = InstancePort(instance=instance, cell_port=port, ia=1, ib=2)
    assert derived.center == (23, 17)
    assert derived.mirror
    assert getattr(derived, "move", None) is None
    assert getattr(derived, "transform", None) is None
    port.dmove((0.001, 0))
    assert derived.dcenter == pytest.approx((0.046, 0.035))

    expected = instance.cplx_trans.dup()
    expected.mirror = False
    instance.mirrored = False
    assert instance.mirrored is False
    assert instance.cplx_trans == expected
    assert instance.a == kdb.Vector(0, 10)
    assert instance.b == kdb.Vector(5, 0)


def test_cell_transform_persists_shapes_ports_and_placements(
    test_engine: Engine,
) -> None:
    create_db_and_tables(dbu=0.002)
    with Session(test_engine) as session:
        layer = Layer(layer=1, datatype=0)
        enclosure = get_or_create_enclosure(
            session, main_layer=layer, definition={}, name="example"
        )
        cross_section = SymmetricCrossSection(
            enclosure=enclosure, canonical_name="example", width=10, layer=layer
        )
        top = create_cell("top", persist=False)
        top.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 2, 3))
        top.attach_port("p", cross_section, trans=kdb.Trans(1, 2))
        top.add_instance(create_cell("child", persist=False), trans=kdb.Trans(10, 4))
        session.add(top)
        session.commit()

        assert top.mirror_y(5).dmove((0.004, -0.002)) is top
        session.commit()

    with Session(test_engine) as session:
        top = session.exec(select(Cell).where(Cell.name == "top")).one()
        assert top.bbox() == kdb.Box(2, 6, 4, 9)
        assert top.ports[0].dcenter == pytest.approx((0.006, 0.014))
        assert top.instances[0].cplx_trans.disp == kdb.Vector(12, 5)
        assert top.instances[0].mirrored

        top.movex(100)
        assert top.bbox() == kdb.Box(102, 6, 104, 9)
        session.rollback()
        assert top.bbox() == kdb.Box(2, 6, 4, 9)
