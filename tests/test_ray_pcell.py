"""Ray PCells return cached IDs from a shared SQLite database."""

from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

import maskyard as mask
import maskyard.engine as database

ray = pytest.importorskip("ray")


def test_ray_pcell_caches_refs_and_persists_cells(
    test_engine: Engine, tmp_path: Path
) -> None:
    def leaf(width: int, counter_path: str) -> mask.Cell:
        """Record a worker invocation and create geometry for the requested width."""
        with Path(counter_path).open("a") as counter:
            counter.write(f"{width}\n")
        cell = mask.get_or_create_pdk("ray_test").create_cell(f"leaf_{width}")
        cell.shapes(mask.kdb.LayerInfo(1, 0)).insert(mask.kdb.Box(0, 0, width, 10))
        return cell

    database.create_db_and_tables()
    pdk = mask.get_or_create_pdk("ray_test")
    counter = tmp_path / "calls.txt"
    remote = pdk.pcell(ray=True, drop_params=("counter_path",))(leaf)
    ray.init(num_cpus=2, include_dashboard=False, logging_level="ERROR")
    try:
        first = remote.remote(10, str(counter))
        assert remote.remote(width=10, counter_path=str(tmp_path / "unused")) is first
        second = remote.remote(20, str(counter))
        another_caller = pdk.pcell(ray=True, drop_params=("counter_path",))(leaf)
        duplicate = another_caller.remote(10, str(counter))
        first_id, second_id, duplicate_id = ray.get([first, second, duplicate])
        assert first_id != second_id
        assert duplicate_id == first_id
        loaded = remote.get_cell(first)
        assert loaded.id == first_id
        assert loaded is database.get_session().get(mask.Cell, first_id)
        assert sorted(counter.read_text().splitlines()) == ["10", "20"]
        assert ray.get(another_caller.remote(10, str(counter))) == first_id
        assert len(counter.read_text().splitlines()) == 2
        with Session(test_engine) as session:
            saved = session.get(mask.Cell, first_id)
            assert saved is not None
            assert saved.name == "leaf_10"
            path = tmp_path / "leaf.gds"
            saved.write(path)
            assert path.is_file()
    finally:
        ray.shutdown()


def test_failed_ray_pcell_can_be_resubmitted(
    test_engine: Engine, tmp_path: Path
) -> None:
    def flaky(flag_path: str) -> mask.Cell:
        """Fail the first invocation and create a cell when retried."""
        flag = Path(flag_path)
        if not flag.exists():
            flag.write_text("failed")
            raise ValueError("first attempt")
        return mask.get_or_create_pdk("ray_test").create_cell("flaky")

    database.create_db_and_tables()
    pdk = mask.get_or_create_pdk("ray_test")
    remote = pdk.pcell(ray=True)(flaky)
    ray.init(num_cpus=1, include_dashboard=False, logging_level="ERROR")
    try:
        flag = str(tmp_path / "flaky.flag")
        failed = remote.remote(flag)
        with pytest.raises(Exception, match="first attempt"):
            ray.get(failed)
        retried = remote.remote(flag)
        assert retried is not failed
        assert ray.get(retried) > 0
    finally:
        ray.shutdown()
