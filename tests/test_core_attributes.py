from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

from fava.core import FavaLedger
from fava.core.attributes import get_active_years
from fava.util.date import END_OF_YEAR
from fava.util.date import FiscalYearEnds

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Sequence
    from pathlib import Path

    from fava.beans.abc import Directive

    from .conftest import SnapshotFunc


def test_get_active_years(load_doc_entries: Sequence[Directive]) -> None:
    """
    2010-11-12 * "test"
        Assets:T   4.00 USD
        Expenses:T
    2011-11-12 * "test"
        Assets:T   4.00 USD
        Expenses:T
    2011-11-12 * "test"
        Assets:T   4.00 USD
        Expenses:T
    2012-12-12 * "test"
        Assets:T   4.00 USD
        Expenses:T
    2013-02-02 * "test"
        Assets:T   4.00 USD
        Expenses:T
    """
    assert get_active_years(load_doc_entries, END_OF_YEAR) == [
        "2013",
        "2012",
        "2011",
        "2010",
    ]
    assert get_active_years(load_doc_entries, FiscalYearEnds.JP) == [
        "FY2012",
        "FY2011",
        "FY2010",
    ]


def test_payee_accounts(example_ledger: FavaLedger) -> None:
    attr = example_ledger.attributes
    assert attr.payee_accounts("NOTAPAYEE") == attr.accounts

    verizon = attr.payee_accounts("Verizon Wireless")
    assert verizon[:2] == ["Assets:US:BofA:Checking", "Expenses:Home:Phone"]
    assert len(verizon) == len(attr.accounts)


def test_payee_transaction(example_ledger: FavaLedger) -> None:
    attr = example_ledger.attributes
    assert attr.payee_transaction("NOTAPAYEE") is None

    txn = attr.payee_transaction("BayBook")
    assert txn
    assert str(txn.date) == "2016-05-05"


def test_narration_transaction(example_ledger: FavaLedger) -> None:
    attr = example_ledger.attributes
    assert attr.narration_transaction("NOTANARRATION") is None

    txn = attr.narration_transaction("Monthly bank fee")
    assert txn
    assert str(txn.date) == "2016-05-04"


def test_narrations(
    example_ledger: FavaLedger,
    snapshot: SnapshotFunc,
) -> None:
    narrations = example_ledger.attributes.narrations
    assert narrations
    snapshot(narrations, json=True)


def test_metadata_dimensions_are_entry_scoped(tmp_path: Path) -> None:
    """
    2025-01-01 open Assets:Bank USD
    2025-01-01 open Income:Rent USD
    2025-01-02 * "Platform" "Owned stay"
      property: "House"
      unit: "Upstairs"
      ownership_scope: "Owned"
      Assets:Bank 100 USD
      Income:Rent -100 USD
    2025-01-03 * "Platform" "Pooled payment"
      property: "Mixed"
      Assets:Bank 50 USD
        property: "Posting-only house"
      Income:Rent -50 USD
    """
    path = tmp_path / "metadata.bean"
    path.write_text(
        dedent(test_metadata_dimensions_are_entry_scoped.__doc__ or "")
    )
    load_doc = FavaLedger(str(path))
    assert load_doc.attributes.metadata_values["property"] == [
        "House",
        "Mixed",
    ]
    assert (
        "Posting-only house"
        not in load_doc.attributes.metadata_values["property"]
    )
    assert any(
        row.get("property") == "House" and row.get("unit") == "Upstairs"
        for row in load_doc.attributes.metadata_records
    )


def test_configured_metadata_keys_and_non_string_values(
    tmp_path: Path,
) -> None:
    """
    2025-01-01 custom "fava-option" "filter-metadata" "department"
    2025-01-01 open Assets:Bank USD
    2025-01-01 open Income:Rent USD
    2025-01-02 * "Platform" "Stay"
      department: "Ops"
      property: "Not selected"
      Assets:Bank 100 USD
      Income:Rent -100 USD
    """
    path = tmp_path / "metadata.bean"
    path.write_text(
        dedent(
            test_configured_metadata_keys_and_non_string_values.__doc__ or ""
        )
    )
    load_doc = FavaLedger(str(path))
    assert load_doc.attributes.metadata_values == {"department": ["Ops"]}
