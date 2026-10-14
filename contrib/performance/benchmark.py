"""Measure Fava ledger load and API performance on a ledger file."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from fava.application import create_app

if TYPE_CHECKING:
    from flask.testing import FlaskClient

    from fava.core import FavaLedger


ACCOUNT = "Assets:Cash:USD:Operating"
PAGE_SIZE = 200


def _percentile(values: list[float], percentile: float) -> float:
    """Return the nearest-rank percentile in milliseconds."""
    ordered = sorted(values)
    rank = max(1, int((percentile * len(ordered) + 99) // 100))
    return ordered[rank - 1]


def _version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _git_revision() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        return subprocess.check_output(
            [git, "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _response_summary(body: bytes) -> dict[str, object]:
    """Summarize API response shape without retaining its complete payload."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"json": False}

    array_counts: dict[str, int] = {}
    totals: dict[str, object] = {}
    metadata: dict[str, object] = {}
    chart_arrays: dict[str, int] = {}

    def visit(value: object, path: str, *, in_chart: bool = False) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            normalized_key = key.lower()
            child_in_chart = in_chart or "chart" in normalized_key
            if normalized_key in {
                "total",
                "total_count",
                "total_entries",
                "total_pages",
                "page",
                "page_size",
            } and not isinstance(child, (dict, list)):
                totals[child_path] = child
            if normalized_key == "metadata" and "[" not in child_path:
                metadata[child_path] = child
            if isinstance(child, list):
                array_counts[child_path] = len(child)
                if child_in_chart and normalized_key not in {
                    "chart",
                    "charts",
                }:
                    chart_arrays[child_path] = len(child)
                if child_in_chart:
                    for index, item in enumerate(child):
                        if isinstance(item, dict):
                            visit(
                                item,
                                f"{child_path}[{index}]",
                                in_chart=True,
                            )
            elif isinstance(child, dict):
                visit(child, child_path, in_chart=child_in_chart)

    visit(payload, "")
    return {
        "json": True,
        "array_counts": array_counts,
        "chart_array_count": len(chart_arrays),
        "chart_arrays": chart_arrays,
        "chart_point_count": sum(chart_arrays.values()),
        "totals": totals,
        "metadata": metadata,
    }


def _measure_request(
    client: FlaskClient,
    name: str,
    path: str,
    iterations: int,
    *,
    summarize_response: bool = False,
) -> dict[str, object]:
    started = time.perf_counter()
    initial_response = client.get(path)
    initial_request_ms = (time.perf_counter() - started) * 1000

    # Warm this exact URL immediately before measuring repeated requests so
    # any bounded per-request cache is populated for the same view.
    client.get(path)

    samples: list[float] = []
    payload_bytes = 0
    last_body = b""
    status_codes: set[int] = set()
    for _ in range(iterations):
        started = time.perf_counter()
        response = client.get(path)
        samples.append((time.perf_counter() - started) * 1000)
        payload_bytes = len(response.data)
        last_body = response.data
        status_codes.add(response.status_code)
    result: dict[str, object] = {
        "name": name,
        "path": path,
        "status_codes": sorted(status_codes),
        "payload_bytes": payload_bytes,
        "initial_status_code": initial_response.status_code,
        "initial_payload_bytes": len(initial_response.data),
        "initial_request_ms": round(initial_request_ms, 3),
        "iterations": iterations,
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(_percentile(samples, 95), 3),
        "samples_ms": [round(sample, 3) for sample in samples],
    }
    if summarize_response:
        result["response_summary"] = _response_summary(last_body)
    return result


def _api_path(slug: str, endpoint: str, params: dict[str, object]) -> str:
    """Build an API path, formatting boolean query values as lowercase."""
    values = {
        key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in params.items()
    }
    return f"/{slug}/api/{endpoint}?{urlencode(values)}"


