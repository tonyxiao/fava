"""Generate a deterministic synthetic Beancount ledger for benchmarks."""

from __future__ import annotations

import argparse
import random
from datetime import date
from datetime import timedelta
from pathlib import Path
from typing import TextIO

START_DATE = date(2010, 1, 1)
END_DATE = date(2025, 1, 1)
CURRENCIES = ("USD", "EUR", "GBP")
CURRENCY_WEIGHTS = (70, 20, 10)
CATEGORIES = (
    "Dining",
    "Groceries",
    "Travel",
    "Software",
    "Office",
    "Utilities",
    "Transport",
    "Healthcare",
)
PAYEES = (
    "Acme Market",
    "Alpine Books",
    "Bluebird Cafe",
    "Cedar Software",
    "City Transit",
    "Cloud Tools",
    "Corner Grocery",
    "Evergreen Supply",
    "Ferry Company",
    "Garden Pharmacy",
    "Harbor Hotel",
    "Indigo Airlines",
    "Juniper Foods",
    "Keystone Office",
    "Lighthouse Media",
    "Metro Parking",
    "Northwind Telecom",
    "Oak Street Cafe",
    "Paper Plane Travel",
    "Quartz Services",
    "Redwood Market",
    "Summit Hardware",
    "Tandem Taxi",
    "Union Utilities",
    "Valley Clinic",
    "West End Deli",
    "Yellow Finch Design",
    "Zenith Hosting",
)
TAGS = ("business", "reimbursable", "recurring", "personal", "online")
EVENT_TYPES = (
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
)


def _account_names() -> list[str]:
    """Return all accounts opened by the generated ledger."""
    accounts = [
        f"Assets:Cash:{currency}:{kind}"
        for currency in CURRENCIES
        for kind in ("Operating", "Reserve", "Clearing")
    ]
    accounts.extend(
        f"Expenses:{category}:{currency}"
        for currency in CURRENCIES
        for category in CATEGORIES
    )
    return accounts


