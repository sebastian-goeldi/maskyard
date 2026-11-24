"""Global layer identity and canonical enclosure persistence."""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from maskyard.engine import create_db_and_tables
from maskyard.models.enclosure import (
    Enclosure,
    EnclosureDefinition,
    canonical_definition,
    get_or_create_enclosure,
)
from maskyard.models.layer import Layer


def test_canonical_definition_deduplicates_and_orders() -> None:
    definition: EnclosureDefinition = {
        "bands": [
            {"layer": 3, "datatype": 0, "d_min": 100, "d_max": 400},
            {"layer": 2, "datatype": 0, "d_min": None, "d_max": 500},
            {"layer": 3, "datatype": 0, "d_min": 100, "d_max": 400},
        ],
        "bboxes": [
            {"layer": 4, "datatype": 0, "offset": 200},
            {"layer": 2, "datatype": 0, "offset": 100},
            {"layer": 4, "datatype": 0, "offset": 200},
        ],
    }

    assert canonical_definition(definition) == {
        "bands": [
            {"layer": 2, "datatype": 0, "d_min": None, "d_max": 500},
            {"layer": 3, "datatype": 0, "d_min": 100, "d_max": 400},
        ],
        "bboxes": [
            {"layer": 2, "datatype": 0, "offset": 100},
            {"layer": 4, "datatype": 0, "offset": 200},
        ],
    }


def test_enclosure_reuses_canonical_geometry(test_engine: Engine) -> None:
    create_db_and_tables()
    definition: EnclosureDefinition = {
        "bands": [
            {"layer": 3, "datatype": 0, "d_min": 100, "d_max": 400},
            {"layer": 2, "datatype": 0, "d_min": None, "d_max": 500},
        ],
        "bboxes": [{"layer": 4, "datatype": 0, "offset": 200}],
    }
    with Session(test_engine) as session:
        layers = [Layer(layer=number, datatype=0) for number in range(1, 5)]
        session.add_all(layers)
        session.flush()
        first = get_or_create_enclosure(
            session, main_layer=layers[0], definition=definition
        )
        reversed_definition: EnclosureDefinition = {
            "bands": [*reversed(definition["bands"]), definition["bands"][0]],
            "bboxes": definition["bboxes"] * 2,
        }
        second = get_or_create_enclosure(
            session,
            main_layer=layers[0],
            definition=reversed_definition,
            name="WG",
        )
        assert first is second
        assert second.name == "WG"
        session.commit()

    with Session(test_engine) as session:
        stored = session.exec(select(Enclosure)).all()
        assert len(stored) == 1
        assert stored[0].definition == canonical_definition(definition)
        raw = (
            session.connection()
            .execute(text("SELECT definition FROM enclosure"))
            .one()[0]
        )
        assert raw == (
            '{"bands":[{"d_max":500,"d_min":null,"datatype":0,"layer":2},'
            '{"d_max":400,"d_min":100,"datatype":0,"layer":3}],'
            '"bboxes":[{"datatype":0,"layer":4,"offset":200}]}'
        )


def test_database_rejects_duplicate_geometry(test_engine: Engine) -> None:
    create_db_and_tables()
    with Session(test_engine) as session:
        layer = Layer(layer=1, datatype=0)
        session.add(layer)
        session.flush()
        assert layer.id is not None
        definition = {"bands": [], "bboxes": []}
        session.add(Enclosure(main_layer_id=layer.id, definition=definition))
        session.commit()
        session.add(Enclosure(main_layer_id=layer.id, definition=definition))
        with pytest.raises(IntegrityError):
            session.commit()


def test_insertion_validates_auxiliary_layers(test_engine: Engine) -> None:
    create_db_and_tables()
    with Session(test_engine) as session:
        layer = Layer(layer=1, datatype=0)
        session.add(layer)
        session.flush()
        with pytest.raises(ValueError, match="unknown layer"):
            get_or_create_enclosure(
                session,
                main_layer=layer,
                definition={
                    "bands": [{"layer": 99, "datatype": 0, "d_min": None, "d_max": 10}],
                    "bboxes": [],
                },
            )


def test_enclosure_stays_pending_until_caller_commits(test_engine: Engine) -> None:
    create_db_and_tables()
    with Session(test_engine) as setup:
        layer = Layer(layer=1, datatype=0)
        setup.add(layer)
        setup.commit()
        assert layer.id is not None
        layer_id = layer.id

    with Session(test_engine) as session:
        main_layer = session.get_one(Layer, layer_id)
        enclosure = get_or_create_enclosure(
            session,
            main_layer=main_layer,
            definition={"bands": [], "bboxes": []},
        )
        assert enclosure.id is None
        assert enclosure in session.new
        assert (
            get_or_create_enclosure(
                session,
                main_layer=main_layer,
                definition={"bands": [], "bboxes": []},
            )
            is enclosure
        )

        # A second connection can write while this session has staged the enclosure.
        with Session(test_engine) as other_session:
            other_session.add(Layer(layer=2, datatype=0))
            other_session.commit()

        assert enclosure.id is None
        session.commit()
        assert enclosure.id is not None


def test_new_layers_and_enclosure_can_be_staged_together(test_engine: Engine) -> None:
    create_db_and_tables()
    with Session(test_engine) as session:
        main_layer = Layer(layer=1, datatype=0)
        auxiliary_layer = Layer(layer=2, datatype=0)
        session.add(auxiliary_layer)
        enclosure = get_or_create_enclosure(
            session,
            main_layer=main_layer,
            definition={
                "bands": [{"layer": 2, "datatype": 0, "d_min": None, "d_max": 100}],
                "bboxes": [],
            },
        )
        assert main_layer.id is None
        assert auxiliary_layer.id is None
        assert enclosure.id is None

        with Session(test_engine) as other_session:
            other_session.add(Layer(layer=3, datatype=0))
            other_session.commit()

        session.commit()
        assert main_layer.id is not None
        assert auxiliary_layer.id is not None
        assert enclosure.main_layer_id == main_layer.id


def test_layer_number_is_globally_unique(test_engine: Engine) -> None:
    create_db_and_tables()
    with Session(test_engine) as session:
        session.add(Layer(layer=1, datatype=0, name="WG"))
        session.commit()
        session.add(Layer(layer=1, datatype=0, name="OTHER"))
        with pytest.raises(IntegrityError):
            session.commit()
