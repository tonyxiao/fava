import { deepEqual, equal, ok } from "node:assert/strict";
import { before, beforeEach, describe, test } from "node:test";

import { flushSync, mount, tick, unmount } from "svelte";

import { Document } from "../src/entries/index.ts";
import { array, unknown } from "../src/lib/validation.ts";
import { setup_jsdom } from "./dom.ts";
import { initialise_ledger_data, load_json_snapshot } from "./helpers.ts";
import { install_table_layout, settle } from "./paged-table-layout.ts";

function request_url(input: RequestInfo | URL): URL {
  if (input instanceof URL) {
    return new URL(input.href);
  }
  if (typeof input === "string") {
    return new URL(input, window.location.href);
  }
  return new URL(input.url, window.location.href);
}

void describe("bounded report API pages", () => {
  before(async () => {
    await initialise_ledger_data();
  });
  beforeEach(setup_jsdom);

  test("validate page metadata and preserve filters", async (t) => {
    const { get_commodity_report, get_documents_page, get_events_page } =
      await import("../src/api/index.ts");
    const [document_snapshot, event_snapshot] = await Promise.all([
      load_json_snapshot("test_json_api-test_api-documents.json"),
      load_json_snapshot("test_json_api-test_api-events.json"),
    ]);
    const document = array(unknown)(document_snapshot).unwrap()[0];
    const event = array(unknown)(event_snapshot).unwrap()[0];
    if (document === undefined || event === undefined) {
      throw new Error("Expected document and event fixture rows.");
    }

    const document_response = {
      documents: [document],
      page: 2,
      page_size: 1,
      total_entries: 120_000,
      total_pages: 120_000,
      revision: "docs-revision",
      accounts: null,
    };
    const events_response = {
      events: [event],
      page: 1,
      page_size: 200,
      total_entries: 25,
      total_pages: 1,
      revision: "events-revision",
      types: [{ type: "Customer", count: 25 }],
      chart_events: [event],
      chart_events_sampled: true,
      chart_total_events: 2_500,
      total_events: 25,
    };
    const commodity_response = {
      pairs: [{ base: "USD", quote: "EUR", count: 2_500 }],
      base: "USD",
      quote: "EUR",
      prices: [["2026-10-01", "0.92"]],
      chart_prices: [["2026-10-01", "0.92"]],
      chart_prices_sampled: true,
      chart_total_prices: 5_000,
      page: 1,
      page_size: 200,
      total_entries: 2_500,
      total_pages: 13,
      revision: "commodity-revision",
    };
    const requests: URL[] = [];

    t.mock.method(globalThis, "fetch", async (input: RequestInfo | URL) => {
      const url = request_url(input);
      requests.push(url);
      const data = url.pathname.endsWith("/documents_page")
        ? document_response
        : url.pathname.endsWith("/events_page")
          ? url.searchParams.get("page") === "2"
            ? {
                ...events_response,
                page: 2,
                types: null,
                chart_events: null,
                chart_events_sampled: null,
                chart_total_events: null,
                total_events: null,
              }
            : events_response
          : commodity_response;
      await Promise.resolve();
      return new Response(JSON.stringify({ data }), { status: 200 });
    });

    const controller = new AbortController();
    const filters = { account: "Assets", filter: "tag:receipt", time: "2026" };
    const [documents, events, later_events, commodity] = await Promise.all([
      get_documents_page({
        ...filters,
        a: "Assets:Receivable",
        page: 2,
        per_page: 1,
        sort: "name",
        order: "asc",
        include_overview: false,
        signal: controller.signal,
      }),
      get_events_page({
        ...filters,
        event_type: "Customer",
        page: 1,
        per_page: 200,
        sort: "type",
        order: "desc",
        include_overview: true,
        signal: controller.signal,
      }),
      get_events_page({
        ...filters,
        event_type: "Customer",
        page: 2,
        per_page: 200,
        sort: "type",
        order: "desc",
        include_overview: false,
        signal: controller.signal,
      }),
      get_commodity_report({
        ...filters,
        base: "USD",
        quote: "EUR",
        page: 1,
        per_page: 200,
        sort: "price",
        order: "asc",
        include_overview: true,
        signal: controller.signal,
      }),
    ]);

    equal(documents.total_entries, 120_000);
    equal(documents.documents.length, 1);
    equal(documents.accounts, null);
    equal(events.total_events, 25);
    equal(events.chart_total_events, 2_500);
    equal(events.chart_events_sampled, true);
    ok(events.chart_events);
    equal(events.chart_events.length, 1);
    equal(events.events.length, 1);
    equal(later_events.events.length, 1);
    equal(later_events.types, null);
    equal(later_events.chart_events, null);
    equal(commodity.total_entries, 2_500);
    equal(commodity.chart_total_prices, 5_000);
    equal(commodity.chart_prices_sampled, true);
    const first_price = commodity.prices[0];
    ok(first_price);
    equal(first_price[0].toISOString().slice(0, 10), "2026-10-01");
    equal(first_price[1], 0.92);

    const by_endpoint = new Map(requests.map((url) => [url.pathname, url]));
    const document_url = [...by_endpoint].find(([path]) =>
      path.endsWith("/documents_page"),
    )?.[1];
    const events_url = requests.find(
      (url) =>
        url.pathname.endsWith("/events_page") &&
        url.searchParams.get("page") === "1",
    );
    const commodity_url = [...by_endpoint].find(([path]) =>
      path.endsWith("/commodity_report"),
    )?.[1];
    ok(document_url && events_url && commodity_url);
    deepEqual(Object.fromEntries(document_url.searchParams), {
      account: "Assets",
      filter: "tag:receipt",
      time: "2026",
      a: "Assets:Receivable",
      page: "2",
      per_page: "1",
      sort: "name",
      order: "asc",
      include_overview: "false",
    });
    equal(events_url.searchParams.get("include_overview"), "true");
    equal(events_url.searchParams.get("event_type"), "Customer");
    equal(events_url.searchParams.get("per_page"), "200");
    equal(commodity_url.searchParams.get("base"), "USD");
    equal(commodity_url.searchParams.get("quote"), "EUR");
    equal(commodity_url.searchParams.get("sort"), "price");
    for (const url of requests) {
      equal(url.searchParams.has("signal"), false);
      equal(url.searchParams.has("conversion"), false);
    }
  });

  test("documents route loads a bounded page and opens the selected preview", async (t) => {
    const { default: documents_component } = await import(
      "../src/reports/documents/Documents.svelte"
    );
    const document_snapshot = await load_json_snapshot(
      "test_json_api-test_api-documents.json",
    );
    const raw_document = array(unknown)(document_snapshot).unwrap()[0];
    if (raw_document === undefined) {
      throw new Error("Expected a document fixture row.");
    }
    const parsed_document = Document.validator(raw_document).unwrap();
    const document_row = {
      t: "Document",
      meta: {
        filename: parsed_document.meta.filename,
        lineno: Number(parsed_document.meta.lineno),
      },
      date: parsed_document.date,
      entry_hash: parsed_document.entry_hash,
      account: parsed_document.account,
      filename: "receipts/sample.pdf",
      tags: parsed_document.tags,
      links: parsed_document.links,
    };

    const requests: URL[] = [];
    t.mock.method(globalThis, "fetch", async (input: RequestInfo | URL) => {
      const url = request_url(input);
      requests.push(url);
      await Promise.resolve();
      return new Response(
        JSON.stringify({
          data: {
            documents: [document_row],
            page: 1,
            page_size: 200,
            total_entries: 100_001,
            total_pages: 501,
            revision: "documents-ui-revision",
            accounts: [{ account: "Assets:Receivable", count: 4 }],
          },
        }),
        { status: 200 },
      );
    });

    const restore_layout = install_table_layout();
    let component: ReturnType<typeof mount> | undefined;
    try {
      component = mount(documents_component, {
        target: document.body,
        props: {
          filters: {
            account: "",
            conversion: "",
            filter: "",
            interval: "",
            time: "",
          },
        },
      });
      await settle();

      const docs_request = requests.find((url) =>
        url.pathname.endsWith("/documents_page"),
      );
      ok(docs_request);
      equal(docs_request.searchParams.get("per_page"), "200");
      equal(docs_request.searchParams.get("page"), "1");
      equal(docs_request.searchParams.get("include_overview"), "true");
      const count = document.querySelector(".accounts-pane .count");
      ok(count);
      equal(count.textContent.trim(), "4");

      const row = document.querySelector<HTMLTableRowElement>(
        '[aria-label="Documents"] tbody tr[data-row-key]',
      );
      ok(row);
      row.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      flushSync();
      await tick();

      const filename = row.title;
      if (filename === "") {
        throw new Error("Expected selected document filename.");
      }
      const preview = document.querySelector<HTMLElement>(".preview-pane");
      ok(preview);
      const preview_object = preview.querySelector("object");
      ok(preview_object);
      equal(preview_object.getAttribute("title"), filename);
    } finally {
      if (component) {
        await unmount(component);
      }
      restore_layout();
    }
  });
});
