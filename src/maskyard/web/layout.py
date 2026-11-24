"""Convert persisted cell geometry into browser-friendly layout shapes."""

from collections.abc import Iterable
from typing import Any

import klayout.db as kdb

from maskyard.config import settings
from maskyard.models.cell import Cell


def _coordinates(points: Iterable[kdb.Point]) -> list[int]:
    return [coordinate for point in points for coordinate in (point.x, point.y)]


def _polygon_data(polygon: kdb.Polygon) -> dict[str, Any]:
    return {
        "kind": "polygon",
        "outer": _coordinates(polygon.each_point_hull()),
        "holes": [
            _coordinates(polygon.each_point_hole(index))
            for index in range(polygon.holes())
        ],
    }


def _shape_data(shape: kdb.Shape) -> dict[str, Any] | None:
    if shape.is_box():
        box = shape.box
        return {
            "kind": "polygon",
            "outer": [
                box.left,
                box.bottom,
                box.right,
                box.bottom,
                box.right,
                box.top,
                box.left,
                box.top,
            ],
            "holes": [],
        }
    if shape.is_polygon():
        return _polygon_data(shape.polygon)
    if shape.is_simple_polygon():
        return {
            "kind": "polygon",
            "outer": _coordinates(shape.simple_polygon.each_point()),
            "holes": [],
        }
    if shape.is_path():
        return _polygon_data(shape.path.polygon())
    if shape.is_text():
        label = shape.text
        return {
            "kind": "text",
            "text": label.string,
            "x": label.trans.disp.x,
            "y": label.trans.disp.y,
            "angle": label.trans.angle * 90,
            "mirror": label.trans.is_mirror(),
            "size": label.size,
        }
    return None


def cell_layout_data(cell: Cell) -> dict[str, Any]:
    """Return local cell shapes and instance placements without flattening them."""
    if cell.id is None:
        raise ValueError("Cell must be persisted before rendering its layout")

    layout = kdb.Layout()
    layout.dbu = settings.dbu
    models = [cell, *cell.called_cells()]
    layout_cells: dict[int, kdb.Cell] = {}
    for model in models:
        if model.id is None:
            continue
        target = layout.create_cell(f"cell_{model.id}")
        layout_cells[model.id] = target
        if model.geometry is not None:
            target.copy_shapes(model.geometry.kdb_cell)

    instances_by_cell: dict[int, list[dict[str, Any]]] = {}
    for model in models:
        if model.id is None:
            continue
        parent = layout_cells[model.id]
        serialized_instances = []
        for instance in model.instances:
            if instance.cell_id is None:
                continue
            child = layout_cells.get(instance.cell_id)
            if child is None:
                continue
            array = kdb.CellInstArray(child.cell_index(), instance.cplx_trans)
            if instance.na > 0 or instance.nb > 0:
                array.a = instance.a
                array.b = instance.b
                array.na = instance.na
                array.nb = instance.nb
            parent.insert(array)
            serialized_instances.append(
                {
                    "id": instance.id,
                    "name": instance.name,
                    "cell": str(instance.cell_id),
                    "placements": [
                        {
                            "x": transform.disp.x,
                            "y": transform.disp.y,
                            "angle": transform.angle,
                            "mag": transform.mag,
                            "mirror": transform.is_mirror(),
                        }
                        for transform in array.each_cplx_trans()
                    ],
                }
            )
        instances_by_cell[model.id] = serialized_instances

    top = layout_cells[cell.id]
    bounds = top.bbox()
    cells = {}
    used_layers: dict[str, dict[str, Any]] = {}
    for model in models:
        if model.id is None:
            continue
        local_layers = []
        source = layout_cells[model.id]
        for index in layout.layer_indices():
            shapes = [
                data
                for shape in source.shapes(index).each()
                if (data := _shape_data(shape)) is not None
            ]
            if not shapes:
                continue
            layer_id = str(index)
            if layer_id not in used_layers:
                info = layout.get_info(index)
                label = f"{info.layer}/{info.datatype}"
                if info.name:
                    label = f"{info.name} ({label})"
                used_layers[layer_id] = {"id": layer_id, "label": label, "shapes": 0}
            used_layers[layer_id]["shapes"] += len(shapes)
            local_layers.append({"id": layer_id, "shapes": shapes})
        cells[str(model.id)] = {
            "layers": local_layers,
            "instances": instances_by_cell[model.id],
        }

    return {
        "dbu": layout.dbu,
        "root": str(cell.id),
        "bounds": None
        if bounds.empty()
        else [bounds.left, bounds.bottom, bounds.right, bounds.top],
        "layers": list(used_layers.values()),
        "cells": cells,
    }
