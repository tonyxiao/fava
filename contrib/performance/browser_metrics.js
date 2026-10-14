/* Paste into the browser console (or evaluate through the preview tool).
 * Start with favaBenchmark.start(), perform journal interactions, then collect
 * favaBenchmark.stop(). This observes the page without driving interactions.
 */
globalThis.favaBenchmark = (() => {
  let frame;
  let observer;
  let started;
  let previous;
  let frames;
  let tasks;
  let maxRows;
  let maxElements;

  function sample(now) {
    if (previous !== undefined) {
      frames.push(now - previous);
    }
    previous = now;
    maxRows = Math.max(
      maxRows,
      document.querySelectorAll(".journal-entries > [data-journal-index]")
        .length,
    );
    frame = requestAnimationFrame(sample);
  }

  function percentile(values, fraction) {
    const sorted = [...values].sort((a, b) => a - b);
    return sorted.length
      ? sorted[Math.ceil(sorted.length * fraction) - 1]
      : null;
  }

  function start() {
    if (frame !== undefined) {
      cancelAnimationFrame(frame);
    }
    observer?.disconnect();
    started = performance.now();
    previous = undefined;
    frames = [];
    tasks = [];
    maxRows = 0;
    maxElements = document.getElementsByTagName("*").length;
    if (PerformanceObserver.supportedEntryTypes.includes("longtask")) {
      observer = new PerformanceObserver((list) => {
        tasks.push(...list.getEntries().map((entry) => entry.duration));
      });
      observer.observe({ type: "longtask" });
    }
    frame = requestAnimationFrame(sample);
  }

  function stop() {
    if (started === undefined) {
      throw new Error("Call favaBenchmark.start() first.");
    }
    cancelAnimationFrame(frame);
    frame = undefined;
    if (observer) {
      tasks.push(...observer.takeRecords().map((entry) => entry.duration));
      observer.disconnect();
    }
    const resources = performance
      .getEntriesByType("resource")
      .filter(
        (entry) =>
          entry.startTime >= started &&
          entry.name.includes("/api/journal_page"),
      );
    return {
      url: location.href,
      userAgent: navigator.userAgent,
      viewport: { width: innerWidth, height: innerHeight },
      duration_ms: performance.now() - started,
      frame_count: frames.length,
      frame_p50_ms: percentile(frames, 0.5),
      frame_p95_ms: percentile(frames, 0.95),
      max_frame_ms: frames.length
        ? frames.reduce((maximum, value) => Math.max(maximum, value), 0)
        : null,
      long_tasks_ms: tasks,
      max_mounted_rows: maxRows,
      initial_dom_elements: maxElements,
      final_dom_elements: document.getElementsByTagName("*").length,
      heap_bytes: performance.memory?.usedJSHeapSize ?? null,
      page_requests: resources.map((entry) => ({
        page: new URL(entry.name).searchParams.get("page"),
        duration_ms: entry.duration,
        transfer_bytes: entry.transferSize,
      })),
    };
  }

  return { start, stop };
})();
