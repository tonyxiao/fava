import { equal, ok } from "node:assert/strict";
import { afterEach, beforeEach, describe, test } from "node:test";

import { flushSync, mount, unmount } from "svelte";

import { setup_jsdom } from "./dom.ts";
import { install_table_layout, settle } from "./paged-table-layout.ts";

interface Row {
  index: number;
  label: string;
}

interface PagedTablePage<T> {
  rows: T[];
  page: number;
  page_size: number;
  total_entries: number;
  total_pages: number;
  revision: string;
}

interface PagedTableRequest {
  page: number;
  per_page: number;
  sort: string;
  order: "asc" | "desc";
  signal: AbortSignal;
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

function page_response(
  page: number,
  revision = "r1",
  total_entries = 100_000,
): PagedTablePage<Row> {
  const rows = Array.from(
    { length: Math.min(200, total_entries - (page - 1) * 200) },
    (_, offset) => {
      const index = (page - 1) * 200 + offset;
      return { index, label: `${revision} row ${index.toString()}` };
    },
  );
  return {
    rows,
    page,
    page_size: 200,
    total_entries,
    total_pages: Math.ceil(total_entries / 200),
    revision,
  };
}

let restore_layout: () => void = () => undefined;

function scroll_to_page(page: number): void {
  const article = document.querySelector<HTMLElement>("article");
  ok(article);
  article.scrollTop = (page - 1) * 200 * 52;
  article.dispatchEvent(new window.Event("scroll"));
}

void describe("PagedTable", () => {
  beforeEach(() => {
    setup_jsdom();
    restore_layout = install_table_layout();
  });
  afterEach(() => {
    restore_layout();
  });

  test("keeps a bounded virtual window and prioritizes the latest requested page", async () => {
    const delayed = new Map<number, Deferred<PagedTablePage<Row>>>();
    const requests: { page: number; signal: AbortSignal }[] = [];
    let active = 0;
    let max_active = 0;
    const load = async ({ page, signal }: PagedTableRequest) => {
      requests.push({ page, signal });
      if (page === 1) {
        return Promise.resolve(page_response(1));
      }
      active += 1;
      max_active = Math.max(max_active, active);
      const request = deferred<PagedTablePage<Row>>();
      delayed.set(page, request);
      return request.promise.finally(() => {
        active -= 1;
      });
    };

    const { default: harness } = await import("./PagedTableHarness.svelte");
    const article = document.querySelector<HTMLElement>("article");
    ok(article);
    const component = mount(harness, {
      target: article,
      props: { load, queryKey: "all-rows" },
    });
    try {
      flushSync();
      await settle();
      ok(requests.some(({ page }) => page === 1));
      ok(article.querySelector("tbody tr"));

      for (const page of [2, 3, 4]) {
        scroll_to_page(page);
        await settle();
      }
      const held_pages = [...delayed.keys()];
      ok(held_pages.length > 0 && held_pages.length <= 3);
      const held_signals = requests
        .filter(({ page }) => held_pages.includes(page))
        .map(({ signal }) => signal);

      for (const page of [101, 201, 51, 301, 91, 51]) {
        scroll_to_page(page);
        await settle();
      }
      ok(held_signals.every((signal) => !signal.aborted));

      const first_held = held_pages[0];
      ok(first_held != null);
      delayed.get(first_held)?.resolve(page_response(first_held));
      await settle();

      const newly_requested = requests.filter(
        ({ page }) => !held_pages.includes(page) && page !== 1,
      );
      ok(newly_requested.some(({ page }) => page === 51));
      ok(max_active <= 3);

      delayed.get(51)?.resolve(page_response(51));
      await settle();
      equal(
        article.querySelectorAll("tbody tr[data-paged-table-index]").length <
          60,
        true,
      );
      const focused_row = article.querySelector<HTMLTableRowElement>(
        'tr[data-paged-table-index="10000"]',
      );
      ok(focused_row);
      focused_row.focus();
      scroll_to_page(101);
      await settle();
      equal(document.activeElement, focused_row);
      ok(focused_row.isConnected);
      const gap_spacer = article.querySelector<HTMLTableRowElement>(
        "tr[data-paged-table-gap]",
      );
      ok(gap_spacer);
      const gap_height = Number.parseFloat(
        gap_spacer.firstElementChild
          ?.getAttribute("style")
          ?.match(/height:\s*([\d.]+)px/)?.[1] ?? "0",
      );
      ok(gap_height > 0);
    } finally {
      await unmount(component);
      for (const [page, request] of delayed) {
        request.resolve(page_response(page));
      }
      await settle();
    }
  });

  test("aborts pending requests on unmount and ignores late results", async () => {
    const requests: { page: number; signal: AbortSignal }[] = [];
    const delayed = new Map<number, Deferred<PagedTablePage<Row>>>();
    const load = async ({ page, signal }: PagedTableRequest) => {
      requests.push({ page, signal });
      if (page === 1) {
        return Promise.resolve(page_response(1));
      }
      const request = deferred<PagedTablePage<Row>>();
      delayed.set(page, request);
      return request.promise;
    };
    const { default: harness } = await import("./PagedTableHarness.svelte");
    const article = document.querySelector<HTMLElement>("article");
    ok(article);
    const component = mount(harness, {
      target: article,
      props: { load, queryKey: "all-rows" },
    });
    flushSync();
    await settle();
    scroll_to_page(6);
    await settle();
    const pending = requests.filter(({ page }) => page > 1);
    ok(pending.length > 0);

    await unmount(component);
    ok(pending.every(({ signal }) => signal.aborted));
    for (const [page, request] of delayed) {
      request.resolve(page_response(page));
    }
    await settle();
    equal(
      article.querySelectorAll("tbody tr[data-paged-table-index]").length,
      0,
    );
  });

  test("refreshes the requested page when animation frames are throttled", async () => {
    restore_layout();
    restore_layout = install_table_layout({ animation_frame_delay_ms: 1_000 });
    const requested_pages: number[] = [];
    const load = async ({ page }: PagedTableRequest) => {
      requested_pages.push(page);
      await Promise.resolve();
      return page_response(page);
    };
    const { default: harness } = await import("./PagedTableHarness.svelte");
    const article = document.querySelector<HTMLElement>("article");
    ok(article);
    const component = mount(harness, {
      target: article,
      props: { load, queryKey: "throttled-animation-frame" },
    });
    try {
      flushSync();
      await settle();
      scroll_to_page(101);
      await new Promise((resolve) => setTimeout(resolve, 100));
      await settle();

      ok(requested_pages.includes(101));
      equal(
        article.querySelector<HTMLTableRowElement>(
          'tbody tr[data-paged-table-index="20000"]',
        ) != null,
        true,
      );
    } finally {
      await unmount(component);
      await settle();
    }
  });

  test("reload identity resets the generation and aborts its old page requests", async () => {
    const requests: { page: number; signal: AbortSignal }[] = [];
    const delayed = new Map<number, Deferred<PagedTablePage<Row>>>();
    let dataset_revision = "r1";
    const load = async ({ page, signal }: PagedTableRequest) => {
      requests.push({ page, signal });
      if (page === 1) {
        return Promise.resolve(page_response(1, dataset_revision));
      }
      const request = deferred<PagedTablePage<Row>>();
      delayed.set(page, request);
      return request.promise;
    };
    const { default: harness } = await import("./PagedTableHarness.svelte");
    const article = document.querySelector<HTMLElement>("article");
    ok(article);
    const component = mount(harness, {
      target: article,
      props: { load, queryKey: "same-query" },
    });
    try {
      flushSync();
      await settle();
      scroll_to_page(2);
      await settle();
      const old_page_request = requests.find(({ page }) => page === 2);
      ok(old_page_request);

      dataset_revision = "r2";
      const reload_button =
        article.querySelector<HTMLButtonElement>("[data-reload]");
      ok(reload_button);
      reload_button.click();
      await settle();

      ok(old_page_request.signal.aborted);
      equal(requests.filter(({ page }) => page === 1).length, 2);
      scroll_to_page(1);
      await settle();
      ok(article.textContent.includes("r2 row 0"));
      delayed.get(2)?.resolve(page_response(2, "r1"));
      await settle();
      ok(article.textContent.includes("r2 row 0"));
    } finally {
      await unmount(component);
      for (const [page, request] of delayed) {
        request.resolve(page_response(page));
      }
      await settle();
    }
  });

  test("preserves a user-selected sort when the query changes", async () => {
    const requests: { page: number; sort: string; order: "asc" | "desc" }[] =
      [];
    const load = async ({ page, sort, order }: PagedTableRequest) => {
      requests.push({ page, sort, order });
      await Promise.resolve();
      return page_response(page);
    };
    const { default: harness } = await import("./PagedTableHarness.svelte");
    const article = document.querySelector<HTMLElement>("article");
    ok(article);
    const component = mount(harness, {
      target: article,
      props: { load, queryKey: "sort-persistence" },
    });
    try {
      flushSync();
      await settle();
      const sort_button =
        article.querySelectorAll<HTMLButtonElement>("thead button")[1];
      const change_query_button = article.querySelector<HTMLButtonElement>(
        "[data-change-query]",
      );
      ok(sort_button);
      ok(change_query_button);
      sort_button.click();
      await settle();
      scroll_to_page(101);
      await settle();
      change_query_button.click();
      await settle();
      equal(article.scrollTop, 0);
      equal(
        article.querySelector<HTMLTableRowElement>(
          "tbody tr[data-paged-table-index]",
        )?.dataset.pagedTableIndex,
        "0",
      );

      const latest_request = requests.at(-1);
      ok(latest_request);
      equal(latest_request.sort, "label");
      equal(latest_request.order, "asc");
    } finally {
      await unmount(component);
      await settle();
    }
  });

  test("retries a transient page failure and keeps loading feedback visible", async () => {
    let attempts = 0;
    const load = async ({ page }: PagedTableRequest) => {
      attempts += 1;
      return attempts === 1
        ? Promise.reject(new TypeError("temporary network failure"))
        : Promise.resolve(page_response(page));
    };
    const { default: harness } = await import("./PagedTableHarness.svelte");
    const article = document.querySelector<HTMLElement>("article");
    ok(article);
    const component = mount(harness, {
      target: article,
      props: { load, queryKey: "retry" },
    });
    try {
      flushSync();
      await settle();
      const status = article.querySelector('[role="status"]');
      ok(status?.textContent.includes("Loading") === true);
      await new Promise((resolve) => setTimeout(resolve, 500));
      await settle();
      equal(attempts, 2);
      ok(article.textContent.includes("r1 row 0"));
    } finally {
      await unmount(component);
      await settle();
    }
  });

  test("pins mobile feedback to the window scroller and reserves its space", async () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 390,
    });
    const pending_page = deferred<PagedTablePage<Row>>();
    const load = async () => pending_page.promise;
    const { default: harness } = await import("./PagedTableHarness.svelte");
    const article = document.querySelector<HTMLElement>("article");
    ok(article);
    const component = mount(harness, {
      target: article,
      props: { load, queryKey: "mobile" },
    });
    try {
      flushSync();
      await settle();
      const status = article.querySelector<HTMLElement>(".paged-table-status");
      const status_space = article.querySelector<HTMLElement>(
        ".paged-table-status-space",
      );
      ok(status);
      ok(status_space);
      ok(status.classList.contains("window-scrolling"));
      ok(status_space.classList.contains("visible"));

      pending_page.resolve(page_response(1));
      await settle();
      equal(status_space.classList.contains("visible"), true);
    } finally {
      await unmount(component);
      await settle();
    }
  });
});
