<script lang="ts">
  import AutocompleteInput from "../components/AutocompleteInput.svelte";
  import { _ } from "../i18n.ts";
  import {
    field_expression,
    type MetadataField,
    metadata_nodes,
    selected_field,
    set_field_filter,
  } from "../lib/metadata_filters.ts";
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
    metadata_issues,
    metadata_schema,
    metadata_values,
    payees,
    tags,
    years,
  } from "../stores/index.ts";

  let filter_fields = $derived(
    $metadata_schema.filter(
      (f) =>
        f.scope !== "posting" && ["string", "enum", "tree"].includes(f.type),
    ),
  );
  let fql_filter_suggestions = $derived([
    ...filter_fields.flatMap((field) =>
      metadata_nodes(field, $metadata_values[field.key] ?? []).map((value) =>
        field_expression(field, value),
      ),
    ),
    ...$tags.map((tag) => `#${tag}`),
    ...$links.map((link) => `^${link}`),
    ...$payees.map((payee) => `payee:"${escape_for_regex(payee)}"`),
  ]);
  let metadata_error = $state("");
  function update_metadata(field: MetadataField, value: string) {
    try {
      const filter = set_field_filter($fql_filter, field, value);
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

{#if filter_fields.length}
  <div class="metadata-filters" aria-label="Entry metadata filters">
    {#each filter_fields as field (field.key)}
      {@const nodes = metadata_nodes(field, $metadata_values[field.key] ?? [])}
      <label>
        <span>{field.label}</span>
        <select
          aria-label={field.label}
          value={selected_field($fql_filter, field, nodes)}
          onchange={(event) => {
            update_metadata(field, event.currentTarget.value);
          }}
        >
          <option value="">All</option>
          {#each nodes as value (value)}
            <option {value}
              >{field.type === "tree"
                ? " ".repeat(value.split(field.separator).length - 1) +
                  value.split(field.separator).join(` ${field.separator} `)
                : value}</option
            >
          {/each}
        </select>
      </label>
    {/each}
    <small>Journal metadata · tree selections include descendants</small>
  </div>
{/if}
{#if metadata_error}<p role="alert">{metadata_error}</p>{/if}
{#if $metadata_issues.length}
  <details class="metadata-issues">
    <summary>Metadata schema: {$metadata_issues.length} issues</summary>
    <ul>
      {#each $metadata_issues as issue (issue)}<li>{issue}</li>{/each}
    </ul>
  </details>
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
    align-items: end;
    padding-top: 6px;
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
