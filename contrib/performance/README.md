# Ledger performance benchmarks

The scripts here generate a deterministic synthetic Beancount ledger and measure
Fava's backend load and APIs. Keep generated ledgers, PDFs, and result JSON
outside the repository so benchmark artifacts do not bloat source history.

From the repository root, generate the original transaction-only fixture at any
supported size:

```sh
.venv/bin/python contrib/performance/generate_ledger.py 10000 /tmp/fava-10k.beancount
.venv/bin/python contrib/performance/generate_ledger.py 100000 /tmp/fava-100k.beancount
```

Optional scale-up directives default to zero, preserving the transaction-only
fixture. For example, generate the larger mixed fixture used for API
measurements:

```sh
.venv/bin/python contrib/performance/generate_ledger.py 100000 \
  /tmp/fava-full-100k.beancount --commodities 1000 --prices 100000 \
  --documents 100000 --events 100000
.venv/bin/python contrib/performance/generate_ledger.py 1000 \
  /tmp/fava-dense-prices-100k.beancount --commodities 1 --prices 100000
```

Generated commodity names and document paths are unique. Prices use unique
commodity/date pairs; their date range grows only when the requested count needs
more dates. Events use 20 types with unique descriptions over the 15-year
fixture range. Each document directive points to a small valid PDF under the
sibling `generated-documents-N` folder. The generator creates one PDF and
hard-links it to each document path where supported, keeping the fixtures
compact while preserving distinct files and paths. Documents are distributed
across the generated cash and expense accounts. The `--seed` default is
`20261013`; pass another seed for a different deterministic transaction fixture.

Run backend measurements with the same Python environment for before/after
comparisons:

```sh
.venv/bin/python contrib/performance/benchmark.py /tmp/fava-full-100k.beancount \
  --iterations 5 --cold-iterations 2 --reports-only \
  --output /tmp/fava-full-100k-reports.json
```

The output records Python/platform and Fava/Beancount versions, source revision,
fixture counts and bytes, cold ledger construction time, and warm request
timings and response sizes. `--cold-iterations` controls ledger constructions
independently from warm request samples, and defaults to `--iterations`.
`--reports-only` measures the existing commodities, documents, events, financial
report, statistics, and account-report APIs without running journal APIs or the
very large full-journal diagnostic. Use this mode to capture the legacy
full-payload baseline for the large enrichment fixtures. It also measures paged
document, event, and commodity report APIs with first-page overview data and
overview-free later pages. Page-last requests, event-type filters, and commodity
pairs are selected from the loaded ledger, so the same command works on
transaction-only and smaller fixtures.

Without `--reports-only`, the harness also measures journal pages at 200 rows,
account and text filters, page 1 and 2 with narration/flag/change sorting, and
the full journal API. It warms each exact URL immediately before timed samples
because the backend retains a small, ledger-wide bounded cache. These are
in-process Flask test-client timings; they exclude network, browser rendering,
and browser memory costs. The full journal response is intentionally included as
a diagnostic baseline and may be much larger than a paginated response.

There are no universal latency targets: results depend on hardware, Python and
Beancount versions, and filesystem cache state. Compare runs on the same machine
and report fixture size, iteration counts, environment, and response bytes
alongside timings. For UI measurements, use a browser harness on the same
generated file and report its browser/version and cold/warm cache state.

## Rapid-scroll recovery

On a freshly loaded 100k journal, evaluate `browser_stress.js`, then run
`await favaScrollStress()`. This development-only test moves the scrollbar
twenty times at 40ms intervals, delays journal requests by 400ms, and injects
HTTP 503 on each requested page's first completed attempt. It restores `fetch`
afterward. Do not interact with the page during the run.

Success requires the final viewport to recover more than 95% real-row coverage
without clicking retry. The result records recovery time, concurrent requests,
cancelled requests, retry buttons, and mounted rows. Run at desktop and mobile
widths, with postings both collapsed and expanded. This tests recovery from slow
and temporarily failing requests; it is separate from the frame-timing
benchmark.

## Paged-report scroll recovery

Open a Documents, Events, or commodity-price report with multiple pages, then
paste and evaluate `report_browser_stress.js` in the browser console. Run
`await favaReportScrollStress()` on a freshly loaded report and avoid
interacting with the page during the run. It scrolls the table's closest
`[data-report-scroll]` pane when present; otherwise it scrolls the article on
desktop and the window on mobile. It waits 400ms before each paged API request
and returns HTTP 503 for each page's first completed attempt, then restores
`fetch` when finished. The helper accepts `delayMs` and `failOnce` overrides.

Success requires more than 95% real-row viewport coverage without clicking
retry. The result records recovery time, concurrent requests, aborted requests,
retry buttons, and mounted rows. Repeat at desktop and mobile widths and include
the report type, page count, browser/version, and viewport in results.
