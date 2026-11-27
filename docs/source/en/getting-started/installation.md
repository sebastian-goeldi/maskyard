# Installation

Maskyard requires Python 3.14 or later. From a checkout of this repository, use [uv](https://docs.astral.sh/uv/) to install the project and its locked dependencies.

```sh
uv sync --locked
```

KLayout's Python package is installed as a dependency. To install the browser viewer or Ray support, pass `--extra web` or `--extra ray` to `uv sync` or `uv run`.

Continue with the [quickstart](quickstart.md).
