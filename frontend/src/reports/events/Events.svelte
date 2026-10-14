<script lang="ts">
  import { get_events_page } from "../../api/index.ts";
  import ChartSwitcher from "../../charts/ChartSwitcher.svelte";
  import { ScatterPlot } from "../../charts/scatterplot.ts";
  import type { Event } from "../../entries/index.ts";
  import { _, format } from "../../i18n.ts";
  import PagedTable from "../PagedTable.svelte";
  import type { EventsReportProps } from "./index.ts";

  let { filters }: EventsReportProps = $props();

  const columns = [
    { key: "date", label: _("Date") },
    { key: "type", label: _("Type") },
    { key: "description", label: _("Description") },
  ];

  let event_type = $state("");
  let types = $state<{ type: string; count: number }[]>([]);
  let chart_events = $state<Event[]>([]);
  let chart_total_events = $state(0);
  let chart_events_sampled = $state(false);
  let total_entries = $state(0);
  let loaded = $state(false);
  let chart_metadata_key = "";

  const queryKey = $derived(
    JSON.stringify([filters.account, filters.filter, filters.time, event_type]),
  );

  async function load_page({
    page,
    per_page,
    sort,
    order,
    signal,
  }: {
    page: number;
    per_page: number;
    sort: string;
    order: "asc" | "desc";
    signal: AbortSignal;
  }) {
    const request_query_key = queryKey;
    const selected_event_type = event_type;
    const global_filter_key = JSON.stringify([
      filters.account,
      filters.filter,
      filters.time,
    ]);
    const result = await get_events_page({
      account: filters.account,
      filter: filters.filter,
      time: filters.time,
      event_type: selected_event_type,
      page,
      per_page,
      sort: sort as "date" | "description" | "type",
      order,
      include_overview: page === 1,
      signal,
    });
    const next_chart_metadata_key = `${global_filter_key}\0${result.revision}`;
    if (!signal.aborted && request_query_key === queryKey) {
      if (
        result.types !== null &&
        result.chart_events !== null &&
        result.chart_events_sampled !== null &&
        result.chart_total_events !== null &&
        result.total_events !== null &&
        next_chart_metadata_key !== chart_metadata_key
      ) {
        types = result.types;
        chart_events = result.chart_events;
        chart_total_events = result.chart_total_events;
        chart_events_sampled = result.chart_events_sampled;
        chart_metadata_key = next_chart_metadata_key;
      }
      total_entries = result.total_entries;
      loaded = true;
    }
    return {
      rows: result.events,
      page: result.page,
      page_size: result.page_size,
      total_entries: result.total_entries,
      total_pages: result.total_pages,
      revision: result.revision,
    };
  }

  let charts = $derived([
    new ScatterPlot(
      _("Events"),
      chart_events.map(({ date, type, description }) => ({
        date: new Date(date),
        type,
        description,
      })),
    ),
  ]);
</script>

{#if chart_events.length > 0}
  <ChartSwitcher {charts} />
  {#if chart_events_sampled}
    <p class="chart-sample-note">
      {format(_("Chart shows %(sample)s of %(total)s matching events."), {
        sample: String(chart_events.length),
        total: String(chart_total_events),
      })}
    </p>
  {/if}
{/if}

<div class="left">
  <label>
    {_("Event type")}
    <select bind:value={event_type}>
      <option value="">{_("All types")}</option>
      {#each types as item (item.type)}
        <option value={item.type}>
          {format(_("%(type)s (%(count)s)"), {
            type: item.type,
            count: String(item.count),
          })}
        </option>
      {/each}
    </select>
  </label>
  {#snippet row(event: Event)}
    <td>{event.date}</td>
    <td>{event.type}</td>
    <td>{event.description}</td>
  {/snippet}
  <PagedTable
    {columns}
    {row}
    load={load_page}
    {queryKey}
    reloadKey={filters}
    initialSort="date"
    initialOrder="desc"
    rowKey={(event: Event) => event.entry_hash}
    ariaLabel={_("Events")}
  />
</div>
{#if loaded && total_entries === 0}
  <p>
    {event_type ? _("No events of this type.") : _("No events.")}
  </p>
{/if}

<style>
  .chart-sample-note {
    font-size: 0.9em;
    color: var(--text-color-lightest);
  }
</style>
