"""Structured data used exclusively by the experimental Transactions report."""

from __future__ import annotations

from typing import cast
from typing import TYPE_CHECKING

from flask import current_app
from msgspec import Struct

from fava.beans.abc import Transaction
from fava.beans.funcs import hash_entry
from fava.context import g
from fava.json_api import NotFoundError
from fava.json_api import ValidationError
from fava.template_filters import replace_numbers

if TYPE_CHECKING:
    from collections.abc import Sequence


class PostingRow(Struct, frozen=True):
    """Exact debit/credit strings, without floating-point conversion."""

    account: str
    debit: str
    credit: str
    note: str


class TransactionRow(Struct, frozen=True):
    """A transaction and its postings, rendered directly by Svelte."""

    entry_hash: str
    date: str
    flag: str
    payee: str
    narration: str
    note: str
    postings: tuple[PostingRow, ...]


class TransactionsPage(Struct, frozen=True):
    """A bounded page of experimental transaction data."""

    transactions: tuple[TransactionRow, ...]
    page: int
    page_size: int
    total_entries: int
    total_pages: int


def _note(meta: object) -> str:
    if isinstance(meta, dict):
        value = meta.get("note")
        return "" if value is None else str(value)
    return ""


def _row(entry: Transaction) -> TransactionRow:
    incognito = current_app.config["INCOGNITO"]
    postings = []
    for posting in entry.postings:
        debit = credit = ""
        if posting.units is not None:
            number = posting.units.number
            amount = f"{number.copy_abs()} {posting.units.currency}"
            if incognito:
                amount = replace_numbers(amount) or ""
            if number.is_signed():
                credit = amount
            else:
                debit = amount
        postings.append(
            PostingRow(posting.account, debit, credit, _note(posting.meta))
        )
    return TransactionRow(
        hash_entry(entry),
        str(entry.date),
        entry.flag,
        entry.payee or "",
        entry.narration or "",
        _note(entry.meta),
        tuple(postings),
    )


def transactions_page(
    page: int,
    per_page: int,
    sort: str,
    order: str,
    show: str,
) -> TransactionsPage:
    """Read a page with ledger filters and no Journal rendering."""
    if page < 1 or not 1 <= per_page <= 200:
        detail = "page must be positive; per_page must be 1-200"
        raise ValidationError(detail)
    if sort not in {"date", "flag", "narration"}:
        detail = "sort must be date, flag, or narration"
        raise ValidationError(detail)
    if order not in {"asc", "desc"}:
        detail = "order must be asc or desc"
        raise ValidationError(detail)
    shown = frozenset(filter(None, show.split(",")))
    if not shown <= {"cleared", "pending", "other"}:
        detail = "show must contain cleared, pending, or other"
        raise ValidationError(detail)

    g.ledger.changed()
    filtered = g.filtered
    key = (filtered, filtered.revision, shown, sort, order)
    entries = cast(
        "Sequence[Transaction] | None",
        g.ledger.get_report_view_cache("experimental_transactions", key),
    )
    if entries is None:
        prepared = [
            entry
            for entry in filtered.entries_without_prices
            if isinstance(entry, Transaction)
            and {"*": "cleared", "!": "pending"}.get(entry.flag, "other")
            in shown
        ]
        # Stable secondary date order also preserves same-day ledger order.
        prepared.sort(key=lambda entry: entry.date, reverse=order == "desc")
        if sort == "flag":
            prepared.sort(
                key=lambda entry: entry.flag, reverse=order == "desc"
            )
        elif sort == "narration":
            prepared.sort(
                key=lambda entry: (entry.payee or "", entry.narration or ""),
                reverse=order == "desc",
            )
        entries = tuple(prepared)
        g.ledger.set_report_view_cache(
            "experimental_transactions", key, entries
        )

    total_pages = max(1, (len(entries) + per_page - 1) // per_page)
    if page > total_pages:
        raise NotFoundError
    start = (page - 1) * per_page
    return TransactionsPage(
        tuple(_row(entry) for entry in entries[start : start + per_page]),
        page,
        per_page,
        len(entries),
        total_pages,
    )
