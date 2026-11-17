<script lang="ts">
  import { url_for } from "../../helpers.ts";
  import { _ } from "../../i18n.ts";
  import { ledger_mtime } from "../../stores/mtime.ts";
  import { get_transactions_page, type TransactionsPage } from "./api.ts";
  import type { TransactionsReportProps } from "./index.ts";

  let { filters }: TransactionsReportProps = $props();
  let page = $state(1);
  let sort = $state("date");
  let order = $state<"asc" | "desc">("desc");
  let cleared = $state(true);
  let pending = $state(true);
  let other = $state(false);
  let retry = $state(0);
  let loading = $state(true);
  let error = $state("");
  let data = $state<TransactionsPage | null>(null);
  let previous_key = "";
  const flag_filters = [
    { key: "cleared", label: "*", title: _("Cleared transactions") },
    { key: "pending", label: "!", title: _("Pending transactions") },
    { key: "other", label: "x", title: _("Other transactions") },
  ];
  const sort_columns = [
    { key: "date", label: _("Date") },
    { key: "flag", label: _("F") },
    { key: "narration", label: `${_("Payee")}/${_("Narration")}` },
  ];
  let shown = $derived(
    [
      ...(cleared ? ["cleared"] : []),
      ...(pending ? ["pending"] : []),
      ...(other ? ["other"] : []),
    ].join(","),
  );

  function sort_by(column: string): void {
    order = sort === column && order === "asc" ? "desc" : "asc";
    sort = column;
  }
  function toggle_flag(key: string): void {
    if (key === "cleared") {
      cleared = !cleared;
    } else if (key === "pending") {
      pending = !pending;
    } else {
      other = !other;
    }
  }

  $effect(() => {
    // This tab owns its state; it never writes Journal preferences.
    const current_filters = filters;
    const key = JSON.stringify([current_filters, shown, sort, order]);
    // Snapshot reload signals independently of the page-reset key.
    const request_state = { page, revision: $ledger_mtime, retry };
    const requested_page = request_state.page;
    if (key !== previous_key) {
      previous_key = key;
      if (requested_page !== 1) {
        page = 1;
        return;
      }
    }
    const controller = new AbortController();
    const signal = AbortSignal.any([
      controller.signal,
      AbortSignal.timeout(10_000),
    ]);
    loading = true;
    error = "";
    get_transactions_page(
      current_filters,
      requested_page,
      sort,
      order,
      shown,
      signal,
    )
      .then((result) => {
        if (!controller.signal.aborted) {
          data = result;
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          error =
            cause instanceof Error
              ? cause.message
              : _("Could not load transactions.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          loading = false;
        }
      });
    return () => {
      controller.abort();
    };
  });
</script>

<section
  class="transactions-report"
  aria-label={_("Experimental transactions")}
>
  <div class="toolbar">
    <span class="count"
      >{data && !loading
        ? `${data.total_entries.toLocaleString()} ${_("transactions")}`
        : ""}</span
    >
    <div class="flags" aria-label={_("Transaction flags")}>
      {#each flag_filters as flag (flag.key)}
        {@const active =
          flag.key === "cleared"
            ? cleared
            : flag.key === "pending"
              ? pending
              : other}
        <button
          type="button"
          title={flag.title}
          aria-label={flag.title}
          aria-pressed={active}
          class:inactive={!active}
          onclick={() => {
            toggle_flag(flag.key);
          }}
        >
          {flag.label}
        </button>
      {/each}
    </div>
  </div>
  <div role="status" aria-live="polite" class="status">
    {#if loading}{_("Loading transactions…")}{/if}
    {#if error}
      <span>{error}</span>
      <button
        type="button"
        onclick={() => {
          retry += 1;
        }}>{_("Retry")}</button
      >
    {/if}
  </div>
  <table aria-label={_("Transactions")} aria-busy={loading}>
    <colgroup>
      <col class="date-column" /><col class="flag-column" /><col
        class="description-column"
      />
      <col class="amount-column" /><col class="amount-column" /><col />
    </colgroup>
    <thead>
      <tr>
        {#each sort_columns as column (column.key)}
          <th
            scope="col"
            aria-sort={sort === column.key
              ? order === "asc"
                ? "ascending"
                : "descending"
              : "none"}
          >
            <button
              class="sort"
              type="button"
              onclick={() => {
                sort_by(column.key);
              }}
            >
              {column.label}
              {#if sort === column.key}<span aria-hidden="true"
                  >{order === "asc" ? "▲" : "▼"}</span
                >{/if}
            </button>
          </th>
        {/each}
        <th scope="col" class="amount">{_("Debit")}</th>
        <th scope="col" class="amount">{_("Credit")}</th>
        <th scope="col">metadata.note</th>
      </tr>
    </thead>
    {#if !loading && !error && data}
      {#each data.transactions as transaction, transaction_index (transaction_index)}
        <tbody>
          <tr class="transaction">
            <td class="date"
              ><a href={`#context-${transaction.entry_hash}`}
                >{transaction.date}</a
              ></td
            >
            <td class="flag" class:pending={transaction.flag === "!"}
              >{transaction.flag}</td
            >
            <td class="description">
              {#if transaction.payee}<strong>{transaction.payee}</strong>{/if}
              {#if transaction.payee && transaction.narration}<span
                  class="separator"
                >
                  ·
                </span>{/if}
              {transaction.narration}
            </td>
            <td class="amount empty"></td><td class="amount empty"></td>
            <td class="note">{transaction.note}</td>
          </tr>
          {#each transaction.postings as posting, index (index)}
            <tr class="posting">
              <td class="date"></td><td class="flag"></td>
              <td class="account"
                ><a href={$url_for(`account/${posting.account}/`)}
                  >{posting.account}</a
                ></td
              >
              <td class="amount debit" data-label={_("Debit")}
                >{posting.debit}</td
              >
              <td class="amount credit" data-label={_("Credit")}
                >{posting.credit}</td
              >
              <td class="note">{posting.note}</td>
            </tr>
          {/each}
        </tbody>
      {:else}
        <tbody
          ><tr
            ><td colspan="6" class="empty-message"
              >{_("No transactions match these filters.")}</td
            ></tr
          ></tbody
        >
      {/each}
    {/if}
  </table>
  {#if data && !error}
    <nav class="pagination" aria-label={_("Transaction pages")}>
      <button
        type="button"
        disabled={loading || page <= 1}
        onclick={() => {
          page -= 1;
        }}>{_("Previous")}</button
      >
      <span>{_("Page")} {page} / {data.total_pages}</span>
      <button
        type="button"
        disabled={loading || page >= data.total_pages}
        onclick={() => {
          page += 1;
        }}>{_("Next")}</button
      >
    </nav>
  {/if}
</section>

<style>
  .transactions-report {
    width: 100%;
    min-width: 0;
  }
  .toolbar,
  .pagination {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    justify-content: space-between;
  }
  .flags {
    display: flex;
    gap: 0.5rem;
  }
  .flags button {
    min-width: 2.75rem;
    min-height: 2.75rem;
    margin: 0;
  }
  .count {
    color: var(--text-color-lighter);
  }
  .status {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    min-height: 2rem;
  }
  table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
  }
  .date-column {
    width: 7.5rem;
  }
  .flag-column {
    width: 2.5rem;
  }
  .description-column {
    width: 38%;
  }
  .amount-column {
    width: 8rem;
  }
  th {
    color: var(--table-header-text);
    text-align: left;
    background: var(--table-header-background);
  }
  th,
  td {
    padding: 0.5rem 0.65rem;
    line-height: 1.5;
    vertical-align: top;
  }
  th .sort {
    width: 100%;
    min-height: 2.75rem;
    padding: 0;
    margin: 0;
    color: inherit;
    text-align: left;
    background: transparent;
  }
  .sort span {
    font-size: 0.7rem;
  }
  .amount {
    font-variant-numeric: tabular-nums;
    text-align: right;
  }
  td.amount {
    font-family: var(--font-family-monospaced);
    overflow-wrap: anywhere;
  }
  .description,
  .account,
  .note {
    overflow-wrap: anywhere;
  }
  .note {
    white-space: pre-wrap;
  }
  .date {
    white-space: nowrap;
  }
  .flag {
    text-align: center;
  }
  .pending {
    font-weight: bold;
    background: var(--entry-background, var(--journal-postings));
  }
  .transaction {
    border-top: 1px solid var(--table-border);
  }
  tbody + tbody .transaction {
    border-top-color: var(--background);
    border-top-width: 0.75rem;
  }
  .posting {
    font-size: 0.9rem;
    background: var(--journal-postings);
    border-bottom: 1px solid var(--table-border);
  }
  .posting td {
    padding-top: 0.3rem;
    padding-bottom: 0.3rem;
  }
  .separator {
    color: var(--text-color-lighter);
  }
  .empty-message {
    padding: 2rem;
    text-align: center;
  }
  .pagination {
    justify-content: flex-end;
    margin-top: 1rem;
  }
  .pagination button {
    min-height: 2.75rem;
    margin: 0;
  }
  @media (width <= 1024px) {
    table,
    tbody {
      display: block;
    }
    colgroup,
    thead {
      display: none;
    }
    tbody {
      margin-bottom: 1rem;
      overflow: hidden;
      border: 1px solid var(--table-border);
      border-radius: 0.4rem;
    }
    tr {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    }
    td {
      min-width: 0;
    }
    .transaction {
      border: 0;
    }
    tbody + tbody .transaction {
      border: 0;
    }
    .transaction .date {
      grid-column: 1;
    }
    .transaction .flag {
      grid-column: 2;
      text-align: right;
    }
    .description,
    .note,
    .account {
      grid-column: 1 / -1;
    }
    .note:empty,
    .empty,
    .posting .date,
    .posting .flag {
      display: none;
    }
    .posting .debit {
      grid-column: 1;
    }
    .posting .credit {
      grid-column: 2;
    }
    .posting .amount:not(:empty)::before {
      font-family: var(--font-family);
      font-size: 0.8rem;
      content: attr(data-label) " ";
    }
    .pagination {
      justify-content: space-between;
    }
  }
</style>
