"""Attributes for auto-completion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fava.core.metadata_schema import field_value
from fava.core.metadata_schema import parse_schema
from fava.core.metadata_schema import validate_value
from fava.core.module_base import FavaModule
from fava.util.date import END_OF_YEAR
from fava.util.ranking import ExponentialDecayRanker

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Sequence

    from fava.beans.abc import Directive
    from fava.beans.abc import Transaction
    from fava.core import FavaLedger
    from fava.util.date import FiscalYearEnd


def get_active_years(
    entries: Sequence[Directive], fye: FiscalYearEnd
) -> list[str]:
    """Return active years, with support for fiscal years.

    Args:
        entries: Beancount entries
        fye: fiscal year end

    Returns:
        A reverse sorted list of years or fiscal years that occur in the
        entries.
    """
    if fye == END_OF_YEAR:
        years = {entry.date.year for entry in entries}
        return [f"{year}" for year in sorted(years, reverse=True)]
    fiscal_years = {fye.fiscal_year(entry.date) for entry in entries}
    return [f"FY{year}" for year in sorted(fiscal_years, reverse=True)]


class AttributesModule(FavaModule):
    """Some attributes of the ledger (mostly for auto-completion)."""

    def __init__(self, ledger: FavaLedger) -> None:
        super().__init__(ledger)
        self.accounts: Sequence[str] = []
        self.currencies: Sequence[str] = []
        self.payees: Sequence[str] = []
        self.links: Sequence[str] = []
        self.tags: Sequence[str] = []
        self.years: Sequence[str] = []
        self.metadata_values: dict[str, list[str]] = {}
        self.metadata_records: list[dict[str, str]] = []
        self.metadata_schema = []
        self.metadata_issues: list[str] = []

    def load_file(self) -> None:  # noqa: D102
        all_entries = self.ledger.all_entries
        self.load_metadata()

        all_links = set()
        all_tags = set()
        for entry in all_entries:
            links = getattr(entry, "links", None)
            if links is not None:
                all_links.update(links)
            tags = getattr(entry, "tags", None)
            if tags is not None:
                all_tags.update(tags)
        self.links = sorted(all_links)
        self.tags = sorted(all_tags)

        self.years = get_active_years(
            all_entries,
            self.ledger.fava_options.fiscal_year_end,
        )

        account_ranker = ExponentialDecayRanker(
            sorted(self.ledger.accounts.keys()),
        )
        currency_ranker = ExponentialDecayRanker()
        payee_ranker = ExponentialDecayRanker()

        for txn in self.ledger.all_entries_by_type.Transaction:
            if txn.payee:
                payee_ranker.update(txn.payee, txn.date)
            for posting in txn.postings:
                account_ranker.update(posting.account, txn.date)
                currency_ranker.update(posting.units.currency, txn.date)
                if posting.cost and posting.cost.currency is not None:
                    currency_ranker.update(posting.cost.currency, txn.date)

        self.accounts = account_ranker.sort()
        self.currencies = currency_ranker.sort()
        self.payees = payee_ranker.sort()

    def load_metadata(self) -> None:
        """Discover and validate schema-defined metadata independently."""
        self.metadata_schema, self.metadata_issues = parse_schema(
            self.ledger.fava_options.metadata_schema,
            self.ledger.fava_options.filter_metadata,
        )
        values: dict[str, set[str]] = {
            f["key"]: set() for f in self.metadata_schema
        }
        combinations: set[tuple[tuple[str, str], ...]] = set()
        for txn in self.ledger.all_entries_by_type.Transaction:
            row: dict[str, str] = {}
            for field in self.metadata_schema:
                targets = []
                if field["scope"] in {"transaction", "both"}:
                    targets.append(("transaction", txn.meta or {}))
                if field["scope"] in {"posting", "both"}:
                    targets.extend(
                        (f"posting {p.account}", p.meta or {})
                        for p in txn.postings
                    )
                for scope, meta in targets:
                    value = field_value(field, meta)
                    issue = validate_value(field, value)
                    if issue:
                        self.metadata_issues.append(
                            f"{txn.date} {scope} {field['key']}: {issue}"
                        )
                    # Posting dimensions must not select a pooled journal.
                    if (
                        scope == "transaction"
                        and isinstance(value, str)
                        and value
                    ):
                        values[field["key"]].add(value)
                        row[field["key"]] = value
            if row:
                combinations.add(tuple(sorted(row.items())))
        self.metadata_records = [dict(row) for row in sorted(combinations)]
        self.metadata_values = {
            key: sorted(items) for key, items in values.items() if items
        }

    def payee_accounts(self, payee: str) -> Sequence[str]:
        """Rank accounts for the given payee."""
        account_ranker = ExponentialDecayRanker(self.accounts)
        transactions = self.ledger.all_entries_by_type.Transaction
        for txn in transactions:
            if txn.payee == payee:
                for posting in txn.postings:
                    account_ranker.update(posting.account, txn.date)
        return account_ranker.sort()

    def payee_transaction(self, payee: str) -> Transaction | None:
        """Get the last transaction for a payee."""
        transactions = self.ledger.all_entries_by_type.Transaction
        for txn in reversed(transactions):
            if txn.payee == payee:
                return txn
        return None

    def narration_transaction(self, narration: str) -> Transaction | None:
        """Get the last transaction for a narration."""
        transactions = self.ledger.all_entries_by_type.Transaction
        for txn in reversed(transactions):
            if txn.narration == narration:
                return txn
        return None

    @property
    def narrations(self) -> Sequence[str]:
        """Get the narrations of all transactions."""
        narration_ranker = ExponentialDecayRanker()
        for txn in self.ledger.all_entries_by_type.Transaction:
            if txn.narration:
                narration_ranker.update(txn.narration, txn.date)
        return narration_ranker.sort()
