# Large-ledger performance plan

Target: keep Fava usable and responsive with 100,000 transactions, including
account journals with concentrated transaction history and expanded postings.
Extend the same bounded work to 100,000 documents, events, and price points
across 1,000 commodities, plus a single 100,000-point price history.

## Implementation

1. Establish reproducible 10k, 50k, and 100k ledgers and record the existing
   backend and browser behavior. Measure ledger parsing separately from warm
   interactions.
1. Add global journal sorting and visibility filtering before pagination. Render
   only the requested page. Page account journals while retaining their full
   chronological running balances. Bound caches and invalidate on reload.
1. Replace eager page downloads and DOM sorting with demand-driven requests,
   bounded prefetch/cache, and a TanStack Virtual journal with variable row
   heights. Preserve expansion, links, keyboard access, empty/error states, and
   prevent stale requests from changing a newer view.
1. Expand the fixture with real small PDF attachments, events, and price
   histories. Page and globally sort the three reports on the server; render one
   virtual table, retain document preview/account navigation, and bound chart
   overviews while keeping all records accessible.
1. Verify accounting and page boundaries with backend tests; verify paging,
   cancellation, and virtual row calculations with frontend tests. Build and
   type-check the application, then exercise the rendered 100k ledger.
1. Request an independent Claude CLI Opus 5.5 review, fix actionable findings,
   repeat affected validation, and publish measured results and limitations.

## Acceptance targets

- No automatic fetch of the entire journal and no DOM proportional to the full
  transaction count.
- Bounded journal page cache and mounted rows during long scroll sessions.
- Target 60fps scrolling and visible interaction feedback within 100ms.
- Target warm journal/filter/sort completion within 500ms at p95 on the recorded
  reference machine. Report cold load and cold account calculations separately.
- Stable ordering, complete filter results, correct running balances and
  conversions, and no stale data after edits/reload.

## Known limitations

- Browser print output contains only rows currently loaded in the virtual views;
  printing does not fetch the complete ledger.
- Large charts use an explicitly labeled, bounded overview. Detailed time
  filters and the complete paged tables preserve access to all observations.

## Delegation

- Luna backend agent: Python paging, sorting, filtering, account balances,
  tests.
- Luna frontend agent: virtual journal, demand loading, cancellation, tests.
- Luna benchmark agent: generated datasets, timing harness, documentation.
- Primary agent: integration, browser measurements, review and final validation.

Performance figures are goals until verified by the benchmark; results belong in
the benchmark documentation alongside the command and machine configuration.

## Verification record

Implementation and regression coverage are complete. The reference 100k fixture
has been exercised in the built-in T3 browser on desktop and mobile. See
[benchmark results](../contrib/performance/results.md) for measurements, review
findings addressed, and limitations.
