"""Run documentation examples against disposable SQLite databases."""

import csv
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]


def run(workdir: Path, database: str, *arguments: str) -> None:
    subprocess.run(  # noqa: S603
        [sys.executable, *arguments],
        cwd=workdir,
        env={
            **os.environ,
            "MASKYARD_DATABASE_URL": f"sqlite:///{workdir / database}",
            "MASKYARD_LAYOUT_CACHE_DIR": str(workdir / "render-cache"),
        },
        check=True,
    )


def check() -> None:
    with TemporaryDirectory(prefix="maskyard-docs-") as directory:
        workdir = Path(directory)
        for example in ("quickstart", "batched_writes"):
            run(workdir, f"{example}.db", str(ROOT / "docs/examples" / f"{example}.py"))
        run(
            workdir,
            "chip.db",
            str(ROOT / "examples/chip_30_mzis.py"),
            "--output",
            "chip.gds",
        )
        with (workdir / "chip.csv").open(newline="", encoding="utf-8") as table:
            assert len(list(csv.DictReader(table))) == 30
        run(
            workdir,
            "chip.db",
            "-c",
            """
from fastapi.testclient import TestClient
from sqlmodel import select

from maskyard import Cell, kdb
from maskyard.engine import session_context
from maskyard.web import app

layout = kdb.Layout()
layout.read("chip.gds")
chip = layout.cell("chip")
fill = layout.cell("FILL_WG")
assert fill is not None and fill.bbox() == kdb.Box(0, 0, 200, 200)
assert any(instance.cell_index == fill.cell_index() for instance in chip.each_inst())

with session_context() as session:
    cell_id = session.exec(select(Cell.id).where(Cell.name == "chip")).one()

with TestClient(app) as client:
    assert client.get(f"/cells/{cell_id}").status_code == 200
    manifest = client.get(f"/cells/{cell_id}/layout")
    manifest.raise_for_status()
    assert str(cell_id) in manifest.json()["cells"]
    client.get(f"/cells/{cell_id}/layout/geometry").raise_for_status()
""",
        )


if __name__ == "__main__":
    check()
