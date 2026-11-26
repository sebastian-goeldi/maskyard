from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from sqlmodel import Field, Relationship, SQLModel
from sqlmodel.main import SQLModelConfig

from .. import kdb
from ..config import settings, to_dbu, to_um
from .cross_section import SymmetricCrossSection  # noqa: TC001
from .trans import PortTrans
from .transformable import Transformable

if TYPE_CHECKING:
    from ..typing import Angle
    from .cell import Cell
    from .instance import Instance


class Port(ABC):
    name: str

    @property
    def cross_section(self) -> SymmetricCrossSection:
        """Return the cross section that defines the port."""
        raise NotImplementedError

    @property
    @abstractmethod
    def transformation(self) -> kdb.Trans | kdb.DCplxTrans:
        """Return the transform in the port's native representation."""

    @property
    @abstractmethod
    def trans(self) -> kdb.Trans:
        """Return the port transform in integer database units."""

    @property
    @abstractmethod
    def dcplx_trans(self) -> kdb.DCplxTrans:
        """Return the complex port transform in micrometers."""

    @property
    def angle(self) -> Angle:
        """Return the simple orientation in counterclockwise quarter turns."""
        return self.trans.angle

    @property
    def orientation(self) -> float:
        """Return the complex orientation in degrees for gdsfactory compatibility."""
        return self.dcplx_trans.angle

    def transformed(
        self,
        trans: kdb.Trans | kdb.DCplxTrans = kdb.Trans.R0,
        post_trans: kdb.Trans | kdb.DCplxTrans = kdb.Trans.R0,
    ) -> CellPort:
        """Copy the port and compose additional transforms around its placement.

        Args:
            trans: Transform applied in the enclosing cell's coordinates.
            post_trans: Transform applied in the port's local coordinates.

        Returns:
            A new cell port with the same cross-section reference.
        """

        cell_port = CellPort(
            name=self.name,
            transformation=self.transformation,
            cell_id=None,  # ty: ignore[invalid-argument-type]
            cross_section_id=self.cross_section.id,  # ty: ignore[invalid-argument-type]
        )
        transformation = self.transformation.dup()
        if (
            isinstance(transformation, kdb.Trans)
            and isinstance(trans, kdb.Trans)
            and isinstance(post_trans, kdb.Trans)
        ):
            transformation = trans * self.trans * post_trans
            cell_port.transformation = transformation
            return cell_port
        if isinstance(transformation, kdb.Trans):
            transformation = kdb.DCplxTrans(transformation.to_dtype(settings.dbu))
        if isinstance(trans, kdb.Trans):
            trans = kdb.DCplxTrans(trans.to_dtype(settings.dbu))
        if isinstance(post_trans, kdb.Trans):
            post_trans = kdb.DCplxTrans(post_trans.to_dtype(settings.dbu))
        cell_port.transformation = trans * transformation * post_trans

        return cell_port

    @abstractmethod
    def dup(self) -> CellPort:
        """Return a standalone cell port at the current placement."""
        ...

    @property
    def center(self) -> tuple:
        """Return the (x, y) center in integer database units."""
        d = self.trans.disp
        return (d.x, d.y)

    @property
    def x(self) -> int:
        """Return the X coordinate in integer database units."""
        return self.trans.disp.x

    @property
    def y(self) -> int:
        """Return the Y coordinate in integer database units."""
        return self.trans.disp.y

    @property
    def width(self) -> int:
        """Return the cross-section width in database units."""
        return self.cross_section.width

    @property
    def ix(self) -> int:
        """X coordinate of the port in dbu."""
        return self.trans.disp.x

    @ix.setter
    def ix(self, value: int) -> None:
        """Update the integer X coordinate on the available transform."""
        if self.trans:
            vec = self.trans.disp
            vec.x = value
            self.trans.disp = vec
        elif self.dcplx_trans:
            vec = self.trans.disp
            vec.x = value
            self.dcplx_trans.disp = to_um(vec)

    @property
    def iy(self) -> int:
        """Y coordinate of the port in dbu."""
        return self.trans.disp.y

    @iy.setter
    def iy(self, value: int) -> None:
        """Update the integer Y coordinate on the available transform."""
        if self.trans:
            vec = self.trans.disp
            vec.y = value
            self.trans.disp = vec
        elif self.dcplx_trans:
            vec = self.trans.disp
            vec.y = value
            self.dcplx_trans.disp = to_um(vec)

    @property
    def dx(self) -> float:
        """X coordinate of the port in um."""
        return self.dcplx_trans.disp.x

    @dx.setter
    def dx(self, value: float) -> None:
        """Update the X coordinate in micrometers on the available transform."""
        vec = self.dcplx_trans.disp
        vec.x = value
        if self.trans:
            self.trans.disp = to_dbu(vec)
        elif self.dcplx_trans:
            self.dcplx_trans.disp = vec

    @property
    def dy(self) -> float:
        """Y coordinate of the port in um."""
        return self.dcplx_trans.disp.y

    @dy.setter
    def dy(self, value: float) -> None:
        """Update the Y coordinate in micrometers on the available transform."""
        vec = self.dcplx_trans.disp
        vec.y = value
        if self.trans:
            self.trans.disp = to_dbu(vec)
        elif self.dcplx_trans:
            self.dcplx_trans.disp = vec

    @property
    def dcenter(self) -> tuple[float, float]:
        """Coordinate of the port in um."""
        vec = self.dcplx_trans.disp
        return (vec.x, vec.y)

    @dcenter.setter
    def dcenter(self, pos: tuple[float, float]) -> None:
        """Update both center coordinates in micrometers."""
        if self.trans:
            self.trans.disp = to_dbu(kdb.DVector(*pos))
        elif self.dcplx_trans:
            self.dcplx_trans.disp = kdb.DVector(*pos)

    @property
    def icenter(self) -> tuple[int, int]:
        """Coordinate of the port in dbu."""
        vec = self.trans.disp
        return (vec.x, vec.y)

    @icenter.setter
    def icenter(self, pos: tuple[int, int]) -> None:
        """Update both center coordinates in integer database units."""
        if self.trans:
            self.trans.disp = kdb.Vector(*pos)
        elif self.dcplx_trans:
            self.dcplx_trans.disp = to_um(kdb.Vector(*pos))


