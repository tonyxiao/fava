# Metadata filter controls

Fork from upstream v1.30.16 on a separate branch, with a pinned upstream
baseline branch for a small reviewable diff. Implement generic configurable
transaction-metadata discovery, exact-match selectors, property-dependent unit
choices, URL/native filter integration and autocomplete. Preserve complex text
filters and report a visible error rather than silently rewriting top-level OR
logic. Never promote posting-only metadata into whole-entry allocations. No
ledger data included in the fork.

Validation completed: 496 Python tests, 127 frontend tests, frontend production
build, Svelte check and scoped Python lint pass. New tests cover configurable
fields, posting-only exclusions, quote/regex escaping, clearing/changing filters
and nested/OR filters. Browser on private live ledger verified property
filtering, unit choices and compound filters; remaining smoke checks cover
property changes, reload and mobile layout. Existing frontend dependency audit
reports five upstream advisories; no dependency upgrades are mixed into this UI
change.

Delivery: commit source changes, open a fork PR against pinned baseline, provide
a separate private preview against the standalone ledger. Money-repository
integration is paused at the user’s request; the attempted integration was
stashed and new service removed. Existing deployed services remain unchanged. No
merge or ledger mutation.
