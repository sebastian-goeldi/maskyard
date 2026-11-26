from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Self, overload

from sqlalchemy import LargeBinary, UniqueConstraint, or_
from sqlalchemy import select as sa_select
from sqlalchemy.orm import aliased, object_session, relationship
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import JSON, Field, Relationship, SQLModel, col, select
from sqlmodel.main import SQLModelConfig

from .. import kdb
from ..config import settings
from ..engine import get_context_session, get_session
from ..serialization import CellNameError
from ..typing import JSONSerializable  # noqa: TC001 - SQLModel resolves field types.
from .cross_section import SymmetricCrossSection
from .geometry import Geometry
from .instance import Instance
from .layer import Layer
from .port import CellPort, Port
from .transformable import Transformable

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.engine import Row

    from .factory import PCellFactory
    from .pdk import Pdk

automatic_cell_name: ContextVar[str | None] = ContextVar[str | None](
    "automatic_cell_name", default=None
)


class Cell(SQLModel, Transformable, table=True):
    __table_args__ = (
        UniqueConstraint(
            "pcell_factory_id", "hashkey", name="uq_cell_pcell_factory_hashkey"
        ),
        UniqueConstraint("pdk_id", "name", name="uq_cell_pdk_name"),
    )
    model_config = SQLModelConfig(arbitrary_types_allowed=True)
    id: int | None = Field(default=None, primary_key=True)
    name: str

    geometry: Geometry = Relationship(back_populates="cell")

    info: CellInfo = Relationship(back_populates="cell")
    settings: CellSettings = Relationship(back_populates="cell")

    pcell_factory_id: int | None = Field(
        default=None, foreign_key="pcellfactory.id", ondelete="CASCADE"
    )
    pcell_factory: PCellFactory | None = Relationship(
        sa_relationship=relationship("PCellFactory", back_populates="cells")
    )
    hashkey: bytes | None = Field(default=None, sa_type=LargeBinary)
    pdk_id: int | None = Field(default=None, foreign_key="pdk.id")
    pdk: Pdk = Relationship(back_populates="cells")

    instances: list[Instance] = Relationship(
        sa_relationship=relationship(
            "Instance",
            back_populates="parent_cell",
            foreign_keys="[Instance.parent_cell_id]",
            cascade="all, delete-orphan",
            passive_deletes=True,
        )
    )
    ports: list[CellPort] = Relationship(
        sa_relationship=relationship(
            "CellPort", back_populates="cell", cascade="all, delete-orphan"
        )
    )

    def bbox(self, layer: Layer | None = None) -> kdb.Box:
        """Combine local geometry and instance bounds in cell coordinates.

        Args:
            layer: Limit the bounds to this layer, or use all layers by default.

        Returns:
            The enclosing box in database units.
        """
        geometry = self.geometry
        if geometry is None:
            own_box = kdb.Box()
        elif layer is None:
            own_box = geometry.kdb_cell.bbox()
        else:
            li = geometry.layout.layer(layer.layer, layer.datatype)
            own_box = geometry.kdb_cell.bbox(li)
        return sum((inst.bbox(layer) for inst in self.instances), own_box)

    def transform(self, trans: kdb.Trans | kdb.DCplxTrans) -> Self:
        """Transform the cell's local shapes, ports, and instance placements.

        Referenced cell definitions retain their local geometry.

        Args:
            trans: An integer DBU transform or a complex transform in micrometers.

        Returns:
            The transformed cell.
        """
        geometry = self.geometry
        ports = self.ports
        instances = self.instances
        if geometry is not None:
            geometry.kdb_cell.transform(trans)
            flag_modified(geometry, "layout")
        for port in ports:
            port.transform(trans)
        for instance in instances:
            instance.transform(trans)
        return self

    def get_port(self, name: str) -> CellPort:
        """Query the current cell's saved ports by name.

        Args:
            name: Port name within the cell.

        Returns:
            The matching port.

        Raises:
            NoResultFound: If no port matches.
            MultipleResultsFound: If more than one port matches.
        """
        session = get_context_session(self)

        return session.execute(
            select(CellPort).where(CellPort.cell_id == self.id, CellPort.name == name)
        ).scalar_one()

    def get_instance(self, name: str) -> Instance:
        """Query the current cell's saved instances by name.

        Args:
            name: Instance name within the parent cell.

        Returns:
            The matching instance.

        Raises:
            NoResultFound: If no instance matches.
            MultipleResultsFound: If more than one instance matches.
        """
        session = get_context_session(self)
        return session.execute(
            select(Instance).where(
                Instance.parent_cell_id == self.id, Instance.name == name
            )
        ).scalar_one()

    @property
    def dbu(self) -> float:
        """Return the configured size of one database unit in micrometers."""
        return settings.dbu

    def insert(
        self,
        cell: Cell,
        *,
        name: str | None = None,
        a: kdb.Vector | None = None,
        b: kdb.Vector | None = None,
        na: int = 0,
        nb: int = 0,
        trans: kdb.Trans | kdb.DCplxTrans | kdb.ICplxTrans | kdb.DTrans | None = None,
    ) -> Instance:
        """Insert a child instance and commit it to the database.

        Args:
            cell: Cell to reference.
            name: Optional name for the new instance.
            a: Offset between placements along the first array axis in DBU.
            b: Offset between placements along the second array axis in DBU.
            na: Number of placements along the first array axis.
            nb: Number of placements along the second array axis.
            trans: Initial placement transform. Defaults to the identity.

        Returns:
            The committed instance.

        Raises:
            ValueError: If only one array axis has a positive count.
        """
        session = get_context_session(self)
        session.add(self)
        session.add(cell)
        session.flush()
        inst = self.add_instance(cell, name=name, a=a, b=b, na=na, nb=nb, trans=trans)
        session.commit()
        return inst

    def add_instance(
        self,
        cell: Cell,
        *,
        name: str | None = None,
        a: kdb.Vector | None = None,
        b: kdb.Vector | None = None,
        na: int = 0,
        nb: int = 0,
        trans: kdb.Trans | kdb.DCplxTrans | kdb.ICplxTrans | kdb.DTrans | None = None,
    ) -> Instance:
        """Attach an instance without flushing or committing the session.

        Args:
            cell: Cell to reference.
            name: Optional name for the new instance.
            a: First array step in DBU. Defaults to the zero vector.
            b: Second array step in DBU. Defaults to the zero vector.
            na: Number of placements along the first array axis.
            nb: Number of placements along the second array axis.
            trans: Initial placement, converted to integer DBU. Defaults to the
                identity.

        Returns:
            The new instance attached to the parent cell.

        Raises:
            ValueError: If only one array axis has a positive count.
        """
        if trans is None:
            trans_ = kdb.ICplxTrans()
        elif isinstance(trans, kdb.Trans):
            trans_ = kdb.ICplxTrans(trans)
        elif isinstance(trans, kdb.DCplxTrans):
            trans_ = kdb.ICplxTrans(trans, self.dbu)
        elif isinstance(trans, kdb.ICplxTrans):
            trans_ = trans
        else:
            trans_ = kdb.ICplxTrans(trans.to_itype(self.dbu))
        if (na > 0 and nb < 1) or (na < 1 and nb > 0):
            raise ValueError("If na is not 0, nb must not be 0 and vice versa.")

        inst = Instance(
            name=name,
            cplx_trans=trans_,
            virtual=False,
            cell=cell,
            a=a if a is not None else kdb.Vector(),
            b=b if b is not None else kdb.Vector(),
            na=na,
            nb=nb,
        )
        self.instances.append(inst)
        return inst

    @overload
    def layer(self, *, name: str) -> kdb.LayerInfo: ...
    @overload
    def layer(
        self, layer: int, datatype: int, name: str | None = None
    ) -> kdb.LayerInfo: ...
    def layer(
        self,
        layer: int | None = None,
        datatype: int | None = None,
        name: str | None = None,
    ) -> kdb.LayerInfo:
        """Look up a registered layer by number and datatype or by name.

        Args:
            layer: Numeric layer identifier. Supply it together with datatype.
            datatype: Numeric datatype within the layer.
            name: Layer name to look up or use as an additional filter.

        Returns:
            The matching layer as KLayout layer information.

        Raises:
            ValueError: If the identifiers are incomplete.
            LookupError: If no matching layer is registered.
        """
        session = get_context_session(self)

        if layer is not None and datatype is not None:
            statement = select(Layer).where(
                Layer.layer == layer,
                Layer.datatype == datatype,
            )
            if name is not None:
                statement = statement.where(Layer.name == name)
        elif layer is None and datatype is None and name is not None:
            statement = select(Layer).where(Layer.name == name)
        else:
            raise ValueError("Provide both layer and datatype, or provide name alone")

        result = session.execute(statement).scalars().first()
        if result is None:
            raise LookupError(f"Layer ({layer=}, {datatype=}, {name=}) not found")

        return kdb.LayerInfo(
            layer=result.layer,
            datatype=result.datatype,
            name=result.name,  # ty: ignore[invalid-argument-type]
        )

    def shapes(self, layer: kdb.LayerInfo) -> kdb.Shapes:
        """Return the mutable collection of local shapes on a layer."""
        return self.geometry.kdb_cell.shapes(layer)

    def fill(
        self,
        fill_cell: Cell,
        *,
        fill_layers: Iterable[tuple[kdb.LayerInfo, int]] = (),
        fill_regions: Iterable[tuple[kdb.Region, int]] = (),
        exclude_layers: Iterable[tuple[kdb.LayerInfo, int]] = (),
        exclude_regions: Iterable[tuple[kdb.Region, int]] = (),
        n_threads: int | None = None,
        tile_size: tuple[int, int] | None = None,
        row_step: kdb.Vector | None = None,
        col_step: kdb.Vector | None = None,
        x_space: int = 0,
        y_space: int = 0,
        tile_border: tuple[int, int] | None = None,
        multi: bool = False,
    ) -> None:
        """Place the fill cell in eligible regions and commit the generated arrays.

        All dimensions use integer database units. See fill_tiled for default areas,
        pitches, and validation.

        Args:
            fill_cell: Cell to repeat in the eligible area.
            fill_layers: Target layers and signed margins to include.
            fill_regions: Explicit regions and signed margins to include.
            exclude_layers: Target layers and signed margins to subtract.
            exclude_regions: Explicit regions and signed margins to subtract.
            n_threads: Number of KLayout tiling workers.
            tile_size: Width and height of each processing tile.
            row_step: Horizontal array pitch vector.
            col_step: Vertical array pitch vector.
            x_space: Extra spacing in the default horizontal pitch.
            y_space: Extra spacing in the default vertical pitch.
            tile_border: Minimum overlap around processing tiles.
            multi: Whether to fill separate polygons using KLayout's multi-region fill.
        """
        fill_tiled(
            self,
            fill_cell,
            fill_layers=fill_layers,
            fill_regions=fill_regions,
            exclude_layers=exclude_layers,
            exclude_regions=exclude_regions,
            n_threads=n_threads,
            tile_size=tile_size,
            row_step=row_step,
            col_step=col_step,
            x_space=x_space,
            y_space=y_space,
            tile_border=tile_border,
            multi=multi,
        )

    def flatten(self, levels: int | None = None) -> Self:
        """Copy geometry from the instance hierarchy into the local cell.

        The traversal recurses through all levels and retains the instance references.

        Args:
            levels: Reserved depth limit. The current implementation always recurses.

        Returns:
            The cell with the copied geometry.
        """
        cell_dict = {cell.name: cell for cell in self.called_cells()}
        cell_regions: dict[str, list[tuple[int, int, kdb.Region, kdb.Texts]]] = {}

        for instance in self.instances:
            flatten_inst_into(
                cell=self,
                instance=instance,
                cell_dict=cell_dict,
                cell_shapes=cell_regions,
                trans=kdb.ICplxTrans(),
            )

        return self

    def begin_shapes_rec(
        self, layer: Layer
    ) -> tuple[kdb.Layout, kdb.RecursiveShapeIterator]:
        """Create an iterator over shapes on one layer throughout the hierarchy.

        Args:
            layer: Layer to scan, identified by its number and datatype.

        Returns:
            The temporary layout and an iterator over its recursive layer shapes. Keep
            the layout alive while consuming the iterator.
        """
        ly, c = self._get_kdb_cell()
        l_ = ly.layer(layer.layer, layer.datatype)

        return ly, c.begin_shapes_rec(l_)

    def _get_kdb_cell(self) -> tuple[kdb.Layout, kdb.Cell]:
        """Reconstruct the referenced hierarchy in a temporary KLayout layout."""
        cells = self.called_cells()
        ly = kdb.Layout()
        ly.dbu = settings.dbu
        cells_dict: dict[str, kdb.Cell] = {}
        for cell in [self, *cells]:
            c = ly.create_cell(cell.name)
            c.copy_shapes(cell.geometry.kdb_cell)
            cells_dict[cell.name] = c
        for cell in [self, *cells]:
            c = cells_dict[cell.name]
            for inst in cell.instances:
                ic = cells_dict[inst.cell.name]
                na = inst.na
                nb = inst.nb

                if na > 0 or nb > 0:
                    c.insert(
                        kdb.CellInstArray(ic, inst.cplx_trans, inst.a, inst.b, na, nb)
                    )
                else:
                    c.insert(kdb.CellInstArray(ic, inst.cplx_trans))
        return ly, cells_dict[self.name]

    def create_port(
        self,
        name: str,
        cross_section: str | SymmetricCrossSection,
        info: dict[str, JSONSerializable] | None = None,
        trans: kdb.Trans | kdb.DCplxTrans = kdb.Trans.R0,
    ) -> CellPort:
        """Create a port on this cell and commit it.

        Args:
            name: Name assigned to the port. Also used for cross-section lookup when
                cross_section is a string.
            cross_section: Cross-section object, or a string to request a name lookup.
            info: Optional metadata passed to the port constructor.
            trans: Placement as an integer or complex micrometer transform.

        Returns:
            The committed port.

        Raises:
            NoResultFound: If the name lookup finds no cross section.
            MultipleResultsFound: If the name lookup finds more than one cross section.
        """
        if info is None:
            info = {}
        session = get_context_session(self)
        if isinstance(cross_section, str):
            cross_section = session.execute(
                select(SymmetricCrossSection).where(SymmetricCrossSection.name == name)
            ).scalar_one()
        port = CellPort(
            name=name,
            cross_section=cross_section,
            cell=self,
            transformation=trans,
            info=info,
        )
        session.add(port)
        session.commit()
        return port

    def attach_port(
        self,
        name: str,
        cross_section: SymmetricCrossSection,
        *,
        trans: kdb.Trans | kdb.DCplxTrans = kdb.Trans.R0,
    ) -> CellPort:
        """Attach a port without flushing or committing the session.

        Args:
            name: Name assigned to the port.
            cross_section: Cross section that defines the port.
            trans: Placement to copy into the new port.

        Returns:
            The new port attached to this cell.
        """
        port = CellPort(
            name=name, cross_section=cross_section, transformation=trans.dup()
        )
        self.ports.append(port)
        return port

    def add_port(self, port: Port, name: str | None = None) -> CellPort:
        """Copy a port and commit the copy in this cell's session.

        Args:
            port: Source port to copy.
            name: Replacement name for the copy, if supplied.

        Returns:
            The saved copy.
        """
        session = get_context_session(self)
        port = port.dup()
        if name is not None:
            port.name = name
        session.add(port)
        session.commit()
        return port

    def called_cells(self) -> list[Cell]:
        """Return each persisted descendant cell once, excluding this cell."""
        descendants = (
            select(Instance.cell_id)
            .where(Instance.parent_cell_id == self.id)
            .cte("descendants", recursive=True)
        )

        descendants = descendants.union(
            select(Instance.cell_id).join(
                descendants, col(Instance.parent_cell_id) == descendants.c.cell_id
            )
        )
        session = get_context_session(self)

        return list(
            session.scalars(
                select(Cell)
                .join(descendants, col(Cell.id) == descendants.c.cell_id)
                .where(Cell.id != self.id)
            ).all()
        )

    def instance_graph_edges(
        self,
    ) -> list[Row[Instance, str, str, bool, bool]]:
        """Query placements in this cell's ancestor and descendant graph.

        Returns:
            Rows containing an instance, its parent and child names, and flags
            identifying whether the edge lies in the ancestor or descendant graph.

        Raises:
            ValueError: If the cell has no persisted ID.
        """
        if self.id is None:
            raise ValueError(
                "Cell must be persisted before querying its instance graph"
            )

        ancestors = (
            select(col(Cell.id).label("cell_id"))
            .where(Cell.id == self.id)
            .cte("ancestors", recursive=True)
        )
        ancestors = ancestors.union(
            select(Instance.parent_cell_id)
            .join(ancestors, col(Instance.cell_id) == ancestors.c.cell_id)
            .where(col(Instance.parent_cell_id).is_not(None))
        )

        descendants = (
            select(col(Cell.id).label("cell_id"))
            .where(Cell.id == self.id)
            .cte("descendants", recursive=True)
        )
        descendants = descendants.union(
            select(Instance.cell_id)
            .join(descendants, col(Instance.parent_cell_id) == descendants.c.cell_id)
            .where(col(Instance.cell_id).is_not(None))
        )

        parent = aliased(Cell)
        child = aliased(Cell)
        ancestor_edge = ancestors.c.cell_id.is_not(None)
        descendant_edge = descendants.c.cell_id.is_not(None)
        statement = (
            sa_select(
                Instance,
                col(parent.name),
                col(child.name),
                ancestor_edge,
                descendant_edge,
            )
            .join(parent, col(Instance.parent_cell_id) == col(parent.id))
            .join(child, col(Instance.cell_id) == col(child.id))
            .outerjoin(ancestors, col(Instance.cell_id) == ancestors.c.cell_id)
            .outerjoin(
                descendants, col(Instance.parent_cell_id) == descendants.c.cell_id
            )
            .where(or_(ancestor_edge, descendant_edge))
            .order_by(col(Instance.id))
        )
        return list(get_context_session(self).execute(statement).all())

    def write(
        self, path: Path | str, options: kdb.SaveLayoutOptions | None = None
    ) -> None:
        """Export this cell and its referenced hierarchy to a layout file.

        Args:
            path: Destination path. KLayout infers the format from its extension.
            options: Reserved save options. The current implementation uses KLayout
                defaults.
        """
        path = Path(path)
        ly = kdb.Layout()
        ly.dbu = settings.dbu
        cells = [self, *self.called_cells()]
        for cell in cells:
            c = ly.create_cell(cell.name)
            c.copy_shapes(cell.geometry.kdb_cell)

        for cell in cells:
            c = ly.cell(cell.name)
            for inst in cell.instances:
                ca = kdb.CellInstArray(ly.cell(inst.cell.name), trans=inst.cplx_trans)
                if inst.na > 0 or inst.nb > 0:
                    ca.a = inst.a
                    ca.b = inst.b
                    ca.na = inst.na
                    ca.nb = inst.nb
                c.insert(ca)

        ly.write(str(path))


