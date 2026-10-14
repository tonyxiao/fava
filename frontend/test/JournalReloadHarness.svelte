<script lang="ts">
  import JournalTable from "../src/reports/journal/JournalTable.svelte";
  import type { FiltersConversionInterval } from "../src/stores/filters.ts";

  let filters = $state<FiltersConversionInterval>({
    account: "",
    conversion: "",
    filter: "",
    interval: "",
    time: "",
  });
</script>

<button
  id="reload-same-filters"
  type="button"
  onclick={() => (filters = { ...filters })}
>
  Reload journal
</button>
<JournalTable {filters} show_change_and_balance={false} />
