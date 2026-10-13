# Nonblocking interval details

User reports that the complete monthly tooltip obscures the chart. Continue in
the separate Fava fork and standalone preview only. Keep deployed services and
money-redux unchanged; no ledger mutation or merge.

D3 already supplies the rendering primitives. Replacing it would require porting
Fava's filters, multiple currencies, conversion, account links and interval
brush, and would not by itself decide where detail appears. First make the
interaction usable: fixed interval details beside a sufficiently wide plot,
below on narrow screens, persistent last-inspected interval, keyboard/touch
interval selector, selected-month highlight, all series and signed net. No
floating stacked tooltip. Preserve single-bar tooltips, account navigation and
brush selection.

Validate visible-currency summaries and component rendering, frontend tests,
Svelte check, production build, live desktop/mobile panel positioning, hover
updates without overlay and keyboard selection. Update existing fork PR, no
merge.

Completed: pure visible-currency interval summary, fixed responsive details
table, linked account series, signed net, persistent selection,
selected-interval band, native interval selector and removal of floating stacked
tooltips. D3 remains; Apache ECharts is a reasonable candidate if a broader
renderer redesign is later requested, but no dependency migration is needed for
nonblocking details.

Validation: 132 frontend tests pass, including panel rendering and summary
currency/zero/net checks; production build and Svelte check pass with zero
errors or warnings. Desktop preview verifies hover updates, highlighted month,
zero floating tooltip opacity and panel positioned outside the plot. At
390-pixel width the panel moves below the plot and fits within the viewport
width. Selector changes update the month and highlight. No Python or ledger
changes in this patch.

Superseded: user rejected the fixed table and requested a charting-library
replacement. See `echarts-interval-charts.md`; the fixed-panel component was
removed.
