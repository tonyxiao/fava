<script lang="ts">
  import { get_documents_page, move_document } from "../../api/index.ts";
  import type { Document } from "../../entries/index.ts";
  import AccountInput from "../../entry-forms/AccountInput.svelte";
  import { _ } from "../../i18n.ts";
  import { basename } from "../../lib/paths.ts";
  import { stratify_accounts } from "../../lib/tree.ts";
  import ModalBase from "../../modals/ModalBase.svelte";
  import { router } from "../../router.ts";
  import PagedTable from "../PagedTable.svelte";
  import Accounts from "./Accounts.svelte";
  import DocumentPreview from "./DocumentPreview.svelte";
  import type { DocumentsReportProps } from "./index.ts";
  import { selected_account } from "./stores.ts";

  let { filters }: DocumentsReportProps = $props();

  const columns = [
    { key: "date", label: _("Date") },
    { key: "name", label: _("Name") },
  ];

  let accounts = $state<{ account: string; count: number }[]>([]);
  let accounts_key = "";
  let selected: Document | null = $state(null);
  let moving: MoveDetails | null = $state(null);
  let node = $derived(
    stratify_accounts(
      accounts,
      (item) => item.account,
      (account, item) => ({ name: account, count: item?.count ?? 0 }),
    ),
  );

  const queryKey = $derived(
    JSON.stringify([
      filters.account,
      filters.filter,
      filters.time,
      $selected_account,
    ]),
  );

  async function load_page({
    page,
    per_page,
    sort,
    order,
    signal,
  }: {
    page: number;
    per_page: number;
    sort: string;
    order: "asc" | "desc";
    signal: AbortSignal;
  }) {
    const request_query_key = queryKey;
    const selected = $selected_account;
    const result = await get_documents_page({
      account: filters.account,
      filter: filters.filter,
      time: filters.time,
      a: selected,
      page,
      per_page,
      sort: sort as "date" | "name",
      order,
      include_overview: page === 1,
      signal,
    });
    const next_accounts_key = `${filters.account}\0${filters.filter}\0${filters.time}\0${result.revision}`;
    if (
      result.accounts !== null &&
      !signal.aborted &&
      request_query_key === queryKey &&
      next_accounts_key !== accounts_key
    ) {
      accounts = result.accounts;
      accounts_key = next_accounts_key;
    }
    return {
      rows: result.documents,
      page: result.page,
      page_size: result.page_size,
      total_entries: result.total_entries,
      total_pages: result.total_pages,
      revision: result.revision,
    };
  }

  interface MoveDetails {
    account: string;
    filename: string;
    new_name: string;
  }

  /**
   * Rename the selected document with <F2>.
   */
  function keyup(ev: KeyboardEvent) {
    if (ev.key === "F2" && selected && !moving) {
      moving = {
        account: selected.account,
        filename: selected.filename,
        new_name: basename(selected.filename),
      };
    }
  }

  async function move(event: SubmitEvent) {
    event.preventDefault();
    if (moving) {
      const moved = await move_document(
        moving.filename,
        moving.account,
        moving.new_name,
      );
      if (moved) {
        moving = null;
        router.reload();
      }
    }
  }

  function document_name(doc: Document) {
    const base = basename(doc.filename);
    return base.startsWith(doc.date) ? base.substring(11) : base;
  }
</script>

<svelte:window onkeyup={keyup} />
{#if moving}
  <ModalBase
    shown={true}
    close_handler={() => {
      moving = null;
    }}
  >
    <form onsubmit={move}>
      <h3>{_("Move or rename document")}</h3>
      <p><code>{moving.filename}</code></p>
      <p>
        <AccountInput bind:value={moving.account} />
        <input size={40} bind:value={moving.new_name} />
        <button type="submit">{_("Move")}</button>
      </p>
    </form>
  </ModalBase>
{/if}
<div class="fixed-fullsize-container">
  <div class="accounts-pane" data-report-scroll>
    <Accounts
      {node}
      move={(arg: { account: string; filename: string }) => {
        moving = { ...arg, new_name: basename(arg.filename) };
      }}
    />
  </div>
  <div class="documents-pane" data-report-scroll>
    {#snippet row(doc: Document)}
      <td>{doc.date}</td>
      <td>{document_name(doc)}</td>
    {/snippet}
    <PagedTable
      {columns}
      {row}
      load={load_page}
      {queryKey}
      reloadKey={filters}
      initialSort="date"
      initialOrder="desc"
      rowKey={(doc: Document) => doc.entry_hash}
      rowClass={(doc: Document) =>
        doc.filename === selected?.filename ? "selected" : ""}
      rowTitle={(doc: Document) => doc.filename}
      ariaLabel={_("Documents")}
      onRowClick={(doc: Document) => {
        selected = doc;
      }}
      onRowDragStart={(doc: Document, event: DragEvent) => {
        event.dataTransfer?.setData("fava/filename", doc.filename);
      }}
    />
  </div>
  <div class="preview-pane" data-report-scroll>
    {#if selected}
      <DocumentPreview filename={selected.filename} />
    {/if}
  </div>
</div>

<style>
  .fixed-fullsize-container {
    display: grid;
    grid-template-columns: 1fr 2fr 3fr;
  }

  .fixed-fullsize-container > div {
    height: 100%;
    overflow: auto;
    resize: horizontal;
  }

  .fixed-fullsize-container > div + div {
    border-left: thin solid var(--sidebar-border);
  }

  .documents-pane :global(.selected) {
    background-color: var(--table-header-background);
  }
</style>
