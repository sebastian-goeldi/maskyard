# ruff: noqa: INP001
"""Thirty MZIs built as maskyard PCells.

Run from the project root:
  uv run python examples/chip_30_mzis.py

The Euler point calculation is included below. The MMIs are illustrative
and require foundry validation before fabrication. Dimensions are micrometres.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from scipy.special import fresnel
from sqlmodel import select

# Maskyard reads the database URL during import, so set the example cache first.
_cache = Path.cwd().resolve() / "maskyard.db"
os.environ.setdefault("MASKYARD_DATABASE_URL", f"sqlite:///{_cache}")

from maskyard import get_or_create_pdk, kdb  # noqa: E402
from maskyard.config import to_dbu  # noqa: E402
from maskyard.engine import get_session  # noqa: E402
from maskyard.models.cross_section import SymmetricCrossSection  # noqa: E402
from maskyard.models.enclosure import get_or_create_enclosure  # noqa: E402
from maskyard.models.layer import Layer  # noqa: E402

if TYPE_CHECKING:
    from maskyard.models.cell import Cell

DBU = 0.001
WIDTH = 0.5
RADIUS = 8.0
PORT_Y = 1.5
ARM_Y = 50.0
COMBINER_X = 370.0
CHIP_WIDTH = 2300.0
CHIP_HEIGHT = 1180.0
WG = kdb.LayerInfo(1, 0)
LABEL = kdb.LayerInfo(10, 0)
OUTLINE = kdb.LayerInfo(99, 0)


def nm(x: float) -> int:
    """Convert a micrometer coordinate to the example's one-nanometer grid."""
    return round(x / DBU)


def box(
    cell: Cell, layer: kdb.LayerInfo, x1: float, y1: float, x2: float, y2: float
) -> None:
    """Insert a rectangle whose corner coordinates are in micrometers."""
    cell.shapes(layer).insert(kdb.Box(nm(x1), nm(y1), nm(x2), nm(y2)))


def taper(cell: Cell, x1: float, x2: float, y: float, w1: float, w2: float) -> None:
    """Insert a waveguide taper with endpoints and widths in micrometers."""
    cell.shapes(WG).insert(
        kdb.Polygon(
            [
                kdb.Point(nm(x1), nm(y - w1 / 2)),
                kdb.Point(nm(x1), nm(y + w1 / 2)),
                kdb.Point(nm(x2), nm(y + w2 / 2)),
                kdb.Point(nm(x2), nm(y - w2 / 2)),
            ]
        )
    )


def euler_bend_points(
    angle_amount: float = 90, radius: float = 100, resolution: float = 150
) -> list[kdb.DPoint]:
    """Sample an Euler bend backbone from the origin.

    Adapted from KFactory's euler_bend_points (MIT license). See EULER_LICENSE.txt for
    the retained copyright and license notice.

    Args:
        angle_amount: Total turn in degrees.
        radius: Radius at the midpoint of the bend in micrometers.
        resolution: Sampling density per radian of the half-angle.

    Returns:
        Points in micrometers, including both endpoints.

    Raises:
        ValueError: If the total turn is negative.
    """
    if angle_amount < 0:
        raise ValueError(f"angle_amount should be positive. Got {angle_amount}")
    end_angle = angle_amount * np.pi / 180
    if end_angle == 0:
        return [kdb.DPoint(0, 0)]

    half_angle = end_angle / 2
    total_length = 4 * radius * half_angle
    scale = np.sqrt(radius**2 * np.abs(half_angle))
    factor = np.sqrt(2 * np.pi) * scale
    fs_end, fc_end = fresnel(np.sqrt(2 / np.pi) * radius * half_angle / scale)

    def point_at(distance: float) -> kdb.DPoint:
        """Evaluate the piecewise Euler backbone at an arc distance."""
        if distance <= total_length / 2:
            fs, fc = fresnel(distance / factor)
            x = factor * fc
            y = factor * fs
        else:
            fs, fc = fresnel((total_length - distance) / factor)
            cosine = np.cos(2 * half_angle)
            sine = np.sin(2 * half_angle)
            x = factor * (fc_end + cosine * (fc_end - fc) + sine * (fs_end - fs))
            y = factor * (fs_end - cosine * (fs_end - fs) + sine * (fc_end - fc))
        return kdb.DPoint(x, y)

    steps = max(int(half_angle * resolution), 1)
    return [point_at(total_length * index / steps) for index in range(steps + 1)]


pdk = get_or_create_pdk("MASKYARD_MZI_EXAMPLE")
session = get_session()
layer = session.exec(select(Layer).where(Layer.layer == 1, Layer.datatype == 0)).first()
if layer is None:
    layer = Layer(layer=1, datatype=0, name="WG")
    session.add(layer)
    session.commit()
