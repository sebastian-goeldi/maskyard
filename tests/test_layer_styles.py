"""Tests for optional KLayout display properties."""

import os
from pathlib import Path

import pytest

from maskyard.web.layer_styles import load_layer_styles


def test_styles_match_layers_and_inherit_group_values(tmp_path: Path) -> None:
    source = tmp_path / "layers.lyp"
    source.write_text(
        """<layer-properties>
          <custom-dither-pattern><pattern>
            <line>*.......</line><line>........</line>
          </pattern></custom-dither-pattern>
          <properties>
            <frame-color>#AABBCC</frame-color><width>2</width>
            <group-members>
              <properties><source>1/0@1</source><fill-color>#123456</fill-color>
                <dither-pattern>C0</dither-pattern><visible>false</visible></properties>
              <properties><source>2/3@1</source><dither-pattern>I1</dither-pattern></properties>
              <properties><source>3/0@1</source><dither-pattern>I0</dither-pattern>
                <width>0</width></properties>
            </group-members>
          </properties>
        </layer-properties>"""
    )

    assert load_layer_styles(source) == {
        "1/0": {
            "frameColor": "#aabbcc",
            "fillColor": "#123456",
            "frameWidth": 2,
            "visible": False,
            "pattern": ["*.......", "........"],
        },
        "2/3": {
            "frameColor": "#aabbcc",
            "frameWidth": 2,
            "pattern": "hollow",
        },
        "3/0": {
            "frameColor": "#aabbcc",
            "frameWidth": 0,
            "pattern": "solid",
        },
    }


def test_first_tab_wins_and_unsupported_builtin_uses_default_pattern(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tabs.lyp"
    source.write_text(
        """<layer-properties-tabs>
          <layer-properties><properties><source>4/0@1</source>
            <frame-color>#fedcba</frame-color><dither-pattern>I5</dither-pattern>
          </properties></layer-properties>
          <layer-properties><properties><source>4/0@1</source>
            <frame-color>#123456</frame-color>
          </properties></layer-properties>
        </layer-properties-tabs>"""
    )
    assert load_layer_styles(source) == {"4/0": {"frameColor": "#fedcba"}}


@pytest.mark.parametrize(
    "content",
    [
        "<bad />",
        "<layer-properties>",
        (
            "<layer-properties><properties><source>1/0@1</source>"
            "<frame-color>red</frame-color></properties></layer-properties>"
        ),
        (
            "<layer-properties><properties><source>1/0@1</source>"
            "<dither-pattern>C0</dither-pattern></properties></layer-properties>"
        ),
    ],
)
def test_invalid_layer_properties_raise(tmp_path: Path, content: str) -> None:
    source = tmp_path / "bad.lyp"
    source.write_text(content)
    with pytest.raises(ValueError):
        load_layer_styles(source)


def test_missing_optional_file_uses_defaults(tmp_path: Path) -> None:
    assert load_layer_styles(None) == {}
    with pytest.raises(ValueError, match="Cannot read layer properties"):
        load_layer_styles(tmp_path / "missing.lyp")


def test_edited_file_reloads_without_rebuilding_geometry(tmp_path: Path) -> None:
    source = tmp_path / "layers.lyp"
    source.write_text(
        "<layer-properties><properties><source>1/0@1</source>"
        "<frame-color>#111111</frame-color></properties></layer-properties>"
    )
    first = load_layer_styles(source)
    source.write_text(
        "<layer-properties><properties><source>1/0@1</source>"
        "<frame-color>#222222</frame-color></properties></layer-properties>"
    )
    modified = source.stat().st_mtime_ns + 1_000_000_000
    os.utime(source, ns=(modified, modified))
    assert load_layer_styles(source) != first
    assert load_layer_styles(source)["1/0"]["frameColor"] == "#222222"
