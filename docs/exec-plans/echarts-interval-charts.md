# ECharts interval charts

User rejected replacing tooltips with a separate table and explicitly requested
a usable charting library. Replace this chart's hand-built D3 renderer with
Apache ECharts 6.1.0 in the separate fork/standalone preview. Do not change
money-redux, ledger data, or deployed services. No merge.

Use modular lazy-loaded SVG rendering, signed currency-specific stacked bars,
net line per currency, compact full-month axis tooltips, crosshair,
scroll/slider zoom and native date-range filtering. Preserve conversion/filter
inputs, account navigation, single bars/budgets, responsive sizing and
light/dark theme. Tooltip content uses DOM text, never interpolated ledger HTML.
No CDN or remote finance-data service. Remove the fixed detail panel and its
component test.

Validate signed/currency-separated series, hidden currencies, budget totals,
complete monthly tooltip with net last and HTML-injection resistance; frontend
tests, Svelte check, production build and live desktop/mobile hover, zoom,
navigation/filter behavior. Update fork PR without merging.

Completed: ECharts 6.1.0 pinned with its two dependencies; module-loaded SVG
renderer replaces this bar-chart component. No CDN. Fixed detail table removed.
Monthly tooltips use short series paths, currency headings, zero rows, colored
markers and signed net last; long breakdowns scroll without expanding the popup.

Validation: 134 frontend tests and 500 Python tests pass; Svelte check has zero
errors/warnings, production build and diff checks pass. Browser verifies actual
mouse-hover tooltip, native currency-separated stacks/net lines, zoom preserving
source data, single/stacked switching, brush event mapping to Fava's time
filter, account-event navigation retaining property/conversion, and compact
tooltip bounds at 390px width. Existing five upstream npm audit advisories
remain; no dependency upgrades or lockfile changes outside the three new
packages.

Follow-up (2026-10-09): user requested smooth hover and an interval P&L table,
with no further PR work. Tooltip now passes pointer events through, has no
position/axis animation, and explicitly selects the horizontal month axis.
Removed its scrolling height cap so hover content is not clipped. The income
statement replaces aggregate trees with an account-by-period table when an
interval chart is active; hierarchy views retain their tree tables. Both table
and chart use the same parsed report, conversion, interval and hidden
currencies. Table retains chart signs and explicitly explains the credit/profit
convention.

Validation: 135 frontend tests pass, Svelte check zero warnings/errors,
production build passes. Live preview verifies 21 left/right month selections;
table headers, all account values and net values match plotted data (within
display rounding). No ledger, money-redux, service configuration or PR changes.

Follow-up: disabled all chart zoom/pan and drag date selection at user request.
Removed inside/slider dataZoom, brush options, brush callback and activation
button, plus unused ECharts interaction registrations. Date range changes use
report controls. Chart/table retain the same fixed period range. Validation: 136
frontend tests pass; Svelte check and production build pass.
