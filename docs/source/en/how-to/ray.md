# Run PCells with Ray

From the repository root, install the optional Ray dependency and run the example with a fresh SQLite database. The driver and workers must share the same absolute database path.

```sh
scratch="$(mktemp -d)"
MASKYARD_DATABASE_URL="sqlite:///$scratch/ray.db" \
  uv run --locked --extra ray python docs/examples/ray_pcell.py
```

```python
--8<-- "ray_pcell.py"
```

With `@pdk.pcell(ray=True)`, `.remote(...)` returns an `ObjectRef[int]` for the saved cell ID. Equivalent calls in one process reuse the same reference. `.get_cell(ref)` waits for the task and loads the result in the caller's session. Pass plain parameters to tasks and keep ORM objects and sessions in their owning processes.
