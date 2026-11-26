import ray

from maskyard import Cell, get_or_create_pdk, kdb

pdk = get_or_create_pdk("ray_example")


@pdk.pcell(ray=True)
def rectangle(width: int) -> Cell:
    """Build a rectangle 100 database units tall using the supplied width."""
    cell = get_or_create_pdk("ray_example").create_cell()
    cell.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(0, 0, width, 100))
    return cell


if __name__ == "__main__":
    ray.init(num_cpus=2, include_dashboard=False)
    try:
        ref = rectangle.remote(200)
        print(rectangle.get_cell(ref).id)
    finally:
        ray.shutdown()