enclosure = get_or_create_enclosure(
    session, main_layer=layer, definition={}, name="strip_enclosure"
)
session.commit()
saved_strip = session.exec(
    select(SymmetricCrossSection).where(
        SymmetricCrossSection.canonical_name == "strip_500nm"
    )
).first()
if saved_strip is None:
    strip = SymmetricCrossSection(
        name="strip",
        canonical_name="strip_500nm",
        width=nm(WIDTH),
        layer=layer,
        enclosure=enclosure,
    )
    session.add(strip)
    session.commit()
else:
    strip = saved_strip


@pdk.pcell(use_writer=True)
def straight(length: float) -> Cell:
    """Build a strip waveguide with west- and east-facing ports.

    Args:
        length: Positive waveguide length in micrometers.

    Returns:
        The straight waveguide cell.

    Raises:
        ValueError: If the length is nonpositive.
    """
    if length <= 0:
        raise ValueError("Straight length must be positive")
    cell = pdk.create_cell(persist=False)
    box(cell, WG, 0, -WIDTH / 2, length, WIDTH / 2)
    cell.attach_port("o1", strip, trans=kdb.Trans(2, False, 0, 0))
    cell.attach_port("o2", strip, trans=kdb.Trans(0, False, nm(length), 0))
    return cell


@pdk.pcell(use_writer=True)
def bend_euler(radius: float = RADIUS) -> Cell:
    """Build a quarter-turn strip waveguide from an Euler backbone.

    Args:
        radius: Bend radius passed to the backbone generator, in micrometers.

    Returns:
        The bend cell with ports at the backbone endpoints.
    """
    cell = pdk.create_cell(persist=False)
    points = euler_bend_points(angle_amount=90, radius=radius)
    cell.shapes(WG).insert(to_dbu(kdb.DPath(points, WIDTH)))
    end = points[-1]
    cell.attach_port("o1", strip, trans=kdb.Trans(2, False, 0, 0))
    cell.attach_port("o2", strip, trans=kdb.Trans(1, False, nm(end.x), nm(end.y)))
    return cell


@pdk.pcell(use_writer=True)
def mmi1x2() -> Cell:
    """Build a tapered splitter with one input port and two output ports."""
    cell = pdk.create_cell(persist=False)
    box(cell, WG, 0, -3, 20, 3)
    box(cell, WG, -10, -WIDTH / 2, -6, WIDTH / 2)
    taper(cell, -6, 0, 0, WIDTH, 1.5)
    for y in (-PORT_Y, PORT_Y):
        taper(cell, 20, 26, y, 1.5, WIDTH)
        box(cell, WG, 26, y - WIDTH / 2, 30, y + WIDTH / 2)
    cell.attach_port("o1", strip, trans=kdb.Trans(2, False, nm(-10), 0))
    cell.attach_port("o2", strip, trans=kdb.Trans(0, False, nm(30), nm(PORT_Y)))
    cell.attach_port("o3", strip, trans=kdb.Trans(0, False, nm(30), nm(-PORT_Y)))
    return cell


@pdk.pcell(use_writer=True)
def arm_transition(offset: float) -> Cell:
    """Connect two horizontal port directions using a pair of quarter bends.

    Args:
        offset: Vertical separation between the endpoints in micrometers.

    Returns:
        The arm transition cell with its intervening straight segment.
    """
    extent = nm(euler_bend_points(angle_amount=90, radius=RADIUS)[-1].x) * DBU
    vertical = offset - 2 * extent
    if vertical <= 0:
        raise ValueError("Offset is too small for two bends")
    bend = bend_euler()
    cell = pdk.create_cell(persist=False)
    cell.add_instance(bend, name="bend_in")
    cell.add_instance(
        straight(vertical),
        name="vertical",
        trans=kdb.Trans(1, False, nm(extent), nm(extent)),
    )
    cell.add_instance(
        bend,
        name="bend_out",
        trans=kdb.Trans(1, True, nm(extent), nm(extent + vertical)),
    )
    cell.attach_port("o1", strip, trans=kdb.Trans(2, False, 0, 0))
    cell.attach_port("o2", strip, trans=kdb.Trans(0, False, nm(2 * extent), nm(offset)))
    return cell