class CellInfo(SQLModel, table=True):
    id: int | None = Field(foreign_key="cell.id", primary_key=True)
    cell: Cell = Relationship(back_populates="info")
    data: dict[str, JSONSerializable] = Field(default_factory=dict, sa_type=JSON)

    def __getitem__(self, name: str) -> JSONSerializable:
        """Return the metadata value stored under a key."""
        return self.data[name]

    def __setitem__(self, name: str, value: JSONSerializable) -> None:
        """Store a metadata value under a key."""
        self.data[name] = value


class CellSettings(SQLModel, table=True):
    id: int | None = Field(foreign_key="cell.id", primary_key=True)
    cell: Cell = Relationship(back_populates="settings")
    data: dict[str, JSONSerializable] = Field(default_factory=dict, sa_type=JSON)

    def __getitem__(self, name: str) -> JSONSerializable:
        """Return the factory parameter stored under a key."""
        return self.data[name]

    def __setitem__(self, name: str, value: JSONSerializable) -> None:
        """Store a factory parameter under a key."""
        self.data[name] = value


def create_cell(
    name: str | None = None, pdk: Pdk | None = None, *, persist: bool = True
) -> Cell:
    """Create an empty cell with geometry, metadata, and settings.

    Args:
        name: Explicit cell name, or None to consume the active PCell's automatic name.
        pdk: Optional process design kit that owns the cell.
        persist: Whether to add the cell to the current session for a later commit.

    Returns:
        The newly initialized cell.

    Raises:
        CellNameError: If a name is required and the automatic name is unavailable.
    """
    if name is None:
        name = automatic_cell_name.get()
        if name is None:
            raise CellNameError(
                "Another cell already took the automatic created cell name. Make sure "
                r"there is only one `create_cell()` call within a `@pcell` block"
            )
        automatic_cell_name.set(None)

    cell = Cell(name=name, pdk=pdk)
    cell.info = CellInfo(id=None)
    cell.settings = CellSettings(id=None)
    cell.geometry = Geometry(id=None)
    if persist:
        get_session().add(cell)
    return cell


