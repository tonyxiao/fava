# Entry metadata filter controls

Small fork of Fava v1.30.16: native metadata discovery and exact-match selectors in the report header. Uses the existing `key:regex` filter engine and URL `filter` parameter. Ledger metadata is authoritative; tags are not required. Schema tree selection changes the complete path, including child predicates. All other standalone filters remain. Complex OR clauses remain under the free-text editor and produce a visible explanation rather than silently changing their meaning.

Configure keys with `2000-01-01 custom "fava-option" "filter-metadata" "property,unit,ownership_scope,platform,event_type,estimate_status"`. Only nonempty string transaction metadata values appear. Posting metadata is deliberately not promoted: matching one pooled posting must not allocate the whole transaction to that property. Use posting-level BQL for allocation and reconciliation. No ledger records or financial values are modified.

Properties/units are dimensions; tags are independent statuses/workflow labels; payees identify evidenced counterparties; links trace reservation/payout identity. No tag hierarchy is inferred.

The versioned metadata schema supersedes hard-coded property/unit dependencies; see [metadata-schema.md](metadata-schema.md).
