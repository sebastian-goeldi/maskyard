"""Minimal PCell decorator behavior."""

from inspect import signature

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import object_session
from sqlmodel import Session, select

import maskyard as oas
import maskyard.engine as database
from maskyard.models.cell import automatic_cell_name
from maskyard.serialization import CellNameError


def test_pcell_preserves_signature_and_commits_cell(
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database.create_db_and_tables()
    monkeypatch.setattr(database, "engine", test_engine)
    pdk = oas.Pdk(name="test")

    @pdk.pcell
    def component(width: int, *, label: str = "default") -> oas.Cell:
        return pdk.create_cell(name=f"{label}-{width}")

    assert str(signature(component)) == (
        "(width: int, *, label: str = 'default') -> maskyard.models.cell.Cell"
    )

    with database.session_context() as session:
        cell = component(5, label="test")
        assert cell.id is not None
        assert session.get(oas.Cell, cell.id) is cell
        cell_id = cell.id

    with Session(test_engine) as session:
        saved = session.exec(select(oas.Cell).where(oas.Cell.id == cell_id)).one()
        assert saved.name == "test-5"

    with database.session_context():
        assert component(5, label="test").id == cell_id


def test_same_pcell_name_in_two_pdks_has_separate_cache(
    test_engine: Engine,
) -> None:
    database.create_db_and_tables()
    first_pdk = oas.Pdk(name="first")
    second_pdk = oas.Pdk(name="second")

    @first_pdk.pcell
    def component(width: int) -> oas.Cell:
        return first_pdk.create_cell(name=f"first_{width}")

    first_component = component

    @second_pdk.pcell
    def component(width: int) -> oas.Cell:
        return second_pdk.create_cell(name=f"second_{width}")

    first = first_component(5)
    second = component(5)
    assert first.id != second.id
    assert first.pcell_id != second.pcell_id
    assert first.hashkey == second.hashkey


def test_pcell_creates_and_reuses_session(
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database.create_db_and_tables()
    monkeypatch.setattr(database, "engine", test_engine)
    pdk = oas.Pdk(name="test")
    sessions: list[Session] = []

    @pdk.pcell
    def component() -> oas.Cell:
        sessions.append(database.get_session())
        return pdk.create_cell(name="created")

    cell = component()
    session = database.get_session()
    assert sessions == [session]
    assert object_session(cell) is session

    assert cell.id is not None
    assert cell.name == "created"
    database.close_session()
    assert object_session(cell) is None

    with Session(test_engine) as session:
        saved = session.get(oas.Cell, cell.id)
        assert saved is not None
        assert saved.name == "created"


def test_nested_pcells_reuse_cached_session(
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database.create_db_and_tables()
    monkeypatch.setattr(database, "engine", test_engine)
    pdk = oas.Pdk(name="test")
    sessions: list[Session] = []

    @pdk.pcell
    def child() -> oas.Cell:
        sessions.append(database.get_session())
        return pdk.create_cell(name="child")

    @pdk.pcell
    def parent() -> oas.Cell:
        sessions.append(database.get_session())
        child()
        return pdk.create_cell(name="parent")

    parent()
    assert sessions == [database.get_session(), database.get_session()]


def test_configured_pcell_decorator_normalizes_calls_and_reloads_cell(
    test_engine: Engine,
) -> None:
    database.create_db_and_tables()
    pdk = oas.Pdk(name="test")
    calls = 0

    @pdk.pcell(drop_params=("unused",))
    def component(width: int, *, label: str = "default") -> oas.Cell:
        nonlocal calls
        calls += 1
        return pdk.create_cell()

    with database.session_context():
        first = component(5)
        assert first.name == "component_W5_Ldefault"
        assert component(width=5, label="default") is first
        cell_id = first.id

    with database.session_context() as second_session:
        restored = component(5)
        assert restored is second_session.get(oas.Cell, cell_id)
        assert restored is not first
        assert calls == 1


def test_pcell_auto_name_is_single_use_and_restored_on_error(
    test_engine: Engine,
) -> None:
    database.create_db_and_tables()
    pdk = oas.Pdk(name="test")

    @pdk.pcell()
    def component() -> oas.Cell:
        pdk.create_cell()
        with pytest.raises(CellNameError):
            pdk.create_cell()
        raise RuntimeError("PCell failed")

    with pytest.raises(RuntimeError, match="PCell failed"):
        component()
    assert automatic_cell_name.get() is None


def test_pcell_preserves_positional_only_and_original_list(
    test_engine: Engine,
) -> None:
    database.create_db_and_tables()
    pdk = oas.Pdk(name="test")
    seen: list[list[int]] = []

    @pdk.pcell
    def component(values: list[int], /) -> oas.Cell:
        seen.append(values)
        return pdk.create_cell()

    with database.session_context():
        first = component([1, 2])
        assert component([1, 2]) is first
    assert seen == [[1, 2]]
    assert type(seen[0]) is list


@pytest.mark.parametrize("use_writer", [False, True])
def test_pcell_persists_json_settings(test_engine: Engine, use_writer: bool) -> None:
    pdk = oas.get_or_create_pdk("settings")
    layer = oas.kdb.LayerInfo(1, 0)

    @pdk.pcell(use_writer=use_writer, drop_params=("layer",))
    def component(widths: dict[str, list[float]], layer: oas.kdb.LayerInfo) -> oas.Cell:
        cell = pdk.create_cell(persist=not use_writer)
        cell.shapes(layer).insert(oas.kdb.Box(0, 0, round(widths["core"][0]), 1))
        cell.info["labels"] = {"core": ["strip", None]}
        return cell

    cell_id = component({"core": [3.0, 4.5]}, layer).id
    assert cell_id is not None
    with Session(test_engine) as session:
        saved = session.get(oas.Cell, cell_id)
        assert saved is not None
        assert saved.pcell is not None
        assert saved.pcell.name == "component"
        assert saved.info["labels"] == {"core": ["strip", None]}
        widths = saved.settings["widths"]
        assert widths == {"core": [3.0, 4.5]}
        assert isinstance(widths, dict)
        assert isinstance(widths["core"], list)
        assert isinstance(widths["core"][0], float)
        assert saved.settings["layer"] == f"!#LayerInfo {layer}"
        assert saved.bbox().width() == 3


def test_nested_pcell_restores_outer_automatic_name(test_engine: Engine) -> None:
    database.create_db_and_tables()
    pdk = oas.Pdk(name="test")

    @pdk.pcell
    def child() -> oas.Cell:
        return pdk.create_cell()

    @pdk.pcell
    def parent() -> oas.Cell:
        assert child().name == "child"
        return pdk.create_cell()

    with database.session_context():
        assert parent().name == "parent"
