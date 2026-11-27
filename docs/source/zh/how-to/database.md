# 配置数据库

MaskYard 默认使用当前目录中的 `sqlite:///maskyard.db`。请在导入 MaskYard 或启动查看器之前设置 `MASKYARD_DATABASE_URL`。如果多个进程从不同目录启动，请使用绝对 SQLite URL，让它们访问同一个文件。

```sh
export MASKYARD_DATABASE_URL="sqlite:////absolute/path/to/layout.db"
```

使用 `maskyard.engine.session_context()` 打开会话，调用 `session.commit()` 保存修改。新数据库的 DBU 默认为 0.001 µm。若要用其他单位初始化新数据库，请在访问数据库前调用 `create_db_and_tables(dbu=...)`。

**如果现有数据库的表结构或 DBU 不兼容，初始化可能会删除并重建数据表。** 请先导出需要保留的版图，并在更改 DBU 时使用新的数据库文件。
