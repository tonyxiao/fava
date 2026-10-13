<script lang="ts">
  import { onMount } from "svelte";
  import type { EChartsType } from "echarts/core";
  import { scaleOrdinal } from "d3-scale";
  import { router } from "../router.ts";
  import { url_for_account } from "../helpers.ts";
  import { bar_chart_mode, chart_toggled_currencies } from "../stores/chart.ts";
  import { color_scheme } from "../stores/color_scheme.ts";
  import {
    ctx,
    current_time_filter_date_format,
    short,
  } from "../stores/format.ts";
  import type { BarChart } from "./bar.ts";
  import { currencies_scale, hcl_color_range } from "./helpers.ts";
  import { interval_options } from "./interval_options.ts";

  interface Props {
    chart: BarChart;
    width: number;
  }
  let { chart, width }: Props = $props();
  let host: HTMLDivElement;
  let instance = $state.raw<EChartsType>();
  let load_error = $state("");
  let system_theme = $state(0);
  let stacked = $derived($bar_chart_mode === "stacked" && chart.hasStackedData);
  let color = $derived(
    scaleOrdinal(hcl_color_range(chart.accounts.length)).domain(chart.accounts),
  );

  onMount(() => {
    let disposed = false;
    const media = matchMedia("(prefers-color-scheme: dark)");
    const refresh = () => {
      system_theme++;
    };
    media.addEventListener("change", refresh);
    void import("./echarts_runtime.ts")
      .then(({ init }) => {
        if (disposed) return;
        const engine = init(host, undefined, { renderer: "svg" });
        engine.on("click", (params: unknown) => {
          if (!params || typeof params !== "object") return;
          if (
            "componentType" in params &&
            params.componentType === "xAxis" &&
            "value" in params
          ) {
            const group = chart
              .filter($chart_toggled_currencies)
              .bar_groups.find((g) => g.label === params.value);
            if (group)
              router.set_search_param(
                "time",
                $current_time_filter_date_format(group.date),
              );
          } else if (
            "seriesName" in params &&
            typeof params.seriesName === "string" &&
            chart.accounts.includes(params.seriesName)
          ) {
            router.navigate($url_for_account(params.seriesName));
          }
        });
        instance = engine;
      })
      .catch((error: unknown) => {
        load_error =
          error instanceof Error ? error.message : "Unable to load chart";
      });
    return () => {
      disposed = true;
      media.removeEventListener("change", refresh);
      instance?.dispose();
    };
  });

  $effect(() => {
    void width;
    void $color_scheme;
    void system_theme;
    if (!instance) return;
    const styles = getComputedStyle(host);
    instance.setOption(
      interval_options(
        chart,
        $chart_toggled_currencies,
        stacked,
        $ctx,
        $short,
        color,
        $currencies_scale,
        {
          background: styles.backgroundColor,
          text: styles.color,
          border: styles.borderTopColor,
        },
      ),
      { notMerge: true },
    );
    instance.resize();
  });
</script>

<div class="interval-actions">
  <small
    >Hover a month for its breakdown. Use the report controls to change the date
    range.</small
  >
</div>
<div
  bind:this={host}
  class="echarts-interval-chart"
  aria-label="Interval income and expenses chart"
></div>
{#if load_error}<p role="alert">{load_error}</p>{/if}
{#if stacked}<small class="net-caption">Line: net amount · ledger signs</small
  >{/if}

<style>
  .echarts-interval-chart {
    height: 390px;
    width: 100%;
    background: var(--background);
    color: var(--text-color);
    border-color: var(--border);
  }
  .interval-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .interval-actions small,
  .net-caption {
    color: var(--text-color-lightest);
  }
  .net-caption {
    display: block;
    text-align: center;
  }
  @media (max-width: 600px) {
    .echarts-interval-chart {
      height: 340px;
    }
    .interval-actions {
      align-items: start;
    }
  }
</style>
