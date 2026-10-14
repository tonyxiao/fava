import { equal, ok } from "node:assert/strict";
import { afterEach, before, beforeEach, describe, test } from "node:test";

import { flushSync, mount, tick, unmount } from "svelte";

import { journal_show, journal_sort } from "../src/stores/journal.ts";
import { setup_jsdom } from "./dom.ts";
import { initialise_ledger_data } from "./helpers.ts";
import { install_journal_layout } from "./journal-layout.ts";

interface JournalRequest {
  page: number;
  show: string;
  signal: AbortSignal | null;
}

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function page_response(page: number, revision = "r1"): Response {
  const row_html = Array.from({ length: 200 }, (_, offset) => {
    const index = (page - 1) * 200 + offset;
    return `<li class="transaction cleared"><p><span class="datecell"><a href="#context-entry-${index.toString()}">2026-01-01</a></span><span class="flag">* </span><span class="description">${revision} Narration ${index.toString()}</span><span class="indicators"><span></span></span></p><dl class="metadata"><dt>source:</dt><dd>sample</dd></dl><ul class="postings"><li><p>posting</p></li></ul></li>`;
  }).join("");
  return {
    ok: true,
    json: async () =>
      Promise.resolve({
        data: {
          page,
          total_pages: 500,
          total_entries: 100_000,
          page_size: 200,
          journal: row_html,
          revision,
        },
        mtime: "1",
      }),
  } as Response;
}

const temporary_error = (): Response =>
  ({
    ok: false,
    status: 503,
    json: async () => Promise.resolve({ detail: "temporarily unavailable" }),
  }) as Response;

let restore_layout: () => void = () => undefined;

async function settle(): Promise<void> {
  await tick();
  await new Promise((resolve) => setTimeout(resolve, 25));
  await tick();
  flushSync();
}

async function wait(milliseconds: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, milliseconds));
  await settle();
}

