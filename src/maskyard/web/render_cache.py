"""Build and read compact, spatially chunked layout shapes for the web viewer.

Chunk format (little endian): ``MYB1`` followed by records. A box is tag 1
and four signed 32-bit coordinates. A polygon is tag 2, a ring count, then
point counts and signed 32-bit x/y pairs. Text is tag 3, its position, angle,
mirror flag, size, and UTF-8 bytes. Instances stay in the database.
"""

from __future__ import annotations

import gzip
import json
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import uuid4

import klayout.db as kdb
from sqlalchemy.engine import make_url
from sqlmodel import col, select

from maskyard.config import settings
from maskyard.engine import session_context
from maskyard.models.cell import Cell
from maskyard.models.geometry import Geometry

if TYPE_CHECKING:
    from collections.abc import Iterable


class _ChunkData(TypedDict):
    file: str
    bbox: list[int] | None
    shapes: int


class CachedLayer(TypedDict):
    id: str
    label: str
    shapes: int
    chunks: list[_ChunkData]


class CellCache(TypedDict):
    layers: list[CachedLayer]


class _CellIndex(TypedDict):
    version: int
    dbu: float
    database_stamp: int | None
    cell: CellCache


class CacheIndex(TypedDict):
    version: int
    dbu: float
    cells: dict[str, CellCache]


FORMAT_VERSION = 1
MAX_CHUNK_BYTES = 256 * 1024
_cell_locks_guard = Lock()
_cell_locks: dict[int, Lock] = {}


def cache_dir() -> Path:
    """Resolve the configured render cache directory or derive it from the database."""
    if settings.layout_cache_dir is not None:
        return settings.layout_cache_dir.resolve()
    database = make_url(settings.database_url)
    if database.get_backend_name() == "sqlite" and database.database not in (
        None,
        ":memory:",
    ):
        return Path(database.database).resolve().with_suffix(".layout-cache")
    return Path("maskyard.layout-cache").resolve()


def box_data(box: kdb.Box) -> list[int] | None:
    """Return the box edges in DBU, or None for an empty box."""
    if box.empty():
        return None
    return [box.left, box.bottom, box.right, box.top]


def _points(points: Iterable[kdb.Point]) -> list[kdb.Point]:
    """Materialize the points of a polygon ring for binary encoding."""
    return list(points)


def _shape_record(shape: kdb.Shape) -> bytes | None:
    """Encode a supported KLayout shape as one binary record."""
    if shape.is_box():
        box = shape.box
        return struct.pack("<B4i", 1, box.left, box.bottom, box.right, box.top)

    if shape.is_polygon():
        polygon = shape.polygon
        rings = [_points(polygon.each_point_hull())]
        rings.extend(
            _points(polygon.each_point_hole(i)) for i in range(polygon.holes())
        )
    elif shape.is_simple_polygon():
        rings = [_points(shape.simple_polygon.each_point())]
    elif shape.is_path():
        polygon = shape.path.polygon()
        rings = [_points(polygon.each_point_hull())]
        rings.extend(
            _points(polygon.each_point_hole(i)) for i in range(polygon.holes())
        )
    elif shape.is_text():
        label = shape.text
        encoded = label.string.encode("utf-8")
        return (
            struct.pack(
                "<BiiBBiI",
                3,
                label.trans.disp.x,
                label.trans.disp.y,
                label.trans.angle,
                int(label.trans.is_mirror()),
                label.size,
                len(encoded),
            )
            + encoded
        )
    else:
        return None

    data = bytearray(struct.pack("<BI", 2, len(rings)))
    for ring in rings:
        data.extend(struct.pack("<I", len(ring)))
        for point in ring:
            data.extend(struct.pack("<ii", point.x, point.y))
    return bytes(data)


@dataclass
class _Chunk:
    payload: bytearray = field(default_factory=lambda: bytearray(b"MYB1"))
    bbox: kdb.Box = field(default_factory=kdb.Box)
    shapes: int = 0

    def add(self, record: bytes, bounds: kdb.Box) -> None:
        """Append a shape record and expand the chunk's bounds and shape count."""
        self.payload.extend(record)
        self.bbox += bounds
        self.shapes += 1


