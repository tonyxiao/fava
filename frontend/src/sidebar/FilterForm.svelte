<script lang="ts">
  import AutocompleteInput from "../components/AutocompleteInput.svelte";
  import {
    metadata_expression,
    selected_metadata,
    set_metadata_filter,
  } from "../lib/metadata_filters.ts";
  import { _ } from "../i18n.ts";
  import { escape_for_regex } from "../lib/regex.ts";
  import { router } from "../router.ts";
  import {
    account_filter,
    fql_filter,
    time_filter,
  } from "../stores/filters.ts";
  import {
    accounts,
    links,
    payees,
    tags,
    years,
    metadata_values,
    metadata_records,
    metadata_keys,
  } from "../stores/index.ts";

  let fql_filter_suggestions = $derived([
    ...Object.entries($metadata_values).flatMap(([key, values]) =>
      values.map((value) => metadata_expression(key, value)),
    ),
    ...$tags.map((tag) => `#${tag}`),
    ...$links.map((link) => `^${link}`),
    ...$payees.map((payee) => `payee:"${escape_for_regex(payee)}"`),
  ]);

  function available_values(key: string, values: string[]): string[] {
    const property = selected_metadata(
      $fql_filter,
      "property",
      $metadata_values["property"] ?? [],
    );
    if (key !== "unit" || !property) return values;
    const units = new Set(
      $metadata_records
        .filter((row) => row["property"] === property)
        .map((row) => row["unit"]),
    );
    return values.filter((value) => units.has(value));
  }
  let metadata_error = $state("");
  function update_metadata(key: string, value: string) {
    try {
      let filter = set_metadata_filter($fql_filter, key, value);
      if (key === "property") filter = set_metadata_filter(filter, "unit", "");
      metadata_error = "";
      router.set_search_param("filter", filter);
    } catch (error) {
      metadata_error =
        error instanceof Error ? error.message : "Unable to update filter";
    }
  }

  function value_extractor(value: string, input: HTMLInputElement) {
    const match = /\S*$/.exec(
      value.slice(0, input.selectionStart ?? undefined),
    );
    return match?.[0] ?? value;
  }
  function value_selector(value: string, input: HTMLInputElement) {
    const selectionStart = input.selectionStart ?? 0;
    const match = /\S*$/.exec(input.value.slice(0, selectionStart));
    const matchLength = match?.[0]?.length;
    return matchLength !== undefined
      ? `${input.value.slice(
          0,
          selectionStart - matchLength,
        )}${value}${input.value.slice(selectionStart)}`
      : value;
  }
</script>

<div class="flex-row">
  <AutocompleteInput
    value={$time_filter}
    placeholder={_("Time")}
    suggestions={$years}
    key="f t"
    clear_button={true}
    set_size={true}
    onchange={(v: string) => {
      router.set_search_param("time", v);
    }}
  />
  <AutocompleteInput
    value={$account_filter}
    placeholder={_("Account")}
    suggestions={$accounts}
    key="f a"
    clear_button={true}
    set_size={true}
    onchange={(v: string) => {
      router.set_search_param("account", v);
    }}
  />
  <AutocompleteInput
    value={$fql_filter}
    placeholder={_("Filter by tag, payee, …")}
    suggestions={fql_filter_suggestions}
    key="f f"
    clear_button={true}
    set_size={true}
    {value_extractor}
    {value_selector}
    onchange={(v: string) => {
      router.set_search_param("filter", v);
    }}
  />
</div>

{#if Object.keys($metadata_values).length}
  <div class="metadata-filters" aria-label="Entry metadata filters">
    {#each $metadata_keys as key (key)}
      {@const values = $metadata_values[key] ?? []}
      <label>
        <span>{key.replaceAll("_", " ")}</span>
        <select
          aria-label={key.replaceAll("_", " ")}
          value={selected_metadata($fql_filter, key, values)}
          onchange={(event) => update_metadata(key, event.currentTarget.value)}
        >
          <option value="">All</option>
          {#each available_values(key, values) as value}<option {value}
              >{value}</option
            >{/each}
        </select>
      </label>
    {/each}
    <small>Entry metadata · pooled entries remain mixed/unallocated</small>
  </div>
  {#if metadata_error}<p role="alert">{metadata_error}</p>{/if}
{/if}

<style>
  div {
    --placeholder-color: var(--header-placeholder-color);
    --placeholder-background: var(--header-placeholder-background);
    --input-padding: 8px 25px 8px 10px;

    color: var(--text-color);

    & > :global(span) {
      max-width: 18rem;
    }

    & :global(input) {
      outline: none;
      background-color: var(--background);
      border: 0;
    }

    & :global([type="text"]:focus) {
      background-color: var(--background);
    }
  }

  .metadata-filters {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding-top: 6px;
    align-items: end;
  }
  .metadata-filters label {
    display: grid;
    gap: 3px;
    font-size: 12px;
  }
  .metadata-filters select {
    max-width: 200px;
    padding: 5px;
    color: var(--text-color);
    background: var(--background);
    border: 1px solid var(--border-color);
    border-radius: 3px;
  }
  .metadata-filters small {
    font-size: 11px;
    opacity: 0.8;
  }
  @media print {
    div {
      --input-padding: 8px 10px;

      & :global(input):placeholder-shown {
        display: none;
      }
    }
  }
</style>
