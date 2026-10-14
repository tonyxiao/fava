"""Tests for the synthetic performance ledger generator."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from beancount import loader
from beancount.core.data import Commodity
from beancount.core.data import Document
from beancount.core.data import Event
from beancount.core.data import Price
from beancount.core.data import Transaction

from contrib.performance.generate_ledger import generate_ledger


def test_generate_ledger_is_deterministic_and_balanced(tmp_path: Path) -> None:
    """Generated ledgers load cleanly and contain split balanced postings."""
    first = tmp_path / "first.beancount"
    second = tmp_path / "second.beancount"
    generate_ledger(first, 25)
    generate_ledger(second, 25)

    assert first.read_bytes() == second.read_bytes()
    entries, errors, _options = loader.load_file(str(first))
    assert not errors

    transactions = [
        entry for entry in entries if isinstance(entry, Transaction)
    ]
    assert len(transactions) == 25
    assert all(len(entry.postings) == 4 for entry in transactions)
    for entry in transactions:
        currencies = set()
        total = Decimal(0)
        for posting in entry.postings:
            assert posting.units is not None
            assert isinstance(posting.units.number, Decimal)
            currencies.add(posting.units.currency)
            total += posting.units.number
        assert len(currencies) == 1
        assert total == 0
    assert all(
        "import_id" in entry.meta and "batch" in entry.meta
        for entry in transactions
    )


def test_generate_ledger_with_enrichment(tmp_path: Path) -> None:
    """Enriched fixtures load cleanly with unique prices and real documents."""
    first = tmp_path / "enriched.beancount"
    second = tmp_path / "enriched-copy.beancount"
    options = {
        "commodities": 3,
        "prices": 7,
        "documents": 5,
        "events": 21,
    }
    generate_ledger(first, 12, **options)
    generate_ledger(second, 12, **options)

    assert first.read_bytes() == second.read_bytes()
    entries, errors, _options = loader.load_file(str(first))
    assert not errors

    transactions = [
        entry for entry in entries if isinstance(entry, Transaction)
    ]
    commodity_entries = [
        entry for entry in entries if isinstance(entry, Commodity)
    ]
    price_entries = [entry for entry in entries if isinstance(entry, Price)]
    documents = [entry for entry in entries if isinstance(entry, Document)]
    events = [entry for entry in entries if isinstance(entry, Event)]

    assert len(transactions) == 12
    assert len(commodity_entries) == options["commodities"]
    assert len(price_entries) == options["prices"]
    assert len(documents) == options["documents"]
    assert len(events) == options["events"]
    assert len({entry.currency for entry in commodity_entries}) == len(
        commodity_entries
    )
    assert len(
        {
            (entry.currency, entry.amount.currency, entry.date)
            for entry in price_entries
        }
    ) == len(price_entries)
    assert len({entry.description for entry in events}) == len(events)
    assert {entry.type for entry in events} == {
        "location",
        "phone",
        "address",
        "employer",
        "visa",
        "project",
        "meeting",
        "conference",
        "travel",
        "insurance",
        "subscription",
        "membership",
        "vehicle",
        "property",
        "account",
        "beneficiary",
        "tax",
        "license",
        "milestone",
        "reminder",
    }
    assert len({entry.filename for entry in documents}) == len(documents)
    assert len({entry.account for entry in documents}) > 1
    for entry in documents:
        document = Path(entry.filename)
        if not document.is_absolute():
            document = tmp_path / document
        assert document.is_file()
        assert document.read_bytes().startswith(b"%PDF-1.4")
