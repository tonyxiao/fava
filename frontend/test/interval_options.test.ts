import { deepEqual, equal, ok } from "node:assert/strict";
import { test } from "node:test";
import { ParsedBarChart } from "../src/charts/bar.ts";
import {
  interval_options,
  interval_tooltip,
} from "../src/charts/interval_options.ts";
import type { FormatterContext } from "../src/format.ts";

const chart = ParsedBarChart.validator({
  label: "Net",
  data: [
    {
      date: "2025-12-01",
      budgets: { USD: 30 },
      balance: { USD: -80, CZK: -40 },
      account_balances: {
        "Income:Rent": { USD: -100, CZK: -50 },
        "Expenses:Cleaning": { USD: 20, CZK: 10 },
        "Expenses:Fees": { USD: 0 },
      },
    },
  ],
})
  .unwrap()
  .with_context({
    currencies: ["USD", "CZK"],
    dateFormat: () => "December 2025",
  });
const format = {
  amount: (v: number, c: string) => `${v} ${c}`,
} as FormatterContext;
const theme = { background: "white", text: "black", border: "gray" };
const options = (hidden: string[], stacked: boolean) =>
  interval_options(
    chart,
    hidden,
    stacked,
    format,
    String,
    () => "red",
    () => "blue",
    theme,
  );

test("ECharts keeps independent signed currency stacks and net lines", () => {
  const config = options([], true);
  const series = config.series;
  ok(Array.isArray(series));
  const bars = series.filter((s) => s.type === "bar");
  equal(bars.length, 6);
  deepEqual(
    new Set(bars.map((s) => ("stack" in s ? s.stack : undefined))),
    new Set(["USD", "CZK"]),
  );
  deepEqual(
    series.find((s) => s.id === "account:USD:Income:Rent")?.data,
    [-100],
  );
  deepEqual(series.find((s) => s.id === "net:USD")?.data, [-80]);
  deepEqual(series.find((s) => s.id === "net:CZK")?.data, [-40]);
  const hidden = options(["CZK"], true).series;
  ok(Array.isArray(hidden));
  equal(hidden.length, 4);
});

test("ECharts single bars preserve totals and budget without a net overlay", () => {
  const series = options(["CZK"], false).series;
  ok(Array.isArray(series));
  deepEqual(
    series.map((s) => s.id),
    ["total:USD", "budget:USD"],
  );
  deepEqual(series[0]?.data, [-80]);
  deepEqual(series[1]?.data, [30]);
});

test("ECharts axis tooltip contains the full interval, zero series and net last", () => {
  const group = chart.filter(["CZK"]).bar_groups[0]!;
  const root = interval_tooltip(chart, group, format, () => "red");
  equal(root.querySelectorAll("table").length, 1);
  equal(root.querySelectorAll("tr").length, 5);
  equal(root.querySelector("tr:last-child")?.textContent, "Net-80 USD");
  ok(root.textContent?.includes("0 USD"));
  ok(root.textContent?.includes("-100 USD"));
  ok(!root.textContent?.includes("CZK"));
  const unsafe = interval_tooltip(
    chart,
    { ...group, label: '<img src=x onerror="alert(1)">' },
    format,
    () => "red",
  );
  equal(unsafe.querySelectorAll("img").length, 0);
  ok(unsafe.textContent?.includes("<img"));
});

test("hover passes through the tooltip and selects months without animation", () => {
  const tooltip = options([], true).tooltip;
  ok(tooltip && !Array.isArray(tooltip));
  equal(tooltip.enterable, false);
  equal(tooltip.transitionDuration, 0);
  equal(tooltip.extraCssText, "pointer-events: none;");
  equal(tooltip.axisPointer?.axis, "x");
  equal(tooltip.axisPointer?.animation, false);
});

test("interval chart has no zoom or drag-selection controls", () => {
  const config = options([], true);
  equal(config.dataZoom, undefined);
  equal(config.brush, undefined);
  equal(config.toolbox, undefined);
});