def _transaction_lines(
    index: int, count: int, rng: random.Random
) -> list[str]:
    """Generate a balanced transaction with split expense postings."""
    date_span = (END_DATE - START_DATE).days
    txn_date = START_DATE + timedelta(days=(index * date_span // count))
    currency = rng.choices(CURRENCIES, weights=CURRENCY_WEIGHTS, k=1)[0]
    cash_account_kind = rng.choices(
        ("Operating", "Reserve", "Clearing"), weights=(90, 6, 4), k=1
    )[0]
    amount_cents = rng.randint(250, 250_000)
    first_part = rng.randint(1, amount_cents - 2)
    second_part = rng.randint(1, amount_cents - first_part - 1)
    third_part = amount_cents - first_part - second_part
    first_category, second_category, third_category = rng.sample(CATEGORIES, 3)
    payee = PAYEES[index % len(PAYEES)]
    tag = TAGS[index % len(TAGS)]

    def amount(cents: int) -> str:
        return f"{cents // 100}.{cents % 100:02d}"

    def posting(account: str, cents: int, sign: str = "") -> str:
        return f"  {account}  {sign}{amount(cents)} {currency}\n"

    transaction_header = (
        f'{txn_date.isoformat()} * "{payee}" '
        f'"{first_category} purchase" #{tag}\n'
    )
    return [
        transaction_header,
        f'  import_id: "synthetic-{index:06d}"\n',
        f'  batch: "batch-{index // 5000:03d}"\n',
        f'  merchant_category: "{first_category.lower()}"\n',
        '  source: "generated-performance-fixture"\n',
        posting(
            f"Assets:Cash:{currency}:{cash_account_kind}", amount_cents, "-"
        ),
        posting(f"Expenses:{first_category}:{currency}", first_part),
        posting(f"Expenses:{second_category}:{currency}", second_part),
        posting(f"Expenses:{third_category}:{currency}", third_part),
        "\n",
    ]


def _minimal_pdf() -> bytes:
    """Return a compact, valid one-page PDF used by generated documents."""
    text = (
        b"BT /F1 18 Tf 48 736 Td (Fava performance fixture) Tj "
        b"/F1 11 Tf 0 -28 Td "
        b"(Synthetic document for large-ledger benchmarks.) Tj ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        f"<< /Length {len(text)} >>\nstream\n".encode("ascii")
        + text
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode("ascii"))
        content.extend(body)
        content.extend(b"\nendobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(content)


def _document_lines(
    index: int,
    account: str,
    documents_directory: str,
    count: int,
) -> str:
    """Return a document directive with a unique, relative generated path."""
    date_span = (END_DATE - START_DATE).days
    document_date = START_DATE + timedelta(days=(index * date_span // count))
    account_directory = account.replace(":", "-")
    filename = f"document-{index:06d}.pdf"
    filepath = f"{documents_directory}/{account_directory}/{filename}"
    return f'{document_date.isoformat()} document {account} "{filepath}"\n'


def _event_line(index: int, count: int) -> str:
    """Return a deterministic event directive from the 15-year fixture span."""
    date_span = (END_DATE - START_DATE).days
    event_date = START_DATE + timedelta(days=(index * date_span // count))
    event_type = EVENT_TYPES[index % len(EVENT_TYPES)]
    return (
        f'{event_date.isoformat()} event "{event_type}" '
        f'"Synthetic event {index:06d}"\n'
    )


def _prepare_documents(output: Path, count: int) -> str:
    """Create compact PDF files and return their ledger-relative directory."""
    if not count:
        return ""
    documents_directory = f"generated-documents-{count}"
    documents_root = output.parent / documents_directory
    documents_root.mkdir(parents=True, exist_ok=True)
    template = documents_root / ".template.pdf"
    template.write_bytes(_minimal_pdf())
    accounts = _account_names()
    template_bytes = template.read_bytes()
    try:
        for index in range(count):
            account_directory = accounts[index % len(accounts)].replace(
                ":", "-"
            )
            directory = documents_root / account_directory
            directory.mkdir(exist_ok=True)
            filepath = directory / f"document-{index:06d}.pdf"
            try:
                filepath.hardlink_to(template)
            except FileExistsError:
                pass
            except OSError:
                filepath.write_bytes(template_bytes)
    finally:
        template.unlink(missing_ok=True)
    return documents_directory


def _write_market_data(ledger: TextIO, commodities: int, prices: int) -> None:
    """Write synthetic commodity declarations and unique dated prices."""
    ledger.writelines(
        f"2000-01-01 commodity SYNTH{index:06d}\n"
        for index in range(commodities)
    )
    if commodities:
        ledger.write("\n")
    for index in range(prices):
        date_index = index // commodities
        price_date = START_DATE + timedelta(days=date_index)
        commodity = f"SYNTH{index % commodities:06d}"
        price = f"{100 + (index % 1000)}.{(index * 37) % 100:02d}"
        ledger.write(
            f"{price_date.isoformat()} price {commodity} {price} USD\n"
        )
    if prices:
        ledger.write("\n")


def _write_transactions(ledger: TextIO, transactions: int, seed: int) -> None:
    """Write balanced synthetic transaction entries."""
    rng = random.Random(seed)  # noqa: S311 - deterministic fixture data.
    for index in range(transactions):
        ledger.writelines(_transaction_lines(index, transactions, rng))


def _write_document_and_event_entries(
    ledger: TextIO,
    documents: int,
    events: int,
    documents_directory: str,
) -> None:
    """Write document and event directives into the synthetic ledger."""
    accounts = _account_names()
    for index in range(documents):
        account = accounts[index % len(accounts)]
        ledger.write(
            _document_lines(index, account, documents_directory, documents)
        )
    if documents:
        ledger.write("\n")
    for index in range(events):
        ledger.write(_event_line(index, events))


def generate_ledger(
    output: Path,
    transactions: int,
    *,
    seed: int = 20261013,
    commodities: int = 0,
    prices: int = 0,
    documents: int = 0,
    events: int = 0,
) -> None:
    """Write a deterministic synthetic ledger and optional scale-up entries."""
    for name, count, minimum in (
        ("transactions", transactions, 1),
        ("commodities", commodities, 0),
        ("prices", prices, 0),
        ("documents", documents, 0),
        ("events", events, 0),
    ):
        if count < minimum:
            qualifier = "positive" if minimum else "non-negative"
            message = f"{name} must be {qualifier}"
            raise ValueError(message)
    if prices and not commodities:
        message = "prices require at least one generated commodity"
        raise ValueError(message)

    output.parent.mkdir(parents=True, exist_ok=True)
    documents_directory = _prepare_documents(output, documents)

    enriched = any((commodities, prices, documents, events))
    with output.open("w", encoding="utf-8", newline="\n") as ledger:
        ledger.write('option "title" "Fava Performance Fixture"\n')
        if enriched:
            ledger.write('option "operating_currency" "USD"\n')
        ledger.write("\n")
        for account in _account_names():
            ledger.write(f"2000-01-01 open {account}\n")
        ledger.write("\n")
        _write_market_data(ledger, commodities, prices)
        _write_transactions(ledger, transactions, seed)
        _write_document_and_event_entries(
            ledger, documents, events, documents_directory
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "transactions", type=int, help="number of transactions"
    )
    parser.add_argument("output", type=Path, help="output .beancount file")
    parser.add_argument("--seed", type=int, default=20261013)
    parser.add_argument("--commodities", type=int, default=0)
    parser.add_argument("--prices", type=int, default=0)
    parser.add_argument("--documents", type=int, default=0)
    parser.add_argument("--events", type=int, default=0)
    args = parser.parse_args()
    generate_ledger(
        args.output,
        args.transactions,
        seed=args.seed,
        commodities=args.commodities,
        prices=args.prices,
        documents=args.documents,
        events=args.events,
    )
    print(  # noqa: T201
        f"Wrote {args.transactions:,} transactions, {args.commodities:,} "
        f"commodities, {args.prices:,} prices, {args.documents:,} documents, "
        f"and {args.events:,} events to {args.output}"
    )


if __name__ == "__main__":
    main()
