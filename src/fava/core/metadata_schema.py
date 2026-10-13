"""Versioned metadata contracts independent of accounting names."""

from __future__ import annotations

import datetime
import decimal
import json
import re
from typing import Any
from typing import Never
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

KEY = re.compile(r"^[a-z][a-zA-Z0-9_-]+$")
TYPES = {"string", "enum", "tree", "number", "boolean", "date"}


def fail(message: str) -> Never:
    """Raise a schema validation error with a useful message."""
    raise ValueError(message)


def parse_schema(
    raw: str, legacy_keys: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize the configured contract; fail visibly on malformed schemas."""
    try:
        if raw:
            schema = json.loads(raw)
            if not isinstance(schema, dict) or schema.get("version") != 1:
                fail("metadata schema requires version 1")
            if set(schema) - {"version", "fields", "$schema"}:
                fail("unknown schema properties")
            fields = schema.get("fields")
            if not isinstance(fields, list):
                fail("metadata schema fields must be an array")
        else:
            fields = [
                {"key": k.strip()} for k in legacy_keys.split(",") if k.strip()
            ]
        normalized = normalize_fields(fields)
    except (ValueError, TypeError) as error:
        return [], [f"Metadata schema: {error}"]
    return normalized, []


def normalize_fields(fields: list[Any]) -> list[dict[str, Any]]:  # noqa: PLR0912
    """Validate explicit contract fields and filter-source ownership."""
    normalized = []
    seen = set()
    filter_sources: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            fail("each field must be an object")
        if set(field) - {
            "key",
            "label",
            "type",
            "scope",
            "required",
            "sources",
            "separator",
            "values",
        }:
            fail("unknown field properties")
        key = field.get("key", "")
        kind = field.get("type", "string")
        scope = field.get("scope", "transaction")
        sources = field.get("sources", [key])
        values = field.get("values", [])
        separator = field.get("separator", "/")
        label = field.get("label", str(key).replace("_", " "))
        if not isinstance(key, str) or not KEY.fullmatch(key) or key in seen:
            fail("field keys must be valid and unique")
        if kind not in TYPES or scope not in {
            "transaction",
            "posting",
            "both",
        }:
            fail(f"invalid type or scope for {key}")
        if (
            not isinstance(sources, list)
            or not sources
            or any(
                not isinstance(s, str) or not KEY.fullmatch(s) for s in sources
            )
            or len(set(sources)) != len(sources)
        ):
            fail(f"invalid sources for {key}")
        if len(sources) > 1 and kind != "tree":
            fail("multiple sources require a tree field")
        if not isinstance(values, list) or any(
            not isinstance(v, str) or not v for v in values
        ):
            fail(f"invalid values for {key}")
        if kind == "enum" and not values:
            fail(f"enum {key} requires values")
        if not isinstance(separator, str) or len(separator) != 1:
            fail("tree separator must be one character")
        if not isinstance(label, str) or not isinstance(
            field.get("required", False), bool
        ):
            fail(f"invalid label or required flag for {key}")
        if kind == "tree" and any(
            any(not segment for segment in value.split(separator))
            or (
                len(sources) > 1 and len(value.split(separator)) > len(sources)
            )
            for value in values
        ):
            fail(f"invalid tree vocabulary for {key}")
        if scope != "posting" and kind in {"string", "enum", "tree"}:
            if filter_sources.intersection(sources):
                fail("filter fields must not share source keys")
            filter_sources.update(sources)
        seen.add(key)
        normalized.append(
            {
                "key": key,
                "label": label,
                "type": kind,
                "scope": scope,
                "sources": sources,
                "values": values,
                "separator": separator,
                "required": field.get("required", False),
            }
        )
    return normalized


def field_value(
    field: dict[str, Any], meta: Mapping[str, object]
) -> object | None:
    """Compose a tree path from contiguous legacy source fields."""
    if len(field["sources"]) == 1:
        return meta.get(field["sources"][0])
    parts = []
    for index, source in enumerate(field["sources"]):
        value = meta.get(source)
        if value is None:
            if any(
                meta.get(s) is not None for s in field["sources"][index + 1 :]
            ):
                return ""
            break
        if not isinstance(value, str):
            return value
        if field["separator"] in value:
            return ""
        parts.append(value)
    return field["separator"].join(parts) if parts else None


def validate_value(field: dict[str, Any], value: object) -> str | None:
    """Validate present values; optional missing values are permitted."""
    if value is None:
        return "required value missing" if field["required"] else None
    kind = field["type"]
    valid = (
        isinstance(value, str)
        if kind in {"string", "enum", "tree"}
        else isinstance(value, decimal.Decimal)
        if kind == "number"
        else isinstance(value, bool)
        if kind == "boolean"
        else isinstance(value, datetime.date)
    )
    if not valid:
        return f"expected {kind}"
    if isinstance(value, str):
        if not value:
            return "empty value"
        if kind == "tree" and any(
            not p for p in value.split(field["separator"])
        ):
            return "empty tree segment"
        if field["values"] and value not in field["values"]:
            return "value outside declared vocabulary"
    return None
