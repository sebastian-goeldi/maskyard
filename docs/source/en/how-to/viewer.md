# Open the layout viewer

Use the same SQLite file as your layout generation script. From the repository root, replace the path below with the absolute path of that database.

```sh
MASKYARD_DATABASE_URL=sqlite:////absolute/path/to/layout.db \
  uv run --locked --extra web uvicorn maskyard.web:app
```

Open <http://127.0.0.1:8000/> and select a cell. The cell page shows its hierarchy and layout. Use **Fit layout**, the grid control, and the layer toggles to inspect the geometry. Try the [30-MZI example](../examples/mzi.md) for a hierarchy with multiple layers.

The web app serves bundled assets and generates compressed geometry chunks as needed. SQLite writes invalidate cached cells on their next request. Set `MASKYARD_LAYOUT_CACHE_DIR` to choose the output directory, or warm the cache with `uv run --locked --extra web maskyard-build-render-cache` using the same database environment.

Set `MASKYARD_LAYOUT_LAYER_PROPERTIES` to a KLayout `.lyp` file to customize layer colors, visibility, outlines, and fills. Unmatched layers retain the default styles. Built-in stipples beyond solid and hollow use a default pattern. Reload the viewer after editing the file.
