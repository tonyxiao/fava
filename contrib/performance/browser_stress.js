/* Development-only stress test for a loaded 100k journal.
 * Paste/evaluate this file, then await favaScrollStress().
 * Moves the scrollbar 20 times at 40ms intervals, delays journal fetches by
 * 400ms, and returns HTTP 503 on each page's first completed attempt.
 * Restores fetch afterward. Run on a fresh page; do not interact during the run.
 * A successful run recovers >95% viewport coverage without a manual retry.
 */
globalThis.favaScrollStress = async () => {
  const originalFetch = window.fetch;
  const requests = [];
  let active = 0;
  let maximum = 0;
  const failedPages = new Set();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  window.fetch = async (input, init) => {
    const url = new URL(String(input), location.href);
    if (!url.pathname.endsWith("/api/journal_page")) {
      return originalFetch(input, init);
    }
    const record = {
      page: Number(url.searchParams.get("page")),
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
        }, 400);
        if (init?.signal?.aborted) {
          abort();
        } else {
          init?.signal?.addEventListener("abort", abort, { once: true });
        }
      });
      if (!failedPages.has(record.page)) {
        failedPages.add(record.page);
        record.status = 503;
        return new Response(
          JSON.stringify({ detail: "Injected transient failure" }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        );
      }
      const response = await originalFetch(input, init);
      record.status = response.status;
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
    const article = document.querySelector("article");
    const scroller = innerWidth > 767 ? article : document.scrollingElement;
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
    let settled = null;
    let coverage = 0;
    while (performance.now() - stopped < 6500) {
      const visible = [
        ...document.querySelectorAll("[data-journal-index]"),
      ].filter((row) => {
        const rect = row.getBoundingClientRect();
        return rect.bottom > 52 && rect.top < innerHeight;
      });
      const listRect = document
        .querySelector(".journal-entries")
        .getBoundingClientRect();
      const top = Math.max(52, listRect.top);
      const bottom = Math.min(innerHeight, listRect.bottom);
      coverage =
        bottom > top
          ? visible.reduce((sum, row) => {
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
      if (
        coverage > 0.95 &&
        document.querySelector(".journal-entries").getAttribute("aria-busy") ===
          "false"
      ) {
        settled = performance.now() - stopped;
        break;
      }
      await sleep(40);
    }
    return {
      delay_ms: 400,
      scroll_steps: 20,
      step_interval_ms: 40,
      recovery_ms: settled,
      viewport_coverage: coverage,
      max_inflight: maximum,
      request_count: requests.length,
      aborts: requests.filter((r) => r.error).length,
      requests,
      retry_buttons: [...document.querySelectorAll("button")].filter((b) =>
        b.textContent.includes("Retry"),
      ).length,
      mounted_rows: document.querySelectorAll("[data-journal-index]").length,
    };
  } finally {
    window.fetch = originalFetch;
  }
};
