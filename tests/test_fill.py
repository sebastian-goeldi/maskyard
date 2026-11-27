"""Tiled fill through MaskYard cells and direct KLayout geometry."""

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from maskyard import Cell, kdb
from maskyard.engine import create_db_and_tables
from maskyard.models.cell import create_cell


def test_fill_unsaved_cells_commits_compact_unnamed_arrays(test_engine: Engine) -> None:
    create_db_and_tables()
    target = create_cell("target", persist=False)
    pattern = create_cell("pattern", persist=False)
    pattern.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 10, 10))
    commits = []
    event.listen(test_engine, "commit", lambda _connection: commits.append(None))

    target.fill(
        pattern,
        fill_regions=[(kdb.Region(kdb.Box(0, 0, 100, 100)), 0)],
        x_space=10,
        y_space=10,
    )

    assert len(commits) == 2  # First save the cells, then save all fill arrays.
    assert target.id is not None
    assert pattern.id is not None
    assert target.instances
    assert all(instance.name is None for instance in target.instances)
    assert (
        sum(max(instance.na, 1) * max(instance.nb, 1) for instance in target.instances)
        == 25
    )
    assert target.bbox() == kdb.Box(0, 0, 90, 90)

    with Session(test_engine) as session:
        saved = session.exec(select(Cell).where(Cell.id == target.id)).one()
        assert len(saved.instances) == len(target.instances)
        assert all(instance.cell_id == pattern.id for instance in saved.instances)
        assert saved.bbox() == target.bbox()


def test_fill_reads_descendant_layer_and_excludes_region(test_engine: Engine) -> None:
    create_db_and_tables()
    target = create_cell("target", persist=False)
    child = create_cell("child", persist=False)
    pattern = create_cell("pattern", persist=False)
    child.shapes(kdb.LayerInfo(2, 0)).insert(kdb.Box(0, 0, 100, 100))
    pattern.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 10, 10))
    target.add_instance(child, trans=kdb.Trans(100, 0))
    with Session(test_engine) as session:
        session.add_all((target, child, pattern))
        session.commit()
        target.fill(
            pattern,
            fill_layers=[(kdb.LayerInfo(2, 0), 0)],
            exclude_regions=[(kdb.Region(kdb.Box(140, 0, 160, 100)), 0)],
            x_space=10,
            y_space=10,
            tile_size=(40, 40),
        )
        positions = {
            (
                instance.cplx_trans.disp.x + ia * instance.a.x + ib * instance.b.x,
                instance.cplx_trans.disp.y + ia * instance.a.y + ib * instance.b.y,
            )
            for instance in target.instances
            if instance.cell_id == pattern.id
            for ia in range(max(instance.na, 1))
            for ib in range(max(instance.nb, 1))
        }
        assert len(positions) == 20
        assert all(100 <= x <= 180 and 0 <= y <= 80 for x, y in positions)
        assert all(x != 140 for x, _ in positions)
        assert target.bbox() == kdb.Box(100, 0, 200, 100)


@pytest.mark.parametrize("dbu", [0.001, 0.002])
def test_fill_defaults_to_bounds_and_commits_once(
    test_engine: Engine, dbu: float
) -> None:
    create_db_and_tables(dbu=dbu)
    target = create_cell("target", persist=False)
    pattern = create_cell("pattern", persist=False)
    target.shapes(kdb.LayerInfo(2, 0)).insert(kdb.Box(0, 0, 100, 100))
    pattern.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 10, 10))
    with Session(test_engine) as session:
        session.add_all((target, pattern))
        session.commit()
        commits = []
        event.listen(test_engine, "commit", lambda _connection: commits.append(None))
        target.fill(pattern, x_space=10, y_space=10)
        assert len(commits) == 1
        assert (
            sum(
                max(instance.na, 1) * max(instance.nb, 1)
                for instance in target.instances
            )
            == 25
        )
        assert all(instance.name is None for instance in target.instances)
        assert target.bbox() == kdb.Box(0, 0, 100, 100)


def test_multi_fill_respects_exclusion_layer(test_engine: Engine) -> None:
    create_db_and_tables()
    target = create_cell("target", persist=False)
    pattern = create_cell("pattern", persist=False)
    target.shapes(kdb.LayerInfo(2, 0)).insert(kdb.Box(0, 0, 50, 50))
    target.shapes(kdb.LayerInfo(3, 0)).insert(kdb.Box(20, 0, 30, 50))
    pattern.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 10, 10))

    target.fill(
        pattern,
        fill_layers=[(kdb.LayerInfo(2, 0), 0)],
        exclude_layers=[(kdb.LayerInfo(3, 0), 0)],
        x_space=10,
        y_space=10,
        tile_size=(30, 30),
        multi=True,
    )

    assert target.instances
    for instance in target.instances:
        assert instance.name is None
        for ia in range(max(instance.na, 1)):
            for ib in range(max(instance.nb, 1)):
                x = instance.cplx_trans.disp.x + ia * instance.a.x + ib * instance.b.x
                y = instance.cplx_trans.disp.y + ia * instance.a.y + ib * instance.b.y
                assert 0 <= x <= 40
                assert 0 <= y <= 40
                assert x + 10 <= 20 or x >= 30


def test_fill_rejects_empty_default_bounds_and_cycles(test_engine: Engine) -> None:
    create_db_and_tables()
    target = create_cell("target", persist=False)
    pattern = create_cell("pattern", persist=False)
    pattern.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 10, 10))
    with pytest.raises(ValueError, match="empty bounds"):
        target.fill(pattern)
    with pytest.raises(ValueError, match="cannot fill itself"):
        target.fill(target)
