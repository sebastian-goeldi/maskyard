# 批量写入单元

使用 `persist=False` 创建未绑定会话的单元，然后将其提交给专用写入线程。`submit_cell` 在调用线程中为单元创建快照，返回一个 `Future[int]`，事务提交后可从中获取已保存的单元 ID。

```python
--8<-- "batched_writes.py"
```

提交前可用 `add_instance(child)` 和 `attach_port(name, cross_section)` 组装单元关系。新的子单元与父单元在同一事务中保存。也可以按 ID 加载并挂接已有的子单元。端口使用的截面必须已经保存。

写入线程从第一条请求起最多等待 5 毫秒，每个事务最多提交 64 条请求。如果某条请求失败，整个批次会回滚，获取该批次的结果时会抛出异常。如果下一步依赖本次写入，可用 `flush=True` 跳过等待时间。调用 `shutdown_writer()` 可等待队列处理完毕。

对 PCell 使用 `@pdk.pcell(use_writer=True)` 时，函数应返回通过 `pdk.create_cell(persist=False)` 创建的单元。装饰后的调用会等待保存完成再返回。
