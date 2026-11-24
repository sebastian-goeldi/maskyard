"""Coordinate PCell generation between local worker processes."""

from __future__ import annotations

from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from hashlib import sha256
from pathlib import Path
from pickle import PicklingError, dumps
from tempfile import gettempdir
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

_LOCK_DIRECTORY = Path(gettempdir()) / "maskyard-pcell-locks"


def serialize_hashkey(key: object) -> bytes:
    """Encode a normalized PCell key with an explicit format version."""
    try:
        return b"\x01" + dumps(key, protocol=5)
    except (AttributeError, PicklingError, TypeError) as error:
        raise TypeError(
            "PCell parameters must be picklable for process-wide caching"
        ) from error


def identity(*parts: str) -> str:
    """Return a stable digest for a PCell and its normalized parameters."""
    digest = sha256()
    for part in parts:
        value = part.encode()
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


@contextmanager
def generation_lock(key: str) -> Generator[None]:
    """Hold a host-wide lock while checking and generating one cache entry."""
    _LOCK_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (_LOCK_DIRECTORY / f"{key}.lock").open("a+b") as lock_file:
        flock(lock_file, LOCK_EX)
        try:
            yield
        finally:
            flock(lock_file, LOCK_UN)
