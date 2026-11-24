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

if TYPE_CHECKING:
    from ..typing import Angle
    from .cell import Cell
    from .instance import Instance


class Port(ABC):
    name: str

    @property
    def cross_section(self) -> SymmetricCrossSection:
        raise NotImplementedError

    @property
    @abstractmethod
    def transformation(self) -> kdb.Trans | kdb.DCplxTrans: ...

    @property
    @abstractmethod
    def trans(self) -> kdb.Trans: ...

    @property
    @abstractmethod
    def dcplx_trans(self) -> kdb.DCplxTrans: ...

    @property
    def angle(self) -> Angle:
        """Angle of the transformation.

        In the range of `[0,1,2,3]` which are increments in 90°.
        """
        return self.trans.angle

    @property
    def orientation(self) -> float:
        """Returns orientation in degrees for gdsfactory compatibility.

        In the range of `[0,360)`
        """
        return self.dcplx_trans.angle

    def transformed(
        self,
        trans: kdb.Trans | kdb.DCplxTrans = kdb.Trans.R0,
        post_trans: kdb.Trans | kdb.DCplxTrans = kdb.Trans.R0,
    ) -> CellPort:
        """Get a transformed copy of the BasePort."""

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

    @property
    def mirror(self) -> bool:
        """Returns `True`/`False` depending on the mirror flag on the transformation."""
        return self.trans.is_mirror()

    @mirror.setter
    def mirror(self, value: bool) -> None:
        """Setter for mirror flag on trans."""
        if self.trans:
            self.trans.mirror = value
        elif self.dcplx_trans:
            self.dcplx_trans.mirror = value

    @abstractmethod
    def dup(self) -> CellPort:
        """Copy the port with a transformation."""
        ...

    @property
    def center(self) -> tuple:
        """Returns port center."""
        d = self.trans.disp
        return (d.x, d.y)

    @property
    def x(self) -> int:
        return self.trans.disp.x

    @property
    def y(self) -> int:
        """Y coordinate of the port."""
        return self.trans.disp.y

    @property
    def width(self) -> int:
        """Width of the port."""
        return self.cross_section.width

    @property
    def ix(self) -> int:
        """X coordinate of the port in dbu."""
        return self.trans.disp.x

    @ix.setter
    def ix(self, value: int) -> None:
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
        if self.trans:
            vec = self.trans.disp
            vec.y = value
            self.trans.disp = vec
        elif self.dcplx_trans:
            vec = self.trans.disp
            vec.y = value
            self.dcplx_trans.disp = to_um(vec)

    # @property
    # def iwidth(self) -> int:
    #     """Width of the port in dbu."""
    #     return self.any_cross_section.width

    @property
    def dx(self) -> float:
        """X coordinate of the port in um."""
        return self.dcplx_trans.disp.x

    @dx.setter
    def dx(self, value: float) -> None:
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
        if self.trans:
            self.trans.disp = kdb.Vector(*pos)
        elif self.dcplx_trans:
            self.dcplx_trans.disp = to_um(kdb.Vector(*pos))

    # @property
    # def dwidth(self) -> float:
    #     """Width of the port in um."""
    #     return to_um(self.any_cross_section.width)

    # @abstractmethod
    # def print(self, print_type: Literal["dbu", "um"] | None = None) -> None: ...
    # @abstractmethod
    # def __repr__(self) -> str: ...


class CellPort(SQLModel, Port, table=True):
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
        if isinstance(self.transformation, kdb.Trans):
            return self.transformation.dup()

        return self.transformation.s_trans().to_itype(settings.dbu)

    @trans.setter
    def trans(self, value: kdb.Trans) -> None:
        self.transformation = value.dup()

    @property
    def dcplx_trans(self) -> kdb.DCplxTrans:
        if isinstance(self.transformation, kdb.Trans):
            return kdb.DCplxTrans(self.transformation.to_dtype(settings.dbu))

        return self.transformation.dup()

    @dcplx_trans.setter
    def dcplx_trans(self, value: kdb.DCplxTrans) -> None:
        self.transformation = value.dup()

    @Port.angle.setter
    def angle(self, value: int) -> None:
        self.trans = self.trans

    @Port.center.setter
    def center(self, value: tuple[int, int]) -> None:
        self.x = value[0]
        self.y = value[1]

    @Port.orientation.setter
    def orientation(self, value: float) -> None:
        """Set the orientation of the port."""
        if not self.dcplx_trans.is_complex():
            dcplx_trans = self.dcplx_trans
            dcplx_trans.angle = value
            self.dcplx_trans = dcplx_trans
        else:
            self.dcplx_trans = self.dcplx_trans
            self.dcplx_trans.angle = value

    @Port.x.setter
    def x(self, value: int) -> None:
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
        """Get a transformed copy of the BasePort."""

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
        dcplx_trans = self.dcplx_trans or kdb.DCplxTrans(
            t=self.trans.to_dtype(settings.dbu)
        )

        self.dcplx_trans = trans * dcplx_trans * post_trans
        return self

    def dup(self) -> CellPort:
        return self.transformed()

    # def __repr__(self) -> str:
    #     """String representation of port."""
    #     return (
    #         f"{self.__class__.__name__}({self.name=}"
    #         f", {self.width=}, trans={self.dcplx_trans.to_s()}, layer="
    #         f"{self.layer_info}, port_type={self.port_type})"
    #     )

    # def print(self, print_type: Literal[dbu, um] | None = None) -> None:
    #     """Print the port pretty."""
    #     config.console.print(pprint_ports([self], unit=print_type))


@dataclass
class InstancePort(Port):
    instance: Instance
    cell_port: CellPort
    ia: int = 0
    ib: int = 0

    @property
    def cross_section(self) -> SymmetricCrossSection:
        return self.cell_port.cross_section

    @property
    def transformation(self) -> kdb.Trans | kdb.DCplxTrans:
        if (
            isinstance(self.cell_port.transformation, kdb.Trans)
            and not self.instance.cplx_trans.is_complex()
        ):
            trans = self.instance.trans
            if self.ia > 0:
                trans *= kdb.Trans(self.instance.a * self.ia)
            if self.ib > 0:
                trans *= kdb.Trans(self.instance.b * self.ib)
            return self.instance.trans * kdb.Trans() * self.cell_port.transformation
        dtrans = self.instance.dcplx_trans
        if self.ia > 0:
            a = self.instance.a.to_dtype(settings.dbu)
            dtrans *= kdb.DCplxTrans(a * self.ia)
        if self.ib > 0:
            b = self.instance.b.to_dtype(settings.dbu)
            dtrans *= kdb.DCplxTrans(b * self.ib)
        return dtrans * self.cell_port.dcplx_trans

    @property
    def trans(self) -> kdb.Trans:
        if isinstance(self.transformation, kdb.Trans):
            return self.transformation.dup()

        return self.transformation.s_trans().to_itype(settings.dbu)

    @property
    def dcplx_trans(self) -> kdb.DCplxTrans:
        if isinstance(self.transformation, kdb.Trans):
            return kdb.DCplxTrans(self.transformation.to_dtype(settings.dbu))

        return self.transformation.dup()

    def dup(self) -> CellPort:
        return self.transformed()
