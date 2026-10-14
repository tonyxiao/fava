<script lang="ts">
  import { untrack } from "svelte";

  import { get_commodity_report } from "../../api/index.ts";
  import type { CommodityReport } from "../../api/validators.ts";
  import ChartSwitcher from "../../charts/ChartSwitcher.svelte";
  import { LineChart } from "../../charts/line.ts";
  import { domHelpers } from "../../charts/tooltip.ts";
  import AutocompleteInput from "../../components/AutocompleteInput.svelte";
  import { day } from "../../format.ts";
  import { _, format } from "../../i18n.ts";
  import { ctx } from "../../stores/format.ts";
  import { currency_name } from "../../stores/index.ts";
  import PagedTable from "../PagedTable.svelte";
  import type { CommoditiesReportProps } from "./index.ts";

  let { filters, initialReport }: CommoditiesReportProps = $props();

  // svelte-ignore state_referenced_locally
  let report = $state.raw<CommodityReport>(initialReport);
  // svelte-ignore state_referenced_locally
  let selected_pair = $state(
    pair_name(initialReport.base, initialReport.quote),
  );
  let pair_input = $state("");
  let chart_key = "";

  function pair_name(base: string, quote: string): string {
    return base && quote ? `${base} / ${quote}` : "";
  }

  let pairs = $derived(
    new Map(
      (report.pairs ?? []).map((pair) => [
        pair_name(pair.base, pair.quote),
        pair,
      ]),
    ),
  );
  let suggestions = $derived([...pairs.keys()]);
  let query_key = $derived(JSON.stringify({ filters, selected_pair }));
  let active_pair = $derived(pairs.get(selected_pair));
  let quote = $derived(active_pair?.quote ?? report.quote);
  let quote_name = $derived($currency_name(quote));

  $effect(() => {
    const next = initialReport;
    untrack(() => {
      const retained_pair =
        next.pairs?.some(
          (pair) => pair_name(pair.base, pair.quote) === selected_pair,
        ) ?? false;
      report = next;
      if (!retained_pair) {
        selected_pair = pair_name(next.base, next.quote);
      }
      pair_input = selected_pair;
      chart_key = "";
    });
  });

  let charts = $derived.by(() => {
    const chart_prices = report.chart_prices;
    if (
      chart_prices == null ||
      chart_prices.length === 0 ||
      pair_name(report.base, report.quote) !== selected_pair
    ) {
      return [];
    }
    const name = pair_name(report.base, report.quote);
    const values = chart_prices.map(([date, value]) => ({
      name,
      date,
      value,
    }));
    return [
      new LineChart(name, [{ name, values }], (context, datum) => [
        `1 ${report.base} = ${context.amount(datum.value, report.quote)}`,
        domHelpers.em(day(datum.date)),
      ]),
    ];
  });

  async function load_prices(request: {
    page: number;
    per_page: number;
    sort: string;
    order: "asc" | "desc";
    signal: AbortSignal;
  }) {
    const request_filters = filters;
    const request_pair = selected_pair;
    const pair = pairs.get(request_pair);
    const result = await get_commodity_report({
      ...request_filters,
      ...request,
      sort: request.sort === "price" ? "price" : "date",
      include_overview: request.page === 1,
      ...(pair ? { base: pair.base, quote: pair.quote } : {}),
    });
    if (
      !request.signal.aborted &&
      filters === request_filters &&
      selected_pair === request_pair &&
      result.pairs != null &&
      result.chart_prices != null
    ) {
      // Scrolling changes table pages, not the chart's complete date range.
      const key = JSON.stringify({
        filters: request_filters,
        base: result.base,
        quote: result.quote,
        revision: result.revision,
      });
      if (key !== chart_key) {
        report = result;
        chart_key = key;
      }
    }
    return { ...result, rows: result.prices };
  }

  function choose_pair(value: string): void {
    if (pairs.has(value)) {
      selected_pair = value;
    }
  }
</script>

{#if report.pairs?.length}
  <div class="commodity-toolbar">
    <label>
      {_("Commodity pair")}
      <AutocompleteInput
        bind:value={pair_input}
        placeholder={_("Search commodity pairs")}
        {suggestions}
        automatic_selection={true}
        onchange={choose_pair}
        check_validity={(value: string) =>
          pairs.has(value) ? "" : _("Select a commodity pair")}
      />
    </label>
    <span class="pair-count">
      {format(_("%(count)s pairs"), {
        count: report.pairs.length.toLocaleString(),
      })}
    </span>
  </div>

  <ChartSwitcher {charts} />
  {#if pair_name(report.base, report.quote) === selected_pair && report.chart_prices_sampled}
    <p class="chart-scope">
      {format(
        _(
          "Chart shows %(shown)s of %(total)s price points. All prices are available in the table.",
        ),
        {
          shown: (report.chart_prices?.length ?? 0).toLocaleString(),
          total: (
            report.chart_total_prices ?? report.total_entries
          ).toLocaleString(),
        },
      )}
    </p>
  {/if}

  <h3>
    <span title={$currency_name(active_pair?.base ?? report.base)}>
      {active_pair?.base ?? report.base}
    </span>
    / {quote}
  </h3>
  {#snippet price_row(price: [Date, number])}
    <td>{day(price[0])}</td>
    <td class="num" title={quote_name}>{$ctx.amount(price[1], quote)}</td>
  {/snippet}
  <PagedTable
    ariaLabel={_("Commodity prices")}
    columns={[
      { key: "date", label: _("Date") },
      { key: "price", label: _("Price"), className: "num" },
    ]}
    row={price_row}
    load={load_prices}
    queryKey={query_key}
    reloadKey={filters}
    initialSort="date"
    initialOrder="desc"
  />
{:else}
  <p>{_("No prices.")}</p>
{/if}

<style>
  .commodity-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    align-items: end;
    margin-bottom: 1rem;
  }

  label {
    display: grid;
    gap: 0.25rem;
    min-width: min(20rem, 100%);
  }

  .pair-count,
  .chart-scope {
    font-size: 0.9em;
    color: var(--text-color-lightest);
  }
</style>
