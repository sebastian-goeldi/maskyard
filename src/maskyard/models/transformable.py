from __future__ import annotations

from abc import ABC, abstractmethod
from math import atan2, degrees
from typing import Self

from .. import kdb
from ..config import to_um


class Transformable(ABC):
    """In-place layout transforms with DBU and micrometer entry points."""

    @abstractmethod
    def transform(self, trans: kdb.Trans | kdb.DCplxTrans) -> Self:
        """Apply a transform in the receiver's enclosing coordinate system.

        Args:
            trans: An integer DBU transform or a complex transform in micrometers.

        Returns:
            The transformed object.
        """

    def move(
        self, origin: tuple[int, int], destination: tuple[int, int] | None = None
    ) -> Self:
        """Translate in database units.

        Args:
            origin: Displacement, or the point to move when destination is given.
            destination: Target point for origin.

        Returns:
            The translated object.
        """
        dx, dy = origin
        if destination is not None:
            dx, dy = destination[0] - dx, destination[1] - dy
        return self.transform(kdb.Trans(dx, dy))

    def movex(self, origin: int, destination: int | None = None) -> Self:
        """Translate along X in database units.

        Args:
            origin: X displacement, or the X coordinate to move.
            destination: Target X coordinate for origin.

        Returns:
            The translated object.
        """
        return self.move((origin if destination is None else destination - origin, 0))

    def movey(self, origin: int, destination: int | None = None) -> Self:
        """Translate along Y in database units.

        Args:
            origin: Y displacement, or the Y coordinate to move.
            destination: Target Y coordinate for origin.

        Returns:
            The translated object.
        """
        return self.move((0, origin if destination is None else destination - origin))

    def rotate(self, angle: int, center: tuple[int, int] | None = None) -> Self:
        """Rotate counterclockwise by quarter turns.

        Args:
            angle: Number of 90-degree turns.
            center: Pivot in DBU. Defaults to the coordinate origin.

        Returns:
            The rotated object.
        """
        shift = kdb.Trans(*(center or (0, 0)))
        return self.transform(
            shift * kdb.Trans(angle % 4, False, 0, 0) * shift.inverted()
        )

    def mirror(
        self, p1: tuple[int, int] = (0, 1), p2: tuple[int, int] = (0, 0)
    ) -> Self:
        """Reflect across the line through two DBU points.

        Args:
            p1: First point on the line.
            p2: Second point on the line. The defaults describe the Y axis.

        Returns:
            The reflected object.

        Raises:
            ValueError: If the points coincide.
        """
        if p1 == p2:
            raise ValueError("Mirror line requires two distinct points")
        if p1[0] == p2[0]:
            return self.mirror_x(p1[0])
        if p1[1] == p2[1]:
            return self.mirror_y(p1[1])
        start = to_um(kdb.Point(*p1))
        end = to_um(kdb.Point(*p2))
        return self.dmirror((start.x, start.y), (end.x, end.y))

    def mirror_x(self, x: int = 0) -> Self:
        """Reflect across the vertical line X = x, reversing X.

        Args:
            x: X coordinate of the line in DBU. Defaults to the Y axis.

        Returns:
            The reflected object.
        """
        return self.transform(kdb.Trans(2, True, 2 * x, 0))

    def mirror_y(self, y: int = 0) -> Self:
        """Reflect across the horizontal line Y = y, reversing Y.

        Args:
            y: Y coordinate of the line in DBU. Defaults to the X axis.

        Returns:
            The reflected object.
        """
        return self.transform(kdb.Trans(0, True, 0, 2 * y))

    def dmove(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float] | None = None,
    ) -> Self:
        """Translate in micrometers.

        Args:
            origin: Displacement, or the point to move when destination is given.
            destination: Target point for origin.

        Returns:
            The translated object.
        """
        dx, dy = origin
        if destination is not None:
            dx, dy = destination[0] - dx, destination[1] - dy
        return self.transform(kdb.DCplxTrans(dx, dy))

    def dmovex(self, origin: float, destination: float | None = None) -> Self:
        """Translate along X in micrometers.

        Args:
            origin: X displacement, or the X coordinate to move.
            destination: Target X coordinate for origin.

        Returns:
            The translated object.
        """
        return self.dmove((origin if destination is None else destination - origin, 0))

    def dmovey(self, origin: float, destination: float | None = None) -> Self:
        """Translate along Y in micrometers.

        Args:
            origin: Y displacement, or the Y coordinate to move.
            destination: Target Y coordinate for origin.

        Returns:
            The translated object.
        """
        return self.dmove((0, origin if destination is None else destination - origin))

    def drotate(self, angle: float, center: tuple[float, float] | None = None) -> Self:
        """Rotate counterclockwise by an angle in degrees.

        Args:
            angle: Rotation in degrees.
            center: Pivot in micrometers. Defaults to the coordinate origin.

        Returns:
            The rotated object.
        """
        shift = kdb.DCplxTrans(*(center or (0, 0)))
        rotation = kdb.DCplxTrans(1, angle, False, 0, 0)
        return self.transform(shift * rotation * shift.inverted())

    def dmirror(
        self, p1: tuple[float, float] = (0, 1), p2: tuple[float, float] = (0, 0)
    ) -> Self:
        """Reflect across the line through two points in micrometers.

        Args:
            p1: First point on the line.
            p2: Second point on the line. The defaults describe the Y axis.

        Returns:
            The reflected object.

        Raises:
            ValueError: If the points coincide.
        """
        if p1 == p2:
            raise ValueError("Mirror line requires two distinct points")
        angle = degrees(atan2(p2[1] - p1[1], p2[0] - p1[0])) % 180
        shift = kdb.DCplxTrans(*p1)
        reflection = kdb.DCplxTrans(1, 2 * angle, True, 0, 0)
        return self.transform(shift * reflection * shift.inverted())

    def dmirror_x(self, x: float = 0) -> Self:
        """Reflect across the vertical line X = x, reversing X.

        Args:
            x: X coordinate in micrometers. Defaults to the Y axis.

        Returns:
            The reflected object.
        """
        return self.transform(kdb.DCplxTrans(1, 180, True, 2 * x, 0))

    def dmirror_y(self, y: float = 0) -> Self:
        """Reflect across the horizontal line Y = y, reversing Y.

        Args:
            y: Y coordinate in micrometers. Defaults to the X axis.

        Returns:
            The reflected object.
        """
        return self.transform(kdb.DCplxTrans(1, 0, True, 0, 2 * y))
