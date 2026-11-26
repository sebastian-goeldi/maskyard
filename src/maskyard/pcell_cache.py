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
    """Encode a normalized PCell key with a version byte and a pickle payload.

    Args:
        key: Picklable cache key to store or compare.

    Returns:
        The versioned key bytes.

    Raises:
        TypeError: If the key cannot be pickled.
    """
    try:
        return b"\x01" + dumps(key, protocol=5)
    except (AttributeError, PicklingError, TypeError) as error:
        raise TypeError(
            "PCell parameters must be picklable for process-wide caching"
        ) from error


def identity(*parts: str) -> str:
    """Hash length-prefixed strings to identify a PCell or registration lock."""
    digest = sha256()
    for part in parts:
        value = part.encode()
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


@contextmanager
def generation_lock(key: str) -> Generator[None]:
    """Hold a host-wide lock while checking and generating one cache entry.

    Args:
        key: Digest identifying the cache entry or factory registration.

    Yields:
        None while the exclusive lock is held.
    """
    _LOCK_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (_LOCK_DIRECTORY / f"{key}.lock").open("a+b") as lock_file:
        flock(lock_file, LOCK_EX)
        try:
            yield
        finally:
            flock(lock_file, LOCK_UN)
