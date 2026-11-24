from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import LargeBinary, TypeDecorator

from .. import kdb

if TYPE_CHECKING:
    from sqlalchemy import Dialect


class Box(TypeDecorator[kdb.Box]):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(
        self, value: kdb.Box | None, dialect: Dialect
    ) -> bytes | None:
        if value is None:
            return None
        return value.to_bytes()

    def process_result_value(
        self, value: bytes | None, dialect: Dialect
    ) -> kdb.Box | None:
        if value is None:
            return None
        return kdb.Box.from_bytes(value)
