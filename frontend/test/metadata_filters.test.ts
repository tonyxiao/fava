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

test("generic tree parents include descendants with a delimiter boundary", async () => {
  const { metadata_nodes, field_expression, selected_field, set_field_filter } =
    await import("../src/lib/metadata_filters.ts");
  const field = {
    key: "location",
    label: "Location",
    type: "tree",
    scope: "transaction",
    sources: ["location"],
    separator: "/",
    values: [],
    required: false,
  };
  const nodes = metadata_nodes(field, [
    "House/Upstairs",
    "House/Downstairs",
    "Houseboat/Suite",
  ]);
  assert.deepEqual(nodes, [
    "House",
    "House/Downstairs",
    "House/Upstairs",
    "Houseboat",
    "Houseboat/Suite",
  ]);
  assert.equal(field_expression(field, "House"), 'location:"^House(?:/|$)"');
  const filter = set_field_filter(
    '#estimated location:"^Old(?:/|$)"',
    field,
    "House/Upstairs",
  );
  assert.equal(selected_field(filter, field, nodes), "House/Upstairs");
  assert.equal(set_field_filter(filter, field, ""), "#estimated");
  const regex = new RegExp("^House(?:/|$)");
  assert.equal(regex.test("House/Upstairs"), true);
  assert.equal(regex.test("Houseboat/Suite"), false);
});

test("composite tree uses existing metadata and switching parents removes child predicates", async () => {
  const { field_expression, set_field_filter, selected_field } =
    await import("../src/lib/metadata_filters.ts");
  const field = {
    key: "location",
    label: "Location",
    type: "tree",
    scope: "transaction",
    sources: ["property", "unit"],
    separator: "/",
    values: [],
    required: false,
  };
  const filter = set_field_filter(
    '#estimated property:"^Old$" unit:"^Suite$"',
    field,
    "House/Upstairs",
  );
  assert.equal(filter, '#estimated property:"^House$" unit:"^Upstairs$"');
  assert.equal(
    selected_field(filter, field, ["House", "House/Upstairs"]),
    "House/Upstairs",
  );
  assert.equal(
    set_field_filter(filter, field, "Other"),
    '#estimated property:"^Other$"',
  );
  assert.equal(field_expression(field, "House"), 'property:"^House$"');
});
