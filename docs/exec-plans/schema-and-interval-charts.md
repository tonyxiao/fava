# Generic metadata schema and interval chart usability

Continue only in the separate Fava fork and standalone-ledger preview. User
explicitly paused money-redux integration and requested no changes to deployed
services. No ledger mutation, integration commits, service installation or
merge.

Implement a version-1 ledger-owned metadata contract with scoped typed fields,
optional vocabularies, native tree paths and composite legacy source paths.
Generate selectors generically, include virtual parent nodes, and validate
transaction/posting values without promoting pooled postings to whole journals.
Keep tags flat, CoA accounting-oriented, and reservation/payout links distinct.

For stacked bars, show the complete interval under every segment, with signed
net at the bottom; overlay a net line on the shared scale, separate per
currency. Preserve account navigation, brush behavior and native currency data.

Validate schema failures/types/scopes, tree parent boundaries and legacy paths,
whole-interval tooltip content, hidden currencies, Python/frontend tests,
production build, Svelte and scoped lint. Test standalone preview hierarchy,
reload, tooltip on different segments, line and mobile. Update fork PR without
merging; leave all existing deployed routes and money repository unchanged.

Validation: 500 Python tests and 131 frontend tests pass; production build,
Svelte check (zero errors/warnings), scoped Ruff and diff checks pass. Live
standalone ledger loads with zero Beancount errors and zero schema issues.
Browser verifies property parents, child selection and reload persistence;
different stacked segments show the same full interval, with net last. The net
line is present, and tooltip bounds and controls work at desktop and 390-pixel
mobile widths. Source data and all original deployed routes are unchanged.
Existing upstream dependency advisories remain outside this feature scope.
