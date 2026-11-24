from functools import cached_property
from pathlib import Path
from typing import overload

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select

from . import kdb


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MASKYARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_file_depth=3,
        extra="ignore",
        frozen=True,
    )

    database_url: str = "sqlite:///maskyard.db"
    layout_cache_dir: Path | None = None
    layout_layer_properties: Path | None = None
    log_level: str = "INFO"

    allow_width_mismatch: bool = False
    allow_layer_mismatch: bool = False
    allow_type_mismatch: bool = False
    allow_cross_section_mismatch: bool = True
    connect_use_mirror: bool = False
    connect_use_angle: bool = True
    max_cellname_length: int = 99

    @cached_property
    def dbu(self) -> float:
        from .engine import _config_table, engine

        with engine.connect() as connection:
            value = connection.scalar(
                select(_config_table.c.dbu).where(_config_table.c.id == 1)
            )
        if value is None:
            raise RuntimeError("Database configuration is missing")
        return value


def get_settings() -> Settings:
    return Settings.settings_cached()


settings = get_settings()


@overload
def to_um(other: None) -> None: ...


@overload
def to_um(other: int) -> float: ...


@overload
def to_um(other: kdb.Point) -> kdb.DPoint: ...


@overload
def to_um(other: kdb.Vector) -> kdb.DVector: ...


@overload
def to_um(other: kdb.Box) -> kdb.DBox: ...


@overload
def to_um(other: kdb.Polygon) -> kdb.DPolygon: ...


@overload
def to_um(other: kdb.Path) -> kdb.DPath: ...


@overload
def to_um(other: kdb.Text) -> kdb.DText: ...


def to_um(
    other: int
    | kdb.Point
    | kdb.Vector
    | kdb.Box
    | kdb.Polygon
    | kdb.Path
    | kdb.Text
    | None,
) -> (
    float
    | kdb.DPoint
    | kdb.DVector
    | kdb.DBox
    | kdb.DPolygon
    | kdb.DPath
    | kdb.DText
    | None
):
    """Convert Shapes or values in dbu to DShapes or floats in um."""
    if other is None:
        return None
    return kdb.CplxTrans(settings.dbu) * other


@overload
def to_dbu(other: None) -> None: ...
@overload
def to_dbu(other: float) -> int: ...


@overload
def to_dbu(other: kdb.DPoint) -> kdb.Point: ...


@overload
def to_dbu(other: kdb.DVector) -> kdb.Vector: ...


@overload
def to_dbu(other: kdb.DBox) -> kdb.Box: ...


@overload
def to_dbu(other: kdb.DPolygon) -> kdb.Polygon: ...


@overload
def to_dbu(other: kdb.DPath) -> kdb.Path: ...


@overload
def to_dbu(other: kdb.DText) -> kdb.Text: ...


def to_dbu(
    other: float
    | kdb.DPoint
    | kdb.DVector
    | kdb.DBox
    | kdb.DPolygon
    | kdb.DPath
    | kdb.DText
    | None,
) -> int | kdb.Point | kdb.Vector | kdb.Box | kdb.Polygon | kdb.Path | kdb.Text | None:
    """Convert Shapes or values in dbu to DShapes or floats in um."""
    if other is None:
        return None
    return kdb.CplxTrans(settings.dbu).inverted() * other
