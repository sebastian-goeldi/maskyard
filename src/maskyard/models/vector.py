from sqlalchemy import Dialect
from sqlmodel import LargeBinary, TypeDecorator

from .. import kdb


class Vector(TypeDecorator[kdb.Vector]):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(
        self, value: kdb.Vector | None, dialect: Dialect
    ) -> bytes | None:
        """Encode a KLayout vector for storage in a binary column."""
        if value is None:
            return None
        return value.to_bytes()

    def process_result_value(
        self, value: bytes | None, dialect: Dialect
    ) -> kdb.Vector | None:
        """Decode a KLayout vector from its stored bytes, preserving NULL."""
        if value is None:
            return None
        return kdb.Vector.from_bytes(value)
