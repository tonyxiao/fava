import { equal, ok } from "node:assert/strict";
import { test } from "node:test";
import { flushSync, mount, unmount } from "svelte";
import IntervalDetails from "../src/charts/IntervalDetails.svelte";
import { ParsedBarChart } from "../src/charts/bar.ts";
import { setup_jsdom } from "./dom.ts";
import { initialise_ledger_data } from "./helpers.ts";

test.before(initialise_ledger_data);
test.beforeEach(setup_jsdom);

test("fixed interval details show linked series, zero values and signed net", async () => {
  const chart = ParsedBarChart.validator({
    label: "Net",
    data: [
      {
        date: "2025-12-01",
        budgets: {},
        balance: { USD: -80 },
        account_balances: {
          "Income:Rent": { USD: -100 },
          "Expenses:Cleaning": { USD: 20 },
          "Expenses:Fees": { USD: 0 },
        },
      },
    ],
  })
    .unwrap()
    .with_context({ currencies: ["USD"], dateFormat: () => "December 2025" });
  const group = chart.filter([]).bar_groups[0]!;
  const instance = mount(IntervalDetails, {
    target: document.body,
    props: { chart, group, color: () => "red" },
  });
  flushSync();
  const table = document.querySelector(
    'table[aria-label="December 2025 USD breakdown"]',
  );
  ok(table);
  equal(table.querySelectorAll("tbody tr").length, 3);
  equal(table.querySelectorAll("a").length, 3);
  ok(
    table
      .querySelector('a[title="Income:Rent"]')
      ?.getAttribute("href")
      ?.includes("Income:Rent"),
  );
  ok(table.querySelector("tfoot")?.textContent?.includes("80.00 USD"));
  ok(table.textContent?.includes("0.00 USD"));
  equal(document.querySelectorAll(".tooltip").length, 0);
  await unmount(instance);
});
