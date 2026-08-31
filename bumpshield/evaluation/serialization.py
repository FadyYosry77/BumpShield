"""Canonical benchmark JSON conversion without runtime dependencies."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path


def jsonable(value: object) -> object:
    """Convert typed evaluation values to deterministic JSON-compatible data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple | list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    raise TypeError(f"unsupported benchmark artifact value: {type(value).__name__}")
