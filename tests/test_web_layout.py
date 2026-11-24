"""Layout manifests use computed hierarchy bounds."""

from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from maskyard import kdb
from maskyard.engine import create_db_and_tables
from maskyard.models.cell import create_cell

pytest.importorskip("fastapi")

from maskyard.web import render_cache
from maskyard.web.app import cell_layout_geometry, cell_layout_manifest


def test_manifest_uses_array_bounds_and_exposes_child_geometry(
    test_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(render_cache, "cache_dir", lambda: tmp_path / "cache")
    create_db_and_tables()
    root = create_cell("viewer_root", persist=False)
    child = create_cell("viewer_child", persist=False)
    child.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 200, 200))
    array = root.add_instance(
        child,
        trans=kdb.Trans(1000, 2000),
        a=kdb.Vector(400, 50),
        b=kdb.Vector(-50, 400),
    )
    array.na = 3
    array.nb = 2
    with Session(test_engine) as session:
        session.add_all((root, child))
        session.commit()
        root_id, child_id = root.id, child.id
        manifest = cell_layout_manifest(root_id)
        geometry = cell_layout_geometry(child_id)

    assert manifest["bounds"] == [950, 2000, 2000, 2700]
    assert manifest["cells"][str(child_id)]["bbox"] == [0, 0, 200, 200]
    assert manifest["cells"][str(root_id)]["instances"][0]["na"] == 3
    assert [layer["id"] for layer in geometry["layers"]] == ["1/0"]
