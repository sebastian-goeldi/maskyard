# 快速上手

完成[安装](installation.md)后，在兼容 Bash 的终端中切换到仓库根目录并运行以下命令。脚本在临时目录中运行，并使用一个全新的 SQLite 数据库。

```sh
repo="$PWD"
scratch="$(mktemp -d)"
(
  cd "$scratch"
  MASKYARD_DATABASE_URL="sqlite:///$scratch/quickstart.db" \
    uv run --project "$repo" --locked python "$repo/docs/examples/quickstart.py"
)
printf 'Outputs are in %s\n' "$scratch"
```

## 创建、保存和导出 { #save-and-export }

脚本在层号 1、数据类型 0 的层上插入一个矩形，提交单元，然后在新会话中按 ID 重新加载该单元。脚本导出 `first_cell.gds`，并通过 KLayout 的 Python API 重新打开文件。默认数据库单位为 0.001 µm，因此矩形尺寸为 10 × 5 µm。

```python
--8<-- "quickstart.py"
```

可以用 KLayout 打开 GDS 文件，也可以用同一个数据库在[版图查看器](../how-to/viewer.md)中查看单元。
