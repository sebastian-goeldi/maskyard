from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship, Session, SQLModel, col, select

from .cell import Cell
from .path import PathType
from .pcell import PCell

if TYPE_CHECKING:
    from pathlib import Path


class Dependency(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    path: Path = Field(unique=True, sa_type=PathType)
    file_hash: str = Field()

    pcells: list[PCell] = Relationship(
        sa_relationship=relationship("PCell", back_populates="dependency")
    )


def find_and_clean_changed_dependencies(session: Session) -> None:
    """Evict affected cells and update hashes in the caller's transaction."""
    changed: list[tuple[Dependency, str]] = []
    for dependency in session.exec(select(Dependency)).all():
        with dependency.path.open("rb") as f:
            file_hash = sha256(f.read()).hexdigest()
        if file_hash != dependency.file_hash:
            changed.append((dependency, file_hash))

    if not changed:
        return

    dependency_ids = [dependency.id for dependency, _ in changed]
    generated_cells = session.exec(
        select(Cell)
        .join(PCell, col(Cell.pcell_id) == col(PCell.id))
        .where(col(PCell.dependency_id).in_(dependency_ids))
    ).all()
    with session.no_autoflush:
        for cell in generated_cells:
            session.delete(cell)

    for dependency, file_hash in changed:
        dependency.file_hash = file_hash
    session.commit()
