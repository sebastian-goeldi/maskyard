from __future__ import annotations

from enum import StrEnum
from functools import cached_property
from typing import TYPE_CHECKING

from numpy import isclose
from sqlalchemy import Dialect, TypeDecorator
from sqlalchemy.util import warn
from sqlmodel import Field, LargeBinary, Relationship, SQLModel
from sqlmodel.main import SQLModelConfig

from .. import kdb
from ..config import settings

if TYPE_CHECKING:
    from .cell import Cell


class Format(StrEnum):
    GDS = "GDS2"
    OASIS = "OASIS"


class Layout(TypeDecorator[kdb.Layout]):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(
        self, value: kdb.Layout | None, dialect: Dialect
    ) -> bytes | None:
        if value is None:
            return None
        cell = value.cell("TOP")
        if cell is not None:
            if cell.child_cells() > 0:
                cell_ = value.create_cell(value.unique_cell_name(cell.name))
                cell_.name = "TOP"
                cell_.copy_shapes(cell)
            else:
                cell_ = cell
        else:
            warn("Found no cell called `TOP`, and saving it.")
            cell_ = value.create_cell("TOP")
        options = kdb.SaveLayoutOptions()
        options.select_this_cell(cell_.cell_index())
        options.format = Format.OASIS

        if not isclose(settings.dbu, value.dbu, atol=1e-12):
            raise ValueError(
                "DBU of actual geometries is not the same as the settings of the"
                " database. They must be the same. "
                f"DB dbu: {settings.dbu} Geometry dbu: {value.dbu}"
            )

        return value.write_bytes(options)

    def process_result_value(
        self, value: bytes | None, dialect: Dialect
    ) -> kdb.Layout | None:
        layout = kdb.Layout()
        if value is None:
            layout.create_cell("TOP")
            return layout
        layout.read_bytes(value)
        return layout


def _create_layout_for_shapes() -> kdb.Layout:
    ly = kdb.Layout()
    ly.dbu = settings.dbu
    ly.create_cell("TOP")
    return ly


class Geometry(SQLModel, table=True):
    model_config = SQLModelConfig(arbitrary_types_allowed=True)
    id: int | None = Field(foreign_key="cell.id", primary_key=True)

    cell: Cell = Relationship(back_populates="geometry")
    layout: kdb.Layout = Field(
        default_factory=_create_layout_for_shapes, sa_type=Layout
    )

    @cached_property
    def kdb_cell(self) -> kdb.Cell:
        return self.layout.cell("TOP")
