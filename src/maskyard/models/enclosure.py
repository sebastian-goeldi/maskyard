"""Persist canonical layer enclosures in global database units."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import TYPE_CHECKING, NotRequired, TypedDict

from sqlalchemy import CheckConstraint, Column, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, Relationship, Session, SQLModel, select

from .layer import Layer

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect

    from .cross_section import SymmetricCrossSection


class Band(TypedDict):
    layer: int
    datatype: int
    d_min: NotRequired[int | None]
    d_max: int


class BBoxSection(TypedDict):
    layer: int
    datatype: int
    offset: int


class EnclosureDefinition(TypedDict, total=False):
    bands: list[Band]
    bboxes: list[BBoxSection]


def _integer(value: object, field: str) -> int:
    """Require a plain integer for an enclosure field."""
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer DBU value")
    return value


def canonical_definition(value: EnclosureDefinition) -> EnclosureDefinition:
    """Validate, deduplicate, and sort an enclosure definition.

    Args:
        value: Mapping of enclosure bands and bounding-box expansions.

    Returns:
        The canonical definition suitable for comparison and storage.

    Raises:
        ValueError: If the definition contains unsupported keys or invalid values.
    """
    if set(value) != {"bands", "bboxes"}:
        raise ValueError("definition must contain bands and bboxes")
    raw_bands = value["bands"]
    raw_bbox = value["bboxes"]
    if not isinstance(raw_bands, list) or not isinstance(raw_bbox, list):
        raise TypeError("bands and bboxes must be lists")

    bands: set[tuple[int, int, int | None, int]] = set()
    for item in raw_bands:
        if not isinstance(item, dict) or set(item) != {
            "layer",
            "datatype",
            "d_min",
            "d_max",
        }:
            raise ValueError("each band needs layer, datatype, d_min, and d_max")
        layer = _integer(item["layer"], "layer")
        datatype = _integer(item["datatype"], "datatype")
        d_min_raw = item["d_min"]
        d_min = None if d_min_raw is None else _integer(d_min_raw, "d_min")
        d_max = _integer(item["d_max"], "d_max")
        if d_min is not None and d_min >= d_max:
            raise ValueError("d_min must be less than d_max")
        bands.add((layer, datatype, d_min, d_max))

    ordered_bands: list[Band] = [
        Band(layer=layer, datatype=datatype, d_min=d_min, d_max=d_max)
        for layer, datatype, d_min, d_max in sorted(
            bands,
            key=lambda band: (
                band[0],
                band[1],
                band[2] is not None,
                0 if band[2] is None else band[2],
                band[3],
            ),
        )
    ]

    bbox_by_layer: dict[tuple[int, int], int] = {}
    for item in raw_bbox:
        if not isinstance(item, dict) or set(item) != {
            "layer",
            "datatype",
            "offset",
        }:
            raise ValueError("each bbox section needs layer, datatype, and offset")
        key = (
            _integer(item["layer"], "layer"),
            _integer(item["datatype"], "datatype"),
        )
        offset = _integer(item["offset"], "offset")
        if key in bbox_by_layer and bbox_by_layer[key] != offset:
            raise ValueError(f"conflicting bbox offsets for layer {key}")
        bbox_by_layer[key] = offset

    ordered_bbox: list[BBoxSection] = [
        BBoxSection(layer=layer, datatype=datatype, offset=offset)
        for (layer, datatype), offset in sorted(bbox_by_layer.items())
    ]
    return EnclosureDefinition(bands=ordered_bands, bboxes=ordered_bbox)


class CanonicalEnclosureJSON(TypeDecorator[EnclosureDefinition]):
    """Store a canonical JSON document as text for database uniqueness."""

    impl = Text
    cache_ok = True

    def process_bind_param(
        self, value: EnclosureDefinition | None, dialect: Dialect
    ) -> str | None:
        """Store the canonical enclosure definition as sorted JSON text."""
        if value is None:
            return None
        return json.dumps(
            canonical_definition(value), sort_keys=True, separators=(",", ":")
        )

    def process_result_value(
        self, value: str | None, dialect: Dialect
    ) -> EnclosureDefinition | None:
        """Read an enclosure definition from its stored JSON text."""
        if value is None:
            return None
        return canonical_definition(json.loads(value))


class Enclosure(SQLModel, table=True):
    """An enclosure whose identity is its main layer and canonical definition."""

    __table_args__ = (
        UniqueConstraint("main_layer_id", "definition"),
        UniqueConstraint("name"),
        CheckConstraint("json_valid(definition)"),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str | None = None
    main_layer_id: int | None = Field(
        default=None, foreign_key="layer.id", nullable=True
    )
    main_layer: Layer = Relationship()
    definition: EnclosureDefinition = Field(
        default_factory=dict, sa_column=Column(CanonicalEnclosureJSON(), nullable=False)
    )
    cross_sections: list[SymmetricCrossSection] = Relationship(
        sa_relationship=relationship(
            "SymmetricCrossSection", back_populates="enclosure"
        )
    )


def get_or_create_enclosure(
    session: Session,
    *,
    main_layer: Layer,
    definition: EnclosureDefinition,
    name: str | None = None,
) -> Enclosure:
    """Find or stage an enclosure by main layer and canonical geometry.

    The caller controls when pending changes are flushed or committed.

    Args:
        session: Session used to look up and stage layers and enclosures.
        main_layer: Layer around which the enclosure is defined.
        definition: Bands and bounding-box expansions that describe the enclosure.
        name: Optional unique name to associate with the geometry.

    Returns:
        A persisted or pending enclosure with matching geometry.

    Raises:
        ValueError: If the definition is invalid, a referenced layer is missing, or the
            name conflicts with existing geometry.
    """
    definition = deepcopy(definition)
    definition.setdefault("bands", [])
    definition.setdefault("bboxes", [])
    canonical = canonical_definition(definition)
    layer_pairs = {
        (item["layer"], item["datatype"])
        for item in (*canonical["bands"], *canonical["bboxes"])
    }
    with session.no_autoflush:
        if main_layer.id is None:
            persisted = session.exec(
                select(Layer).where(
                    Layer.layer == main_layer.layer,
                    Layer.datatype == main_layer.datatype,
                )
            ).first()
            if persisted is not None:
                if main_layer in session.new:
                    raise ValueError("pending main layer duplicates a persisted layer")
                main_layer = persisted
            else:
                session.add(main_layer)

        pending_layers = {
            (item.layer, item.datatype)
            for item in session.new
            if isinstance(item, Layer)
        }
        for layer_number, datatype in layer_pairs - pending_layers:
            exists = session.exec(
                select(Layer.id).where(
                    Layer.layer == layer_number, Layer.datatype == datatype
                )
            ).first()
            if exists is None:
                raise ValueError(f"unknown layer ({layer_number}, {datatype})")

        for candidate in (*session.new, *session.dirty):
            if not isinstance(candidate, Enclosure):
                continue
            if (
                candidate.main_layer is main_layer
                or (
                    main_layer.id is not None
                    and candidate.main_layer_id == main_layer.id
                )
            ) and canonical_definition(candidate.definition) == canonical:
                if name is not None and candidate.name not in (None, name):
                    raise ValueError("enclosure geometry already has a different name")
                if name is not None:
                    candidate.name = name
                return candidate
            if name is not None and candidate.name == name:
                raise ValueError("enclosure name already identifies different geometry")

        existing = (
            session.exec(
                select(Enclosure).where(
                    Enclosure.main_layer_id == main_layer.id,
                    Enclosure.definition == canonical,
                )
            ).first()
            if main_layer.id is not None
            else None
        )
        if existing is not None:
            if name is not None and existing.name not in (None, name):
                raise ValueError("enclosure geometry already has a different name")
            if name is not None and existing.name is None:
                existing.name = name
            return existing

        if name is not None:
            named = session.exec(
                select(Enclosure).where(Enclosure.name == name)
            ).first()
            if named is not None:
                raise ValueError("enclosure name already identifies different geometry")
    enclosure = Enclosure(name=name, main_layer=main_layer, definition=canonical)
    session.add(enclosure)
    return enclosure
