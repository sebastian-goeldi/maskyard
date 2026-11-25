# MaskYard

**English** · [简体中文](README.zh-CN.md)

<p align="center">
  <img src="logo.png" alt="Crane lifting a chip" width="420">
</p>

Build, store, and inspect chip layouts with Python and KLayout. MaskYard stores
cell geometry and hierarchy in a database for reuse and inspection.

## Quickstart

From a checkout with [uv](https://docs.astral.sh/uv/) installed, run the example
against a fresh SQLite database. It creates a cell and exports it as GDS.

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

## Documentation

[English](docs/source/en/index.md) · [简体中文](docs/source/zh/index.md)

Download **maskyard-docs** from a successful GitHub Actions run and extract it
into `docs/site/` to browse available versions. The site opens `/en/latest/`,
or `/en/dev/` before the first release. Use the language menu in the header
to switch to Simplified Chinese. For a quick local preview, build the current
checkout and open `http://127.0.0.1:8000/`.

```sh
just docs-serve
```

Run `just docs` to build without starting the server. You can also use `uv` directly.

```sh
uv run --locked --group docs python docs/scripts/build.py
uv run --locked python -m http.server 8000 --bind 127.0.0.1 --directory docs/site
```

See [Working on the docs](docs/CONTRIBUTING.md) for the translation workflow.

## License

MaskYard is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version. See [LICENSE](LICENSE) for the full text.

Bundled JavaScript libraries retain their respective licenses; their copyright
and license notices are in `src/maskyard/web/static/*_LICENSE.txt`. Other
third-party files retain their own notices as well.
