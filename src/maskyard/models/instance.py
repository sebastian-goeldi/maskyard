from __future__ import annotations

from typing import TYPE_CHECKING, Self, overload

from sqlmodel import Field, Relationship, SQLModel, select
from sqlmodel.main import SQLModelConfig

from .. import kdb
from ..config import settings
from ..engine import get_context_session
from .info import InfoBase
from .port import CellPort, InstancePort, Port
from .trans import InstanceTrans
from .transformable import Transformable
from .vector import Vector

if TYPE_CHECKING:
    from .cell import Cell
    from .layer import Layer


class Instance(SQLModel, Transformable, table=True):
    model_config = SQLModelConfig(arbitrary_types_allowed=True)

    id: int | None = Field(default=None, primary_key=True)
    name: str | None = None
    cplx_trans: kdb.ICplxTrans = Field(sa_type=InstanceTrans)
    virtual: bool

    a: kdb.Vector = Field(default=kdb.Vector(), sa_type=Vector)
    b: kdb.Vector = Field(default=kdb.Vector(), sa_type=Vector)
    na: int = 0
    nb: int = 0

    info: InstanceInfo = Relationship(back_populates="instance", cascade_delete=True)

    cell_id: int = Field(
        default=None, foreign_key="cell.id", ondelete="CASCADE", index=True
    )
    parent_cell_id: int = Field(
        default=None, foreign_key="cell.id", ondelete="CASCADE", index=True
    )

    cell: Cell = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Instance.cell_id]"},
    )
    parent_cell: Cell = Relationship(
        back_populates="instances",
        sa_relationship_kwargs={"foreign_keys": "[Instance.parent_cell_id]"},
    )

    def bbox(self, layer: Layer | None = None) -> kdb.Box:
        """Compute the bounds of every placement in parent-cell coordinates.

        Args:
            layer: Limit the bounds to this layer, or use all layers by default.

        Returns:
            The enclosing box in database units.
        """
        if self.na == 0 and self.nb == 0:
            return self.cell.bbox(layer).transformed(self.cplx_trans)
        cell_bb = self.cell.bbox(layer).transformed(self.cplx_trans)
        aa = self.a * (self.na - 1)
        bb = self.b * (self.nb - 1)
        return (
            cell_bb
            + cell_bb.transformed(kdb.Trans(aa))
            + cell_bb.transformed(kdb.Trans(bb))
            + cell_bb.transformed(kdb.Trans(aa + bb))
        )

    def transform(self, trans: kdb.Trans | kdb.DCplxTrans) -> Self:
        """Transform the placement and array pitch in parent coordinates.

        Args:
            trans: An integer DBU transform or a complex transform in micrometers.

        Returns:
            The transformed instance.
        """
        if isinstance(trans, kdb.Trans):
            self.cplx_trans = kdb.ICplxTrans(trans) * self.cplx_trans
            if self.na and self.nb:
                self.a = trans * self.a
                self.b = trans * self.b
        else:
            dbu = settings.dbu
            self.dcplx_trans = trans * self.dcplx_trans
            if self.na and self.nb:
                self.a = (trans * self.a.to_dtype(dbu)).to_itype(dbu)
                self.b = (trans * self.b.to_dtype(dbu)).to_itype(dbu)
        return self

    def get_port(
        self, name: str, ia: int | None = None, ib: int | None = None
    ) -> InstancePort:
        """Look up a child port at a particular instance placement.

        Args:
            name: Name of the port on the referenced cell.
            ia: Index along the first array vector. Defaults to the first placement.
            ib: Index along the second array vector. Defaults to the first placement.

        Returns:
            A view of the port in parent-cell coordinates.

        Raises:
            ValueError: If a supplied index reaches or exceeds the array size.
            NoResultFound: If the referenced cell has no port with that name.
        """
        session = get_context_session(self)
        if ia is not None and ia >= self.na:
            raise ValueError(
                f"Instance {self.name!r} has only {self.na} "
                f"instances in the array, not {ia}"
            )
        if ib is not None and ib >= self.nb:
            raise ValueError(
                f"Instance {self.name!r} has only {self.nb} "
                f"instances in the array, not {ib}"
            )

        cell_port = session.execute(
            select(CellPort).where(
                CellPort.cell_id == self.cell_id, CellPort.name == name
            )
        ).scalar_one()

        return InstancePort(instance=self, cell_port=cell_port, ia=ia or 0, ib=ib or 0)

    @property
    def trans(self) -> kdb.Trans:
        """Return the simple integer form of the instance placement."""
        return self.cplx_trans.s_trans()

    @trans.setter
    def trans(self, value: kdb.Trans) -> None:
        """Replace the placement with a simple integer transform."""
        self.cplx_trans = kdb.ICplxTrans(value)

    @property
    def mirrored(self) -> bool:
        """Return whether the instance placement includes a reflection."""
        return self.cplx_trans.is_mirror()

    @mirrored.setter
    def mirrored(self, value: bool) -> None:
        """Set the reflection flag at the current placement.

        Args:
            value: Whether the placement includes a reflection.
        """
        trans = self.cplx_trans.dup()
        trans.mirror = value
        self.cplx_trans = trans

    @property
    def dcplx_trans(self) -> kdb.DCplxTrans:
        """Return the complex placement in micrometers."""
        return kdb.DCplxTrans(self.cplx_trans, dbu=settings.dbu)

    @dcplx_trans.setter
    def dcplx_trans(self, value: kdb.DCplxTrans) -> None:
        """Convert a complex micrometer transform to an integer placement."""
        self.cplx_trans = kdb.ICplxTrans(value, dbu=settings.dbu)

    @property
    def dtrans(self) -> kdb.DTrans:
        """Return the simple form of the placement in micrometers."""
        return self.cplx_trans.s_trans().to_dtype(settings.dbu)

    @dtrans.setter
    def dtrans(self, value: kdb.DTrans) -> None:
        """Convert a simple micrometer transform to an integer placement."""
        self.cplx_trans = kdb.ICplxTrans(kdb.DCplxTrans(value), dbu=settings.dbu)

    @overload
    def connect(
        self,
        port: str | Port | None,
        other: Port,
        *,
        mirror: bool = False,
        allow_width_mismatch: bool | None = None,
        allow_layer_mismatch: bool | None = None,
        allow_type_mismatch: bool | None = None,
        allow_cross_section_mismatch: bool | None = None,
        use_mirror: bool | None = None,
        use_angle: bool | None = None,
    ) -> Self: ...

    @overload
    def connect(
        self,
        port: str | Port | None,
        other: Instance,
        other_port_name: str | int | tuple[int | str, int, int] | None,
        *,
        mirror: bool = False,
        allow_width_mismatch: bool | None = None,
        allow_layer_mismatch: bool | None = None,
        allow_type_mismatch: bool | None = None,
        allow_cross_section_mismatch: bool | None = None,
        use_mirror: bool | None = None,
        use_angle: bool | None = None,
    ) -> Self: ...

    def connect(
        self,
        port: str | tuple[str, int, int],
        other: Instance | Port,
        other_port_name: str | tuple[str, int, int] | None = None,
        *,
        mirror: bool = False,
        allow_width_mismatch: bool | None = None,
        allow_layer_mismatch: bool | None = None,
        allow_type_mismatch: bool | None = None,
        allow_cross_section_mismatch: bool | None = None,
        use_mirror: bool | None = None,
        use_angle: bool | None = None,
    ) -> Self:
        """Align an instance port to a target port and commit the placement.

        Args:
            port: Source port name or a tuple of name and two array indices.
            other: Target port or instance containing the target port.
            other_port_name: Target port name or a tuple of name and two array indices
                when the target is an instance.
            mirror: Whether to reflect instead of using a half-turn for angular
                alignment.
            allow_width_mismatch: Reserved for width compatibility checks.
            allow_layer_mismatch: Reserved for layer compatibility checks.
            allow_type_mismatch: Reserved for port type compatibility checks.
            allow_cross_section_mismatch: Reserved for cross-section compatibility
                checks.
            use_mirror: Whether angular alignment uses the target port's reflection.
                Defaults to the configured behavior.
            use_angle: Whether to align orientation as well as position. Defaults to the
                configured behavior.

        Returns:
            The updated instance.

        Raises:
            ValueError: If a target instance is supplied without a port name or a
                supplied array index exceeds its upper bound.
            NoResultFound: If a named port does not exist.
        """
        if allow_width_mismatch is None:
            allow_width_mismatch = settings.allow_width_mismatch
        if allow_layer_mismatch is None:
            allow_layer_mismatch = settings.allow_layer_mismatch
        if allow_type_mismatch is None:
            allow_type_mismatch = settings.allow_type_mismatch
        if allow_cross_section_mismatch is None:
            allow_cross_section_mismatch = settings.allow_cross_section_mismatch
        if use_mirror is None:
            use_mirror = settings.connect_use_mirror
        if use_angle is None:
            use_angle = settings.connect_use_angle

        if isinstance(other, Instance):
            if other_port_name is None:
                raise ValueError(
                    "If the instance and port are given as "
                    r"\`instance\`, \`port_name\`,"
                    " port_name must not be None"
                )
            if isinstance(other_port_name, str):
                op = other.get_port(other_port_name)
            else:
                op = other.get_port(*other_port_name)
        else:
            op = other
        p = self.get_port(port) if isinstance(port, str) else self.get_port(*port)
        p_istrans = isinstance(p.transformation, kdb.Trans)
        op_istrans = isinstance(op.transformation, kdb.Trans)
        if p_istrans and op_istrans:
            conn_trans = kdb.Trans.M90 if mirror else kdb.Trans.R180
            match (use_mirror, use_angle):
                case True, True:
                    trans = op.trans * conn_trans * p.trans.inverted()
                case False, True:
                    conn_trans = (
                        kdb.Trans.M90
                        if mirror ^ self.trans.mirror ^ p.trans.mirror
                        else kdb.Trans.R180
                    )
                    op_trans = op.trans
                    op_trans.mirror = False
                    trans = op_trans * conn_trans * p.trans.inverted()
                case False, False:
                    trans = kdb.Trans(op.trans.disp - p.trans.disp)
                case True, False:
                    trans = kdb.Trans(op.trans.disp - p.trans.disp)
                case _:
                    raise NotImplementedError("This shouldn't happen")
            self.trans = trans
        else:
            dconn_trans = kdb.DCplxTrans.M90 if mirror else kdb.DCplxTrans.R180
            match (use_mirror, use_angle):
                case True, True:
                    dcplx_trans = (
                        op.dcplx_trans * dconn_trans * p.dcplx_trans.inverted()
                    )
                case False, True:
                    dconn_trans = (
                        kdb.DCplxTrans.M90
                        if mirror ^ self.dcplx_trans.mirror ^ p.dcplx_trans.mirror
                        else kdb.DCplxTrans.R180
                    )
                    op_dcplx_trans = op.dcplx_trans
                    op_dcplx_trans.mirror = False
                    dcplx_trans = (
                        op_dcplx_trans * dconn_trans * p.dcplx_trans.inverted()
                    )
                case False, False:
                    dcplx_trans = kdb.DCplxTrans(
                        op.dcplx_trans.disp - p.dcplx_trans.disp
                    )
                case True, False:
                    dcplx_trans = kdb.DCplxTrans(
                        op.dcplx_trans.disp - p.dcplx_trans.disp
                    )
                case _:
                    raise NotImplementedError("This shouldn't happen")
            self.dcplx_trans = dcplx_trans
        session = get_context_session(self)
        session.add(self)
        session.commit()

        return self


class InstanceInfo(InfoBase, table=True):
    id: int | None = Field(foreign_key="instance.id", primary_key=True)
    instance: Instance = Relationship(back_populates="info")
