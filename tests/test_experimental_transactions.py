from __future__ import annotations

import datetime
from decimal import Decimal
from typing import cast
from typing import TYPE_CHECKING

import pytest
from beancount.core.amount import Amount
from beancount.core.data import Posting
from beancount.core.data import Transaction

from fava.experimental_transactions import _row

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient

    from fava.beans.abc import Transaction as FavaTransaction


def test_exact_debits_credits_and_notes(app: Flask) -> None:
    number = Decimal("12345678901234567890.123456789")
    entry = Transaction(
        {"filename": "test.bean", "lineno": 1, "note": "Transaction note"},
        datetime.date(2026, 1, 1),
        "*",
        "Payee",
        "Narration",
        frozenset(),
        frozenset(),
        [
            Posting(
                "Assets:Cash",
                Amount(number, "BTC"),
                None,
                None,
                None,
                {"note": "Debit note"},
            ),
            Posting(
                "Income:Test",
                Amount(number.copy_negate(), "BTC"),
                None,
                None,
                None,
                None,
            ),
            Posting(
                "Assets:Zero",
                Amount(Decimal(0), "USD"),
                None,
                None,
                None,
                None,
            ),
            Posting("Assets:Missing", None, None, None, None, None),
        ],
    )
    with app.app_context():
        row = _row(cast("FavaTransaction", entry))
    assert row.note == "Transaction note"
    assert [(p.debit, p.credit, p.note) for p in row.postings] == [
        ("12345678901234567890.123456789 BTC", "", "Debit note"),
        ("", "12345678901234567890.123456789 BTC", ""),
        ("0 USD", "", ""),
        ("", "", ""),
    ]

    with app.app_context(), pytest.MonkeyPatch.context() as patch:
        patch.setitem(app.config, "INCOGNITO", value=True)
        masked = _row(cast("FavaTransaction", entry))
    assert masked.postings[0].debit == "XXXXXXXXXXXXXXXXXXXX.XXXXXXXXX BTC"
    assert masked.postings[1].credit == "XXXXXXXXXXXXXXXXXXXX.XXXXXXXXX BTC"


def test_pages_and_filters(test_client: FlaskClient) -> None:
    url = "/long-example/api/experimental_transactions"
    params = {"per_page": 2, "order": "asc", "show": "cleared"}
    first = test_client.get(url, query_string=params).get_json()["data"]
    second = test_client.get(
        url, query_string={**params, "page": 2}
    ).get_json()["data"]
    assert len(first["transactions"]) == 2
    assert first["total_entries"] > 2
    assert first["total_pages"] == (first["total_entries"] + 1) // 2
    assert {t["entry_hash"] for t in first["transactions"]}.isdisjoint(
        t["entry_hash"] for t in second["transactions"]
    )
    assert all(t["flag"] == "*" for t in first["transactions"])
    assert (
        first["transactions"][0]["date"] <= second["transactions"][0]["date"]
    )
    assert "journal" not in first
    empty = test_client.get(url, query_string={"show": ""}).get_json()["data"]
    assert empty["transactions"] == []
    assert empty["total_entries"] == 0
    filtered = test_client.get(url, query_string={"time": "1900"}).get_json()[
        "data"
    ]
    assert filtered["transactions"] == []
    assert (
        test_client.get(url, query_string={"page": 100000}).status_code == 404
    )


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"per_page": 0},
        {"per_page": 201},
        {"sort": "bad"},
        {"order": "bad"},
        {"show": "bad"},
    ],
)
def test_rejects_invalid_parameters(
    test_client: FlaskClient, params: dict[str, str | int]
) -> None:
    response = test_client.get(
        "/long-example/api/experimental_transactions",
        query_string=params,
    )
    assert response.status_code == 400


@pytest.mark.parametrize("sort", ["flag", "narration"])
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_sorted_pages(test_client: FlaskClient, sort: str, order: str) -> None:
    response = test_client.get(
        "/long-example/api/experimental_transactions",
        query_string={"sort": sort, "order": order, "per_page": 200},
    )
    assert response.status_code == 200
    transactions = response.get_json()["data"]["transactions"]
    values = [
        row["flag"] if sort == "flag" else (row["payee"], row["narration"])
        for row in transactions
    ]
    assert values == sorted(values, reverse=order == "desc")