class CellPort(SQLModel, Port, Transformable, table=True):
    model_config = SQLModelConfig(arbitrary_types_allowed=True)

    id: int | None = Field(default=None, primary_key=True)
    name: str
    transformation: kdb.Trans | kdb.DCplxTrans = Field(
        default_factory=kdb.Trans, sa_type=PortTrans
    )
    cell_id: int = Field(default=None, foreign_key="cell.id", ondelete="CASCADE")
    cell: Cell = Relationship(back_populates="ports")
    cross_section_id: int = Field(
        default=None, foreign_key="symmetriccrosssection.id", ondelete="CASCADE"
    )
    cross_section: SymmetricCrossSection = Relationship()

    @property
    def trans(self) -> kdb.Trans:
        """Return a copy of the port's simple transform in database units."""
        if isinstance(self.transformation, kdb.Trans):
            return self.transformation.dup()

        return self.transformation.s_trans().to_itype(settings.dbu)

    @trans.setter
    def trans(self, value: kdb.Trans) -> None:
        """Store a copy of the simple integer transform."""
        self.transformation = value.dup()

    @property
    def dcplx_trans(self) -> kdb.DCplxTrans:
        """Return a copy of the port's complex transform in micrometers."""
        if isinstance(self.transformation, kdb.Trans):
            return kdb.DCplxTrans(self.transformation.to_dtype(settings.dbu))

        return self.transformation.dup()

    @dcplx_trans.setter
    def dcplx_trans(self, value: kdb.DCplxTrans) -> None:
        """Store a copy of the complex micrometer transform."""
        self.transformation = value.dup()

    @property
    def mirrored(self) -> bool:
        """Return whether the port transformation includes a reflection."""
        return self.transformation.is_mirror()

    @mirrored.setter
    def mirrored(self, value: bool) -> None:
        """Set the mirror flag on the port transformation.

        Args:
            value: Whether the transformation includes a reflection.
        """
        trans = self.transformation.dup()
        trans.mirror = value
        self.transformation = trans

    @Port.angle.setter
    def angle(self, value: int) -> None:
        """Store the current placement in its simple integer representation."""
        self.trans = self.trans

    @Port.center.setter
    def center(self, value: tuple[int, int]) -> None:
        """Update X and Y through the integer coordinate setters."""
        self.x = value[0]
        self.y = value[1]

    @Port.orientation.setter
    def orientation(self, value: float) -> None:
        """Update the orientation in degrees through the complex transform."""
        if not self.dcplx_trans.is_complex():
            dcplx_trans = self.dcplx_trans
            dcplx_trans.angle = value
            self.dcplx_trans = dcplx_trans
        else:
            self.dcplx_trans = self.dcplx_trans
            self.dcplx_trans.angle = value

    @Port.x.setter
    def x(self, value: int) -> None:
        """Update X on the integer grid when the placement can represent it."""
        if isinstance(self.transformation, kdb.Trans):
            disp = self.transformation.disp
            disp.x = value
            self.transformation.disp = disp
        else:
            disp = self.transformation.disp
            disp.x = to_um(value)
            if not self.transformation.is_complex() and to_um(to_dbu(disp)) == disp:
                trans = self.transformation.s_trans().to_itype(settings.dbu)
                trans.disp = disp.to_itype(settings.dbu)
                self.transformation = trans

    @Port.y.setter
    def y(self, value: int) -> None:
        """Update Y on the integer grid when the placement can represent it."""
        if isinstance(self.transformation, kdb.Trans):
            disp = self.transformation.disp
            disp.y = value
            self.transformation.disp = disp
        else:
            disp = self.transformation.disp
            disp.y = to_um(value)
            if not self.transformation.is_complex() and to_um(to_dbu(disp)) == disp:
                trans = self.transformation.s_trans().to_itype(settings.dbu)
                trans.disp = disp.to_itype(settings.dbu)
                self.transformation = trans

    def transform(
        self,
        trans: kdb.Trans | kdb.DCplxTrans = kdb.Trans.R0,
        post_trans: kdb.Trans | kdb.DCplxTrans = kdb.Trans.R0,
    ) -> Self:
        """Transform the port in place.

        Args:
            trans: Transform applied in cell coordinates.
            post_trans: Transform applied in the port's local coordinates.

        Returns:
            The transformed port.
        """

        if (
            isinstance(self.transformation, kdb.Trans)
            and isinstance(trans, kdb.Trans)
            and isinstance(post_trans, kdb.Trans)
        ):
            self.trans = trans * self.trans * post_trans
            return self
        if isinstance(trans, kdb.Trans):
            trans = kdb.DCplxTrans(trans.to_dtype(settings.dbu))
        if isinstance(post_trans, kdb.Trans):
            post_trans = kdb.DCplxTrans(post_trans.to_dtype(settings.dbu))
        self.dcplx_trans = trans * self.dcplx_trans * post_trans
        return self

    def dup(self) -> CellPort:
        """Copy the cell port at its current placement."""
        return self.transformed()


