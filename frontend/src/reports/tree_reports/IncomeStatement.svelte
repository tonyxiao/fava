<script lang="ts">
  import { ParsedBarChart } from "../../charts/bar.ts";
  import ChartSwitcher from "../../charts/ChartSwitcher.svelte";
  import { chart_context } from "../../charts/context.ts";
  import { last_active_chart_name } from "../../stores/chart.ts";
  import TreeTable from "../../tree-table/TreeTable.svelte";
  import IntervalStatement from "./IntervalStatement.svelte";
  import type { TreeReportProps } from "./index.ts";

  let { charts, trees, date_range }: TreeReportProps = $props();
  let active = $derived(
    charts.find((chart) => chart.label === $last_active_chart_name) ??
      charts[0],
  );
  let interval_chart = $derived(
    active instanceof ParsedBarChart
      ? active.with_context($chart_context)
      : null,
  );
  let end = $derived(date_range?.end ?? null);
</script>

<ChartSwitcher {charts} />

{#if interval_chart}
  <IntervalStatement chart={interval_chart} />
{:else}
  <div class="row">
    <div class="column">
      {#each trees.slice(0, 2) as tree (tree.account)}
        <TreeTable {tree} {end} />
      {/each}
    </div>
    <div class="column">
      {#each trees.slice(2) as tree (tree.account)}
        <TreeTable {tree} {end} />
      {/each}
    </div>
  </div>
{/if}
