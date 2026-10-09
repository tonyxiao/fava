import assert from "node:assert/strict";
import { test } from "node:test";
import {
  filter_clauses,
  metadata_expression,
  selected_metadata,
  set_metadata_filter,
} from "../src/lib/metadata_filters.ts";

test("exact metadata filters escape regex and quoted values", () => {
  assert.equal(
    metadata_expression("property", 'House (A). "Suite"'),
    'property:"^House \\(A\\)\\. \\x22Suite\\x22$"',
  );
  const value = "House with spaces";
  assert.equal(
    selected_metadata(metadata_expression("property", value), "property", [
      value,
    ]),
    value,
  );
});
test("changing property preserves time-independent status and nested posting filters", () => {
  const before =
    '#estimated any(property:"Other" account:"Assets") property:"^Old$"';
  const after = set_metadata_filter(before, "property", "New");
  assert.equal(
    after,
    '#estimated any(property:"Other" account:"Assets") property:"^New$"',
  );
  assert.equal(
    set_metadata_filter(after, "property", ""),
    '#estimated any(property:"Other" account:"Assets")',
  );
});
test("complex OR filters fail visibly rather than silently changing meaning", () => {
  assert.throws(
    () => set_metadata_filter("#one, #two", "property", "House"),
    /text filter/,
  );
});
test("quoted whitespace and parenthesized predicates stay intact", () => {
  assert.deepEqual(
    filter_clauses('payee:"A B" (property:"X" property:"Y") #reviewed'),
    ['payee:"A B"', '(property:"X" property:"Y")', "#reviewed"],
  );
});

test("commas inside quoted metadata values are not OR operators", () => {
  assert.equal(
    set_metadata_filter('property:"^House, East$"', "property", "West"),
    'property:"^West$"',
  );
});
