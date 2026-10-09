<script lang="ts">
  import { url_for_account } from "../helpers.ts";
  import { ctx } from "../stores/format.ts";
  import type { BarChart, BarChartDatum } from "./bar.ts";

  interface Props {
    chart: BarChart;
    group: BarChartDatum;
    color: (account: string) => string;
  }
  let { chart, group, color }: Props = $props();
  let summaries = $derived(chart.interval_summary(group));
</script>

{#each summaries as summary (summary.currency)}
  <table aria-label={`${group.label} ${summary.currency} breakdown`}>
    <thead
      ><tr
        ><th scope="col">Series</th><th scope="col">{summary.currency}</th></tr
      ></thead
    >
    <tbody>
      {#each summary.series as { account, value } (account)}
        <tr>
          <th scope="row">
            <span class="swatch" style:background-color={color(account)}></span>
            <a href={$url_for_account(account)} title={account}
              >{account.split(":").slice(1).join(" / ").replaceAll("-", " ")}</a
            >
          </th>
          <td>{$ctx.amount(value, summary.currency)}</td>
        </tr>
      {/each}
    </tbody>
    <tfoot
      ><tr
        ><th scope="row">Net amount</th><td
          >{$ctx.amount(summary.net, summary.currency)}</td
        ></tr
      ></tfoot
    >
  </table>
{/each}
{#if !summaries.length}<p>No visible currencies.</p>{/if}

<style>
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  th,
  td {
    padding: 6px 4px;
    vertical-align: top;
  }
  th {
    text-align: left;
    font-weight: normal;
    overflow-wrap: anywhere;
  }
  th:last-child,
  td {
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  tbody tr + tr {
    border-top: 1px solid var(--border);
  }
  tfoot {
    border-top: 2px solid var(--border);
  }
  tfoot th,
  tfoot td {
    font-weight: bold;
  }
  .swatch {
    display: inline-block;
    width: 8px;
    height: 8px;
    margin-right: 5px;
  }
</style>
