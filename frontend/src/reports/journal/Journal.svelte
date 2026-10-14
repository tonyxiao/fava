<script lang="ts">
  import type { JournalReportProps } from "./index.ts";
  import JournalTable from "./JournalTable.svelte";

  let { filters }: JournalReportProps = $props();
</script>

<JournalTable {filters} show_change_and_balance={false} />
