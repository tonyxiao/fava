import { deepEqual, equal, ok } from "node:assert/strict";
import { before, test } from "node:test";

import { flushSync, mount, tick, unmount } from "svelte";
import { get } from "svelte/store";

import { journal_show, journal_sort } from "../src/stores/journal.ts";
import { setup_jsdom, user_events } from "./dom.ts";
import { initialise_ledger_data } from "./helpers.ts";

before(initialise_ledger_data);

async function settle(): Promise<void> {
  await tick();
  await new Promise((resolve) => setTimeout(resolve, 20));
  flushSync();
}

test("experimental table renders structured rows and keeps Journal preferences isolated", async () => {
  setup_jsdom();
  const journal_preferences = {
    show: [...get(journal_show)],
    sort: [...get(journal_sort)],
  };
  const requests: URL[] = [];
  const real_fetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url =
      input instanceof URL
        ? input
        : new URL(typeof input === "string" ? input : input.url);
    requests.push(url);
    return Promise.resolve(
      new Response(
        JSON.stringify({
          data: {
            page: Number(url.searchParams.get("page")),
            page_size: 50,
            total_pages: 2,
            total_entries: 51,
            transactions: [
              {
                entry_hash: `entry-${url.searchParams.get("page") ?? "1"}`,
                date: "2026-01-01",
                flag: "!",
                payee: "Payee",
                narration: "Narration",
                note: "<b>Plain text note</b>",
                postings: [
                  {
                    account: "Assets:Cash",
                    debit: "12345678901234567890.123456789 BTC",
                    credit: "",
                    note: "Debit note",
                  },
                  {
                    account: "Income:Test",
                    debit: "",
                    credit: "12345678901234567890.123456789 BTC",
                    note: "",
                  },
                ],
              },
            ],
          },
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    );
  };
  let component: ReturnType<typeof mount> | undefined;
  try {
    const { default: transactions } = await import(
      "../src/reports/transactions/Transactions.svelte"
    );
    const target = document.querySelector("article");
    ok(target);
    component = mount(transactions, {
      target,
      props: {
        filters: {
          account: "",
          conversion: "",
          filter: "",
          interval: "",
          time: "2026",
        },
      },
    });
    flushSync();
    await settle();
    equal(target.querySelectorAll("tr.posting").length, 2);
    equal(
      target.querySelector(".debit")?.textContent,
      "12345678901234567890.123456789 BTC",
    );
    equal(
      target.querySelectorAll(".credit")[1]?.textContent,
      "12345678901234567890.123456789 BTC",
    );
    equal(
      target.querySelector(".transaction .note")?.textContent,
      "<b>Plain text note</b>",
    );
    equal(target.querySelector(".note b"), null);
    const pending_button = target.querySelector<HTMLButtonElement>(
      'button[aria-label="Pending transactions"]',
    );
    ok(pending_button);
    user_events.click(pending_button);
    await settle();
    equal(requests.at(-1)?.searchParams.get("show"), "cleared");
    const next = [...target.querySelectorAll("button")].find(
      (button) => button.textContent === "Next",
    );
    ok(next);
    user_events.click(next);
    await settle();
    equal(requests.at(-1)?.searchParams.get("page"), "2");
    const date_sort = target.querySelector<HTMLButtonElement>("thead button");
    ok(date_sort);
    user_events.click(date_sort);
    await settle();
    equal(requests.at(-1)?.searchParams.get("page"), "1");
    equal(requests.at(-1)?.searchParams.get("order"), "asc");
    ok(
      requests.every((url) =>
        url.pathname.endsWith("/api/experimental_transactions"),
      ),
    );
    deepEqual(
      { show: get(journal_show), sort: get(journal_sort) },
      journal_preferences,
    );
  } finally {
    if (component) {
      await unmount(component);
    }
    globalThis.fetch = real_fetch;
  }
});