def _report_scenarios(ledger: FavaLedger, slug: str) -> list[tuple[str, str]]:
    """Build report requests using data present in the loaded ledger."""
    report_scenarios = [
        ("commodities", f"/{slug}/api/commodities"),
        ("documents", f"/{slug}/api/documents"),
        ("events", f"/{slug}/api/events"),
        ("income_statement", f"/{slug}/api/income_statement"),
        ("balance_sheet", f"/{slug}/api/balance_sheet"),
        ("trial_balance", f"/{slug}/api/trial_balance"),
        ("statistics", f"/{slug}/api/statistics"),
        (
            "account_report_without_journal",
            f"/{slug}/api/account_report?a={ACCOUNT}&include_journal=false",
        ),
    ]
    document_entries = ledger.all_entries_by_type.Document
    if document_entries:
        document_pages = max(
            1, (len(document_entries) + PAGE_SIZE - 1) // PAGE_SIZE
        )
        report_scenarios.extend(
            [
                (
                    "documents_page_first_200",
                    _api_path(
                        slug,
                        "documents_page",
                        {
                            "page": 1,
                            "per_page": PAGE_SIZE,
                            "include_overview": True,
                        },
                    ),
                ),
                (
                    "documents_page_last",
                    _api_path(
                        slug,
                        "documents_page",
                        {
                            "page": document_pages,
                            "per_page": PAGE_SIZE,
                            "include_overview": False,
                        },
                    ),
                ),
                (
                    "documents_page_name_asc",
                    _api_path(
                        slug,
                        "documents_page",
                        {
                            "sort": "name",
                            "order": "asc",
                            "per_page": PAGE_SIZE,
                            "include_overview": True,
                        },
                    ),
                ),
            ]
        )
        account_documents = sum(
            entry.account.startswith("Assets:Cash:USD")
            for entry in document_entries
        )
        if account_documents:
            report_scenarios.append(
                (
                    "documents_page_cash_account",
                    _api_path(
                        slug,
                        "documents_page",
                        {
                            "a": "Assets:Cash:USD",
                            "per_page": PAGE_SIZE,
                            "include_overview": True,
                        },
                    ),
                )
            )

    event_entries = ledger.all_entries_by_type.Event
    if event_entries:
        event_pages = max(1, (len(event_entries) + PAGE_SIZE - 1) // PAGE_SIZE)
        event_type = event_entries[0].type
        report_scenarios.extend(
            [
                (
                    "events_page_first",
                    _api_path(
                        slug,
                        "events_page",
                        {
                            "page": 1,
                            "per_page": PAGE_SIZE,
                            "include_overview": True,
                        },
                    ),
                ),
                (
                    "events_page_last",
                    _api_path(
                        slug,
                        "events_page",
                        {
                            "page": event_pages,
                            "per_page": PAGE_SIZE,
                            "include_overview": False,
                        },
                    ),
                ),
                (
                    "events_page_description_asc",
                    _api_path(
                        slug,
                        "events_page",
                        {
                            "sort": "description",
                            "order": "asc",
                            "per_page": PAGE_SIZE,
                            "include_overview": True,
                        },
                    ),
                ),
                (
                    "events_page_type_populated",
                    _api_path(
                        slug,
                        "events_page",
                        {
                            "event_type": event_type,
                            "per_page": PAGE_SIZE,
                            "include_overview": True,
                        },
                    ),
                ),
            ]
        )

    price_counts = Counter(
        (entry.currency, entry.amount.currency)
        for entry in ledger.all_entries_by_type.Price
    )
    visible_pairs = [
        pair for pair in ledger.commodity_pairs() if price_counts[pair]
    ]
    if visible_pairs:
        selected_base, selected_quote = visible_pairs[0]
        selected_price_count = price_counts[(selected_base, selected_quote)]
        price_pages = max(
            1, (selected_price_count + PAGE_SIZE - 1) // PAGE_SIZE
        )
        report_scenarios.extend(
            [
                (
                    "commodity_report_first_200",
                    _api_path(
                        slug,
                        "commodity_report",
                        {
                            "base": selected_base,
                            "quote": selected_quote,
                            "page": 1,
                            "per_page": PAGE_SIZE,
                            "include_overview": True,
                        },
                    ),
                ),
                (
                    "commodity_report_last_page",
                    _api_path(
                        slug,
                        "commodity_report",
                        {
                            "base": selected_base,
                            "quote": selected_quote,
                            "page": price_pages,
                            "per_page": PAGE_SIZE,
                            "include_overview": False,
                        },
                    ),
                ),
                (
                    "commodity_report_price_asc_first_200",
                    _api_path(
                        slug,
                        "commodity_report",
                        {
                            "base": selected_base,
                            "quote": selected_quote,
                            "page": 1,
                            "per_page": PAGE_SIZE,
                            "sort": "price",
                            "order": "asc",
                            "include_overview": True,
                        },
                    ),
                ),
            ]
        )
        synth_pair = ("SYNTH000999", "USD")
        if price_counts[synth_pair]:
            report_scenarios.append(
                (
                    "commodity_report_synth_999_price_asc",
                    _api_path(
                        slug,
                        "commodity_report",
                        {
                            "base": synth_pair[0],
                            "quote": synth_pair[1],
                            "page": 1,
                            "per_page": PAGE_SIZE,
                            "sort": "price",
                            "order": "asc",
                            "include_overview": True,
                        },
                    ),
                )
            )
    return report_scenarios


def _journal_scenarios(slug: str) -> list[tuple[str, str]]:
    """Build journal requests for the standard benchmark ledger."""
    default_show = (
        "balance,budget,cleared,custom,discovered,document,note,pending,"
        "query,statement,transaction"
    )
    return [
        (
            "journal_first_page_desc",
            f"/{slug}/api/journal_page?page=1&order=desc",
        ),
        (
            "journal_first_page_asc",
            f"/{slug}/api/journal_page?page=1&order=asc",
        ),
        (
            "journal_first_page_account_filter",
            f"/{slug}/api/journal_page?page=1&order=desc&account={ACCOUNT}",
        ),
        (
            "journal_first_page_text_filter",
            f"/{slug}/api/journal_page?page=1&order=desc&filter=payee%3AAcme%20Market",
        ),
        (
            "journal_ui_first_page_200_default_types",
            (
                f"/{slug}/api/journal_page?page=1&order=desc&sort=date"
                f"&per_page=200&show={default_show}"
            ),
        ),
        (
            "account_journal_first_page_200",
            (
                f"/{slug}/api/journal_page?page=1&per_page=200"
                f"&show={default_show}&a={ACCOUNT}"
            ),
        ),
        *[
            (
                f"journal_sort_{sort}_page_{page}",
                (
                    f"/{slug}/api/journal_page?page={page}&per_page=200"
                    f"&order=desc&sort={sort}&show={default_show}"
                ),
            )
            for sort in ("narration", "flag", "change")
            for page in (1, 2)
        ],
        ("journal_full_payload", f"/{slug}/api/journal"),
        ("account_report_journal", f"/{slug}/api/account_report?a={ACCOUNT}"),
    ]


def benchmark(
    ledger_path: Path,
    iterations: int,
    *,
    cold_iterations: int | None = None,
    reports_only: bool = False,
) -> dict[str, object]:
    """Run cold-load and warm API measurements and return JSON-safe results."""
    if iterations < 1:
        message = "iterations must be positive"
        raise ValueError(message)
    if cold_iterations is None:
        cold_iterations = iterations
    if cold_iterations < 1:
        message = "cold_iterations must be positive"
        raise ValueError(message)
    ledger_path = ledger_path.resolve()

    cold_samples: list[float] = []
    for _ in range(cold_iterations):
        started = time.perf_counter()
        create_app([ledger_path], load=True)
        cold_samples.append((time.perf_counter() - started) * 1000)

    app = create_app([ledger_path], load=True)
    client = app.test_client()
    ledgers = app.config["LEDGERS"]
    slug = ledgers.first_slug()
    ledger = ledgers[slug]
    report_scenarios = _report_scenarios(ledger, slug)
    journal_scenarios = _journal_scenarios(slug)
    scenarios = report_scenarios + ([] if reports_only else journal_scenarios)
    warm_results = []
    for name, path in scenarios:
        summarize_response = name.startswith(
            ("documents_page_", "events_page_", "commodity_report_")
        )
        warm_results.append(
            _measure_request(
                client,
                name,
                path,
                iterations,
                summarize_response=summarize_response,
            )
        )

    line_count = 0
    transaction_count = 0
    with ledger_path.open(encoding="utf-8") as ledger:
        for line in ledger:
            line_count += 1
            transaction_count += " * " in line
    return {
        "schema_version": 1,
        "ledger": {
            "path": str(ledger_path),
            "bytes": ledger_path.stat().st_size,
            "lines": line_count,
            "transaction_count": transaction_count,
        },
        "environment": {
            "python": sys.version,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "fava_version": _version("fava"),
            "beancount_version": _version("beancount"),
            "git_revision": _git_revision(),
        },
        "cold_load": {
            "iterations": cold_iterations,
            "p50_ms": round(statistics.median(cold_samples), 3),
            "p95_ms": round(_percentile(cold_samples, 95), 3),
            "samples_ms": [round(sample, 3) for sample in cold_samples],
        },
        "warm_requests": warm_results,
        "reports_only": reports_only,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "ledger", type=Path, help="Beancount ledger to benchmark"
    )
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--cold-iterations",
        type=int,
        help="cold ledger constructions (defaults to --iterations)",
    )
    parser.add_argument(
        "--reports-only",
        action="store_true",
        help="measure report and data APIs without journal endpoints",
    )
    parser.add_argument("--output", type=Path, help="write results as JSON")
    args = parser.parse_args()
    results = benchmark(
        args.ledger,
        args.iterations,
        cold_iterations=args.cold_iterations,
        reports_only=args.reports_only,
    )
    rendered = json.dumps(results, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")  # noqa: T201


if __name__ == "__main__":
    main()