def flatten_inst_into(
    cell: Cell,
    instance: Instance,
    cell_dict: dict[str, Cell],
    cell_shapes: dict[str, list[tuple[int, int, kdb.Region, kdb.Texts]]],
    trans: kdb.ICplxTrans,
) -> None:
    """Copy one referenced cell's regions and text and recurse into its children.

    Args:
        cell: Target cell receiving the copied geometry.
        instance: Instance whose referenced cell supplies the geometry.
        cell_dict: Cell lookup carried through the recursion.
        cell_shapes: Cache of source regions and text grouped by layer and cell name.
        trans: Accumulated transform applied in the target cell's coordinates.
    """
    insert_cell = instance.cell
    insert_cell_name = insert_cell.name
    if insert_cell_name not in cell_shapes:
        cell_shapes_ = []
        ly = insert_cell.geometry.layout
        c = insert_cell.geometry.kdb_cell
        for layer_index in ly.layer_indexes():
            layer = ly.get_info(layer_index)
            r = kdb.Region(c.shapes(layer))
            t = kdb.Texts(c.shapes(layer))
            cell_shapes_.append((layer.layer, layer.datatype, r, t))
        cell_shapes[insert_cell_name] = cell_shapes_
    else:
        ly = insert_cell.geometry.layout
        cell_shapes_ = cell_shapes[insert_cell_name]
    for layer, datatype, region, texts in cell_shapes_:
        layer_ = kdb.LayerInfo(layer, datatype)
        cell.shapes(layer_).insert(region.transformed(trans))
        cell.shapes(layer_).insert(texts.transformed(trans))
    for instance_ in insert_cell.instances:
        flatten_inst_into(
            cell=cell,
            instance=instance_,
            cell_dict=cell_dict,
            cell_shapes=cell_shapes,
            trans=trans * instance_.cplx_trans,
        )


