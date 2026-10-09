import type { EChartsOption } from "echarts";
import type { FormatterContext } from "../format.ts";
import type { BarChart, BarChartDatum } from "./bar.ts";

export interface IntervalTheme {
  background: string;
  text: string;
  border: string;
}
export const series_label = (account: string) =>
  account.split(":").slice(1).join(" / ").replaceAll("-", " ");

/** DOM text, never interpolated HTML, because ledger strings are source data. */
export function interval_tooltip(
  chart: BarChart,
  group: BarChartDatum,
  format: FormatterContext,
  color: (account: string) => string,
): HTMLElement {
  const root = document.createElement("div");
  root.className = "echarts-interval-tooltip";
  const title = document.createElement("strong");
  title.textContent = group.label;
  root.append(title);
  for (const summary of chart.interval_summary(group)) {
    const table = document.createElement("table");
    table.setAttribute("aria-label", `${group.label} ${summary.currency}`);
    const body = table.createTBody();
    const currency = body.insertRow().insertCell();
    currency.colSpan = 2;
    currency.className = "currency";
    currency.textContent = summary.currency;
    for (const { account, value } of summary.series) {
      const row = body.insertRow();
      const name = row.insertCell();
      name.title = account;
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.backgroundColor = color(account);
      name.append(swatch, series_label(account));
      row.insertCell().textContent = format.amount(value, summary.currency);
    }
    const net = body.insertRow();
    net.className = "net";
    net.insertCell().textContent = "Net";
    net.insertCell().textContent = format.amount(summary.net, summary.currency);
    root.append(table);
  }
  return root;
}

/** Preserve ledger signs, each currency's own stack, and existing conversion. */
export function interval_options(
  chart: BarChart,
  hidden: string[],
  stacked: boolean,
  format: FormatterContext,
  short: (value: number) => string,
  color: (account: string) => string,
  currency_color: (currency: string) => string,
  theme: IntervalTheme,
): EChartsOption {
  const { currencies, bar_groups } = chart.filter(hidden);
  const series: NonNullable<EChartsOption["series"]> = [];
  for (const currency of currencies) {
    if (stacked) {
      for (const account of chart.accounts) {
        series.push({
          id: `account:${currency}:${account}`,
          name: account,
          type: "bar",
          stack: currency,
          stackStrategy: "samesign",
          barMaxWidth: 64,
          data: bar_groups.map(
            (g) => g.account_balances[account]?.[currency] ?? 0,
          ),
          itemStyle: { color: color(account) },
          emphasis: { focus: "none" },
        });
      }
      series.push({
        id: `net:${currency}`,
        name: `Net (${currency})`,
        type: "line",
        data: bar_groups.map(
          (g) => g.values.find((v) => v.currency === currency)?.value ?? 0,
        ),
        symbol: "circle",
        symbolSize: 5,
        z: 10,
        lineStyle: { width: 2.5, color: currency_color(currency) },
        itemStyle: {
          color: currency_color(currency),
          borderColor: theme.background,
          borderWidth: 1,
        },
      });
    } else {
      series.push({
        id: `total:${currency}`,
        name: currency,
        type: "bar",
        barMaxWidth: 64,
        data: bar_groups.map(
          (g) => g.values.find((v) => v.currency === currency)?.value ?? 0,
        ),
        itemStyle: { color: currency_color(currency) },
      });
      if (
        bar_groups.some((g) =>
          g.values.some((v) => v.currency === currency && v.budget),
        )
      ) {
        series.push({
          id: `budget:${currency}`,
          name: `Budget (${currency})`,
          type: "bar",
          barMaxWidth: 64,
          data: bar_groups.map(
            (g) => g.values.find((v) => v.currency === currency)?.budget ?? 0,
          ),
          itemStyle: { color: currency_color(currency), opacity: 0.3 },
        });
      }
    }
  }
  return {
    animation: false,
    aria: {
      enabled: true,
      label: {
        description:
          "Income and expenses by interval. Bars show signed ledger amounts and lines show net. Hover or tap a month for its full breakdown; use the slider to zoom.",
      },
    },
    textStyle: { color: theme.text, fontFamily: "Fira Sans, sans-serif" },
    grid: { left: 12, right: 18, top: 20, bottom: 95, outerBoundsMode: "same" },
    xAxis: {
      type: "category",
      data: bar_groups.map((g) => g.label),
      triggerEvent: true,
      axisLabel: { color: theme.text },
      axisLine: { lineStyle: { color: theme.border } },
    },
    yAxis: {
      type: "value",
      axisLabel: { formatter: short, color: theme.text },
      splitLine: { lineStyle: { color: theme.border } },
    },
    tooltip: {
      trigger: "axis",
      confine: true,
      enterable: true,
      hideDelay: 80,
      axisPointer: { type: "cross", label: { show: false } },
      backgroundColor: theme.background,
      borderColor: theme.border,
      padding: 10,
      textStyle: { color: theme.text, fontSize: 12 },
      formatter: (params: unknown) => {
        const first = Array.isArray(params) ? params[0] : params;
        const index =
          first && typeof first === "object" && "dataIndex" in first
            ? first.dataIndex
            : undefined;
        const group = typeof index === "number" ? bar_groups[index] : undefined;
        if (!group) return "";
        if (stacked) return interval_tooltip(chart, group, format, color);
        const root = document.createElement("div");
        root.append(...chart.tooltip_text(format, group));
        return root;
      },
    },
    legend: {
      type: "scroll",
      bottom: 40,
      selectedMode: false,
      textStyle: { color: theme.text, fontSize: 11 },
      formatter: (name: string) =>
        chart.accounts.includes(name) ? series_label(name) : name,
    },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      {
        type: "slider",
        xAxisIndex: 0,
        filterMode: "none",
        height: 20,
        bottom: 4,
        textStyle: { color: theme.text },
      },
    ],
    brush: {
      xAxisIndex: 0,
      brushType: "lineX",
      brushMode: "single",
      transformable: false,
    },
    series,
  };
}
