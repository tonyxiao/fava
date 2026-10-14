export interface ResizeEntryOverrides {
  blockSize?: number;
  contentHeight?: number;
}

export interface JournalResizeObserver {
  readonly targets: Set<Element>;
  deliver(target: Element, overrides?: ResizeEntryOverrides): void;
}

const resize_observers: JournalResizeObserver[] = [];

export function journal_resize_observers(): JournalResizeObserver[] {
  return [...resize_observers];
}

/** Install deterministic JSDOM geometry while keeping TanStack's real adapter. */
export function install_journal_layout(
  width = 1280,
  row_height: number | ((row: HTMLElement) => number) = 52,
): () => void {
  const saved = [
    [window, "innerWidth"],
    [window, "innerHeight"],
    [window, "scrollY"],
    [window, "scrollTo"],
    [window, "scrollBy"],
    [window, "requestAnimationFrame"],
    [window, "cancelAnimationFrame"],
    [globalThis, "requestAnimationFrame"],
    [globalThis, "cancelAnimationFrame"],
    [window, "ResizeObserver"],
    [globalThis, "ResizeObserver"],
    [window.HTMLElement.prototype, "offsetHeight"],
    [window.HTMLElement.prototype, "offsetWidth"],
    [window.HTMLElement.prototype, "getBoundingClientRect"],
  ] as const;
  const descriptors = saved.map(
    ([target, key]) =>
      [target, key, Object.getOwnPropertyDescriptor(target, key)] as const,
  );

  resize_observers.length = 0;
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: width,
  });
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    value: 600,
  });
  let scroll_y = 0;
  Object.defineProperty(window, "scrollY", {
    configurable: true,
    get: () => scroll_y,
  });
  Object.defineProperty(window, "scrollTo", {
    configurable: true,
    value: (options: ScrollToOptions | number, y?: number) => {
      scroll_y =
        typeof options === "number" ? (y ?? 0) : (options.top ?? scroll_y);
    },
  });
  Object.defineProperty(window, "scrollBy", {
    configurable: true,
    value: (_x: number, delta_y: number) => {
      scroll_y += delta_y;
    },
  });
  Object.defineProperty(window.HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return this instanceof HTMLLIElement
        ? typeof row_height === "function"
          ? row_height(this)
          : row_height
        : 0;
    },
  });
  Object.defineProperty(window.HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get(this: HTMLElement) {
      return this instanceof HTMLLIElement ? 1200 : 0;
    },
  });

  let next_animation_id = 1;
  const animation_timers = new Map<number, number>();
  const observer_timers = new Set<number>();
  let scroll_timer: number | undefined;
  Object.defineProperty(window, "requestAnimationFrame", {
    configurable: true,
    value: (callback: FrameRequestCallback) => {
      const id = next_animation_id++;
      animation_timers.set(
        id,
        window.setTimeout(() => {
          animation_timers.delete(id);
          callback(performance.now());
        }, 0),
      );
      return id;
    },
  });
  Object.defineProperty(window, "cancelAnimationFrame", {
    configurable: true,
    value: (id: number) => {
      const timer = animation_timers.get(id);
      if (timer != null) {
        window.clearTimeout(timer);
        animation_timers.delete(id);
      }
    },
  });
  Object.defineProperty(globalThis, "requestAnimationFrame", {
    configurable: true,
    writable: true,
    value: window.requestAnimationFrame.bind(window),
  });
  Object.defineProperty(globalThis, "cancelAnimationFrame", {
    configurable: true,
    writable: true,
    value: window.cancelAnimationFrame.bind(window),
  });

  class LayoutResizeObserver implements ResizeObserver {
    readonly targets = new Set<Element>();
    private readonly callback: ResizeObserverCallback;
    private readonly initial_notifications = new Map<Element, number>();

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
      resize_observers.push(this);
    }

    observe(target: Element): void {
      this.targets.add(target);
      const timer = window.setTimeout(() => {
        observer_timers.delete(timer);
        this.initial_notifications.delete(target);
        if (this.targets.has(target) && target.isConnected) {
          this.deliver(target);
        }
      }, 0);
      observer_timers.add(timer);
      this.initial_notifications.set(target, timer);
    }

    unobserve(target: Element): void {
      this.targets.delete(target);
    }

    disconnect(): void {
      this.targets.clear();
    }

    deliver(target: Element, overrides: ResizeEntryOverrides = {}): void {
      const initial = this.initial_notifications.get(target);
      if (initial != null) {
        window.clearTimeout(initial);
        observer_timers.delete(initial);
        this.initial_notifications.delete(target);
      }
      const entry = {
        target,
        contentRect: {
          height:
            overrides.contentHeight ??
            (target instanceof HTMLElement ? target.offsetHeight : 600),
          width: target instanceof HTMLElement ? target.offsetWidth : 1200,
        },
        borderBoxSize:
          overrides.blockSize == null
            ? []
            : [{ blockSize: overrides.blockSize, inlineSize: 1200 }],
      } as unknown as ResizeObserverEntry;
      this.callback([entry], this);
    }
  }

  Object.defineProperty(globalThis, "ResizeObserver", {
    configurable: true,
    writable: true,
    value: LayoutResizeObserver,
  });
  Object.defineProperty(window, "ResizeObserver", {
    configurable: true,
    writable: true,
    value: LayoutResizeObserver,
  });

  const article = document.querySelector<HTMLElement>("article");
  if (article) {
    const row_size = (element: Element): number => {
      if (element instanceof HTMLElement && element.style.height) {
        return Number.parseFloat(element.style.height);
      }
      return element instanceof HTMLElement ? element.offsetHeight : 0;
    };
    const list_size = () =>
      [...(article.querySelector(".journal-entries")?.children ?? [])].reduce(
        (height, row) => height + row_size(row),
        0,
      );
    Object.defineProperties(article, {
      clientHeight: { configurable: true, value: 600 },
      offsetHeight: { configurable: true, value: 600 },
      clientWidth: { configurable: true, value: 1200 },
      offsetWidth: { configurable: true, value: 1200 },
      scrollHeight: { configurable: true, get: list_size },
      scrollTo: {
        configurable: true,
        value: (options: ScrollToOptions) => {
          const offset = Math.max(
            0,
            Math.min(options.top ?? article.scrollTop, list_size() - 600),
          );
          if (offset !== article.scrollTop) {
            article.scrollTop = offset;
            if (scroll_timer != null) {
              window.clearTimeout(scroll_timer);
            }
            scroll_timer = window.setTimeout(() => {
              scroll_timer = undefined;
              article.dispatchEvent(new window.Event("scroll"));
            }, 0);
          }
        },
      },
    });
    const original_rect = (element: HTMLElement) =>
      window.Element.prototype.getBoundingClientRect.call(element);
    Object.defineProperty(
      window.HTMLElement.prototype,
      "getBoundingClientRect",
      {
        configurable: true,
        writable: true,
        value(this: HTMLElement): DOMRect {
          if (this === article) {
            return new window.DOMRect(0, 0, 1200, 600);
          }
          const list = article.querySelector(".journal-entries");
          if (this === list) {
            return new window.DOMRect(0, -article.scrollTop, 1200, list_size());
          }
          if (list != null && this.parentElement === list) {
            let top = -article.scrollTop;
            for (const row of list.children) {
              if (row === this) {
                break;
              }
              top += row_size(row);
            }
            return new window.DOMRect(0, top, 1200, row_size(this));
          }
          return original_rect(this);
        },
      },
    );
  }

  return () => {
    if (scroll_timer != null) {
      window.clearTimeout(scroll_timer);
    }
    for (const timer of observer_timers) {
      window.clearTimeout(timer);
    }
    for (const timer of animation_timers.values()) {
      window.clearTimeout(timer);
    }
    resize_observers.length = 0;
    for (const [target, key, descriptor] of descriptors) {
      if (descriptor) {
        Object.defineProperty(target, key, descriptor);
      } else {
        Reflect.deleteProperty(target, key);
      }
    }
  };
}
