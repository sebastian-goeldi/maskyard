from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .enclosure import Enclosure
    from .layer import Layer


class SymmetricCrossSection(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    name: str | None = None
    canonical_name: str

    width: int
    layer: Layer = Relationship()
    layer_id: int = Field(default=None, foreign_key="layer.id", ondelete="CASCADE")

    enclosure_id: int = Field(
        default=None, foreign_key="enclosure.id", ondelete="CASCADE"
    )
    enclosure: Enclosure = Relationship(back_populates="cross_sections")
