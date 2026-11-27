# Configure the database

Maskyard defaults to `sqlite:///maskyard.db` in the current directory. Set `MASKYARD_DATABASE_URL` before importing Maskyard or starting the viewer. Use an absolute SQLite URL to share the same file across processes started from different directories.

```sh
export MASKYARD_DATABASE_URL="sqlite:////absolute/path/to/layout.db"
```

Use `maskyard.engine.session_context()` to open a session and call `session.commit()` after changes you want to persist. A new database defaults to 0.001 µm per DBU. To initialize a fresh database with a different unit, call `create_db_and_tables(dbu=...)` before any other database access.

**When an existing database's schema or DBU is incompatible, initialization can drop and recreate its tables.** Export layouts you want to preserve and use a new database file when changing DBU.
