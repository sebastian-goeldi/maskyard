# 安装

MaskYard 需要 Python 3.14 或更高版本。在本仓库的本地检出目录中，使用 [uv](https://docs.astral.sh/uv/) 安装项目及锁定的依赖。

```sh
uv sync --locked
```

KLayout 的 Python 包会作为依赖一并安装。需要浏览器版图查看器或 Ray 支持时，可在 `uv sync` 或 `uv run` 中加上 `--extra web` 或 `--extra ray`。

接下来请参阅[快速上手](quickstart.md)。
