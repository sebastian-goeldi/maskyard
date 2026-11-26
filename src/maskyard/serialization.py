from __future__ import annotations

import functools
import inspect
from collections import UserDict, UserList
from collections.abc import Callable, Hashable, Mapping, Sequence
from hashlib import sha3_512
from types import FunctionType, UnionType
from typing import TYPE_CHECKING, TypeGuard, overload

import klayout.db as kdb
import numpy as np
import toolz
from klayout import lay

from .config import settings

if TYPE_CHECKING:
    from .models.cross_section import SymmetricCrossSection
    from .typing import (
        DShapeLike,
        IShapeLike,
        JSONSerializable,
        MetaData,
        SerializableShape,
    )


class CellNameError(ValueError):
    """Raised if a Cell is created and the automatic assigned name is taken."""


class DecoratorList(UserList[object]):
    """Hashable decorator for a list."""

    def __hash__(self) -> int:
        """Hash the list."""
        return hash(tuple(self.data))

    def __reduce__(self) -> tuple[type[DecoratorList], tuple[list[object]]]:
        """Supply the wrapper constructor and items for pickling."""
        return (DecoratorList, (self.data,))


class DecoratorDict(UserDict[Hashable, object]):
    """Hashable decorator for a dictionary."""

    def __hash__(self) -> int:
        """Hash the dictionary."""
        return hash(tuple(sorted(self.data.items())))

    def __reduce__(self) -> tuple[type[DecoratorDict], tuple[dict[Hashable, object]]]:
        """Supply the wrapper constructor and mapping for pickling."""
        return (DecoratorDict, (self.data,))


class DecoratorTuple(tuple[object, ...]):
    """Tuple whose unhashable elements were converted by `to_hashable`."""

    __slots__ = ()


_TO_HASHABLE = dict | list | tuple
_FROM_HASHABLE = DecoratorDict | DecoratorList | DecoratorTuple


type _NameValues = dict[str, str | _NameValues]


def clean_dict(d: Mapping[str, object]) -> _NameValues:
    """Recursively clean string-keyed values for use in generated names.

    Args:
        d: Mapping whose leaves should be converted to name fragments.

    Returns:
        A dictionary with the original keys and cleaned string leaves.
    """
    return {
        k: clean_dict(dict(v)) if isinstance(v, dict) else clean_value(v)
        for k, v in d.items()
    }


def clean_name(name: str) -> str:
    """Replace selected punctuation and spaces for use in cell names.

    Args:
        name: Original name or name fragment.

    Returns:
        The text after applying the configured character replacements.
    """
    replace_map = {
        "=": "",
        ",": "_",
        ")": "",
        "(": "",
        "-": "m",
        ".": "p",
        ":": "_",
        "[": "",
        "]": "",
        " ": "_",
        "<": "",
        ">": "",
    }
    for k, v in list(replace_map.items()):
        name = name.replace(k, v)
    return name


def cell_name_hash(name: str) -> str:
    """Return the first eight hexadecimal digits of the name's SHA3-512 hash."""
    return sha3_512(name.encode()).hexdigest()[:8]


