from __future__ import annotations

import struct
from enum import IntEnum
from typing import TYPE_CHECKING

from sqlmodel import LargeBinary, TypeDecorator

from .. import kdb

if TYPE_CHECKING:
    from sqlalchemy import Dialect


class Transformation(IntEnum):
    Trans = 0
    DCplxTrans = 1


class PortTrans(TypeDecorator[kdb.Trans | kdb.DCplxTrans]):
    impl = LargeBinary
    cache_ok = True

    def compare_values(self, x: object, y: object) -> bool:
        """Compare port transforms for SQLAlchemy change tracking.

        Args:
            x: Current value.
            y: Previously loaded value.

        Returns:
            Whether the values have the same representation and compare equal.
        """
        return type(x) is type(y) and x == y

    def process_bind_param(
        self, value: kdb.Trans | kdb.DCplxTrans | None, dialect: Dialect
    ) -> bytes | None:
        """Prefix a port transform's bytes with its representation tag."""
        if value is None:
            return None
        if isinstance(value, kdb.Trans):
            return struct.pack("B", Transformation.Trans) + value.to_bytes()
        return struct.pack("B", Transformation.DCplxTrans) + value.to_bytes()

    def process_result_value(
        self, value: bytes | None, dialect: Dialect
    ) -> kdb.Trans | kdb.DCplxTrans | None:
        """Decode a simple or complex port transform using its stored tag."""
        if value is None:
            return None
        trans_type = Transformation(value[0])
        if trans_type is Transformation.Trans:
            return kdb.Trans.from_bytes(value[1:])
        return kdb.DCplxTrans.from_bytes(value[1:])


class InstanceTrans(TypeDecorator[kdb.ICplxTrans]):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(
        self, value: kdb.ICplxTrans | None, dialect: Dialect
    ) -> bytes | None:
        """Encode a complex integer placement for database storage."""
        if value is None:
            return None
        return value.to_bytes()

    def process_result_value(
        self, value: bytes | None, dialect: Dialect
    ) -> kdb.ICplxTrans | None:
        """Decode a complex integer placement from database storage."""
        if value is None:
            return None
        return kdb.ICplxTrans.from_bytes(value)
