import { equal, ok } from "node:assert/strict";
import { afterEach, before, beforeEach, describe, test } from "node:test";

import { flushSync, mount, tick, unmount } from "svelte";

import { journal_show, journal_sort } from "../src/stores/journal.ts";
import { setup_jsdom } from "./dom.ts";
import { initialise_ledger_data } from "./helpers.ts";
import {
  install_journal_layout,
  journal_resize_observers,
} from "./journal-layout.ts";

interface JournalRequest {
  url: URL;
  signal: AbortSignal | null;
}

function request_url(input: RequestInfo | URL): URL {
  if (input instanceof URL) {
    return new URL(input.href);
  }
  if (typeof input === "string") {
    return new URL(input, window.location.href);
  }
  return new URL(input.url, window.location.href);
}

function first_visible_journal_index(
  list: HTMLOListElement,
): number | undefined {
  const row = [
    ...list.querySelectorAll<HTMLLIElement>("li[data-journal-index]"),
  ].find((candidate) => candidate.getBoundingClientRect().bottom > 0);
  return row ? Number(row.dataset.journalIndex) : undefined;
}

const page_response = (page: number, revision = "r1"): Response => {
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
};

async function settle(): Promise<void> {
  await tick();
  await new Promise((resolve) => setTimeout(resolve, 25));
  await tick();
  flushSync();
}

async function wait_for_layout(milliseconds: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, milliseconds));
  await settle();
}

let restore_layout: () => void = () => undefined;

