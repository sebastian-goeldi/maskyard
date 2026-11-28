# Batch cell writes

Build detached cells with `persist=False` and submit them to the dedicated writer. `submit_cell` snapshots the cell on the calling thread and returns a `Future[int]` that resolves to the saved cell ID after commit.

```python
--8<-- "batched_writes.py"
```

Use `add_instance(child)` and `attach_port(name, cross_section)` to assemble the graph before submission. New children save in the parent's transaction. You can also load an existing child by ID and attach it. Ports require a saved cross-section.

The writer commits up to 64 requests per transaction or collects requests for up to 5 ms after the first. If one request fails, the batch rolls back and its futures raise. Set `flush=True` to skip the batching delay when the next cell depends on this write. Call `shutdown_writer()` to drain the queue.

To persist a PCell through the writer, use `@pdk.pcell(use_writer=True)` and return a cell built with `pdk.create_cell(persist=False)`. The decorated call waits for its saved cell before returning.
