# Maskyard

**English** · [简体中文](README.zh-CN.md)

<p align="center">
  <img src="docs/assets/logo/logo.svg" alt="Maskyard logo" width="420">
</p>

Build, store, and inspect chip layouts with Python and KLayout. Maskyard stores
cell geometry and hierarchy in a database for reuse and inspection.

> Maskyard will remain experimental until at least version 0.1. During this
> period, the API may change at any time, including in ways that break existing
> code.

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

The [published docs](https://sebastian-goeldi.github.io/maskyard/) open the latest
release in English. Use the header menus to select a version or switch to
Simplified Chinese. Every docs workflow run builds a `maskyard-docs` preview
artifact. Pushes to `main` update `dev`, and tags such as `v0.0.2` publish numbered
versions to the `gh-pages` branch.

For a local preview, build the current checkout and open `http://127.0.0.1:8000/`.

```sh
just docs-serve
```

Run `just docs` to build without starting the server. You can also use `uv` directly.

```sh
uv run --locked --group docs python docs/scripts/build.py
uv run --locked python -m http.server 8000 --bind 127.0.0.1 --directory docs/site
```

To publish manually with your Git credentials, use `just docs-deploy-dev` from
`main` or `just docs-deploy-release 0.0.2` from the corresponding tagged checkout.

## Acknowledgments

Thanks to Frank Böttinger of [modulstyle.com](https://modulstyle.com/) for
designing the Maskyard logo.

## License

Maskyard is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version. See [LICENSE](LICENSE) for the full text.

All assets in [`docs/assets/logo/`](docs/assets/logo), including the logo and
favicon, are © 2026 Sebastian Goeldi. All rights reserved. The
[logo license](docs/assets/logo/LICENSE) governs these assets separately from
the software’s AGPL. Forks used solely to contribute changes upstream may keep
these assets. Independent forks must remove the assets and references to them
unless Sebastian Goeldi gives written permission.

Bundled JavaScript libraries retain their respective licenses; their copyright
and license notices are in `src/maskyard/web/static/*_LICENSE.txt`. Other
third-party files retain their own notices as well.
