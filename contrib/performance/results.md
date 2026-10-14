# 100k transaction results

Measured on October 13, 2026 with the deterministic seed `20261013`: 100,000
transactions, four postings per transaction, metadata, three currencies, and
fifteen years of history. The ledger is 33,671,594 bytes. Backend reference
machine: Apple M4 Pro, 14 cores, macOS 27.0.1, Python 3.14.8, Beancount 3.2.3.
Baseline source revision: `fa7be27ffcd4f8b75e07b2af7dcccbe9edd1c298`.

## Backend

Baseline used three iterations; final used seven. These are Flask test-client
measurements on the same machine and fixture, excluding browser/network time.
Small-sample p95 is the maximum observation in these runs. First-request timing
includes any work required by that request at its place in the scenario
sequence; it is not guaranteed to be a cold ledger or cold account cache.

| Operation                      | First request | Warm p50 | Warm p95 | Response |
| ------------------------------ | ------------: | -------: | -------: | -------: |
| UI journal (200 rows)          |       87.9 ms |  18.5 ms |  20.1 ms |   600 KB |
| Account journal (200 rows)     |      202.9 ms |  19.8 ms |  20.8 ms |   634 KB |
| Journal sorted by narration    |      752.6 ms |  18.1 ms |  18.3 ms |   601 KB |
| Journal sorted by flag         |      119.9 ms |  17.8 ms |  18.8 ms |   600 KB |
| Journal sorted by change       |      192.0 ms |  18.5 ms |  19.1 ms |   598 KB |
| Account charts without journal |       95.2 ms |  96.3 ms | 100.0 ms |   314 KB |

Cold ledger construction: **7.81 s p50 / 8.30 s p95**, compared with baseline
7.56 / 8.02 s. This work improves interactive journals, not cold parsing.

The previous UI loaded journal pages eagerly; a baseline 1,000-row page was 3.00
MB and 93.9 ms p50. The new UI requests 200 rows (0.60 MB, 18.5 ms p50) and
loads further pages as needed. These are different page sizes, so the main
improvement is bounded work rather than a fivefold improvement in per-row
rendering.

The previous account report returned a 200.7 MB journal payload (6.79 s p50).
The UI now requests 314 KB of chart data plus a 634 KB journal page. The legacy
full-account endpoint is still available and measured 6.45 s p50 in the final
run. The legacy full-journal API still returns 94.7 MB.

