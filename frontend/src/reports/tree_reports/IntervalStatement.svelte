<script lang="ts">
  import type { BarChart } from "../../charts/bar.ts";
  import { url_for_account } from "../../helpers.ts";
  import { chart_toggled_currencies } from "../../stores/chart.ts";
  import { ctx } from "../../stores/format.ts";

  let { chart }: { chart: BarChart } = $props();
  let data = $derived(chart.filter($chart_toggled_currencies));
</script>

<div class="interval-statement">
  {#each data.currencies as currency (currency)}
    <table aria-label={`${chart.label ?? "P&L"} by interval in ${currency}`}>
      <caption>{chart.label ?? "P&L"} by interval · {currency}</caption>
      <thead>
        <tr>
          <th scope="col">Account</th>
          {#each data.bar_groups as group (group.date)}
            <th scope="col">{group.label}</th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each chart.accounts as account (account)}
          <tr>
            <th scope="row"
              ><a href={$url_for_account(account)}>{account}</a></th
            >
            {#each data.bar_groups as group (group.date)}
              <td
                >{$ctx.num(
                  group.account_balances[account]?.[currency] ?? 0,
                  currency,
                )}</td
              >
            {/each}
          </tr>
        {/each}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row">Net</th>
          {#each data.bar_groups as group (group.date)}
            <td
              >{$ctx.num(
                group.values.find((value) => value.currency === currency)
                  ?.value ?? 0,
                currency,
              )}</td
            >
          {/each}
        </tr>
      </tfoot>
    </table>
  {/each}
  <p>
    Same signed ledger amounts as the chart: income credits are negative; a
    negative net indicates profit. Periods follow the selected interval.
  </p>
</div>

<style>
  .interval-statement {
    margin-top: 1em;
    overflow-x: auto;
  }
  table {
    width: 100%;
    margin-bottom: 1em;
    border-collapse: collapse;
  }
  caption {
    padding: 0.5em 0;
    font-weight: bold;
    text-align: left;
  }
  th,
  td {
    padding: 0.5em 0.75em;
    text-align: right;
    white-space: nowrap;
    border-bottom: 1px solid var(--border-color);
  }
  th:first-child {
    text-align: left;
  }
  td {
    font-variant-numeric: tabular-nums;
  }
  tfoot {
    font-weight: bold;
    border-top: 2px solid var(--border-color);
  }
  p {
    font-size: 0.9em;
    color: var(--text-color-lighter);
  }
</style>