@pdk.pcell(use_writer=True)
def mzi(delta_length: float) -> Cell:
    """Build a Mach-Zehnder interferometer with a mirrored output combiner.

    Args:
        delta_length: Added optical path length in one arm in micrometers.

    Returns:
        The interferometer cell with input and output ports.
    """
    if delta_length < 0:
        raise ValueError("delta_length must be nonnegative")
    cell = pdk.create_cell(persist=False)
    splitter = mmi1x2()
    cell.add_instance(splitter, name="splitter")
    cell.add_instance(
        splitter, name="combiner", trans=kdb.Trans(2, False, nm(COMBINER_X), 0)
    )
    extent = nm(euler_bend_points(angle_amount=90, radius=RADIUS)[-1].x) * DBU
    x1 = 30 + 2 * extent
    x2 = COMBINER_X - 30 - 2 * extent
    arm = straight(x2 - x1)
    for branch, port_y, arm_y in (
        ("top", PORT_Y, ARM_Y),
        ("bottom", -PORT_Y, -ARM_Y - delta_length / 2),
    ):
        transition = arm_transition(abs(arm_y - port_y))
        cell.add_instance(
            transition,
            name=f"{branch}_fanout",
            trans=kdb.Trans(0, arm_y < port_y, nm(30), nm(port_y)),
        )
        cell.add_instance(arm, name=f"{branch}_arm", trans=kdb.Trans(nm(x1), nm(arm_y)))
        cell.add_instance(
            transition,
            name=f"{branch}_fanin",
            trans=kdb.Trans(0, port_y < arm_y, nm(x2), nm(arm_y)),
        )
    cell.attach_port("o1", strip, trans=kdb.Trans(2, False, nm(-10), 0))
    cell.attach_port("o2", strip, trans=kdb.Trans(0, False, nm(COMBINER_X + 10), 0))
    cell.info["delta_length_um"] = delta_length
    return cell


@pdk.pcell(use_writer=True)
def fill_wg() -> Cell:
    """Build the 200 nm square waveguide fill pattern."""
    cell = pdk.create_cell("FILL_WG", persist=False)
    box(cell, WG, 0, 0, 0.2, 0.2)
    return cell


@pdk.pcell(use_writer=True)
def chip() -> Cell:
    """Arrange 30 interferometers in five columns and six rows.

    Path-length differences run from 2 to 60 micrometers.
    """
    cell = pdk.create_cell(persist=False)
    for index in range(30):
        delta_length = 2.0 * (index + 1)
        column, row = index % 5, index // 5
        x, y = 60 + column * 450, 100 + row * 190
        cell.add_instance(
            mzi(delta_length),
            name=f"mzi_{index + 1:02d}",
            trans=kdb.Trans(nm(x), nm(y)),
        )
        cell.shapes(LABEL).insert(
            kdb.Text(
                f"MZI {index + 1:02d}  dL={delta_length:g}um",
                kdb.Trans(nm(x - 10), nm(y + 65)),
            )
        )
        cell.attach_port(
            f"mzi_{index + 1:02d}_in",
            strip,
            trans=kdb.Trans(2, False, nm(x - 10), nm(y)),
        )
        cell.attach_port(
            f"mzi_{index + 1:02d}_out",
            strip,
            trans=kdb.Trans(0, False, nm(x + COMBINER_X + 10), nm(y)),
        )
    box(cell, OUTLINE, 0, 0, CHIP_WIDTH, 1)
    box(cell, OUTLINE, 0, CHIP_HEIGHT - 1, CHIP_WIDTH, CHIP_HEIGHT)
    box(cell, OUTLINE, 0, 0, 1, CHIP_HEIGHT)
    box(cell, OUTLINE, CHIP_WIDTH - 1, 0, CHIP_WIDTH, CHIP_HEIGHT)
    return cell


def main() -> None:
    """Export the filled chip layout and its interferometer parameter table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_suffix(".gds")
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # --8<-- [start:chip-fill]
    top = chip()
    fill_cell = fill_wg()
    if not any(instance.cell_id == fill_cell.id for instance in top.instances):
        top.fill(
            fill_cell,
            fill_regions=[
                (
                    kdb.Region(
                        kdb.Box(
                            nm(20),
                            nm(20),
                            nm(CHIP_WIDTH - 20),
                            nm(CHIP_HEIGHT - 20),
                        )
                    ),
                    0,
                )
            ],
            exclude_layers=[(WG, nm(5))],
            row_step=kdb.Vector(400, 50),
            col_step=kdb.Vector(-50, 400),
            tile_size=(nm(200), nm(200)),
        )
    top.write(args.output)
    # --8<-- [end:chip-fill]
    table = args.output.with_suffix(".csv")
    with table.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "mzi",
                "column",
                "row",
                "delta_length_um",
                "input_x_um",
                "output_x_um",
                "port_y_um",
            ]
        )
        for index in range(30):
            column, row = index % 5, index // 5
            x, y = 60 + column * 450, 100 + row * 190
            writer.writerow(
                [
                    index + 1,
                    column + 1,
                    row + 1,
                    2 * (index + 1),
                    x - 10,
                    x + COMBINER_X + 10,
                    y,
                ]
            )
    sys.stdout.write(f"Wrote {args.output} and {table}\n")


if __name__ == "__main__":
    main()