class FillOperator(kdb.TileOutputReceiver):
    """Collect KLayout's compact fill arrays before the database commit."""

    def __init__(
        self,
        cell: Cell,
        fill_cell: Cell,
        fc_bbox: kdb.Box,
        origin: kdb.Point,
        row_step: kdb.Vector,
        column_step: kdb.Vector,
        multi: bool = False,
    ) -> None:
        """Start collecting compact arrays in a temporary KLayout layout.

        Args:
            cell: Target cell that will receive the fill instances.
            fill_cell: Repeated fill pattern.
            fc_bbox: Pattern footprint in DBU.
            origin: Grid origin for single-region fill.
            row_step: First array pitch vector in DBU.
            column_step: Second array pitch vector in DBU.
            multi: Whether to use KLayout's multi-region fill.
        """
        self.cell = cell
        self.fc = fill_cell
        self.fc_bbox = fc_bbox
        self.row_step = row_step
        self.column_step = column_step
        self.multi = multi
        self.origin = origin
        self.temp_ly = kdb.Layout()
        self.temp_ly.dbu = cell.dbu
        self.temp_tc = self.temp_ly.create_cell("MASKYARD_FILL_TARGET")
        self.temp_fc = self.temp_ly.create_cell("MASKYARD_FILL_PATTERN")
        self.temp_fc_ind = self.temp_fc.cell_index()
        self.temp_ly.start_changes()

    def put(
        self,
        ix: int,
        iy: int,
        tile: kdb.Box,
        region: kdb.Region,
        dbu: float,
        clip: bool,
    ) -> None:
        """Pack one processed tile into arrays in the temporary layout.

        Args:
            ix: Horizontal tile index supplied by KLayout.
            iy: Vertical tile index supplied by KLayout.
            tile: Tile bounds used to join arrays across tile edges.
            region: Eligible fill area returned by the tiling script.
            dbu: Database unit of the tiling processor.
            clip: Clipping flag supplied by the tiling processor.
        """
        if self.multi:
            self.temp_tc.fill_region_multi(
                region=region,
                fill_cell_index=self.temp_fc_ind,
                fc_bbox=self.fc_bbox,
                row_step=self.row_step,
                column_step=self.column_step,
                fill_margin=kdb.Vector(
                    max(0, self.row_step.x - self.fc_bbox.width()),
                    max(0, self.column_step.y - self.fc_bbox.height()),
                ),
                remaining_polygons=None,
                glue_box=tile,
            )
        else:
            self.temp_tc.fill_region(
                region=region,
                fill_cell_index=self.temp_fc_ind,
                fc_bbox=self.fc_bbox,
                row_step=self.row_step,
                column_step=self.column_step,
                origin=self.origin,
                remaining_parts=None,
                fill_margin=kdb.Vector(0, 0),
                remaining_polygons=None,
                glue_box=tile,
            )

    def insert_fill(self) -> kdb.Box:
        """Attach unnamed fill arrays and return their combined bounds."""
        self.temp_ly.end_changes()
        insts: list[Instance] = []
        bounds = kdb.Box()
        for inst in self.temp_tc.each_inst():
            transformed_bbox = self.fc_bbox.transformed(inst.cplx_trans)
            for ia in (0, inst.na - 1):
                for ib in (0, inst.nb - 1):
                    offset = kdb.Vector(
                        ia * inst.a.x + ib * inst.b.x,
                        ia * inst.a.y + ib * inst.b.y,
                    )
                    bounds += transformed_bbox.moved(offset)
            if inst.na > 1 or inst.nb > 1:
                insts.append(
                    Instance(
                        name=None,
                        cplx_trans=inst.cplx_trans,
                        virtual=False,
                        a=inst.a,
                        na=inst.na,
                        b=inst.b,
                        nb=inst.nb,
                        cell=self.fc,
                    )
                )
            else:
                insts.append(
                    Instance(
                        name=None,
                        cplx_trans=inst.cplx_trans,
                        virtual=False,
                        cell=self.fc,
                    )
                )
        self.cell.instances.extend(insts)
        return bounds


