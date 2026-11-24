"""FastAPI entry point for the MaskYard web interface."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import col, select
from starlette.middleware.gzip import GZipMiddleware

from maskyard.config import settings
from maskyard.engine import session_context
from maskyard.models.cell import Cell, CellInfo, CellSettings
from maskyard.models.factory import PCellFactory
from maskyard.models.instance import Instance

from .layer_styles import load_layer_styles
from .render_cache import box_data, cache_dir, get_cell_cache, load_cache_index

_WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="MaskYard")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount(
    "/static",
    StaticFiles(directory=str(_WEB_DIR / "static")),
    name="static",
)
_templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the home page."""
    with session_context() as session:
        rows = session.exec(
            select(Cell, PCellFactory)
            .outerjoin(PCellFactory, col(Cell.pcell_factory_id) == col(PCellFactory.id))
            .order_by(
                col(PCellFactory.name),
                col(PCellFactory.id),
                col(Cell.name),
                col(Cell.id),
            )
        ).all()

    grouped: dict[int | None, tuple[PCellFactory | None, list[Cell]]] = {}
    for cell, factory in rows:
        factory_id = factory.id if factory is not None else None
        if factory_id not in grouped:
            grouped[factory_id] = (factory, [])
        grouped[factory_id][1].append(cell)

    return _templates.TemplateResponse(
        request=request, name="index.html", context={"groups": list(grouped.values())}
    )


@app.get("/cells/{cell_id}", response_class=HTMLResponse, name="cell_page")
def cell_page(request: Request, cell_id: int) -> HTMLResponse:
    """Show a cell's instance graph, info, and settings."""
    with session_context() as session:
        cell = session.get(Cell, cell_id)
        if cell is None:
            raise HTTPException(status_code=404, detail="Cell not found")
        info = session.get(CellInfo, cell_id)
        settings = session.get(CellSettings, cell_id)
        info_data = info.data if info is not None else None
        settings_data = settings.data if settings is not None else None

        nodes = {
            cell_id: {
                "data": {"id": str(cell_id), "label": f"{cell.name} (#{cell_id})"},
                "classes": "selected",
            }
        }
        edge_by_pair: dict[tuple[int, int], dict] = {}
        rows = []
        for instance, parent_name, child_name, _, _ in cell.instance_graph_edges():
            parent_id = instance.parent_cell_id
            child_id = instance.cell_id
            if parent_id is None or child_id is None or instance.id is None:
                continue
            nodes.setdefault(
                parent_id,
                {
                    "data": {
                        "id": str(parent_id),
                        "label": f"{parent_name} (#{parent_id})",
                    }
                },
            )
            nodes.setdefault(
                child_id,
                {"data": {"id": str(child_id), "label": f"{child_name} (#{child_id})"}},
            )
            label = instance.name or f"Instance #{instance.id}"
            edge = edge_by_pair.setdefault(
                (parent_id, child_id),
                {
                    "data": {
                        "id": f"cells-{parent_id}-{child_id}",
                        "source": str(parent_id),
                        "target": str(child_id),
                        "instances": [],
                    }
                },
            )
            transform = instance.cplx_trans
            edge["data"]["instances"].append(
                {
                    "id": instance.id,
                    "label": label,
                    "x": transform.disp.x,
                    "y": transform.disp.y,
                    "angle": transform.angle,
                    "mirror": transform.mirror,
                    "na": max(instance.na, 1),
                    "nb": max(instance.nb, 1),
                }
            )
            if parent_id == cell_id:
                rows.append((label, child_id, child_name, transform))
        edges = list(edge_by_pair.values())
        for edge in edges:
            count = len(edge["data"]["instances"])
            edge["data"]["countLabel"] = f"{count} instances" if count > 1 else ""
        graph_limited = len(edges) > 1000
        if graph_limited:
            selected = str(cell_id)
            edges = [
                edge
                for edge in edges
                if edge["data"]["source"] == selected
                or edge["data"]["target"] == selected
            ]
            visible_nodes = {selected}
            for edge in edges:
                visible_nodes.add(edge["data"]["source"])
                visible_nodes.add(edge["data"]["target"])
            nodes = {
                id_: node for id_, node in nodes.items() if str(id_) in visible_nodes
            }
    return _templates.TemplateResponse(
        request=request,
        name="cell.html",
        context={
            "cell": cell,
            "graph": list(nodes.values()) + edges,
            "graph_limited": graph_limited,
            "instance_rows": rows,
            "info_data": info_data,
            "settings_data": settings_data,
        },
    )


