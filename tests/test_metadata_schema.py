from __future__ import annotations

import datetime
import decimal
import json
from typing import TYPE_CHECKING

from fava.core import FavaLedger
from fava.core.metadata_schema import field_value
from fava.core.metadata_schema import parse_schema
from fava.core.metadata_schema import validate_value

if TYPE_CHECKING:
    from pathlib import Path


def test_schema_types_and_invalid_contracts() -> None:
    for raw in [
        '{"version":2}',
        '{"version":1,"fields":{}}',
        "no JSON",
        '{"version":1,"fields":[{"key":2}]}',
    ]:
        fields, issues = parse_schema(raw, "")
        assert fields == []
        assert issues
    for kind, good, bad in [
        ("number", decimal.Decimal(3), "3"),
        ("boolean", True, "yes"),
        ("date", datetime.date(2025, 1, 1), "2025-01-01"),
    ]:
        fields, issues = parse_schema(
            json.dumps(
                {
                    "version": 1,
                    "fields": [
                        {"key": "test_field", "type": kind, "required": True}
                    ],
                }
            ),
            "",
        )
        assert not issues
        assert validate_value(fields[0], good) is None
        assert validate_value(fields[0], bad)
        assert validate_value(fields[0], None)


def test_schema_rejects_invalid_properties_and_filter_sources() -> None:
    invalid_fields = [
        {"extra": True, "fields": []},
        {"fields": [1]},
        {"fields": [{"key": "bad_type", "type": "unknown"}]},
        {"fields": [{"key": "bad_sources", "sources": ["not valid"]}]},
        {"fields": [{"key": "multi_source", "sources": ["region", "room"]}]},
        {"fields": [{"key": "bad_values", "values": [1]}]},
        {"fields": [{"key": "empty_enum", "type": "enum"}]},
        {"fields": [{"key": "bad_separator", "separator": ""}]},
        {"fields": [{"key": "bad_required", "required": 1}]},
        {
            "fields": [
                {"key": "first_filter", "sources": ["same_source"]},
                {"key": "second_filter", "sources": ["same_source"]},
            ]
        },
    ]
    for properties in invalid_fields:
        fields, issues = parse_schema(
            json.dumps({"version": 1, **properties}), ""
        )
        assert fields == []
        assert issues


def test_tree_field_value_preserves_non_string_metadata_for_validation() -> (
    None
):
    fields, issues = parse_schema(
        json.dumps(
            {
                "version": 1,
                "fields": [
                    {
                        "key": "location",
                        "type": "tree",
                        "sources": ["region", "room"],
                    }
                ],
            }
        ),
        "",
    )
    assert not issues
    assert field_value(fields[0], {"region": 3}) == 3


def test_generic_tree_and_enum() -> None:
    fields, issues = parse_schema(
        json.dumps(
            {
                "version": 1,
                "fields": [
                    {
                        "key": "location",
                        "type": "tree",
                        "sources": ["region", "room"],
                    },
                    {"key": "status", "type": "enum", "values": ["reviewed"]},
                ],
            }
        ),
        "",
    )
    assert not issues
    assert (
        field_value(fields[0], {"region": "North", "room": "Suite"})
        == "North/Suite"
    )
    assert field_value(fields[0], {"region": "North"}) == "North"
    assert validate_value(fields[0], "North//Suite")
    assert validate_value(fields[1], "unknown")


def test_ledger_schema_validates_postings_without_promoting_them(
    tmp_path: Path,
) -> None:
    schema = json.dumps(
        {
            "version": 1,
            "fields": [
                {
                    "key": "location",
                    "type": "tree",
                    "sources": ["property", "unit"],
                },
                {
                    "key": "allocation",
                    "scope": "posting",
                    "type": "enum",
                    "values": ["House"],
                },
            ],
        }
    )
    path = tmp_path / "schema.bean"
    path.write_text(
        '2000-01-01 custom "fava-option" "metadata-schema" '
        + json.dumps(schema)
        + """
2000-01-01 open Assets:Bank USD
2000-01-01 open Income:Rent USD
2025-01-01 * "Stay"
  property: "House"
  unit: "Upstairs"
  Assets:Bank 100 USD
    allocation: "Other"
  Income:Rent -100 USD
"""
    )
    ledger = FavaLedger(str(path))
    assert ledger.attributes.metadata_values == {
        "location": ["House/Upstairs"]
    }
    assert any(
        "allocation" in issue for issue in ledger.attributes.metadata_issues
    )


def test_invalid_tree_sources_fail_visibly() -> None:
    fields, issues = parse_schema(
        json.dumps(
            {
                "version": 1,
                "fields": [
                    {
                        "key": "location",
                        "type": "tree",
                        "sources": ["property", "unit"],
                    }
                ],
            }
        ),
        "",
    )
    assert not issues
    assert validate_value(fields[0], field_value(fields[0], {"unit": "Suite"}))
    assert validate_value(
        fields[0],
        field_value(fields[0], {"property": "House", "unit": "Floor/Suite"}),
    )
    for bad_field in [
        {
            "key": "location",
            "type": "tree",
            "sources": ["property", "unit"],
            "values": ["House/Floor/Suite"],
        },
        {"key": "location", "typo": "tree"},
    ]:
        assert parse_schema(
            json.dumps({"version": 1, "fields": [bad_field]}), ""
        )[1]
