from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship, SQLModel

from .path import PathType

if TYPE_CHECKING:
    from pathlib import Path

    from .pcell import PCell


class Dependency(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    path: Path = Field(unique=True, sa_type=PathType)
    file_hash: str = Field()

    pcells: list[PCell] = Relationship(
        sa_relationship=relationship("PCell", back_populates="dependency")
    )
