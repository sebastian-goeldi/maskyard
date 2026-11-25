from maskyard import kdb, shutdown_writer, submit_cell
from maskyard.models.cell import create_cell

cell = create_cell("leaf", persist=False)
cell.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, 100, 100))

try:
    pending_id = submit_cell(cell)
    print(pending_id.result())
finally:
    shutdown_writer()
