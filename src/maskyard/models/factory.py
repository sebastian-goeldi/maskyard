from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .cell import Cell
    from .dependency import Dependency
    from .pdk import Pdk


class PCellFactory(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "pdk_id", "dependency_id", "name", name="uq_pcell_factory_identity"
        ),
    )
    id: int = Field(default=None, primary_key=True)

    name: str

    pdk_id: int = Field(default=None, foreign_key="pdk.id", ondelete="CASCADE")
    pdk: Pdk = Relationship(
        sa_relationship=relationship("Pdk", back_populates="pcell_factories")
    )

    dependency_id: int = Field(
        default=None, foreign_key="dependency.id", ondelete="CASCADE"
    )
    dependency: Dependency = Relationship(
        sa_relationship=relationship("Dependency", back_populates="pcell_factories")
    )
    cells: list[Cell] = Relationship(
        sa_relationship=relationship("Cell", back_populates="pcell_factory")
    )
