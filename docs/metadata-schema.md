# Metadata contract version 1

Fava reads a ledger-owned contract from a `custom "fava-option" "metadata-schema"`
entry containing a JSON string. The editor contract is
[metadata-schema-v1.schema.json](metadata-schema-v1.schema.json). The schema changes presentation and validates
metadata; it never changes accounting postings or amounts. Do not infer property
allocations from a pooled journal's posting metadata.

```json
{
  "version": 1,
  "fields": [
    {
      "key": "location",
      "label": "Property / unit",
      "type": "tree",
      "scope": "transaction",
      "sources": ["property", "unit"],
      "separator": "/"
    },
    {
      "key": "platform",
      "type": "enum",
      "values": ["Airbnb", "Vrbo", "Direct"],
      "scope": "transaction"
    },
    {"key": "allocation", "type": "tree", "scope": "posting"},
    {"key": "estimate_status", "type": "string", "scope": "transaction"}
  ]
}
```

`key` is the dimension's identity. Default `sources` is `[key]`, default scope is
transaction, default type is string, default required is false. An enum requires
an explicit string vocabulary. A tree accepts any nonempty path unless `values`
is supplied, in which case stored paths must appear in the vocabulary. Its
virtual parents remain selectable. Keys and source keys use Beancount metadata
names; each key is unique. Schemas do not prohibit undeclared provenance metadata.

With one source, store `property: "Beacon-Hill/Upstairs"`. A parent filter uses
`property:"^Beacon\-Hill(?:/|$)"`, including the house and descendants but excluding
similarly named houses. With multiple sources, existing `property: "Beacon-Hill"`
and `unit: "Upstairs"` become `Beacon-Hill/Upstairs` in the UI; selecting the parent
filters just property, selecting the child adds unit. There are no hard-coded
property names or property/unit relationships in the UI. Full-House is a sibling
of Upstairs and Downstairs. Parent selection includes every unit, so concurrent
unit and full-house bookings still need the ledger's inventory rules for occupancy.

Fields support `string`, `enum`, `tree`, `number` (Beancount Decimal), `boolean`,
and `date` (Beancount date). Typed numeric/date/boolean fields are validated and
remain available for queries, but this first UI generates selectors only for
string/enum/tree dimensions. Required applies to every transaction or posting in
the declared scope. Errors are advisory, visible, and do not suppress transactions
or force balances. Posting-scoped dimensions require posting-level queries;
whole-journal filters only use transaction metadata. `both` validates both scopes
and filters by transaction values only.

Selectors preserve tags, payees and unrelated filters. Top-level OR expressions
remain in the text editor. Only standalone generated predicates are changed;
nested or negated expressions remain untouched. Legacy `filter-metadata` works
without a schema. A supplied invalid schema fails visibly rather than falling
back to misleading controls.

# Interval charts

Interval charts use Apache ECharts 6.1.0 through a lazy-loaded local SVG renderer.
Stacked bars have a net line for each visible currency. Hover or tap a month for a
compact axis tooltip listing all account series, zero values and signed net last.
A crosshair marks the month. Long/multicurrency breakdowns scroll inside the
tooltip. No fixed detail table replaces the tooltip.

Use the slider or scroll to zoom visually; source data remains unchanged. The
Filter date range button enables dragging a range into Fava's native time filter.
Click a month axis label to filter that interval, or a bar series to open its
account report. Single bars retain totals and budgets. Property, time, currency
and conversion filters remain owned by Fava.

Income-statement credits remain negative. Each native currency has its own stack
and net line, never a sum across currencies. Convert the report to USD for one
comparable net series. Dark/light colors follow Fava. Rendering is local; no CDN,
remote chart service or third-party finance-data transfer is involved.
