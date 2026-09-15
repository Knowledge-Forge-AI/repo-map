"""Exact validators for private test-hygiene evidence and configuration."""

from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar


class HygieneValidationError(ValueError):
    """A private hygiene value has the wrong exact shape or type."""


EnumT = TypeVar("EnumT", bound=Enum)


def exact_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise HygieneValidationError(f"{name} must be an exact Boolean")
    return value


def nonnegative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise HygieneValidationError(f"{name} must be a nonnegative integer")
    return value


def bounded_string(value: Any, name: str, limit: int = 128) -> str:
    if type(value) is not str or not value or len(value) > limit:
        raise HygieneValidationError(f"invalid {name}")
    if any(char in value for char in ("\0", "\n", "\r")):
        raise HygieneValidationError(f"unsafe {name}")
    return value


def exact_object(value: Any, required: set[str], name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != required:
        raise HygieneValidationError(f"invalid {name} object keys")
    if any(type(key) is not str for key in value):
        raise HygieneValidationError(f"invalid {name} object keys")
    return value


def exact_array(value: Any, name: str) -> list[Any]:
    if type(value) is not list:
        raise HygieneValidationError(f"invalid {name} array")
    return value


def closed_enum(enum_type: type[EnumT], value: Any, name: str) -> EnumT:
    if type(value) is not str:
        raise HygieneValidationError(f"invalid {name}")
    try:
        return enum_type(value)
    except ValueError as error:
        raise HygieneValidationError(f"unsupported {name}") from error


def sha256_hex(value: Any, name: str) -> str:
    result = bounded_string(value, name, 64)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise HygieneValidationError(f"invalid {name}")
    return result


__all__ = [
    "HygieneValidationError",
    "bounded_string",
    "closed_enum",
    "exact_array",
    "exact_bool",
    "exact_object",
    "nonnegative_int",
    "sha256_hex",
]