def _flush_chunk(
    tile: tuple[int, int],
    tiles: dict[tuple[int, int], _Chunk],
    layer: CachedLayer,
    layer_index: int,
    cell_dir: Path,
) -> None:
    """Publish a compressed tile chunk and append its layer index entry."""
    chunk = tiles.pop(tile)
    number = len(layer["chunks"])
    filename = f"{layer_index}_{number}.bin.gz"
    output = cell_dir / filename
    temporary = cell_dir / f".{filename}.{uuid4().hex}.tmp"
    temporary.write_bytes(gzip.compress(bytes(chunk.payload), compresslevel=4, mtime=0))
    temporary.replace(output)
    layer["chunks"].append(
        {"file": filename, "bbox": box_data(chunk.bbox), "shapes": chunk.shapes}
    )


def _build_cell_layout(cell_id: int, layout: kdb.Layout) -> CellCache:
    """Encode the local TOP geometry into spatially tiled layer chunks."""
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    tile_size = max(1, round(500 / settings.dbu))
    cell = layout.cell("TOP")
    layers = []
    cell_dir = root / str(cell_id)
    cell_dir.mkdir(exist_ok=True)
    for layer_index in layout.layer_indices():
        shapes = cell.shapes(layer_index)
        if shapes.is_empty():
            continue
        info = layout.get_info(layer_index)
        label = f"{info.layer}/{info.datatype}"
        if info.name:
            label = f"{info.name} ({label})"
        layer: CachedLayer = {
            "id": f"{info.layer}/{info.datatype}",
            "label": label,
            "shapes": 0,
            "chunks": [],
        }
        tiles: dict[tuple[int, int], _Chunk] = defaultdict(_Chunk)

        for shape in shapes.each():
            record = _shape_record(shape)
            if record is None:
                continue
            bounds = shape.bbox()
            tile = (
                (bounds.left + bounds.right) // (2 * tile_size),
                (bounds.bottom + bounds.top) // (2 * tile_size),
            )
            chunk = tiles[tile]
            if chunk.shapes and len(chunk.payload) + len(record) > MAX_CHUNK_BYTES:
                _flush_chunk(tile, tiles, layer, layer_index, cell_dir)
                chunk = tiles[tile]
            chunk.add(record, bounds)
            layer["shapes"] += 1
        for tile in list(tiles):
            _flush_chunk(tile, tiles, layer, layer_index, cell_dir)
        if layer["shapes"]:
            layers.append(layer)
    return {"layers": layers}


def _database_stamp() -> int | None:
    """Return a conservative SQLite change stamp for automatic invalidation."""
    database = make_url(settings.database_url)
    if database.get_backend_name() != "sqlite" or database.database in (
        None,
        ":memory:",
    ):
        return None
    path = Path(database.database).resolve()
    return max(
        (
            candidate.stat().st_mtime_ns
            for candidate in (path, Path(f"{path}-wal"))
            if candidate.exists()
        ),
        default=None,
    )


@lru_cache(maxsize=256)
def _read_cell_index(path: Path, _modified_ns: int) -> _CellIndex:
    """Read the per-cell manifest, caching it by path and modification time."""
    return cast("_CellIndex", json.loads(path.read_text()))


def _valid_cell_index(path: Path, stamp: int | None) -> CellCache | None:
    """Reuse a per-cell manifest if its format, DBU, and database stamp match."""
    if not path.is_file():
        return None
    value = _read_cell_index(path, path.stat().st_mtime_ns)
    if (
        value.get("version") == FORMAT_VERSION
        and value.get("dbu") == settings.dbu
        and (stamp is None or value.get("database_stamp") == stamp)
    ):
        return value["cell"]
    return None