All 15 final request scenarios returned HTTP 200. The backend warm interactive
requests meet the 500 ms p95 target on this fixture; first sort/index
construction can exceed it (narration's first measured request took 753 ms).

## Browser

Verified using the built-in T3 collaborative browser: T3 Code 0.0.45, Electron
44.4.2, Chromium 152.0.7977.130. Fava was served over the local network. Desktop
viewport: 1280 × 800; mobile verification: 390 × 844.

A 30.2-second desktop session of the initial custom virtualizer, with expanded
postings, narration sorting, and ten scroll actions (including two million-pixel
jumps and upward scrolling) measured using `browser_metrics.js`:

| Measurement                      | Result               |
| -------------------------------- | -------------------- |
| Frame interval p50 / p95         | 8.3 / 10.0 ms        |
| Maximum observed frame interval  | 16.7 ms              |
| Long tasks above 50 ms           | 0                    |
| Maximum mounted journal rows     | 40                   |
| Final DOM elements               | 2,086                |
| Final JS heap (browser estimate) | 15.3 MB              |
| Newly requested pages            | 9, each about 600 KB |
| Page request duration range      | 26–70 ms             |

This is a mixed interaction/idle sample with 3,625 frames, not an automated
continuous-scroll stress test or a general 60fps guarantee. Frame timing
includes the lightweight measurement observer. Network timings include server
and transfer time. The entire 100k journal is never fetched automatically.

Additional checks of that initial implementation reached entry 99,999, preserved
keyboard focus during scrolling, reloaded evicted pages, filtered by payee,
changed global sorting, expanded postings, opened a transaction context modal,
and scrolled an account journal on desktop and mobile. No horizontal document
overflow was observed at the mobile viewport. Automated tests cover stale
responses, revision changes, reloads, eviction, border-box measurements, and
scroll compensation.

The baseline eager journal became unresponsive during two 15-second browser
inspection attempts. That run was stopped; there is no reliable baseline browser
latency or heap figure to compare against.

### TanStack migration and rapid-scroll recovery

The journal now uses `@tanstack/svelte-virtual` 3.13.38 for measured
variable-height rows, viewport ranges, and scroll offsets. The custom height
index was removed. The request scheduler allows three concurrent pages,
prioritizes the latest viewport, and lets active requests finish during
scrolling. Prefetch waits until scrolling settles. Temporary network failures
and HTTP 408, 429, and 5xx responses retry automatically twice; requests time
out after ten seconds.

The reproducible `browser_stress.js` test makes 20 scrollbar jumps 40 ms apart,
adds 400 ms to every journal request, and returns HTTP 503 on each page's first
completed attempt. Recovery is measured after the final jump, when real rows
cover more than 95% of the viewport and the list is no longer busy.

| Implementation / view                         |                     Recovery |  Maximum concurrent requests | Aborted requests | Manual retry buttons | Mounted rows |
| --------------------------------------------- | ---------------------------: | ---------------------------: | ---------------: | -------------------: | -----------: |
| Custom virtualizer, desktop journal           | Did not recover within 6.5 s | 6 (including abort turnover) |               41 |                    2 |            0 |
| TanStack, desktop journal, postings expanded  |                     1,246 ms |                            3 |                0 |                    0 |           22 |
| TanStack, desktop journal, postings collapsed |                     1,242 ms |                            3 |                0 |                    0 |           52 |
| TanStack, mobile account, postings expanded   |                     1,248 ms |                            3 |                0 |                    0 |           28 |

All three TanStack runs recovered 100% viewport coverage. These are individual
fault-injection runs, not latency percentiles. The earlier frame-time sample
describes the custom implementation and should not be treated as a TanStack
frame-rate measurement. Keyboard focus also remained on the original transaction
link after a two-million-pixel scroll in the TanStack implementation. Toggling
postings deep in the journal preserves the first visible transaction and aligns
it to the top; it does not preserve a pixel inset that could exceed the
collapsed row.

[TanStack desktop screenshot](https://orbit.corp.stripe.com/workspaces/9bcf1345-7486-4ed6-904f-72d0c999df50/artifacts/bf443c54-9f6c-4509-bc7b-1f9c98f0d090).

A separate 15.6-second final-build desktop sample with expanded postings and ten
scroll actions (including million-pixel jumps in both directions) recorded 1,870
frames: 8.3 ms p50, 9.9 ms p95, 17.9 ms maximum, and no long tasks above 50 ms.
At most 40 transaction rows were mounted; the final DOM contained 2,086
elements. Eleven page requests took 22–49 ms each. This is a mixed
interaction/idle observation, not a continuous-scroll frame-rate guarantee.

## Scope and limitations

- Paging and virtualization bound network requests, cached pages, and mounted
  DOM. Server-side filtering, first sort, and first account balance computation
  still examine the complete relevant dataset.
- The ledger-wide journal and account caches each retain at most two views and
  are cleared on reload. Ordinary filtered-ledger caching remains in place.
- If all three active page requests stall, a newly visible page waits for a slot
  until one completes or hits its ten-second timeout. Scrolling does not
  repeatedly cancel active requests. Persistent failures expose a manual retry
  after two automatic retries.
- Cold parsing remains a multi-second operation. The legacy full-journal and
  full-account APIs retain their complete payloads for compatibility.
- Browser printing includes only currently mounted journal entries and displays
  a scope note. Virtual spacer heights are excluded from print output.
- Python case-folded text sorting is deterministic but may differ from the
  browser locale's previous collation order.

## Independent review

Claude CLI using `claude-opus-5-5` reviewed the implementation. Findings
prompted fixes for reload invalidation, focus retention, page-one revision
checks, cancellation races, mobile border measurements, scroll anchoring,
visibility validation, cache bounds, event coalescing, and print spacers.

The follow-up review identified and verified the fix for a cache-value shape
mismatch introduced during cache relocation. Its final verdict was: “the last
blocker is fixed correctly, and I see no remaining substantive blockers from
either review.”

The TanStack follow-up review prompted fixes for presentation-cache
invalidation, anchor restoration after remeasurement, and retries skipped while
off-screen. Opus verified the final source: “no substantive correctness blockers
remain.”

Validation: 612 Python tests with 100% coverage, 153 frontend tests, TypeScript,
Svelte checks, Python type checks, and production build. The `uv`
dependency/type validation ran inside Docker with Python 3.14. The configured
`uv check` hook is unsupported by the available uv release; its type check was
run with
`uv sync --locked --no-install-project --no-default-groups --group types`
followed by `uv run --no-sync ty check` inside the container.

[Desktop screenshot](https://orbit.corp.stripe.com/workspaces/9bcf1345-7486-4ed6-904f-72d0c999df50/artifacts/8fb51987-fefb-499b-8cd9-1d2a7fe01251).
The fixture is valid Beancount; Fava shows an operating-currency configuration
warning because the fixture does not choose one reporting currency.

## Outage recovery follow-up

A later blank-viewport report was reproduced with the development server
stopped: journal requests and the ledger poll both timed out. The retry control
was below the full virtual list and therefore inaccessible from the scrolled
viewport.

Loading and retry feedback now stays in the desktop article viewport and is
fixed to the window on mobile. One retry reloads all failed pages visible across
a page boundary. Feedback remains in the accessibility tree and does not cover
rows when empty. The benchmark server was restarted as a detached process.

T3 verification injected network failures after a 450,000-pixel mobile scroll,
confirmed the retry button was visible, restored the connection, and recovered
the complete viewport with one click and no page reload. A desktop burst of six
large scrollbar jumps also recovered visible rows without a retry. New tests
cover pending viewport feedback and recovery across two failed pages. Claude CLI
Opus 5.5 reviewed the follow-up and reported no substantive blockers.

## Documents, events, and commodity prices at scale

The expanded fixture contains 100,000 transactions, 100,000 documents, 100,000
events across 20 types, and 100,000 prices across 1,000 commodities. It has 33
opened accounts and occupies 54,425,121 ledger bytes. Every document points to a
valid, readable PDF; distinct paths share one backing file through hard links. A
second fixture concentrates 100,000 daily prices in one commodity to exercise a
single large price table. Both fixtures load without Beancount errors. Commands
are in [the benchmark README](README.md).

Documents and events now use 200-row pages and a shared TanStack Virtual table.
Commodities uses a searchable pair selector and one paged price table. Tables
retain at most nine pages and issue at most three simultaneous requests.
Filtering and sorting apply to all matching records before pagination. Account
counts, event types, and chart overviews are retained when subsequent pages omit
them. Server caches are bounded and cleared on ledger reload.

Measurements used the reference machine and browser described above. Backend
results have three warm samples and one cold ledger construction; p95 is the
maximum sample. First-request figures depend on the preceding scenario's cache
state. These Flask test-client measurements exclude browser and network time.
The comparison uses the current uncommitted working tree and a preserved build
of the preceding eager report frontend; the Git revision alone does not identify
the implementation.

| Operation                                   | First request | Warm p95 | Response bytes |
| ------------------------------------------- | ------------: | -------: | -------------: |
| Documents, first 200                        |     53.662 ms | 0.731 ms |         64,461 |
| Documents, last 200 without overview        |      0.735 ms | 0.770 ms |         62,839 |
| Documents, first filename sort              |    176.506 ms | 0.748 ms |         64,471 |
| Events, first 200 plus overview             |     76.887 ms | 1.101 ms |        475,226 |
| Events, last 200 without overview           |             — | 0.601 ms |         43,353 |
| Mixed commodity, selected pair plus catalog |             — | 0.206 ms |         54,025 |
| Dense prices, first 200 plus overview       |      4.792 ms | 0.376 ms |         53,384 |
| Dense prices, last 200 without overview     |             — | 0.121 ms |          5,038 |
| Dense prices, first price sort              |     15.111 ms | 0.336 ms |              — |

The legacy full responses remain available: documents transfer 31,345,512 bytes,
events 21,565,022 bytes, and mixed commodities 2,458,022 bytes. Paging bounds
the requested work; these differently sized operations are not a per-row speed
comparison. All measured scenarios returned HTTP 200. The adaptive harness also
completed transaction-only, small enriched, and small dense fixtures without
request errors.

Cold construction of the expanded ledger took **9.301 seconds** in one
observation; the dense-price fixture took **0.614 seconds**. Cold parsing still
needs separate optimization. Chart overviews are capped at 2,000 points and
labeled when sampled; every observation remains accessible in the table.
Virtual-table printing contains only mounted rows and includes a scope note.

The eager frontend mounted 100,000 rows on each report: 300,278 DOM elements for
documents, 300,366 for events, and 311,158 for commodities across 1,000 tables.
The new reports stayed bounded in the following fault-injection runs.

`report_browser_stress.js` makes 20 scrollbar jumps 40 ms apart, adds 400 ms to
page responses, and returns HTTP 503 for each page's first completed attempt.
Recovery starts after the last jump and ends when real rows cover more than 95%
of the viewport and the table is no longer busy.

| Report / viewport     | Recovery | Mounted rows | DOM elements | Maximum requests | Viewport coverage |
| --------------------- | -------: | -----------: | -----------: | ---------------: | ----------------: |
| Documents, desktop    | 1,453 ms |           43 |          421 |                3 |              100% |
| Events, desktop       | 1,441 ms |           45 |          431 |                2 |              100% |
| Dense prices, desktop | 1,403 ms |           45 |          350 |                2 |              100% |
| Documents, mobile     | 1,353 ms |           30 |          382 |                2 |             96.3% |
| Events, mobile        | 1,443 ms |           45 |          431 |                2 |              100% |
| Dense prices, mobile  | 1,440 ms |           43 |          344 |                2 |              100% |

All six runs had zero aborted requests and zero manual retry buttons. These are
individual recovery observations, not latency percentiles or a frame-rate
guarantee. T3 delivered animation frames approximately once per second during
these runs despite a visible document. A coalesced 40 ms fallback prevents page
scheduling from waiting for a slow animation frame.

Browser checks also verified PDF preview, F2 rename-modal opening, document
account filtering, event-type selection, commodity search, keyboard focus
retention after a large scroll, and reaching dense price row 99,999. Automated
coverage verifies sort retention and resetting the viewport after query changes.

Final validation: **633 Python tests with 100% coverage**, **161 frontend
tests**, TypeScript and Svelte checks, production build, generator regression
tests, and Python type checking with `uv` inside Docker. Claude CLI Opus 5.5
reviewed the expanded implementation and reported “no substantive correctness or
performance blockers. All the previous findings are resolved.” Its remaining
minor sticky header overlap was subsequently fixed.

[Expanded documents screenshot with PDF preview](https://orbit.corp.stripe.com/workspaces/9bcf1345-7486-4ed6-904f-72d0c999df50/artifacts/adefc80c-342c-48a6-8128-9eb717c92575).