def fill_tiled(
    c: Cell,
    fill_cell: Cell,
    *,
    fill_layers: Iterable[tuple[kdb.LayerInfo, int]] = (),
    fill_regions: Iterable[tuple[kdb.Region, int]] = (),
    exclude_layers: Iterable[tuple[kdb.LayerInfo, int]] = (),
    exclude_regions: Iterable[tuple[kdb.Region, int]] = (),
    n_threads: int | None = None,
    tile_size: tuple[int, int] | None = None,
    row_step: kdb.Vector | None = None,
    col_step: kdb.Vector | None = None,
    x_space: int = 0,
    y_space: int = 0,
    tile_border: tuple[int, int] | None = None,
    multi: bool = False,
) -> None:
    """Fill a cell with unnamed instances of another cell.

    Sizes, distances, regions, and vectors use integer database units. New cells are
    saved first, then generated instances are committed as one batch.

    Args:
        c: Target cell whose regions or layers are filled.
        fill_cell: Cell whose bounding box defines the fill footprint.
        fill_layers: Layer and signed margin pairs to include.
        fill_regions: Region and signed margin pairs to include. With no inclusion
            inputs, the target bounds are used.
        exclude_layers: Layer and signed margin pairs to subtract.
        exclude_regions: Region and signed margin pairs to subtract.
        n_threads: Positive worker count, or None to use the KLayout default.
        tile_size: Processing tile width and height. Defaults to 100 nominal pitches per
            axis.
        row_step: First array pitch vector. Defaults to the pattern width plus x_space
            along X.
        col_step: Second array pitch vector. Defaults to the pattern height plus y_space
            along Y.
        x_space: Extra spacing in the default horizontal pitch.
        y_space: Extra spacing in the default vertical pitch.
        tile_border: Minimum tile border in X and Y. The border is expanded as needed
            for the pattern and margins.
        multi: Whether to use KLayout's multi-region fill to pack separate polygons.

    Raises:
        TypeError: If a DBU dimension or step vector has the wrong type.
        ValueError: If the fill would create a cycle, the cells belong to different
            sessions, or the fill area, footprint, pitch, tile dimensions, or worker
            count is invalid.
    """

    def require_dbu(value: int, name: str) -> int:
        """Require a plain integer for a dimension expressed in DBU."""
        if type(value) is not int:
            raise TypeError(f"{name} must be an integer number of DBU")
        return value

    if c is fill_cell:
        raise ValueError("A cell cannot fill itself")
    target_session = object_session(c)
    fill_session = object_session(fill_cell)
    if (
        target_session is not None
        and fill_session is not None
        and target_session is not fill_session
    ):
        raise ValueError("Target and fill cells must use the same session")
    session = target_session or fill_session or get_session()
    needs_setup_commit = c.id is None or fill_cell.id is None
    session.add_all((c, fill_cell))
    if needs_setup_commit:
        session.commit()

    if c.id == fill_cell.id or any(
        child.id == c.id for child in fill_cell.called_cells()
    ):
        raise ValueError("Filling would create a cell instance cycle")

    fill_layers = tuple(fill_layers)
    fill_regions = tuple(fill_regions)
    exclude_layers = tuple(exclude_layers)
    exclude_regions = tuple(exclude_regions)
    x_space = require_dbu(x_space, "x_space")
    y_space = require_dbu(y_space, "y_space")

    _target_ly, target_kdb = c._get_kdb_cell()
    _pattern_ly, pattern_kdb = fill_cell._get_kdb_cell()
    target_bbox = target_kdb.bbox()
    fc_bbox = pattern_kdb.bbox()
    if fc_bbox.empty() or fc_bbox.width() <= 0 or fc_bbox.height() <= 0:
        raise ValueError("Fill cell must have a nonempty, two-dimensional footprint")

    if not fill_layers and not fill_regions:
        if target_bbox.empty():
            raise ValueError("A cell with empty bounds needs a fill layer or region")
        fill_regions = ((kdb.Region(target_bbox), 0),)

    frame = target_bbox.dup()
    largest_margin = 0
    for _, margin in (*fill_layers, *fill_regions, *exclude_layers, *exclude_regions):
        largest_margin = max(largest_margin, abs(require_dbu(margin, "margin")))
    layer_margin = max(
        (require_dbu(margin, "fill layer margin") for _, margin in fill_layers),
        default=0,
    )
    if not frame.empty() and layer_margin > 0:
        frame = frame.enlarged(layer_margin)
    for region, margin in fill_regions:
        frame += region.bbox().enlarged(max(0, margin))
    if frame.empty():
        raise ValueError("Fill area is empty")

    if row_step is not None and not isinstance(row_step, kdb.Vector):
        raise TypeError("row_step must be a kdb.Vector in DBU")
    if col_step is not None and not isinstance(col_step, kdb.Vector):
        raise TypeError("col_step must be a kdb.Vector in DBU")
    if row_step is None:
        row_step = kdb.Vector(fc_bbox.width() + x_space, 0)
    if col_step is None:
        col_step = kdb.Vector(0, fc_bbox.height() + y_space)
    if row_step.x <= 0 or col_step.y <= 0:
        raise ValueError("Fill row and column steps must have positive pitch")
    if row_step.x * col_step.y - row_step.y * col_step.x <= 0:
        raise ValueError("Fill row and column steps must span a positive area")

    if tile_size is None:
        tile_size = (
            100 * (fc_bbox.width() + x_space),
            100 * (fc_bbox.height() + y_space),
        )
    tile_width, tile_height = (
        require_dbu(tile_size[0], "tile width"),
        require_dbu(tile_size[1], "tile height"),
    )
    if tile_width <= 0 or tile_height <= 0:
        raise ValueError("Tile size must be positive")
    if tile_border is None:
        tile_border = (0, 0)
    border_x, border_y = (
        require_dbu(tile_border[0], "tile border x"),
        require_dbu(tile_border[1], "tile border y"),
    )
    if border_x < 0 or border_y < 0:
        raise ValueError("Tile border must be nonnegative")
    border_x = max(border_x, fc_bbox.width() + largest_margin)
    border_y = max(border_y, fc_bbox.height() + largest_margin)

    dbu = c.dbu
    tp = kdb.TilingProcessor()
    tp.dbu = dbu
    tp.frame = frame.to_dtype(dbu)  # ty: ignore[invalid-assignment]
    if n_threads is not None:
        if type(n_threads) is not int or n_threads < 1:
            raise ValueError("n_threads must be a positive integer")
        tp.threads = n_threads
    tp.tile_size(tile_width * dbu, tile_height * dbu)
    tp.tile_border(border_x * dbu, border_y * dbu)

    positive_terms: list[str] = []
    exclude_terms: list[str] = []
    for prefix, layers, regions, terms in (
        ("fill", fill_layers, fill_regions, positive_terms),
        ("exclude", exclude_layers, exclude_regions, exclude_terms),
    ):
        for index, (layer, margin) in enumerate(layers):
            name = f"{prefix}_layer_{index}"
            tp.input(name, target_kdb.layout(), target_kdb.cell_index(), layer)
            terms.append(f"{name}.sized({margin})" if margin else name)
        for index, (region, margin) in enumerate(regions):
            name = f"{prefix}_region_{index}"
            tp.input(name, region)
            terms.append(f"{name}.sized({margin})" if margin else name)

    operator = FillOperator(
        c,
        fill_cell,
        fc_bbox=fc_bbox,
        row_step=row_step,
        column_step=col_step,
        origin=frame.p1,
        multi=multi,
    )
    tp.output("to_fill", operator)
    fill_expression = " + ".join(positive_terms)
    script = (
        f"var fill = {fill_expression}; "
        "var fill_region = _tile.minkowski_sum(Box.new("
        f"0,0,{fc_bbox.width() - 1},{fc_bbox.height() - 1}))"
        " & _frame & fill"
    )
    if exclude_terms:
        script += f" - ({' + '.join(exclude_terms)})"
    script += "; _output(to_fill, fill_region)"
    tp.queue(script)
    tp.execute(f"Fill {c.name}")

    operator.insert_fill()
    session.commit()
