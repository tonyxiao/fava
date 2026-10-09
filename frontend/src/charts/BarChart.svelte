<script lang="ts">
  import type { Attachment } from "svelte/attachments";
  import { line } from "d3-shape";
  import { extent, least } from "d3-array";
  import { axisBottom, axisLeft } from "d3-axis";
  import { scaleBand, scaleLinear, scaleOrdinal } from "d3-scale";

  import { url_for_account } from "../helpers.ts";
  import { bar_chart_mode, chart_toggled_currencies } from "../stores/chart.ts";
  import {
    ctx,
    current_time_filter_date_format,
    short,
  } from "../stores/format.ts";
  import Axis from "./Axis.svelte";
  import Brush from "./Brush.svelte";
  import IntervalDetails from "./IntervalDetails.svelte";
  import type { BarChart, BarChartDatum } from "./bar.ts";
  import { get_chart_tooltip } from "./context.ts";
  import {
    currencies_scale,
    filter_ticks,
    hcl_color_range,
    include_zero,
    pad_extent,
    url_for_time_filter,
  } from "./helpers.ts";

  interface Props {
    chart: BarChart;
    width: number;
  }

  let { chart, width }: Props = $props();

  const today = new Date();
  const tooltip = get_chart_tooltip();

  // Constant dimensions
  const max_column_width = 100;
  const margin = { top: 10, right: 10, bottom: 30, left: 40 };
  const height = 250;
  const inner_height = height - margin.top - margin.bottom;

  // Chart data
  let accounts = $derived(chart.accounts);
  let { currencies, bar_groups, stacks } = $derived(
    chart.filter($chart_toggled_currencies),
  );

  /** Whether to display stacked bars. */
  let show_stacked_bars = $derived(
    $bar_chart_mode === "stacked" && chart.hasStackedData,
  );

  let selected_interval = $state<number>();
  let active_group = $derived(
    bar_groups.find((g) => g.date.getTime() === selected_interval) ??
      bar_groups.findLast((g) => g.date <= today) ??
      bar_groups.at(-1),
  );
  let wide = $derived(width >= 1050);
  let plot_width = $derived(show_stacked_bars && wide ? width - 356 : width);

  function inspect_interval(
    group: BarChartDatum,
    stacked: boolean,
  ): Attachment<SVGElement> {
    if (!stacked)
      return tooltip.following(() => chart.tooltip_text($ctx, group));
    return (node) => {
      const inspect = () => {
        selected_interval = group.date.getTime();
        tooltip.hide();
      };
      node.addEventListener("pointerenter", inspect);
      node.addEventListener("pointerdown", inspect);
      return () => {
        node.removeEventListener("pointerenter", inspect);
        node.removeEventListener("pointerdown", inspect);
      };
    };
  }

  // Computed dimensions
  let max_width = $derived(bar_groups.length * max_column_width);
  let offset = $derived(margin.left + Math.max(0, plot_width - max_width) / 2);
  let inner_width = $derived(
    Math.min(plot_width - margin.left - margin.right, max_width),
  );

  $effect(() => {
    if (show_stacked_bars) tooltip.hide();
  });

  // Scales
  let x0 = $derived(
    scaleBand([0, inner_width])
      .domain(bar_groups.map((d) => d.label))
      .padding(0.1),
  );
  let x1 = $derived(scaleBand([0, x0.bandwidth()]).domain(currencies));

  let y_extent = $derived(
    show_stacked_bars
      ? extent([
          ...stacks.flatMap(([, s]) => s.flat(2)),
          ...bar_groups.flatMap((g) => g.values.map((v) => v.value)),
        ])
      : extent(
          bar_groups.flatMap((d) => d.values),
          (d) => d.value,
        ),
  );
  let y = $derived(
    scaleLinear([inner_height, 0]).domain(pad_extent(include_zero(y_extent))),
  );

  let account_color_scale = $derived(
    scaleOrdinal(hcl_color_range(accounts.length)).domain(accounts),
  );

  // Axes
  let x_axis = $derived(
    axisBottom(x0)
      .tickSizeOuter(0)
      .tickValues(filter_ticks(x0.domain(), inner_width / 70)),
  );
  let y_axis = $derived(
    axisLeft(y).tickPadding(6).tickSize(-inner_width).tickFormat($short),
  );

  /** Invert a pixel x position to the date of the nearest bar group. */
  function invert(px: number): Date {
    const half = x0.bandwidth() / 2;
    const closest = least(bar_groups, ({ label }) =>
      Math.abs(px - (x0(label) ?? 0) - half),
    );
    return closest?.date ?? new Date();
  }
</script>

