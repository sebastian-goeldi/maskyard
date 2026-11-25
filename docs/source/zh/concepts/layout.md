# 单元、层与几何图形

[`Cell`](../reference/index.md) 表示一个版图单元。在数据库会话中创建单元，用 `cell.shapes(kdb.LayerInfo(layer, datatype))` 访问指定层的几何图形，再提交会话以保存修改。已注册的 `Layer` 也可按名称查询，例如 `cell.layer(name="metal")`。

`kdb.Box` 等 KLayout 整数几何类型使用数据库单位（DBU）。默认值为 0.001 µm，因此 1,000 个 DBU 等于 1 µm。使用 `maskyard.config` 中的 `to_dbu` 和 `to_um` 在整数几何与微米坐标之间转换。更改 DBU 前请参阅[数据库配置](../how-to/database.md)。

`Cell.write("layout.gds")` 会导出该单元及其下级单元。若要导出 OASIS，请使用 `.oas` 后缀。
