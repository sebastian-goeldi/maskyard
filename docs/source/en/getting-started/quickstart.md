# Quickstart

Complete [installation](installation.md), then run this from the repository root in a Bash-compatible shell. The script runs in a scratch directory and uses a fresh SQLite database.

```sh
repo="$PWD"
scratch="$(mktemp -d)"
(
  cd "$scratch"
  MASKYARD_DATABASE_URL="sqlite:///$scratch/quickstart.db" \
    uv run --project "$repo" --locked python "$repo/docs/examples/quickstart.py"
)
printf 'Outputs are in %s\n' "$scratch"
```

## Create, save, and export { #save-and-export }

The script inserts a box on layer 1, datatype 0, commits the cell, and loads it by ID in a new session. It exports `first_cell.gds` and reopens the file with KLayout's Python API. With the default database unit of 0.001 µm, the box is 10 × 5 µm.

```python
--8<-- "quickstart.py"
```

Open the GDS in KLayout, or use the [layout viewer](../how-to/viewer.md) with the same database.
