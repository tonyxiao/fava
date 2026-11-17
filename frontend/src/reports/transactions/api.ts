/** Data access for the experimental tab; no Journal HTML or shared preferences. */
import { get } from "svelte/store";

import { fetch_json } from "../../lib/fetch.ts";
import { array, number, object, string } from "../../lib/validation.ts";
import type { FiltersConversionInterval } from "../../stores/filters.ts";
import { base_url } from "../../stores/index.ts";

interface PostingRow {
  account: string;
  debit: string;
  credit: string;
  note: string;
}
interface TransactionRow {
  entry_hash: string;
  date: string;
  flag: string;
  payee: string;
  narration: string;
  note: string;
  postings: PostingRow[];
}
export interface TransactionsPage {
  transactions: TransactionRow[];
  page: number;
  page_size: number;
  total_entries: number;
  total_pages: number;
}

const posting = object<PostingRow>({
  account: string,
  debit: string,
  credit: string,
  note: string,
});
const transaction = object<TransactionRow>({
  entry_hash: string,
  date: string,
  flag: string,
  payee: string,
  narration: string,
  note: string,
  postings: array(posting),
});
const page_validator = object<TransactionsPage>({
  transactions: array(transaction),
  page: number,
  page_size: number,
  total_entries: number,
  total_pages: number,
});

export async function get_transactions_page(
  filters: FiltersConversionInterval,
  page: number,
  sort: string,
  order: "asc" | "desc",
  show: string,
  signal: AbortSignal,
): Promise<TransactionsPage> {
  const url = new URL(
    `${get(base_url)}api/experimental_transactions`,
    window.location.href,
  );
  for (const [key, value] of Object.entries({
    ...filters,
    page: String(page),
    sort,
    order,
    show,
  })) {
    url.searchParams.set(key, value);
  }
  const response = await fetch_json(url, { signal });
  return page_validator(response.data).unwrap();
}