@dataclass
class InstancePort(Port):
    instance: Instance
    cell_port: CellPort
    ia: int = 0
    ib: int = 0

    @property
    def cross_section(self) -> SymmetricCrossSection:
        """Return the referenced cell port's cross section."""
        return self.cell_port.cross_section

    @property
    def mirror(self) -> bool:
        """Return whether the derived port transformation includes a reflection."""
        return self.trans.is_mirror()

    @mirror.setter
    def mirror(self, value: bool) -> None:
        """Set the mirror flag on the derived transform.

        Args:
            value: Whether the transformation includes a reflection.
        """
        if self.trans:
            self.trans.mirror = value
        elif self.dcplx_trans:
            self.dcplx_trans.mirror = value

    @property
    def transformation(self) -> kdb.Trans | kdb.DCplxTrans:
        """Return the derived port transform in parent-cell coordinates."""
        offset = self.instance.a * max(0, self.ia) + self.instance.b * max(0, self.ib)
        if (
            isinstance(self.cell_port.transformation, kdb.Trans)
            and not self.instance.cplx_trans.is_complex()
        ):
            return (
                kdb.Trans(offset) * self.instance.trans * self.cell_port.transformation
            )
        return (
            kdb.DCplxTrans(offset.to_dtype(settings.dbu))
            * self.instance.dcplx_trans
            * self.cell_port.dcplx_trans
        )

    @property
    def trans(self) -> kdb.Trans:
        """Express the derived parent-cell placement in integer database units."""
        if isinstance(self.transformation, kdb.Trans):
            return self.transformation.dup()

        return self.transformation.s_trans().to_itype(settings.dbu)

    @property
    def dcplx_trans(self) -> kdb.DCplxTrans:
        """Express the derived parent-cell placement in micrometers."""
        if isinstance(self.transformation, kdb.Trans):
            return kdb.DCplxTrans(self.transformation.to_dtype(settings.dbu))

        return self.transformation.dup()

    def dup(self) -> CellPort:
        """Make a standalone copy in parent-cell coordinates."""
        return self.transformed()