def get_cell_cache(cell_id: int, *, force: bool = False) -> CellCache:
    """Return or build the render cache for one cell.

    Args:
        cell_id: Database ID of the cell whose local geometry is requested.
        force: Whether to rebuild the chunks even when a current index exists.

    Returns:
        The cell's layers and binary chunk descriptors.

    Raises:
        LookupError: If the cell ID is missing from the database.
    """
    stamp = _database_stamp()
    cell_dir = cache_dir() / str(cell_id)
    path = cell_dir / "index.json"
    if not force:
        cached = _valid_cell_index(path, stamp)
        if cached is not None:
            return cached
        global_path = cache_dir() / "index.json"
        if global_path.is_file() and (
            stamp is None or global_path.stat().st_mtime_ns >= stamp
        ):
            global_index = load_cache_index()
            cached = global_index["cells"].get(str(cell_id))
            if cached is not None:
                return cached

    with _cell_locks_guard:
        lock = _cell_locks.setdefault(cell_id, Lock())
    with lock:
        stamp = _database_stamp()
        if not force:
            cached = _valid_cell_index(path, stamp)
            if cached is not None:
                return cached
        with session_context() as session:
            model = session.get(Cell, cell_id)
            if model is None:
                raise LookupError(f"Cell {cell_id} does not exist")
            geometry = session.get(Geometry, cell_id)
            layout = geometry.layout if geometry is not None else kdb.Layout()
            cached = _build_cell_layout(cell_id, layout)
        cell_dir.mkdir(parents=True, exist_ok=True)
        temporary = cell_dir / f".index.{uuid4().hex}.tmp"
        temporary.write_text(
            json.dumps(
                {
                    "version": FORMAT_VERSION,
                    "dbu": settings.dbu,
                    "database_stamp": stamp,
                    "cell": cached,
                },
                separators=(",", ":"),
            )
        )
        temporary.replace(path)
        return cached


def build_cache() -> CacheIndex:
    """Precompute layout chunks for persisted cells that have geometry.

    Publish a global index and remove binary chunks it no longer references.

    Returns:
        The global index mapping cell IDs to their cache entries.
    """
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    index: CacheIndex = {
        "version": FORMAT_VERSION,
        "dbu": settings.dbu,
        "cells": {},
    }

    with session_context() as session:
        rows = session.exec(
            select(col(Cell.id), col(Geometry.layout)).join(
                Geometry, col(Cell.id) == Geometry.id
            )
        )
        for cell_id, layout in rows:
            if cell_id is None:
                continue
            index["cells"][str(cell_id)] = _build_cell_layout(cell_id, layout)

    output = root / "index.json"
    temporary = root / "index.json.tmp"
    temporary.write_text(json.dumps(index, separators=(",", ":")))
    temporary.replace(output)
    # Remove chunks superseded by the completed index, including old builds.
    referenced = {
        root / cell_id / chunk["file"]
        for cell_id, cell_data in index["cells"].items()
        for layer in cell_data["layers"]
        for chunk in layer["chunks"]
    }
    for pattern in ("*/*.bin", "*/*.bin.gz"):
        for path in root.glob(pattern):
            if path not in referenced:
                path.unlink()
    _read_cache_index.cache_clear()
    return index


@lru_cache(maxsize=4)
def _read_cache_index(path: Path, _modified_ns: int) -> CacheIndex:
    """Load the global index and validate its format version and database unit."""
    index = cast("CacheIndex", json.loads(path.read_text()))
    if index.get("version") != FORMAT_VERSION or index.get("dbu") != settings.dbu:
        raise ValueError(
            "Render cache format or DBU differs from the database; rebuild it"
        )
    return index


def load_cache_index() -> CacheIndex:
    """Load the global index, returning an empty index if missing or stale.

    Raises:
        ValueError: If the stored format version or DBU differs from the current
            settings.
    """
    path = cache_dir() / "index.json"
    if not path.is_file() or (
        (stamp := _database_stamp()) is not None and path.stat().st_mtime_ns < stamp
    ):
        return {"version": FORMAT_VERSION, "dbu": settings.dbu, "cells": {}}
    return _read_cache_index(path, path.stat().st_mtime_ns)


def main() -> None:
    """Rebuild the render cache and report where it was saved."""
    result = build_cache()
    sys.stdout.write(f"Cached {len(result['cells'])} cells at {cache_dir()}\n")


if __name__ == "__main__":
    main()
