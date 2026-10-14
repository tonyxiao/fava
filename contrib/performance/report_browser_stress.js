/* Evaluate on Documents, Events, or a dense commodity-price report, then
 * await favaReportScrollStress(). Fault injection is temporary and fetch is
 * restored afterward. Do not interact with the page during the run.
 */
globalThis.favaReportScrollStress = async ({
  delayMs = 400,
  failOnce = true,
} = {}) => {
  const originalFetch = window.fetch;
  const requests = [];
  const failedPages = new Set();
  let active = 0;
  let maximum = 0;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const table = document.querySelector("table[aria-label]");
  if (!table) {
    throw new Error("Open a paged report first.");
  }
  const explicit = table.closest("[data-report-scroll]");
  const scroller =
    explicit ??
    (innerWidth > 767 ? table.closest("article") : document.scrollingElement);
  window.fetch = async (input, init) => {
    const url = new URL(
      input instanceof Request ? input.url : String(input),
      location.href,
    );
    if (
      !/\/api\/(documents_page|events_page|commodity_report)$/.test(
        url.pathname,
      )
    ) {
      return originalFetch(input, init);
    }
    const record = {
      page: Number(url.searchParams.get("page")),
      overview: url.searchParams.get("include_overview"),
      start: performance.now(),
    };
    requests.push(record);
    maximum = Math.max(maximum, ++active);
    try {
      await new Promise((resolve, reject) => {
        const abort = () => {
          clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        };
        const timer = setTimeout(() => {
          init?.signal?.removeEventListener("abort", abort);
          resolve();
        }, delayMs);
        if (init?.signal?.aborted) {
          abort();
        } else {
          init?.signal?.addEventListener("abort", abort, { once: true });
        }
      });
      if (failOnce && !failedPages.has(record.page)) {
        failedPages.add(record.page);
        record.status = 503;
        return new Response(
          JSON.stringify({ detail: "Injected transient failure" }),
          {
            status: 503,
            headers: { "Content-Type": "application/json" },
          },
        );
      }
      const response = await originalFetch(input, init);
      record.status = response.status;
      record.bytes = (await response.clone().arrayBuffer()).byteLength;
      return response;
    } catch (error) {
      record.error = String(error);
      throw error;
    } finally {
      record.ms = performance.now() - record.start;
      active--;
    }
  };
  try {
    const fractions = [
      0.08, 0.6, 0.15, 0.8, 0.24, 0.5, 0.35, 0.7, 0.1, 0.9, 0.4, 0.65, 0.2,
      0.55, 0.3, 0.75, 0.45, 0.85, 0.12, 0.62,
    ];
    for (const fraction of fractions) {
      scroller.scrollTop =
        (scroller.scrollHeight - scroller.clientHeight) * fraction;
      await sleep(40);
    }
    const stopped = performance.now();
    let recovery = null;
    let coverage = 0;
    while (performance.now() - stopped < 6500) {
      const bounds =
        explicit?.getBoundingClientRect() ??
        (innerWidth > 767
          ? scroller.getBoundingClientRect()
          : { top: 0, bottom: innerHeight });
      const body = table.tBodies[0].getBoundingClientRect();
      const top = Math.max(bounds.top, body.top);
      const bottom = Math.min(bounds.bottom, body.bottom);
      const rows = [...table.querySelectorAll("tr[data-paged-table-index]")];
      coverage =
        bottom > top
          ? rows.reduce((sum, row) => {
              const rect = row.getBoundingClientRect();
              return (
                sum +
                Math.max(
                  0,
                  Math.min(bottom, rect.bottom) - Math.max(top, rect.top),
                )
              );
            }, 0) /
            (bottom - top)
          : 0;
      if (coverage > 0.95 && table.getAttribute("aria-busy") === "false") {
        recovery = performance.now() - stopped;
        break;
      }
      await sleep(40);
    }
    return {
      report: table.getAttribute("aria-label"),
      delay_ms: delayMs,
      injected_failures: failOnce,
      scroll_steps: 20,
      step_interval_ms: 40,
      recovery_ms: recovery,
      viewport_coverage: coverage,
      max_inflight: maximum,
      request_count: requests.length,
      aborts: requests.filter((request) => request.error).length,
      retry_buttons: document.querySelectorAll(".paged-table-status button")
        .length,
      mounted_rows: table.querySelectorAll("tr[data-paged-table-index]").length,
      dom_elements: document.getElementsByTagName("*").length,
      requests,
    };
  } finally {
    window.fetch = originalFetch;
  }
};
