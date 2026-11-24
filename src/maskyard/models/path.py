from pathlib import Path

from sqlalchemy import Dialect, String
from sqlmodel import TypeDecorator


class PathType(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value: Path | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> Path | None:
        return None if value is None else Path(value)
