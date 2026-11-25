# PDKs and PCells

Use `get_or_create_pdk(name)` to obtain a named process design kit (PDK) and `pdk.pcell()` to register a Python function as a parametric cell (PCell) factory. The function takes layout parameters and returns a `Cell`. Call `pdk.create_cell()` inside the factory to use its automatically assigned name.

Each PCell factory has a persistent identity. Equivalent normalized arguments can reuse a saved cell across sessions. On the same host, generation locks coordinate identical calls across processes. A database uniqueness constraint prevents duplicate keyed rows, including when processes on different hosts compute the same result.

PCell calls run synchronously by default. See [batched writes](../how-to/batched-writes.md) for writer-backed persistence and [Ray](../how-to/ray.md) for remote tasks.
