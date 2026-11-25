# 使用 Ray 运行参数化单元

在仓库根目录运行以下命令，安装可选的 Ray 依赖，并使用一个全新的 SQLite 数据库运行示例。驱动进程和工作进程必须使用同一个数据库绝对路径。

```sh
scratch="$(mktemp -d)"
MASKYARD_DATABASE_URL="sqlite:///$scratch/ray.db" \
  uv run --locked --extra ray python docs/examples/ray_pcell.py
```

```python
--8<-- "ray_pcell.py"
```

使用 `@pdk.pcell(ray=True)` 时，`.remote(...)` 返回一个 `ObjectRef[int]`，其结果是已保存的单元 ID。同一进程中相同的调用会复用引用。`.get_cell(ref)` 等待任务完成，并在调用方的会话中加载结果。传给远程任务的应是普通参数，ORM 对象和会话应留在各自的进程中。
