"""The JSON form of the values hooks and the hosted server exchange: engine arguments, results and parsed facts.

A dataclass from airspace.types travels as {"__t": "Verdict", ...its fields}; tuples travel as lists and come back
as tuples where the field says so; sets travel as sorted lists. Anything else must already be JSON.
"""

import dataclasses
import typing
from typing import Any

from airspace import types as _types

_TYPES: dict[str, type] = {
    name: cls for name, cls in vars(_types).items() if isinstance(cls, type) and dataclasses.is_dataclass(cls)
}


def encode(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        name = type(value).__name__
        if name not in _TYPES:
            raise TypeError(f"{name} is not a wire type")
        return {"__t": name, **{f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(encode(v) for v in value)
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"{type(value).__name__} cannot be sent")


def _hints(cls: type) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def _shape(value: Any, hint: Any) -> Any:
    """Turn decoded lists back into the tuples a field's annotation asks for."""
    origin = typing.get_origin(hint)
    if origin is tuple and isinstance(value, list):
        return tuple(value)
    if origin is list and isinstance(value, list):
        (inner,) = typing.get_args(hint) or (Any,)
        return [_shape(v, inner) for v in value]
    if origin is dict and isinstance(value, dict):
        _, inner = typing.get_args(hint) or (Any, Any)
        return {k: _shape(v, inner) for k, v in value.items()}
    return value


def decode(value: Any) -> Any:
    if isinstance(value, list):
        return [decode(v) for v in value]
    if isinstance(value, dict):
        name = value.get("__t")
        if name is None:
            return {k: decode(v) for k, v in value.items()}
        cls = _TYPES.get(name)
        if cls is None:
            raise ValueError(f"unknown wire type {name!r}")
        hints = _hints(cls)
        names = {f.name for f in dataclasses.fields(cls)}
        fields = {k: _shape(decode(v), hints.get(k, Any)) for k, v in value.items() if k in names}
        return cls(**fields)
    return value
