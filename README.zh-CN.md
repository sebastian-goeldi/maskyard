# Maskyard

[English](README.md) · **简体中文**

<p align="center">
  <img src="docs/assets/logo/logo.svg" alt="Maskyard 标志" width="420">
</p>

使用 Python 和 KLayout 创建、存储和查看芯片版图。Maskyard 将单元的几何图形和层次结构保存到数据库中，便于复用和查看。

## 快速上手

安装 [uv](https://docs.astral.sh/uv/) 后，在仓库根目录运行以下命令。示例使用新建的 SQLite 数据库，创建一个单元并将其导出为 GDS 文件。

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

## 文档

[English](docs/source/en/index.md) · [简体中文](docs/source/zh/index.md)

从成功的 GitHub Actions 运行中下载 **maskyard-docs**，解压到 `docs/site/` 即可浏览各个版本。网站默认打开 `/en/latest/`，首次发布前则打开 `/en/dev/`。可通过页眉中的语言菜单切换到简体中文。要在本地预览当前检出的文档，运行以下命令后访问 `http://127.0.0.1:8000/`。

```sh
just docs-serve
```

如果只需构建文档，运行 `just docs`。也可以直接使用 `uv`。

```sh
uv run --locked --group docs python docs/scripts/build.py
uv run --locked python -m http.server 8000 --bind 127.0.0.1 --directory docs/site
```

翻译流程见[文档贡献指南](docs/CONTRIBUTING.md)。

## 致谢

感谢 [modulstyle.com](https://modulstyle.com/) 的 Frank Böttinger 为 Maskyard 设计标志。

## 许可证

Maskyard 是自由软件。你可以依据自由软件基金会发布的 GNU Affero 通用公共许可证第 3 版（或自行选择任何后续版本）的条款重新分发和修改本软件。完整条款见 [LICENSE](LICENSE)。

[`docs/assets/logo/`](docs/assets/logo) 目录中的所有素材（包括项目标志和网站图标）的版权均归 Sebastian Goeldi 所有（© 2026），保留所有权利。这些素材适用单独的[标志许可证](docs/assets/logo/LICENSE)。仅用于向上游项目贡献改动的派生仓库可以保留这些素材。独立维护的派生项目必须移除这些素材及其引用，除非获得 Sebastian Goeldi 的书面许可。

随项目分发的 JavaScript 库继续适用各自的许可证。版权和许可声明见 `src/maskyard/web/static/*_LICENSE.txt`。其他第三方文件也保留各自的声明。