def clean_value(value: object) -> str:
    """Format an argument as a fragment of a generated cell name.

    Args:
        value: Argument to format, such as a number, container, or named callable.

    Returns:
        A string fragment describing the value.

    Raises:
        CellNameError: If a dictionary cannot be expanded as named arguments.
        ValueError: If a lambda function is supplied.
    """
    if isinstance(value, int):  # integer
        return str(value)
    if isinstance(value, float | np.float64):  # float
        return f"{value}".replace(".", "p").rstrip("0").rstrip("p")
    if isinstance(value, kdb.LayerInfo):
        return f"{value.name or str(value.layer) + '_' + str(value.datatype)}"
    if isinstance(value, list | tuple):
        return "_".join(clean_value(v) for v in value)
    if isinstance(value, dict):
        try:
            return dict2name(**value)
        except TypeError as e:
            raise CellNameError(
                "Dictionaries passed to functions as args/kwargs"
                " must be of type dict[str, ...] to be properly serialized"
                " for Cell/Component names or similar."
            ) from e
    if hasattr(value, "name"):
        return clean_name(value.name)  # ty:ignore[invalid-argument-type]
    if callable(value):
        if isinstance(value, FunctionType) and value.__name__ == "<lambda>":
            msg = "Unable to serialize lambda function. Use a named function instead."
            raise ValueError(msg)
        if isinstance(value, functools.partial):
            sig = inspect.signature(value.func)
            args_as_kwargs = dict(zip(sig.parameters.keys(), value.args, strict=False))
            args_as_kwargs.update(**value.keywords)
            cleaned_args = clean_dict(args_as_kwargs)
            func = value.func
            while hasattr(func, "func"):
                func = func.func
            v = {
                "function": get_function_name(func),  # ty:ignore[invalid-argument-type]
                "module": func.__module__,
                "settings": cleaned_args,
            }
            return clean_value(v)
        if isinstance(value, toolz.functoolz.Compose):
            return "_".join(
                [clean_value(value.first)] + [clean_value(func) for func in value.funcs]
            )
        return getattr(value, "__name__", value.__class__.__name__)
    return clean_name(str(value))


@overload
def to_hashable[K: Hashable, V](d: dict[K, V]) -> DecoratorDict: ...


@overload
def to_hashable[T](d: list[T]) -> DecoratorList: ...


@overload
def to_hashable(d: tuple[object, ...]) -> tuple[object, ...]: ...


def to_hashable[K: Hashable, V, T](
    d: dict[K, V] | list[T] | tuple[object, ...],
) -> DecoratorDict | DecoratorList | tuple[object, ...]:
    """Recursively wrap built-in containers for use in cache keys.

    Args:
        d: Dictionary, list, or tuple with hashable values or nested containers.

    Returns:
        A hashable wrapper, an already hashable tuple, or the original tuple subclass.
    """
    if isinstance(d, tuple):
        if type(d) is not tuple:
            return d
        try:
            hash(d)
        except TypeError:
            return DecoratorTuple(
                to_hashable(value) if isinstance(value, _TO_HASHABLE) else value
                for value in d
            )
        return d
    if isinstance(d, dict):
        return DecoratorDict(
            {
                item: to_hashable(value) if isinstance(value, _TO_HASHABLE) else value
                for item, value in sorted(d.items())
            }
        )
    return DecoratorList(
        [
            to_hashable(value) if isinstance(value, _TO_HASHABLE) else value
            for value in d
        ]
    )


@overload
def hashable_to_original(udl: DecoratorDict) -> dict[Hashable, object]: ...


@overload
def hashable_to_original(udl: DecoratorList) -> list[object]: ...


@overload
def hashable_to_original(udl: DecoratorTuple) -> tuple[object, ...]: ...


@overload
def hashable_to_original(udl: object) -> object: ...


def hashable_to_original(udl: object) -> object:
    """Convert cache-key wrappers back to plain containers.

    Args:
        udl: Wrapped container or ordinary value.

    Returns:
        The recursively unwrapped container or the supplied ordinary value.
    """
    if isinstance(udl, DecoratorDict):
        return {
            k: hashable_to_original(v) if isinstance(v, _FROM_HASHABLE) else v
            for k, v in udl.data.items()
        }
    if isinstance(udl, DecoratorList):
        return [
            hashable_to_original(v) if isinstance(v, _FROM_HASHABLE) else v
            for v in udl.data
        ]
    if isinstance(udl, DecoratorTuple):
        return tuple(
            hashable_to_original(v) if isinstance(v, _FROM_HASHABLE) else v for v in udl
        )
    return udl


