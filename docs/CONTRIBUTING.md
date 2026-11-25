# Working on the docs

The [README](../README.md#documentation) shows how to build and preview the site.
The Zensical configs are `docs/zensical.en.toml` and `docs/zensical.zh.toml`.
The build stages both languages in `docs/source-built/` and writes the checkout
preview to `docs/site/`.

Use English as the source for user-facing prose. Update the English and Simplified
Chinese versions in the same pull request when guide behavior changes. Keep
guide paths identical in the two language directories and use the same explicit
IDs for linked headings. The build checks page coverage and language links.
The Python API reference comes from English docstrings.

Keep executable examples in `docs/examples/` and include them using Snippets.
Use a temporary database and output directory when checking examples. Keep
identifiers, environment variables, units, and shell commands unchanged in
translations. Review Chinese prose in the site alongside its English counterpart.

| English | 简体中文 |
| --- | --- |
| Cell | 单元 |
| Instance | 实例 |
| Layer | 层 |
| Port | 端口 |
| Cross-section | 截面 |
| Database unit (DBU) | 数据库单位（DBU） |
| Process design kit (PDK) | 工艺设计套件（PDK） |
| Parametric cell (PCell) | 参数化单元（PCell） |

## Documentation versions

CI uses the Zensical-compatible `mike` fork to archive both languages. Pushes
to `main` refresh `dev`, and tags in the form `vX.Y.Z` add a release snapshot.
The `docs-versions` branch stores the snapshots and both version catalogs.
Pull requests build a local `dev` snapshot for their artifact. Open `/en/dev/`
or `/zh/dev/` to preview it when the artifact also contains releases.

To test a versioned build locally, run the following from the repository root
with a Git author identity configured. It updates a local `docs-versions`
branch and exports the browsable artifact.

```sh
uv run --locked --group docs python docs/scripts/build.py --version dev
uv run --locked python -m http.server 8000 --bind 127.0.0.1 --directory docs/_build/versioned-site
```