void describe("Journal virtualizer request scheduler", () => {
  before(initialise_ledger_data);
  beforeEach(() => {
    setup_jsdom();
    restore_layout = install_journal_layout();
    journal_sort.set(["date", "desc"]);
    journal_show.set(["transaction", "cleared"]);
  });
  afterEach(() => {
    restore_layout();
  });

  test("real virtualizer prioritizes the latest viewport while pages are pending", async () => {
    const real_fetch = globalThis.fetch;
    const requests: JournalRequest[] = [];
    const delayed = new Map<number, Deferred<Response>>();
    let in_flight = 0;
    let maximum_in_flight = 0;

    globalThis.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      const page = Number(url.searchParams.get("page"));
      requests.push({
        page,
        show: url.searchParams.get("show") ?? "",
        signal: init?.signal ?? null,
      });
      if (page === 1) {
        return page_response(page);
      }
      in_flight += 1;
      maximum_in_flight = Math.max(maximum_in_flight, in_flight);
      const request = deferred<Response>();
      delayed.set(page, request);
      return request.promise.finally(() => {
        in_flight -= 1;
      });
    };

    let component: ReturnType<typeof mount> | undefined;
    try {
      const { default: journal_table } = await import(
        "../src/reports/journal/JournalTable.svelte"
      );
      const article = document.querySelector<HTMLElement>("article");
      ok(article);
      component = mount(journal_table, {
        target: article,
        props: {
          filters: {
            account: "",
            conversion: "",
            filter: "",
            interval: "",
            time: "",
          },
          show_change_and_balance: false,
        },
      });
      flushSync();
      await settle();

      const list =
        article.querySelector<HTMLOListElement>("ol.journal-entries");
      ok(list);
      ok(requests.some(({ page }) => page === 1));

      // Hold several nearby-page responses open, then demand three different
      // distant ranges. Only the final range should be added to the load queue.
      for (const page of [2, 3, 4]) {
        article.scrollTop = (page - 1) * 200 * 52;
        article.dispatchEvent(new window.Event("scroll"));
        await settle();
      }
      const held_pages = [...delayed.keys()];
      ok(held_pages.length > 0);
      ok(held_pages.length <= 3);
      const held_signals = requests
        .filter(({ page }) => held_pages.includes(page))
        .map(({ signal }) => signal);

      const rapid_targets = [
        101, 201, 301, 501, 1001, 21, 91, 401, 51, 151, 251, 751, 51, 351, 41,
        651, 201, 51, 551, 51,
      ];
      for (const page of rapid_targets) {
        article.scrollTop = (page - 1) * 200 * 52;
        article.dispatchEvent(new window.Event("scroll"));
        await settle();
      }
      ok(held_signals.every((signal) => signal != null && !signal.aborted));

      const first_held_page = held_pages[0];
      ok(first_held_page != null);
      const first_response = delayed.get(first_held_page);
      ok(first_response);
      first_response.resolve(page_response(first_held_page));
      await settle();

      // Visible work for the latest scroll wins the next free slot; stale
      // intermediate scroll targets remain queued out.
      const newly_requested = requests.filter(
        ({ page }) => !held_pages.includes(page) && page !== 1,
      );
      ok(newly_requested.some(({ page }) => page === 51));
      ok(
        !newly_requested.some(
          ({ page }) => page !== 51 && rapid_targets.includes(page),
        ),
      );
      ok(requests.length <= 5);

      delayed.get(51)?.resolve(page_response(51));
      await settle();
      ok(list.querySelector('li[data-journal-index="10000"]'));
      ok(list.querySelectorAll("li[data-journal-index]").length < 80);
      ok(maximum_in_flight <= 3);
      ok(
        !requests.some(({ page }) => page > 52 && page !== 101 && page !== 201),
      );

      for (const [page, request] of delayed) {
        request.resolve(page_response(page));
      }
      await settle();
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("unmount clears queued pages and ignores late completions", async () => {
    const real_fetch = globalThis.fetch;
    const requests: JournalRequest[] = [];
    const delayed = new Map<number, Deferred<Response>>();
    globalThis.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      const page = Number(url.searchParams.get("page"));
      requests.push({
        page,
        show: url.searchParams.get("show") ?? "",
        signal: init?.signal ?? null,
      });
      if (page === 1) {
        return page_response(page);
      }
      const request = deferred<Response>();
      delayed.set(page, request);
      return request.promise;
    };

    const { default: journal_table } = await import(
      "../src/reports/journal/JournalTable.svelte"
    );
    const article = document.querySelector<HTMLElement>("article");
    ok(article);
    let component: ReturnType<typeof mount> | undefined = mount(journal_table, {
      target: article,
      props: {
        filters: {
          account: "",
          conversion: "",
          filter: "",
          interval: "",
          time: "",
        },
        show_change_and_balance: false,
      },
    });
    try {
      flushSync();
      await settle();
      for (const page of [2, 3, 4]) {
        article.scrollTop = (page - 1) * 200 * 52;
        article.dispatchEvent(new window.Event("scroll"));
        await settle();
      }
      const pending = [...delayed.values()];
      ok(pending.length > 0);
      ok(pending.length <= 3);

      article.scrollTop = 50 * 200 * 52;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      const before_unmount = requests.length;
      await unmount(component);
      component = undefined;
      ok(
        requests
          .filter(({ page }) => delayed.has(page))
          .every(({ signal }) => signal?.aborted === true),
      );

      for (const [page, request] of delayed) {
        request.resolve(page_response(page));
      }
      await wait(250);
      equal(requests.length, before_unmount);
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("transient HTTP and network failures retry automatically", async (t) => {
    for (const failure_kind of ["http", "network"] as const) {
      await t.test(`${failure_kind} failure recovers`, async () => {
        const real_fetch = globalThis.fetch;
        const attempts = new Map<number, number>();
        globalThis.fetch = async (input) => {
          const url = new URL(
            input instanceof Request ? input.url : String(input),
          );
          const page = Number(url.searchParams.get("page"));
          const attempt = (attempts.get(page) ?? 0) + 1;
          attempts.set(page, attempt);
          if (page === 1 && attempt === 1) {
            if (failure_kind === "network") {
              throw new TypeError("temporary network error");
            }
            return Promise.resolve(temporary_error());
          }
          return Promise.resolve(page_response(page));
        };
        let component: ReturnType<typeof mount> | undefined;
        try {
          const { default: journal_table } = await import(
            "../src/reports/journal/JournalTable.svelte"
          );
          const article = document.querySelector<HTMLElement>("article");
          ok(article);
          component = mount(journal_table, {
            target: article,
            props: {
              filters: {
                account: "",
                conversion: "",
                filter: "",
                interval: "",
                time: "",
              },
              show_change_and_balance: false,
            },
          });
          flushSync();
          await wait(500);
          equal(attempts.get(1), 2);
          const list =
            article.querySelector<HTMLOListElement>("ol.journal-entries");
          ok(list);
          ok(list.textContent.includes("r1 Narration 0"));
          equal(list.getAttribute("aria-busy"), "false");
        } finally {
          if (component) {
            await unmount(component);
          }
          globalThis.fetch = real_fetch;
        }
      });
    }
  });

  test("an offscreen retry timer does not consume a retry attempt", async () => {
    const real_fetch = globalThis.fetch;
    let page_51_attempts = 0;
    globalThis.fetch = async (input) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      const page = Number(url.searchParams.get("page"));
      if (page === 51) {
        page_51_attempts += 1;
        if (page_51_attempts === 1) {
          return Promise.resolve(temporary_error());
        }
      }
      return Promise.resolve(page_response(page));
    };

    let component: ReturnType<typeof mount> | undefined;
    try {
      const { default: journal_table } = await import(
        "../src/reports/journal/JournalTable.svelte"
      );
      const article = document.querySelector<HTMLElement>("article");
      ok(article);
      component = mount(journal_table, {
        target: article,
        props: {
          filters: {
            account: "",
            conversion: "",
            filter: "",
            interval: "",
            time: "",
          },
          show_change_and_balance: false,
        },
      });
      flushSync();
      await settle();
      equal(page_51_attempts, 0);

      article.scrollTop = 525_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      equal(page_51_attempts, 1);

      article.scrollTop = 1_045_000;
      article.dispatchEvent(new window.Event("scroll"));
      await wait(450);
      equal(page_51_attempts, 1);

      article.scrollTop = 525_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      article.scrollTop = 1_045_000;
      article.dispatchEvent(new window.Event("scroll"));
      await wait(850);
      equal(page_51_attempts, 1);

      article.scrollTop = 525_000;
      article.dispatchEvent(new window.Event("scroll"));
      await wait(450);
      equal(page_51_attempts, 2);
      const list =
        article.querySelector<HTMLOListElement>("ol.journal-entries");
      ok(list);
      ok(
        [
          ...list.querySelectorAll<HTMLLIElement>("li[data-journal-index]"),
        ].some((row) => {
          const index = Number(row.dataset.journalIndex);
          return index >= 10_000 && index < 10_200;
        }),
      );
      equal(article.querySelector(".journal-page-retry"), null);
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("discarded queued retries do not consume automatic retry attempts", async () => {
    const real_fetch = globalThis.fetch;
    const requests: JournalRequest[] = [];
    const held_requests: {
      page: number;
      response: Deferred<Response>;
    }[] = [];
    let page_51_attempts = 0;
    globalThis.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      const page = Number(url.searchParams.get("page"));
      requests.push({
        page,
        show: url.searchParams.get("show") ?? "",
        signal: init?.signal ?? null,
      });
      if (page === 1) {
        return page_response(page);
      }
      if (page === 51) {
        page_51_attempts += 1;
        return page_51_attempts === 1 ? temporary_error() : page_response(page);
      }
      const response = deferred<Response>();
      held_requests.push({ page, response });
      return response.promise;
    };

    let component: ReturnType<typeof mount> | undefined;
    try {
      const { default: journal_table } = await import(
        "../src/reports/journal/JournalTable.svelte"
      );
      const article = document.querySelector<HTMLElement>("article");
      ok(article);
      component = mount(journal_table, {
        target: article,
        props: {
          filters: {
            account: "",
            conversion: "",
            filter: "",
            interval: "",
            time: "",
          },
          show_change_and_balance: false,
        },
      });
      flushSync();
      await settle();

      // Fail page 51 once, then occupy every request slot with other pages.
      article.scrollTop = 525_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      equal(page_51_attempts, 1);

      for (const page of [2, 3, 4]) {
        article.scrollTop = (page - 1) * 200 * 52;
        article.dispatchEvent(new window.Event("scroll"));
        await settle();
      }
      ok(held_requests.length >= 3);

      // Return before the retry timer fires so its retry is queued behind the
      // three held requests. Moving away then drops that queued retry.
      article.scrollTop = 525_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      await wait(450);
      equal(page_51_attempts, 1);

      article.scrollTop = 1_045_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      equal(page_51_attempts, 1);

      // A second visible-demand enqueue is discarded while the same slots are
      // occupied. Neither queued request has started, so neither spends an
      // automatic retry attempt.
      article.scrollTop = 525_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      article.scrollTop = 1_045_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      equal(page_51_attempts, 1);

      for (const { page, response } of held_requests) {
        response.resolve(page_response(page));
      }
      await settle();
      equal(page_51_attempts, 1);

      // Once demand returns and a slot is available, page 51 retries on its own.
      article.scrollTop = 525_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      equal(page_51_attempts, 2);
      const list =
        article.querySelector<HTMLOListElement>("ol.journal-entries");
      ok(list);
      ok(
        [
          ...list.querySelectorAll<HTMLLIElement>("li[data-journal-index]"),
        ].some((row) => {
          const index = Number(row.dataset.journalIndex);
          return index >= 10_000 && index < 10_200;
        }),
      );
      equal(article.querySelector(".journal-page-retry"), null);
    } finally {
      for (const { page, response } of held_requests) {
        response.resolve(page_response(page));
      }
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("a failed page after a quick scroll can be retried from the viewport status", async () => {
    const real_fetch = globalThis.fetch;
    const missing_page = deferred<Response>();
    let page_51_attempts = 0;
    globalThis.fetch = async (input) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      const page = Number(url.searchParams.get("page"));
      if (page === 51 && ++page_51_attempts === 1) {
        return missing_page.promise;
      }
      return Promise.resolve(page_response(page));
    };
    let component: ReturnType<typeof mount> | undefined;
    try {
      const { default: journal_table } = await import(
        "../src/reports/journal/JournalTable.svelte"
      );
      const article = document.querySelector<HTMLElement>("article");
      ok(article);
      component = mount(journal_table, {
        target: article,
        props: {
          filters: {
            account: "",
            conversion: "",
            filter: "",
            interval: "",
            time: "",
          },
          show_change_and_balance: false,
        },
      });
      flushSync();
      await settle();
      article.scrollTop = 525_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      const list = article.querySelector(".journal-entries");
      const status = article.querySelector(".journal-page-status");
      ok(list);
      ok(status);
      ok(status.textContent.includes("Loading journal entries"));
      ok(status.classList.contains("has-message"));
      equal(list.getAttribute("aria-busy"), "true");

      missing_page.resolve({
        ok: false,
        status: 400,
        json: async () => Promise.resolve({ detail: "unavailable page" }),
      } as Response);
      await settle();
      const retry = status.querySelector<HTMLButtonElement>(
        ".journal-page-retry",
      );
      ok(retry);
      // The retry belongs to the sticky viewport status, before the huge list.
      equal(status.nextElementSibling, list);
      ok(status.textContent.includes("Could not load"));
      retry.click();
      await settle();
      equal(page_51_attempts, 2);
      equal(status.querySelector(".journal-page-retry"), null);
      equal(status.textContent.trim(), "");
      equal(status.classList.contains("has-message"), false);
      ok(list.querySelector("[data-journal-index]"));
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("one viewport retry recovers both pages across a page boundary", async () => {
    const real_fetch = globalThis.fetch;
    let available = false;
    const retried_pages = new Set<number>();
    globalThis.fetch = async (input) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      const page = Number(url.searchParams.get("page"));
      if (page === 51 || page === 52) {
        if (!available) {
          return Promise.resolve({
            ok: false,
            status: 400,
            json: async () => Promise.resolve({ detail: "unavailable page" }),
          } as Response);
        }
        retried_pages.add(page);
      }
      return Promise.resolve(page_response(page));
    };
    let component: ReturnType<typeof mount> | undefined;
    try {
      const { default: journal_table } = await import(
        "../src/reports/journal/JournalTable.svelte"
      );
      const article = document.querySelector<HTMLElement>("article");
      ok(article);
      component = mount(journal_table, {
        target: article,
        props: {
          filters: {
            account: "",
            conversion: "",
            filter: "",
            interval: "",
            time: "",
          },
          show_change_and_balance: false,
        },
      });
      flushSync();
      await settle();
      article.scrollTop = 530_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      const retry = article.querySelector<HTMLButtonElement>(
        ".journal-page-retry",
      );
      ok(retry);
      available = true;
      retry.click();
      await settle();
      ok(retried_pages.has(51));
      ok(retried_pages.has(52));
      equal(article.querySelector(".journal-page-retry"), null);
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("persistent page failures stop after the bounded automatic retries", async () => {
    const real_fetch = globalThis.fetch;
    let attempts = 0;
    globalThis.fetch = async (input) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      if (Number(url.searchParams.get("page")) === 1) {
        attempts += 1;
      }
      return Promise.resolve(temporary_error());
    };
    let component: ReturnType<typeof mount> | undefined;
    try {
      const { default: journal_table } = await import(
        "../src/reports/journal/JournalTable.svelte"
      );
      const article = document.querySelector<HTMLElement>("article");
      ok(article);
      component = mount(journal_table, {
        target: article,
        props: {
          filters: {
            account: "",
            conversion: "",
            filter: "",
            interval: "",
            time: "",
          },
          show_change_and_balance: false,
        },
      });
      flushSync();
      await wait(1_400);
      equal(attempts, 3);
      const status = article.querySelector<HTMLElement>(".journal-page-status");
      ok(status);
      ok(status.textContent.includes("Could not load"));
      ok(article.querySelector(".journal-page-retry"));
      await wait(900);
      equal(attempts, 3);
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("dataset reset cancels a retry and unmount cancels pending page requests", async () => {
    const real_fetch = globalThis.fetch;
    const requests: JournalRequest[] = [];
    let old_query_attempts = 0;
    let pending_new_query: Deferred<Response> | undefined;
    globalThis.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input));
      const page = Number(url.searchParams.get("page"));
      const show = url.searchParams.get("show") ?? "";
      const request = { page, show, signal: init?.signal ?? null };
      requests.push(request);
      if (show === "cleared,transaction") {
        old_query_attempts += 1;
        return temporary_error();
      }
      pending_new_query = deferred<Response>();
      init?.signal?.addEventListener(
        "abort",
        () => {
          pending_new_query?.resolve(page_response(page));
        },
        { once: true },
      );
      return pending_new_query.promise;
    };

    let component: ReturnType<typeof mount> | undefined;
    try {
      const { default: journal_table } = await import(
        "../src/reports/journal/JournalTable.svelte"
      );
      const article = document.querySelector<HTMLElement>("article");
      ok(article);
      component = mount(journal_table, {
        target: article,
        props: {
          filters: {
            account: "",
            conversion: "",
            filter: "",
            interval: "",
            time: "",
          },
          show_change_and_balance: false,
        },
      });
      flushSync();
      await settle();
      equal(old_query_attempts, 1);

      journal_show.set(["transaction", "pending"]);
      flushSync();
      await settle();
      const new_request = requests.find(
        ({ show }) => show === "pending,transaction",
      );
      ok(new_request?.signal);
      equal(new_request.signal.aborted, false);

      // The old query's 400 ms retry timer must not survive the reset.
      await wait(500);
      equal(old_query_attempts, 1);
      await unmount(component);
      component = undefined;
      equal(new_request.signal.aborted, true);
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });
});
