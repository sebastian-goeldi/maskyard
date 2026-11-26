"""Read the display properties used by KLayout's layer-properties files."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

if TYPE_CHECKING:
    from pathlib import Path

_SOURCE = re.compile(r"^(\d+)/(\d+)(?:@|$)")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _value(node: ET.Element, name: str) -> str | None:
    """Read and trim the text of a named XML child element."""
    child = node.find(name)
    return child.text.strip() if child is not None and child.text else None


def _pattern_rows(node: ET.Element) -> list[str]:
    """Read and validate the rows of a custom KLayout stipple pattern."""
    rows = [(line.text or "").strip() for line in node.findall("./pattern/line")]
    if (
        not rows
        or len(rows[0]) not in (8, 16, 32)
        or any(len(row) != len(rows[0]) or set(row) - {".", "*"} for row in rows)
    ):
        raise ValueError("Invalid custom stipple pattern in layer properties")
    return rows


def _parse_list(root: ET.Element, styles: dict[str, dict]) -> None:
    """Populate viewer styles from one KLayout layer-properties list."""
    patterns = [_pattern_rows(node) for node in root.findall("custom-dither-pattern")]

    def visit(node: ET.Element, inherited: dict[str, str]) -> None:
        """Apply inherited display options and visit nested layer groups."""
        values = inherited.copy()
        for field in (
            "frame-color",
            "fill-color",
            "dither-pattern",
            "width",
            "visible",
        ):
            value = _value(node, field)
            if value is not None:
                values[field] = value
        source = _value(node, "source")
        match = _SOURCE.match(source) if source else None
        if match:
            style: dict = {}
            for field, key in (
                ("frame-color", "frameColor"),
                ("fill-color", "fillColor"),
            ):
                color = values.get(field)
                if color is not None:
                    if not _COLOR.fullmatch(color):
                        raise ValueError(
                            f"Invalid {field} in layer properties: {color}"
                        )
                    style[key] = color.lower()
            width = values.get("width")
            if width is not None:
                if not width.isdecimal():
                    raise ValueError(
                        f"Invalid frame width in layer properties: {width}"
                    )
                style["frameWidth"] = int(width)
            visible = values.get("visible")
            if visible is not None:
                if visible not in ("true", "false"):
                    raise ValueError(
                        f"Invalid visibility in layer properties: {visible}"
                    )
                style["visible"] = visible == "true"
            dither = values.get("dither-pattern")
            if dither in ("I0", "I1"):
                style["pattern"] = "solid" if dither == "I0" else "hollow"
            elif dither and re.fullmatch(r"C\d+", dither):
                index = int(dither[1:])
                if index >= len(patterns):
                    raise ValueError(f"Missing custom stipple {dither}")
                style["pattern"] = patterns[index]
            styles.setdefault(f"{match[1]}/{match[2]}", style)
        for child in node:
            if child.tag in ("group-members", "properties", "group-member"):
                for member in child if child.tag == "group-members" else (child,):
                    if member.tag in ("properties", "group-member"):
                        visit(member, values)

    for node in root:
        if node.tag in ("properties", "group-member"):
            visit(node, {})


@lru_cache(maxsize=8)
def _read(path: Path, modified_ns: int) -> dict[str, dict]:
    """Parse and cache layer properties by file path and modification time."""
    del modified_ns
    try:
        root = ET.parse(path).getroot()  # noqa: S314 - server-configured local file
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"Cannot read layer properties {path}: {exc}") from exc
    lists = (
        [root] if root.tag == "layer-properties" else root.findall("layer-properties")
    )
    if not lists:
        raise ValueError(f"Not a KLayout layer-properties file: {path}")
    styles: dict[str, dict] = {}
    for item in lists:
        _parse_list(item, styles)
    return styles


def load_layer_styles(path: Path | None) -> dict[str, dict]:
    """Read viewer styles from a KLayout layer-properties file.

    Args:
        path: Path to the file, or None to use default viewer styles.

    Returns:
        Styles keyed by numeric layer/datatype. Edited files are parsed again.

    Raises:
        ValueError: If the file cannot be read or contains invalid properties.
    """
    if path is None:
        return {}
    path = path.expanduser().resolve()
    try:
        return _read(path, path.stat().st_mtime_ns)
    except OSError as exc:
        raise ValueError(f"Cannot read layer properties {path}: {exc}") from exc
