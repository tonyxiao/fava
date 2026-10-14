<script lang="ts">
  import PagedTable, {
    type PagedTablePage,
    type PagedTableRequest,
  } from "../src/reports/PagedTable.svelte";

  interface Row {
    index: number;
    label: string;
  }

  interface Props {
    load: (request: PagedTableRequest) => Promise<PagedTablePage<Row>>;
    // eslint-disable-next-line @typescript-eslint/naming-convention -- Matches PagedTable's public component prop.
    queryKey: unknown;
  }

  let { load, queryKey }: Props = $props();
  function initial_query_key(): unknown {
    return queryKey;
  }
  let query_key = $state(initial_query_key());
  let reload_version = $state(0);

  const columns = [
    { key: "index", label: "Index" },
    { key: "label", label: "Label" },
  ];
</script>

{#snippet cells(item: Row)}
  <td>{item.index}</td>
  <td>{item.label}</td>
{/snippet}

<PagedTable
  {columns}
  row={cells}
  {load}
  queryKey={query_key}
  reloadKey={reload_version}
  initialSort="index"
  initialOrder="asc"
  ariaLabel="Test rows"
  onRowClick={() => undefined}
/>
<button type="button" data-reload onclick={() => (reload_version += 1)}>
  Refresh data
</button>
<button
  type="button"
  data-change-query
  onclick={() => (query_key = "changed-query")}
>
  Change query
</button>