<div class="interval-chart" class:wide={show_stacked_bars && wide}>
  <div class="plot">
    <svg viewBox={`0 0 ${plot_width.toString()} ${height.toString()}`}>
      <Brush
        {invert}
        height={inner_height}
        transform={`translate(${offset.toString()},${margin.top.toString()})`}
      >
        <Axis x axis={x_axis} {inner_height} />
        <Axis y axis={y_axis} line_at_zero={y(0)} />
        {#each bar_groups as group (group.date)}
          <g
            class={["group", group.date > today && "desaturate"]}
            class:is-active={show_stacked_bars && group === active_group}
            {@attach inspect_interval(group, show_stacked_bars)}
            transform={`translate(${(x0(group.label) ?? 0).toString()},0)`}
          >
            <rect
              class="group-box"
              x={(x0.bandwidth() - x0.step()) / 2}
              width={x0.step()}
              height={inner_height}
            />
            <a
              href={url_for_time_filter(group.date)}
              aria-label={$current_time_filter_date_format(group.date)}
            >
              <rect
                class="axis-group-box"
                y={inner_height}
                width={x0.bandwidth()}
                height={margin.bottom}
              />
            </a>
            {#if !show_stacked_bars}
              {#each group.values as { currency, value, budget } (currency)}
                <rect
                  fill={$currencies_scale(currency)}
                  width={x1.bandwidth()}
                  x={x1(currency)}
                  y={y(Math.max(0, value))}
                  height={Math.abs(y(value) - y(0))}
                />
                <rect
                  class="budget"
                  width={x1.bandwidth()}
                  x={x1(currency)}
                  y={y(Math.max(0, budget))}
                  height={Math.abs(y(budget) - y(0))}
                />
              {/each}
            {/if}
          </g>
        {/each}
        {#if show_stacked_bars}
          <g class="stacks">
            {#each stacks as [currency, account_stacks] (currency)}
              {#each account_stacks as stack (stack.key)}
                {@const account = stack.key}
                <a href={$url_for_account(account)}>
                  {#each stack as bar (bar.data.date)}
                    <rect
                      class={[bar.data.date > today && "desaturate"]}
                      width={x1.bandwidth()}
                      x={(x0(bar.data.label) ?? 0) + (x1(currency) ?? 0)}
                      y={y(Math.max(bar[0], bar[1]))}
                      height={Math.abs(y(bar[1]) - y(bar[0]))}
                      fill={account_color_scale(account)}
                      {@attach inspect_interval(bar.data, true)}
                    />
                  {/each}
                </a>
              {/each}
            {/each}
          </g>
        {/if}
        {#if show_stacked_bars}
          <g class="net-overlay" aria-label="Net amount by interval">
            {#each currencies as currency (currency)}
              {@const path = line<(typeof bar_groups)[number]>()
                .x(
                  (g) =>
                    (x0(g.label) ?? 0) +
                    (x1(currency) ?? 0) +
                    x1.bandwidth() / 2,
                )
                .y((g) =>
                  y(g.values.find((v) => v.currency === currency)?.value ?? 0),
                )(bar_groups)}
              <path class="net-halo" d={path} />
              <path
                class="net-line"
                d={path}
                stroke={$currencies_scale(currency)}
              />
              {#each bar_groups as group (group.date)}
                <circle
                  cx={(x0(group.label) ?? 0) +
                    (x1(currency) ?? 0) +
                    x1.bandwidth() / 2}
                  cy={y(
                    group.values.find((v) => v.currency === currency)?.value ??
                      0,
                  )}
                  r="3"
                  fill={$currencies_scale(currency)}
                />
              {/each}
            {/each}
          </g>
        {/if}
      </Brush>
    </svg>
    {#if show_stacked_bars}<small class="net-caption"
        >Line: net amount · ledger signs · separate line per currency</small
      >{/if}
  </div>
  {#if show_stacked_bars}
    <aside class="interval-details" aria-label="Interval details">
      <label>
        <span>Interval details</span>
        <select
          aria-label="Chart interval"
          value={active_group?.date.getTime().toString() ?? ""}
          onchange={(event) =>
            (selected_interval = Number(event.currentTarget.value))}
        >
          {#each bar_groups as group (group.date)}<option
              value={group.date.getTime().toString()}>{group.label}</option
            >{/each}
        </select>
      </label>
      <small>Hover a month or choose an interval. Details stay here.</small>
      {#if active_group}<IntervalDetails
          {chart}
          group={active_group}
          color={account_color_scale}
        />
      {:else}<p>No intervals in this report.</p>{/if}
    </aside>
  {/if}
</div>

<style>
  .interval-chart {
    display: grid;
    gap: 16px;
    align-items: start;
  }
  .interval-chart.wide {
    grid-template-columns: minmax(0, 1fr) 340px;
  }
  .plot {
    min-width: 0;
  }
  .plot svg {
    display: block;
    width: 100%;
  }
  .interval-details {
    border: 1px solid var(--border);
    padding: 10px;
    max-height: 400px;
    overflow: auto;
  }
  .interval-details label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-weight: bold;
  }
  .interval-details select {
    color: var(--text-color);
    background: var(--background);
    border: 1px solid var(--border);
    padding: 5px;
  }
  .interval-details small {
    display: block;
    margin: 8px 0;
    color: var(--text-color-lightest);
  }
  .group.is-active .group-box {
    opacity: 0.12;
  }
  .net-overlay {
    pointer-events: none;
  }
  .net-line,
  .net-halo {
    fill: none;
    stroke-width: 2.5;
  }
  .net-halo {
    stroke: var(--background);
    stroke-width: 5;
  }
  .net-caption {
    display: block;
    text-align: center;
    opacity: 0.8;
  }

  .axis-group-box,
  .group-box {
    opacity: 0;
  }

  .group:hover .group-box {
    opacity: 0.1;
  }

  .budget {
    opacity: 0.3;
  }

  .desaturate {
    filter: saturate(50%);
  }
</style>
