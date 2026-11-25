# Hierarchy and ports

An instance places a child cell in a parent. Use `parent.add_instance(child, name="first", trans=kdb.Trans(200, 0))` to reuse the child geometry with a translation of 200 DBU along x. Each instance can have its own name and transform.

A cell port identifies a connection point and uses a transform to describe its position and orientation. A symmetric cross-section describes the port's width, layer, and enclosure. Ports on an instance reflect the placement of that instance in its parent. Use `cell.get_port(name)` and `cell.get_instance(name)` to retrieve named objects.

See [batched writes](../how-to/batched-writes.md) for saving an entire cell hierarchy in one transaction.
