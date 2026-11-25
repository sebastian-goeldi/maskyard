# Cells, layers, and geometry

A [`Cell`](../reference/index.md) stores a piece of layout. Create it in a database session, use `cell.shapes(kdb.LayerInfo(layer, datatype))` to access a layer's shapes, and commit to persist your work. A registered `Layer` can also be looked up by name through `cell.layer(name="metal")`.

Integer KLayout geometry such as `kdb.Box` uses database units (DBU). The default DBU is 0.001 µm, so 1,000 integer units represent 1 µm. Use `to_dbu` and `to_um` from `maskyard.config` when moving between integer geometry and micrometres. See [database setup](../how-to/database.md) before selecting a different DBU.

`Cell.write("layout.gds")` exports the cell with its descendants. Use an `.oas` suffix for OASIS.
