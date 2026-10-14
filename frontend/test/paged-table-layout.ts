import { ok } from "node:assert/strict";

import { flushSync, tick } from "svelte";

export function install_table_layout(options?: {
  animation_frame_delay_ms?: number;
}): () => void {
  const article = document.querySelector<HTMLElement>("article");
  ok(article);
  const saved = [
    [window, "innerWidth"],
    [window, "innerHeight"],
    [window, "scrollY"],
    [window, "scrollTo"],
    [window.HTMLElement.prototype, "offsetHeight"],
    [window.HTMLElement.prototype, "offsetWidth"],
    [window.HTMLElement.prototype, "clientHeight"],
    [window.HTMLElement.prototype, "clientWidth"],
    [window.HTMLElement.prototype, "getBoundingClientRect"],
    [window.HTMLElement.prototype, "scrollTo"],
    [window, "requestAnimationFrame"],
    [window, "cancelAnimationFrame"],
    [globalThis, "requestAnimationFrame"],
    [globalThis, "cancelAnimationFrame"],
    [window, "ResizeObserver"],
    [globalThis, "ResizeObserver"],
  ] as const;
  const descriptors = saved.map(
    ([target, key]) =>
      [target, key, Object.getOwnPropertyDescriptor(target, key)] as const,
  );
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 1280,
  });
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    value: 600,
  });
  let window_scroll_y = 0;
  Object.defineProperty(window, "scrollY", {
    configurable: true,
    get: () => window_scroll_y,
  });
  Object.defineProperty(window, "scrollTo", {
    configurable: true,
    value: (options: ScrollToOptions | number, y?: number) => {
      window_scroll_y =
        typeof options === "number"
          ? (y ?? 0)
          : (options.top ?? window_scroll_y);
      window.dispatchEvent(new window.Event("scroll"));
    },
  });
  let next_frame_id = 1;
  const frame_timers = new Map<number, ReturnType<typeof setTimeout>>();
  const request_frame = (callback: FrameRequestCallback): number => {
    const id = next_frame_id++;
    frame_timers.set(
      id,
      setTimeout(() => {
        frame_timers.delete(id);
        callback(performance.now());
      }, options?.animation_frame_delay_ms ?? 0),
    );
    return id;
  };
  const cancel_frame = (id: number): void => {
    const timer = frame_timers.get(id);
    if (timer != null) {
      clearTimeout(timer);
      frame_timers.delete(id);
    }
  };
  Object.defineProperty(window, "requestAnimationFrame", {
    configurable: true,
    value: request_frame,
  });
  Object.defineProperty(window, "cancelAnimationFrame", {
    configurable: true,
    value: cancel_frame,
  });
  Object.defineProperty(globalThis, "requestAnimationFrame", {
    configurable: true,
    writable: true,
    value: request_frame,
  });
  Object.defineProperty(globalThis, "cancelAnimationFrame", {
    configurable: true,
    writable: true,
    value: cancel_frame,
  });
  Object.defineProperties(article, {
    clientHeight: { configurable: true, value: 600 },
    clientWidth: { configurable: true, value: 1200 },
    clientTop: { configurable: true, value: 0 },
    clientLeft: { configurable: true, value: 0 },
    scrollHeight: { configurable: true, get: () => 5_200_000 },
    getBoundingClientRect: {
      configurable: true,
      value: () => new window.DOMRect(0, 0, 1200, 600),
    },
    scrollTo: {
      configurable: true,
      value: (options: ScrollToOptions) => {
        article.scrollTop = options.top ?? article.scrollTop;
        article.dispatchEvent(new window.Event("scroll"));
      },
    },
  });
  Object.defineProperties(window.HTMLElement.prototype, {
    clientHeight: {
      configurable: true,
      get(this: HTMLElement) {
        return this.matches("[data-report-scroll]") ? 600 : 0;
      },
    },
    clientWidth: {
      configurable: true,
      get(this: HTMLElement) {
        return this.matches("[data-report-scroll]") ? 1200 : 0;
      },
    },
    scrollTo: {
      configurable: true,
      value(this: HTMLElement, options: ScrollToOptions) {
        if (this.matches("[data-report-scroll]")) {
          this.scrollTop = options.top ?? this.scrollTop;
          this.dispatchEvent(new window.Event("scroll"));
        }
      },
    },
  });
  Object.defineProperty(window.HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get(this: HTMLElement) {
      if (this instanceof window.HTMLTableRowElement) {
        return this.classList.contains("paged-table-spacer")
          ? Number.parseFloat(
              this.firstElementChild
                ?.getAttribute("style")
                ?.match(/height:([\d.]+)px/)?.[1] ?? "0",
            )
          : 36;
      }
      return this.matches("[data-report-scroll]") || this === article ? 600 : 0;
    },
  });
  Object.defineProperty(window.HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get(this: HTMLElement) {
      return this.matches("[data-report-scroll]") || this === article
        ? 1200
        : 0;
    },
  });
  Object.defineProperty(window.HTMLElement.prototype, "getBoundingClientRect", {
    configurable: true,
    writable: true,
    value(this: HTMLElement): DOMRect {
      if (this === article) {
        return new window.DOMRect(0, 0, 1200, 600);
      }
      if (this.matches("[data-report-scroll]")) {
        return new window.DOMRect(0, 0, 1200, 600);
      }
      if (this instanceof window.HTMLTableElement) {
        const scroller =
          this.closest<HTMLElement>("[data-report-scroll]") ?? article;
        return new window.DOMRect(0, -scroller.scrollTop, 1200, 5_200_000);
      }
      if (this instanceof window.HTMLTableSectionElement) {
        const scroller =
          this.closest<HTMLElement>("[data-report-scroll]") ?? article;
        return new window.DOMRect(0, 32 - scroller.scrollTop, 1200, 5_200_000);
      }
      if (this instanceof window.HTMLTableRowElement) {
        return new window.DOMRect(0, 0, 1200, this.offsetHeight);
      }
      return new window.DOMRect(0, 0, 1200, 0);
    },
  });

  class TestResizeObserver implements ResizeObserver {
    private targets = new Set<Element>();
    private callback: ResizeObserverCallback;
    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
    }
    observe(target: Element): void {
      this.targets.add(target);
      const target_height =
        target === article ||
        (target instanceof HTMLElement &&
          target.matches("[data-report-scroll]"))
          ? 600
          : 36;
      queueMicrotask(() => {
        if (!this.targets.has(target)) {
          return;
        }
        this.callback(
          [
            {
              target,
              contentRect: {
                width: 1200,
                height: target_height,
                x: 0,
                y: 0,
                top: 0,
                right: 1200,
                bottom: target_height,
                left: 0,
                toJSON: () => ({}),
              },
              borderBoxSize: [{ inlineSize: 1200, blockSize: target_height }],
              contentBoxSize: [{ inlineSize: 1200, blockSize: target_height }],
              devicePixelContentBoxSize: [],
            },
          ],
          this,
        );
      });
    }
    unobserve(target: Element): void {
      this.targets.delete(target);
    }
    disconnect(): void {
      this.targets.clear();
    }
  }
  Object.defineProperty(globalThis, "ResizeObserver", {
    configurable: true,
    writable: true,
    value: TestResizeObserver,
  });
  Object.defineProperty(window, "ResizeObserver", {
    configurable: true,
    writable: true,
    value: TestResizeObserver,
  });

  return () => {
    for (const timer of frame_timers.values()) {
      clearTimeout(timer);
    }
    frame_timers.clear();
    for (const [target, key, descriptor] of descriptors) {
      if (descriptor) {
        Object.defineProperty(target, key, descriptor);
      } else {
        Reflect.deleteProperty(target, key);
      }
    }
  };
}

export async function settle(): Promise<void> {
  await tick();
  await new Promise((resolve) => setTimeout(resolve, 25));
  await tick();
  flushSync();
}
