# 层次结构与端口

实例将一个子单元放置在父单元中。例如，`parent.add_instance(child, name="first", trans=kdb.Trans(200, 0))` 复用子单元的几何图形，并将其沿 x 轴平移 200 DBU。每个实例都可以有自己的名称和变换。

单元端口表示连接点，其变换描述位置和方向。对称截面描述端口的宽度、所在层及包围结构。实例端口的位置和方向会随实例在父单元中的放置而变化。可用 `cell.get_port(name)` 和 `cell.get_instance(name)` 按名称查找对象。

如需在一次事务中保存整个单元层次结构，请参阅[批量写入](../how-to/batched-writes.md)。
