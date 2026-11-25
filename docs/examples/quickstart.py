from maskyard import Cell, kdb
from maskyard.engine import session_context
from maskyard.models.cell import create_cell

with session_context() as session:
    cell = create_cell("first_cell")
    cell.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 10_000, 5_000))
    session.commit()
    cell_id = cell.id

with session_context() as session:
    saved_cell = session.get(Cell, cell_id)
    assert saved_cell is not None
    saved_cell.write("first_cell.gds")

layout = kdb.Layout()
layout.read("first_cell.gds")
assert layout.cell("first_cell").bbox() == kdb.Box(0, 0, 10_000, 5_000)
print(f"Saved cell {cell_id} and exported first_cell.gds")