def _render_index() -> dict:
    try:
        return load_cache_index()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/cells/{cell_id}/layout", name="cell_layout_manifest")
def cell_layout_manifest(cell_id: int) -> dict:
    """Return hierarchy metadata without generating geometry for descendants."""
    index = _render_index()
    try:
        layer_styles = load_layer_styles(settings.layout_layer_properties)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    with session_context() as session:
        cell = session.get(Cell, cell_id)
        if cell is None:
            raise HTTPException(status_code=404, detail="Cell not found")
        models = {model.id: model for model in [cell, *cell.called_cells()]}
        ids = list(models)
        bounds = {id_: box_data(model.bbox()) for id_, model in models.items()}
        cells = {
            str(id_): {
                "bbox": bounds[id_],
                "layers": index["cells"].get(str(id_), {}).get("layers", []),
                "instances": [],
            }
            for id_, model in models.items()
        }
        # Keep the query below SQLite's older 999-variable limit.
        for offset in range(0, len(ids), 500):
            for instance in session.exec(
                select(Instance).where(
                    col(Instance.parent_cell_id).in_(ids[offset : offset + 500])
                )
            ):
                if instance.cell_id not in models or instance.parent_cell_id is None:
                    continue
                transform = instance.cplx_trans
                cells[str(instance.parent_cell_id)]["instances"].append(
                    {
                        "cell": str(instance.cell_id),
                        "transform": {
                            "x": transform.disp.x,
                            "y": transform.disp.y,
                            "angle": transform.angle,
                            "mag": transform.mag,
                            "mirror": transform.is_mirror(),
                        },
                        "a": [instance.a.x, instance.a.y],
                        "b": [instance.b.x, instance.b.y],
                        "na": max(instance.na, 1),
                        "nb": max(instance.nb, 1),
                    }
                )
        return {
            "root": str(cell_id),
            "dbu": settings.dbu,
            "bounds": bounds[cell_id],
            "layerStyles": layer_styles,
            "cells": cells,
        }


@app.get("/cells/{cell_id}/layout/geometry", name="cell_layout_geometry")
def cell_layout_geometry(cell_id: int) -> dict:
    """Generate and return one cell's binary chunk manifest on demand."""
    try:
        return get_cell_cache(cell_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/cells/{cell_id}/layout/chunks/{layer_number}/{chunk_number}")
def cell_layout_chunk(cell_id: int, layer_number: int, chunk_number: int) -> Response:
    """Serve one stored binary shape chunk."""
    try:
        layers = get_cell_cache(cell_id)["layers"]
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not 0 <= layer_number < len(layers):
        raise HTTPException(status_code=404, detail="Layer not found")
    chunks = layers[layer_number]["chunks"]
    if not 0 <= chunk_number < len(chunks):
        raise HTTPException(status_code=404, detail="Chunk not found")
    path = cache_dir() / str(cell_id) / Path(chunks[chunk_number]["file"]).name
    if not path.is_file():
        layers = get_cell_cache(cell_id, force=True)["layers"]
        if not 0 <= layer_number < len(layers):
            raise HTTPException(status_code=404, detail="Layer not found")
        chunks = layers[layer_number]["chunks"]
        if not 0 <= chunk_number < len(chunks):
            raise HTTPException(status_code=404, detail="Chunk not found")
        path = cache_dir() / str(cell_id) / Path(chunks[chunk_number]["file"]).name
        if not path.is_file():
            raise HTTPException(
                status_code=503, detail="Could not generate render chunk"
            )
    return Response(
        content=path.read_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Encoding": "gzip"},
    )