def join_first_letters(name: str) -> str:
    """Join the first letter of each nonempty underscore-separated segment.

    Args:
        name: Name whose segments should be abbreviated.

    Returns:
        The initials with their original casing. For example, taper_length gives tl.
    """
    return "".join([x[0] for x in name.split("_") if x])


def dict2name(prefix: str | None = None, **kwargs: object) -> str:
    """Build a name from abbreviated parameter names and cleaned values.

    Args:
        prefix: Optional label preceding the parameter fragments.
        **kwargs: Parameters to encode in insertion order. The self entry is skipped.

    Returns:
        The combined and cleaned name.
    """
    kwargs.pop("self", None)
    label = [prefix] if prefix else []
    for key, value in kwargs.items():
        key_ = join_first_letters(key)
        label += [f"{key_.upper()}{clean_value(value)}"]
    label_ = "_".join(label)
    return clean_name(label_)


def convert_metadata_type(value: object) -> MetaData:
    """Normalize metadata recursively for layout settings.

    Args:
        value: Value to normalize, including nested containers and KLayout objects.

    Returns:
        Metadata with integral floats converted to integers and other unsupported leaf
        values converted to name fragments.
    """
    if value is None:
        return None
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    if serializible_value_or_shape_guard(value):
        return value
    if isinstance(value, tuple):
        return tuple(convert_metadata_type(tv) for tv in value)
    if isinstance(value, list):
        return [convert_metadata_type(tv) for tv in value]
    if isinstance(value, dict):
        return {k: convert_metadata_type(v) for k, v in value.items()}
    return clean_value(value)


def check_metadata_type(value: object) -> MetaData:
    """Validate a value recursively against supported metadata types.

    Args:
        value: Candidate metadata value, possibly containing nested containers.

    Returns:
        The metadata value with integral floats converted to integers.

    Raises:
        ValueError: If a leaf value has an unsupported type.
    """
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if serializible_value_or_shape_guard(value):
        return value
    if isinstance(value, tuple):
        return tuple(check_metadata_type(tv) for tv in value)
    if isinstance(value, list):
        return [check_metadata_type(tv) for tv in value]
    if isinstance(value, dict):
        return {k: check_metadata_type(v) for k, v in value.items()}
    msg = (
        "MetaData values of the info dict only support int, float, string"
        f", tuple or list. {value=}, {type(value)=}"
    )
    raise ValueError(msg)


def serialize_setting(setting: object) -> JSONSerializable:
    """Encode a raw factory argument for JSON storage.

    Args:
        setting: Argument value, which may contain nested containers or KLayout objects.

    Returns:
        JSON-compatible data with KLayout objects represented by tagged strings and
        other unsupported values represented by name fragments.
    """
    if setting is None or isinstance(setting, bool | int | float | str):
        return setting
    if serializible_shape_guard(setting):
        return f"!#{setting.__class__.__name__} {setting!s}"
    if isinstance(setting, Mapping):
        return {str(name): serialize_setting(value) for name, value in setting.items()}
    if isinstance(setting, tuple):
        return tuple(serialize_setting(value) for value in setting)
    if isinstance(setting, Sequence):
        return [serialize_setting(value) for value in setting]
    return clean_value(setting)


def deserialize_setting(setting: JSONSerializable) -> MetaData:
    """Decode metadata from JSON-compatible settings.

    Args:
        setting: Stored setting containing scalars, nested containers, or tagged
            strings.

    Returns:
        The setting with recognized KLayout objects reconstructed from their tags.
    """
    if isinstance(setting, dict):
        return {
            name: deserialize_setting(_setting) for name, _setting in setting.items()
        }
    if isinstance(setting, list):
        return [deserialize_setting(s) for s in setting]
    if isinstance(setting, tuple):
        return tuple(deserialize_setting(s) for s in setting)
    if isinstance(setting, str) and setting.startswith("!#"):
        cls_name, value = setting.removeprefix("!#").split(" ", 1)
        match cls_name:
            case "LayerInfo":
                return getattr(kdb, cls_name).from_string(value)
            case _:
                return getattr(kdb, cls_name).from_s(value)
    return setting


