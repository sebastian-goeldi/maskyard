# 打开版图查看器

请使用版图生成脚本所用的 SQLite 文件。在仓库根目录运行以下命令，并把示例路径替换成数据库的绝对路径。

```sh
MASKYARD_DATABASE_URL=sqlite:////absolute/path/to/layout.db \
  uv run --locked --extra web uvicorn maskyard.web:app
```

打开 <http://127.0.0.1:8000/> 并选择一个单元。单元页面显示其层次结构和版图。使用 **Fit layout**（缩放至整个版图）、网格和图层开关来查看几何图形。[30 个 MZI 的芯片示例](../examples/mzi.md)包含多层版图。

Web 应用会提供内置资源，并按需生成压缩的几何数据块。SQLite 写入后，对应单元的缓存会在下一次请求时失效。设置 `MASKYARD_LAYOUT_CACHE_DIR` 可更改缓存目录，也可在使用同一数据库配置的环境中运行 `uv run --locked --extra web maskyard-build-render-cache` 来预先生成缓存。

将 `MASKYARD_LAYOUT_LAYER_PROPERTIES` 设置为 KLayout 的 `.lyp` 文件，即可自定义图层的颜色、可见性、轮廓和填充样式。未匹配到的层使用默认样式。除实心和空心外的内置点阵填充使用默认图案。编辑文件后请重新加载查看器。
