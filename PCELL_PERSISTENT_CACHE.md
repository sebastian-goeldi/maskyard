# Persist PCell cache keys

Add a `Factory` table with an ID, PDK name, module, and qualified function name; make `(pdk, module, qualname)` unique. Add nullable `factory_id` (foreign key to `Factory.id`) and `parameter_hash` columns to `Cell`, with a unique index on `(factory_id, parameter_hash)` for decorated cells. Keep `Cell.name` as a display name, not a cache identity.

Compute the digest from the **same key** used by the in-memory cache, after applying defaults, `drop_params`, and configured serializers:

```python
parameter_hash = "v1:" + sha256(pickle.dumps(key, protocol=5)).hexdigest()
```

On an in-memory miss, resolve or create the `Factory` row, then query `Cell` by `(factory_id, parameter_hash)` and return the match through the active session. Run the factory only on a database miss; save the identity with the cell and populate the in-memory ID cache after commit. If concurrent calls race to insert the same identity, load the row that won the unique constraint.

The `Factory` row is the anchor for future file-dependency tracking using the files actually opened during execution. Store those observations in a separate table when that feature is built; do not infer them from the Python source path. If opened files vary by parameters, associate the observations with the specific cell/build as well as its factory.

Migrate existing databases by creating `Factory`, adding the nullable `Cell` columns and index, then advancing `databaseconfig.schema_version`. The current schema-version path **drops all tables**, so this migration needs an explicit upgrade path before the purge check. Leave legacy cells with `NULL` keys: their original parameters cannot be reliably recovered from `name`, especially for explicitly named cells. A miss for such a row rebuilds it.

Test reuse across sessions and process restarts, equivalent argument forms, serializer and `drop_params` behavior, duplicate insert races, and preservation of legacy rows during migration. Treat a future change to pickle, key normalization, or serializer output as a new digest version; it may cause a cache miss, but must not return the wrong cell.
