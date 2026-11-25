# MaskYard

<p align="center">
  <img src="logo.png" alt="MaskYard logo" width="360">
</p>

## Batched cell writes

Build new cells without attaching them to a worker thread's database session, then
submit them to the dedicated writer. `submit_cell` snapshots the cell on the calling
thread and returns a `Future[int]`. The future completes after the writer commits
the batch; its result is the saved cell ID.

```python
from maskyard import kdb, submit_cell
from maskyard.models.cell import create_cell

cell = create_cell("leaf", persist=False)
cell.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 100, 100))
cell_id_future = submit_cell(cell)

# Other workers can keep building cells here.
cell_id = cell_id_future.result()
```

Use `cell.add_instance(child)` and `cell.attach_port(name, cross_section)` to
attach relationships without an immediate commit. New child cells in the same
graph are saved in the parent's transaction. An already saved child can be loaded
by ID and attached before submitting the parent. Ports require a saved cross
section.

`submit_cell` uses one process-wide writer with a bounded queue. It commits up to
64 requests per transaction, or requests collected within 5 ms of the first
request. An error rolls back the entire batch and raises through every affected
future. Call `shutdown_writer()` to drain the queue explicitly; it is also called
at process exit.

For a write that must finish before the next cell can be built, pass
`flush=True` to `submit_cell`. It commits immediately instead of waiting for the
batch window. This is useful for a deep dependency chain.

For a PCell factory, `@pdk.pcell(use_writer=True)` opts into this path. The factory
must return a cell built with `pdk.create_cell(persist=False)`. This decorator
still returns a saved `Cell`, so the call waits for the writer's future before it
returns. The existing decorator behavior remains the default.

Identical PCell calls made by processes on the same host share a lock. The first
process generates and commits the cell; later callers load that committed cell.
The normalized argument key is stored in `Cell.hashkey` as versioned bytes, and
`(pcell_factory_id, hashkey)` is unique in SQL. A worker crash cannot leave a
stale in-memory claim. The lock coordinates processes on one host. The SQL constraint
also prevents duplicate keyed rows across hosts, though it cannot prevent both
hosts from doing the computation.

Without Ray, ordinary `@pdk.pcell` calls run synchronously in the calling
process. Use `ray=True` to submit PCells to Ray instead.

## Ray PCells

Install the optional `ray` extra to submit PCells to Ray. `@pdk.pcell(ray=True)`
exposes `.remote(...)`, which returns an `ObjectRef[int]` for the saved cell ID.
Equivalent calls in one process return the same ref; the database cache also
deduplicates calls made from other processes on the same host. Workers and the
driver must use the same local SQLite file. Use an absolute database URL such as
`MASKYARD_DATABASE_URL=sqlite:////srv/maskyard/build.db`.

```python
import ray
from maskyard import Cell, get_or_create_pdk

pdk = get_or_create_pdk("my_pdk")

@pdk.pcell(ray=True)
def build(width: int) -> Cell:
    return get_or_create_pdk("my_pdk").create_cell(f"width_{width}")

ray.init()
ref = build.remote(100)
cell = build.get_cell(ref)
```

`get_cell(ref)` waits for the task and loads its cell in the caller's current
database session. Keep database sessions
and ORM objects out of remote task arguments. The full example is in `test.py`.

## Web interface

Run the minimal FastAPI interface with the optional web dependencies:

```sh
uv run --extra web uvicorn maskyard.web:app --reload
```

Open `http://127.0.0.1:8000/`. The Jinja page serves bundled Bootstrap CSS and
JavaScript from the package, without a frontend build step. The viewer reads
cell and instance metadata from `/cells/{id}/layout`. As cells enter the view,
`/cells/{id}/layout/geometry` converts their stored GDS/OASIS shapes into gzip
encoded binary chunks under `maskyard.layout-cache/`, and the browser fetches
visible chunks from `/cells/{id}/layout/chunks/{layer}/{chunk}`. SQLite database
writes invalidate cached cells on their next request. Set
`MASKYARD_LAYOUT_CACHE_DIR` to use another directory. To warm the complete cache
ahead of time, optionally run
`uv run --extra web maskyard-build-render-cache`.

The layout viewer uses a dark canvas with framed, stippled layer fills. Set
`MASKYARD_LAYOUT_LAYER_PROPERTIES=/path/to/layers.lyp` to load a KLayout layer
properties file. Colors, visibility, frame widths, and solid, hollow, or custom
stipple fills are supported. Unmatched layers use the built-in styles. Built-in
KLayout stipples beyond solid and hollow use a built-in fill pattern; patterned
line styles and other advanced `.lyp` effects are not applied. Reload the page
after editing the `.lyp` file.

## License

MaskYard is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version. See [LICENSE](LICENSE) for the full text.

Bundled JavaScript libraries retain their respective licenses; their copyright
and license notices are in `src/maskyard/web/static/*_LICENSE.txt`. Other
third-party files retain their own notices as well.