void describe("Journal virtualizer integration", () => {
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

  test("100k journal stays bounded in the article scroller and restores expanded rows after eviction", async () => {
    const real_fetch = globalThis.fetch;
    const requests: JournalRequest[] = [];
    globalThis.fetch = async (input, init) => {
      const url = request_url(input);
      requests.push({ url, signal: init?.signal ?? null });
      return Promise.resolve(
        page_response(Number(url.searchParams.get("page"))),
      );
    };

    let component: ReturnType<typeof mount> | undefined;
    try {
      const { default: journal_table } = await import(
        "../src/reports/journal/JournalTable.svelte"
      );
      const article = document.querySelector<HTMLElement>("article");
      ok(article);
      Object.defineProperty(article, "clientHeight", {
        configurable: true,
        value: 600,
      });
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
      const initially_loaded = requests.map(({ url }) =>
        Number(url.searchParams.get("page")),
      );
      ok(initially_loaded.length >= 1);
      ok(initially_loaded.length <= 3);
      ok(initially_loaded.every((page) => page <= 2));
      ok(list.querySelectorAll("li[data-journal-index]").length < 80);

      const first_row = list.querySelector<HTMLLIElement>(
        'li[data-journal-index="0"]',
      );
      ok(first_row);
      const row_observer = journal_resize_observers().find(({ targets }) =>
        targets.has(first_row),
      );
      ok(row_observer);
      row_observer.deliver(first_row, { blockSize: 100 });
      await settle();
      flushSync();
      first_row
        .querySelector(".indicators")
        ?.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      flushSync();
      ok(first_row.classList.contains("show-full-entry"));

      // Window scrolling remains at the top; the article scroll drives paging.
      Object.defineProperty(window, "scrollY", {
        configurable: true,
        value: 0,
      });
      article.scrollTop = 530_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();

      const requested_pages = requests.map(({ url }) =>
        Number(url.searchParams.get("page")),
      );
      ok(requested_pages.includes(51));
      ok(!requested_pages.includes(500));
      ok(list.querySelectorAll("li[data-journal-index]").length < 80);
      equal(list.querySelector('li[data-journal-index="0"]'), null);

      article.scrollTop = 0;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      const restored_row = list.querySelector<HTMLLIElement>(
        'li[data-journal-index="0"]',
      );
      ok(restored_row);
      ok(restored_row.classList.contains("show-full-entry"));
      ok(
        requests.filter(({ url }) => url.searchParams.get("page") === "1")
          .length > 1,
      );

      const focused_link =
        restored_row.querySelector<HTMLAnchorElement>(".datecell a");
      ok(focused_link);
      focused_link.focus();
      article.scrollTop = 6_000;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      equal(document.activeElement, focused_link);
      focused_link.blur();
      flushSync();

      // The real virtualizer keeps the current range bounded after returning to
      // the measured section of the journal.
      article.scrollTop = 5_248;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();
      ok(list.querySelector("li[data-journal-index]"));
      ok(list.querySelectorAll("li[data-journal-index]").length < 80);
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("posting visibility preserves the first visible row after measured heights change", async () => {
    restore_layout();
    restore_layout = install_journal_layout(1280, () =>
      document.querySelector(".journal-entries.show-postings") ? 120 : 52,
    );
    journal_show.set(["transaction", "cleared", "postings"]);
    flushSync();

    const real_fetch = globalThis.fetch;
    globalThis.fetch = async (input) => {
      const url = request_url(input);
      return Promise.resolve(
        page_response(Number(url.searchParams.get("page"))),
      );
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
      ok(list.classList.contains("show-postings"));
      article.scrollTop = 750_000;
      article.dispatchEvent(new window.Event("scroll"));
      await wait_for_layout(500);
      const first_visible_before = first_visible_journal_index(list);
      ok(first_visible_before != null && first_visible_before > 1_000);
      ok(
        list.querySelector(
          `li[data-journal-index="${first_visible_before.toString()}"]`,
        ),
      );

      journal_show.set(["transaction", "cleared"]);
      flushSync();
      await wait_for_layout(500);

      ok(!list.classList.contains("show-postings"));
      equal(first_visible_journal_index(list), first_visible_before);
      ok(
        list.querySelector(
          `li[data-journal-index="${first_visible_before.toString()}"]`,
        ),
      );
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("filter and sort changes replace pending requests and unmount cancels navigation work", async () => {
    const real_fetch = globalThis.fetch;
    const requests: JournalRequest[] = [];
    globalThis.fetch = async (input, init) => {
      requests.push({
        url: request_url(input),
        signal: init?.signal ?? null,
      });
      return new Promise<Response>((_resolve, reject) => {
        if (init?.signal != null) {
          init.signal.addEventListener(
            "abort",
            () => {
              reject(new DOMException("Request aborted", "AbortError"));
            },
            { once: true },
          );
        }
      });
    };

    let component: ReturnType<typeof mount> | undefined;
    try {
      journal_show.set(["transaction", "cleared", "legacy-invalid-type"]);
      const { default: journal_table } = await import(
        "../src/reports/journal/JournalTable.svelte"
      );
      const article = document.querySelector<HTMLElement>("article");
      ok(article);
      component = mount(journal_table, {
        target: article,
        props: {
          account: "Assets:Checking",
          filters: {
            account: "",
            conversion: "USD",
            filter: "Expenses",
            interval: "month",
            time: "2026-01",
          },
          show_change_and_balance: true,
        },
      });
      flushSync();
      await settle();

      const initial = requests[0];
      ok(initial);
      equal(initial.url.searchParams.get("a"), "Assets:Checking");
      equal(initial.url.searchParams.get("filter"), "Expenses");
      equal(initial.url.searchParams.get("conversion"), "USD");
      equal(initial.url.searchParams.get("interval"), "month");
      equal(initial.url.searchParams.get("time"), "2026-01");
      equal(initial.url.searchParams.get("sort"), "date");
      equal(initial.url.searchParams.get("order"), "desc");
      equal(initial.url.searchParams.get("show"), "cleared,transaction");

      journal_show.set(["transaction", "pending", "legacy-invalid-type"]);
      journal_sort.set(["flag", "asc"]);
      flushSync();
      await settle();

      equal(initial.signal?.aborted, true);
      const updated = requests.at(-1);
      ok(updated);
      equal(updated.url.searchParams.get("show"), "pending,transaction");
      equal(updated.url.searchParams.get("sort"), "flag");
      equal(updated.url.searchParams.get("order"), "asc");
      equal(updated.url.searchParams.get("a"), "Assets:Checking");
      ok(updated.signal);
      ok(!updated.signal.aborted);

      // Leaving the journal (route navigation) must abort its in-flight fetch.
      await unmount(component);
      component = undefined;
      ok(updated.signal.aborted);
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("same-value route reload fetches page 1 again and clears aria-busy when requests finish", async () => {
    const real_fetch = globalThis.fetch;
    const requests: JournalRequest[] = [];
    let page1_calls = 0;
    let current_revision = "r1";
    let resolve_reload!: (response: Response) => void;
    globalThis.fetch = async (input, init) => {
      const url = request_url(input);
      requests.push({ url, signal: init?.signal ?? null });
      const page = Number(url.searchParams.get("page"));
      if (page === 1) {
        page1_calls += 1;
        current_revision = `r${page1_calls.toString()}`;
        if (page1_calls === 2) {
          return new Promise<Response>((resolve) => {
            resolve_reload = resolve;
          });
        }
      }
      return Promise.resolve(page_response(page, current_revision));
    };

    let component: ReturnType<typeof mount> | undefined;
    try {
      const { default: journal_reload_harness } = await import(
        "./JournalReloadHarness.svelte"
      );
      const article = document.querySelector<HTMLElement>("article");
      ok(article);
      component = mount(journal_reload_harness, { target: article });
      flushSync();

      const list =
        article.querySelector<HTMLOListElement>("ol.journal-entries");
      ok(list);
      equal(list.getAttribute("aria-busy"), "true");
      await settle();
      equal(list.getAttribute("aria-busy"), "false");
      ok(list.textContent.includes("r1 Narration 0"));
      equal(page1_calls, 1);

      const reload = article.querySelector<HTMLButtonElement>(
        "#reload-same-filters",
      );
      ok(reload);
      reload.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
      flushSync();

      equal(page1_calls, 2);
      equal(list.getAttribute("aria-busy"), "true");
      const refreshed_request = requests.filter(
        ({ url }) => url.searchParams.get("page") === "1",
      );
      equal(refreshed_request.length, 2);
      resolve_reload(page_response(1, "r2"));
      await settle();

      equal(list.getAttribute("aria-busy"), "false");
      ok(list.textContent.includes("r2 Narration 0"));
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });

  test("ResizeObserver border-box sizes preserve mobile offsets and anchor the viewport", async () => {
    const real_fetch = globalThis.fetch;
    const scroll_y_descriptor = Object.getOwnPropertyDescriptor(
      window,
      "scrollY",
    );
    const scroll_to_descriptor = Object.getOwnPropertyDescriptor(
      window,
      "scrollTo",
    );
    let scroll_y = 0;
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 375,
    });
    Object.defineProperty(window, "scrollY", {
      configurable: true,
      get: () => scroll_y,
    });
    Object.defineProperty(window, "scrollTo", {
      configurable: true,
      value: (options: ScrollToOptions) => {
        scroll_y = options.top ?? scroll_y;
      },
    });
    globalThis.fetch = async (input) => {
      const url = request_url(input);
      return Promise.resolve(
        page_response(Number(url.searchParams.get("page"))),
      );
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
      list.getBoundingClientRect = () =>
        ({ top: -scroll_y, bottom: 100_000 - scroll_y }) as DOMRect;

      const first_row = list.querySelector<HTMLLIElement>(
        'li[data-journal-index="0"]',
      );
      ok(first_row);
      const first_row_observer = journal_resize_observers().find(
        ({ targets }) => targets.has(first_row),
      );
      ok(first_row_observer);
      first_row_observer.deliver(first_row, {
        contentHeight: 52,
        blockSize: 53,
      });
      await settle();

      // On mobile, one-pixel row borders contribute to the virtual document height.
      window.scrollTo({ top: 5_201 });
      window.dispatchEvent(new window.Event("scroll"));
      await settle();
      const first_visible_row = list.querySelector<HTMLLIElement>(
        "li[data-journal-index]",
      );
      ok(first_visible_row);
      const top_spacer = list.querySelector<HTMLLIElement>(
        ".journal-virtual-spacer",
      );
      ok(top_spacer);
      equal(
        Number.parseFloat(top_spacer.style.height),
        Number(first_visible_row.dataset.journalIndex) * 52 + 1,
      );

      // A measured row above the visible row advances scrollY by its border-box
      // delta so content below it stays at the same viewport position.
      const anchored_row = list.querySelector<HTMLLIElement>(
        'li[data-journal-index="90"]',
      );
      ok(anchored_row);
      const anchored_observer = journal_resize_observers().find(({ targets }) =>
        targets.has(anchored_row),
      );
      ok(anchored_observer);
      anchored_observer.deliver(anchored_row, {
        contentHeight: 59,
        blockSize: 60,
      });
      await settle();
      equal(scroll_y, 5_209);

      // Browsers without borderBoxSize use the target's rendered border-box size.
      const fallback_row = list.querySelector<HTMLLIElement>(
        'li[data-journal-index="91"]',
      );
      ok(fallback_row);
      Object.defineProperty(fallback_row, "offsetHeight", {
        configurable: true,
        value: 61,
      });
      const fallback_observer = journal_resize_observers().find(({ targets }) =>
        targets.has(fallback_row),
      );
      ok(fallback_observer);
      fallback_observer.deliver(fallback_row, { contentHeight: 52 });
      await settle();
      equal(scroll_y, 5_218);
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
      if (scroll_y_descriptor) {
        Object.defineProperty(window, "scrollY", scroll_y_descriptor);
      } else {
        Reflect.deleteProperty(window, "scrollY");
      }
      if (scroll_to_descriptor) {
        Object.defineProperty(window, "scrollTo", scroll_to_descriptor);
      } else {
        Reflect.deleteProperty(window, "scrollTo");
      }
    }
  });

  test("a page-1 revision change clears cached pages before rendering the new revision", async () => {
    const real_fetch = globalThis.fetch;
    const requests: JournalRequest[] = [];
    let page1_calls = 0;
    let revision = "r1";
    globalThis.fetch = async (input, init) => {
      const url = request_url(input);
      requests.push({ url, signal: init?.signal ?? null });
      const page = Number(url.searchParams.get("page"));
      if (page === 1) {
        page1_calls += 1;
        if (page1_calls === 2) {
          revision = "r2";
        }
      }
      return Promise.resolve(page_response(page, revision));
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
      article.scrollTop = 0;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();

      // The first page-1 response after eviction reports r2. The component must
      // discard the cached r1 pages and load page 1 again for a consistent view.
      ok(page1_calls >= 3);
      article.scrollTop = 10_400;
      article.dispatchEvent(new window.Event("scroll"));
      await settle();

      const list =
        article.querySelector<HTMLOListElement>("ol.journal-entries");
      ok(list);
      ok(list.textContent.includes("r2 Narration 200"));
      ok(!list.textContent.includes("r1 Narration 200"));
      ok(requests.some(({ url }) => url.searchParams.get("page") === "2"));
    } finally {
      if (component) {
        await unmount(component);
      }
      globalThis.fetch = real_fetch;
    }
  });
});