def get_cell_name(
    cell_type: str, max_cellname_length: int | None = None, **kwargs: object
) -> str:
    """Generate a bounded-length name from a cell type and its parameters.

    Args:
        cell_type: Base name, usually the factory name.
        max_cellname_length: Maximum name length. A false value uses the configured
            limit.
        **kwargs: Parameter values to encode in the name.

    Returns:
        The generated name with a hash suffix if the full name exceeds the limit.
    """
    name = cell_type
    max_cellname_length = max_cellname_length or settings.max_cellname_length

    if kwargs:
        name += f"_{dict2name(None, **kwargs)}"

    if len(name) > max_cellname_length:
        name_hash = cell_name_hash(name)
        name = f"{name[: (max_cellname_length - 9)]}_{name_hash}"

    return name


_ISHAPES: UnionType = (
    kdb.Box
    | kdb.Edge
    | kdb.Path
    | kdb.Polygon
    | kdb.Region
    | kdb.SimplePolygon
    | kdb.Text
)
_DSHAPES: UnionType = (
    kdb.DBox | kdb.DEdge | kdb.DPath | kdb.DPolygon | kdb.DSimplePolygon | kdb.DText
)
_SERIALIZABLE_SHAPES: UnionType = (
    kdb.CplxTrans
    | kdb.DCplxTrans
    | kdb.DEdgePair
    | kdb.DPoint
    | kdb.DTrans
    | kdb.DVector
    | kdb.EdgePair
    | kdb.EdgePairs
    | kdb.Edges
    | kdb.ICplxTrans
    | kdb.LayerInfo
    | kdb.Matrix2d
    | kdb.Matrix3d
    | kdb.Point
    | kdb.Texts
    | kdb.Trans
    | kdb.VCplxTrans
    | kdb.Vector
    | lay.LayerProperties
    | _ISHAPES
    | _DSHAPES
)
_SERIALIZABLE_VALUES_OR_SHAPES: UnionType = (
    bool | int | float | str | _SERIALIZABLE_SHAPES
)


def serializible_value_or_shape_guard(
    value: object,
) -> TypeGuard[int | float | bool | str | SerializableShape]:
    """Check whether the value is a supported scalar or KLayout object."""
    return isinstance(value, _SERIALIZABLE_VALUES_OR_SHAPES)


def serializible_shape_guard(
    value: object,
) -> TypeGuard[SerializableShape]:
    """Check whether the value is on the KLayout serialization allowlist."""
    return isinstance(value, _SERIALIZABLE_SHAPES)


def ishape_guard(value: object) -> TypeGuard[IShapeLike]:
    """Recognize supported integer-coordinate KLayout shapes."""
    return isinstance(value, _ISHAPES)


def dshape_guard(value: object) -> TypeGuard[DShapeLike]:
    """Recognize supported floating-point KLayout shapes."""
    return isinstance(value, _DSHAPES)


def get_function_name(f: Callable[..., object]) -> str:
    """Resolve a callable name, following wrapped functions such as partials.

    Args:
        f: Callable to inspect.

    Returns:
        The first available callable name.

    Raises:
        ValueError: If neither the callable nor its wrapped function has a name.
    """
    if hasattr(f, "__name__"):
        return str(f.__name__)
    if hasattr(f, "func") and callable(f.func):
        return get_function_name(f.func)
    raise ValueError(f"Function {f} has no name.")


def kcl_cross_section_serializer() -> Callable[[SymmetricCrossSection], int]:
    """Build a cache-key serializer that uses persisted cross-section IDs."""

    def serialize_cross_section_spec(cross_section: SymmetricCrossSection) -> int:
        """Return the database ID of a saved cross section."""
        if cross_section.id is None:
            raise ValueError("Cross section must be saved before serialization")
        return cross_section.id

    return serialize_cross_section_spec
