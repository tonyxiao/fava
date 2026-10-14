<script lang="ts" generics="T extends object">
  /* eslint-disable @typescript-eslint/naming-convention -- Public Svelte props and TanStack options use camelCase. */
  import {
    createVirtualizer,
    createWindowVirtualizer,
    defaultRangeExtractor,
    type SvelteVirtualizer,
    type VirtualItem,
  } from "@tanstack/svelte-virtual";
  import { onMount, type Snippet, untrack } from "svelte";

  import { _, format } from "../i18n.ts";

  export interface PagedTableColumn {
    key: string;
    label: string;
    className?: string;
  }

  export interface PagedTablePage<T> {
    rows: T[];
    page: number;
    page_size: number;
    total_entries: number;
    total_pages: number;
    revision: string;
  }

  export interface PagedTableRequest {
    page: number;
    per_page: number;
    sort: string;
    order: "asc" | "desc";
    signal: AbortSignal;
  }

  interface Props<T> {
    columns: PagedTableColumn[];
    row: Snippet<[T]>;
    load: (request: PagedTableRequest) => Promise<PagedTablePage<T>>;
    queryKey: unknown;
    reloadKey?: unknown;
    initialSort: string;
    initialOrder?: "asc" | "desc";
    rowKey?: (row: T, globalIndex: number) => string | number;
    onRowClick?: (row: T, event: MouseEvent) => void;
    rowClass?: (row: T) => string;
    rowTitle?: (row: T) => string;
    onRowDragStart?: (row: T, event: DragEvent) => void;
    ariaLabel?: string;
  }

  let {
    columns,
    row,
    load,
    queryKey,
    reloadKey,
    initialSort,
    initialOrder = "desc",
    rowKey,
    onRowClick,
    rowClass,
    rowTitle,
    onRowDragStart,
    ariaLabel = _("Report data"),
  }: Props<T> = $props();

  const page_size = 200;
  const max_concurrent_pages = 3;
  const max_cached_pages = 9;
  const estimated_row_height = 52;
  const max_automatic_retries = 2;
  const request_timeout_ms = 10_000;
  const retry_delay_ms = 400;
  const mobile_breakpoint = 767;

  let table: HTMLTableElement | undefined = $state();
  let body: HTMLTableSectionElement | undefined = $state();
  let active_sort = $state("");
  let active_order = $state<"asc" | "desc">("desc");
  let total_entries = $state(0);
  let total_pages = 0;
  let revision = "";
  let dataset_initialized = $state(false);
  let loading_message = $state(_("Loading…"));
  let failed_visible_page = $state<number | null>(null);
  let using_window_scroller = $state(false);
  let explicit_scroller: HTMLElement | undefined;
  let article_scroller: HTMLElement | undefined;
  let desktop_virtualizer_instance:
    SvelteVirtualizer<HTMLElement, HTMLTableRowElement> | undefined;
  let window_virtualizer_instance:
    SvelteVirtualizer<Window, HTMLTableRowElement> | undefined;
  let virtual_items = $state.raw<VirtualItem[]>([]);
  let rows_version = $state(0);
  let virtual_total_size = $state(0);
  let visible_range = $state<{ startIndex: number; endIndex: number } | null>(
    null,
  );
  let generation = 0;
  let destroyed = false;
  let refresh_frame: number | undefined;
  let refresh_timeout: ReturnType<typeof setTimeout> | undefined;
  let current_page = 1;
  let active_query_key: unknown;
  let active_reload_key: unknown;
  let applied_initial_sort = "";
  let applied_initial_order: "asc" | "desc" = "desc";
  let active_data_key = "";
  let initialized_effect = false;
  let applied_count = Number.NaN;
  let applied_margin = Number.NaN;
  let applied_window_scroller: boolean | undefined;

  // These maps hold at most a few pages. Virtual row snapshots are refreshed
  // explicitly after writes so they do not add reactivity overhead per row.
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const page_cache = new Map<number, T[]>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const pending_pages = new Map<number, AbortController>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const failed_pages = new Map<number, unknown>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const queued_pages = new Map<number, number>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const retry_attempts = new Map<number, number>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const retry_timers = new Map<number, ReturnType<typeof setTimeout>>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  let visible_pages = new Set<number>();

  function active_virtualizer():
    | SvelteVirtualizer<HTMLElement, HTMLTableRowElement>
    | SvelteVirtualizer<Window, HTMLTableRowElement>
    | undefined {
    return using_window_scroller
      ? window_virtualizer_instance
      : desktop_virtualizer_instance;
  }

  function focused_row_index(): number | null {
    const active = document.activeElement;
    const focused =
      active instanceof Element && table?.contains(active) === true
        ? active.closest<HTMLTableRowElement>("tr[data-paged-table-index]")
        : null;
    const index = Number(focused?.dataset.pagedTableIndex);
    return Number.isInteger(index) && index >= 0 ? index : null;
  }

  function extract_range(
    range: Parameters<typeof defaultRangeExtractor>[0],
  ): number[] {
    const indexes = defaultRangeExtractor(range);
    const focused_index = focused_row_index();
    if (
      focused_index != null &&
      focused_index < range.count &&
      !indexes.includes(focused_index)
    ) {
      indexes.push(focused_index);
      indexes.sort((left, right) => left - right);
    }
    return indexes;
  }

  const desktop_virtualizer = createVirtualizer<
    HTMLElement,
    HTMLTableRowElement
  >({
    count: 0,
    enabled: false,
    estimateSize: () => estimated_row_height,
    getItemKey: (index) => index,
    getScrollElement: () => explicit_scroller ?? article_scroller ?? null,
    indexAttribute: "data-index",
    onChange: () => {
      schedule_refresh();
    },
    overscan: 8,
    rangeExtractor: extract_range,
    useAnimationFrameWithResizeObserver: true,
  });
  const window_virtualizer = createWindowVirtualizer<HTMLTableRowElement>({
    count: 0,
    enabled: false,
    estimateSize: () => estimated_row_height,
    getItemKey: (index) => index,
    indexAttribute: "data-index",
    onChange: () => {
      schedule_refresh();
    },
    overscan: 8,
    rangeExtractor: extract_range,
    useAnimationFrameWithResizeObserver: true,
  });

  function row_key_at(index: number): string | number {
    const value = row_at(index);
    return value == null || rowKey == null ? index : rowKey(value, index);
  }

  function row_at(index: number): T | undefined {
    const page = Math.floor(index / page_size) + 1;
    return page_cache.get(page)?.[index - (page - 1) * page_size];
  }

  function scroll_margin(): number {
    if (!body) {
      return 0;
    }
    if (using_window_scroller) {
      return body.getBoundingClientRect().top + window.scrollY;
    }
    const scroller = explicit_scroller ?? article_scroller;
    return scroller
      ? body.getBoundingClientRect().top -
          scroller.getBoundingClientRect().top +
          scroller.scrollTop -
          scroller.clientTop
      : 0;
  }

  function set_virtualizer_options(force = false): void {
    const count = dataset_initialized ? total_entries : 0;
    const margin = scroll_margin();
    if (
      !force &&
      count === applied_count &&
      margin === applied_margin &&
      using_window_scroller === applied_window_scroller
    ) {
      return;
    }
    applied_count = count;
    applied_margin = margin;
    applied_window_scroller = using_window_scroller;
    const common = {
      count,
      onChange: () => {
        schedule_refresh();
      },
      scrollMargin: margin,
    };
    desktop_virtualizer_instance?.setOptions({
      ...common,
      enabled: !using_window_scroller,
    });
    window_virtualizer_instance?.setOptions({
      ...common,
      enabled: using_window_scroller,
    });
  }

  function update_busy_state(): void {
    table?.setAttribute(
      "aria-busy",
      pending_pages.size > 0 || queued_pages.size > 0 ? "true" : "false",
    );
  }

  function is_abort_error(error: unknown): boolean {
    return error instanceof DOMException && error.name === "AbortError";
  }

  function is_retryable(error: unknown): boolean {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      return true;
    }
    if (typeof error === "object" && error != null && "status" in error) {
      const status = error.status;
      return (
        typeof status === "number" &&
        (status === 408 || status === 429 || status >= 500)
      );
    }
    return error instanceof TypeError;
  }

  function page_is_visible(page: number): boolean {
    return visible_pages.has(page);
  }

  function queue_page(page: number, priority: number): void {
    if (
      destroyed ||
      page < 1 ||
      (total_pages > 0 && page > total_pages) ||
      page_cache.has(page) ||
      pending_pages.has(page) ||
      failed_pages.has(page)
    ) {
      return;
    }
    const current_priority = queued_pages.get(page);
    if (current_priority == null || priority < current_priority) {
      queued_pages.set(page, priority);
    }
  }

  function update_visible_pages(): void {
    if (!visible_range || !dataset_initialized) {
      visible_pages =
        !dataset_initialized || total_entries > 0 ? new Set([1]) : new Set();
      current_page = 1;
    } else {
      const first = Math.floor(visible_range.startIndex / page_size) + 1;
      const last = Math.floor(visible_range.endIndex / page_size) + 1;
      current_page = first;
      visible_pages = new Set(
        Array.from({ length: last - first + 1 }, (_, offset) => first + offset),
      );
    }

    for (const page of queued_pages.keys()) {
      if (!visible_pages.has(page)) {
        queued_pages.delete(page);
      }
    }
    for (const page of visible_pages) {
      queue_page(page, Math.abs(page - current_page));
      if (failed_pages.has(page)) {
        schedule_page_retry(page);
      }
    }

    failed_visible_page =
      [...visible_pages].find(
        (page) => failed_pages.has(page) && !retry_timers.has(page),
      ) ?? null;
    const retrying = [...visible_pages].some((page) => retry_timers.has(page));
    const waiting =
      retrying ||
      [...visible_pages].some(
        (page) => !page_cache.has(page) && !failed_pages.has(page),
      );
    loading_message =
      failed_visible_page != null
        ? _("Could not load this page.")
        : waiting || pending_pages.size > 0 || queued_pages.size > 0
          ? _("Loading…")
          : "";
    update_busy_state();
    pump_page_queue();
  }

  function schedule_page_retry(page: number): void {
    const error = failed_pages.get(page);
    const attempts = retry_attempts.get(page) ?? 0;
    if (
      error == null ||
      !is_retryable(error) ||
      attempts > max_automatic_retries ||
      retry_timers.has(page) ||
      !page_is_visible(page)
    ) {
      return;
    }
    const request_generation = generation;
    const timer = setTimeout(
      () => {
        retry_timers.delete(page);
        if (
          destroyed ||
          generation !== request_generation ||
          !page_is_visible(page)
        ) {
          return;
        }
        failed_pages.delete(page);
        queue_page(page, 0);
        pump_page_queue();
      },
      retry_delay_ms * 2 ** Math.max(0, attempts - 1),
    );
    retry_timers.set(page, timer);
  }

  function pump_page_queue(): void {
    while (pending_pages.size < max_concurrent_pages && queued_pages.size > 0) {
      const next = [...queued_pages.entries()].sort(
        ([page_a, priority_a], [page_b, priority_b]) =>
          priority_a - priority_b ||
          Math.abs(page_a - current_page) - Math.abs(page_b - current_page),
      )[0];
      if (!next) {
        break;
      }
      const [page] = next;
      queued_pages.delete(page);
      if (!page_cache.has(page) && !pending_pages.has(page)) {
        void load_page(page, generation);
      }
    }
    update_busy_state();
  }

  function evict_distant_pages(): void {
    const focused_index = focused_row_index();
    const focused_page =
      focused_index == null ? null : Math.floor(focused_index / page_size) + 1;
    const ranked = [...page_cache.keys()].sort(
      (a, b) => Math.abs(a - current_page) - Math.abs(b - current_page),
    );
    for (const page of page_cache.keys()) {
      if (
        page !== current_page &&
        page !== focused_page &&
        Math.abs(page - current_page) > 3
      ) {
        page_cache.delete(page);
      }
    }
    while (page_cache.size > max_cached_pages) {
      const evict = [...ranked]
        .reverse()
        .find((page) => page !== current_page && page !== focused_page);
      if (evict == null) {
        break;
      }
      page_cache.delete(evict);
      ranked.splice(ranked.indexOf(evict), 1);
    }
  }

  async function load_page(
    page: number,
    request_generation: number,
  ): Promise<void> {
    if (destroyed || page_cache.has(page) || pending_pages.has(page)) {
      return;
    }
    const controller = new AbortController();
    const attempts = retry_attempts.get(page) ?? 0;
    retry_attempts.set(page, attempts + 1);
    pending_pages.set(page, controller);
    update_busy_state();

    let timeout_timer: ReturnType<typeof setTimeout> | undefined;
    let remove_abort_listener: (() => void) | undefined;
    const aborted = new Promise<never>((_resolve, reject) => {
      const on_abort = () => {
        const reason: unknown = controller.signal.reason;
        reject(
          reason instanceof Error
            ? reason
            : new DOMException("Aborted", "AbortError"),
        );
      };
      controller.signal.addEventListener("abort", on_abort, { once: true });
      remove_abort_listener = () => {
        controller.signal.removeEventListener("abort", on_abort);
      };
    });
    const timeout = new Promise<never>((_resolve, reject) => {
      timeout_timer = setTimeout(() => {
        const error = new DOMException(
          "Page request timed out.",
          "TimeoutError",
        );
        controller.abort(error);
        reject(error);
      }, request_timeout_ms);
    });

    try {
      const result = await Promise.race([
        load({
          page,
          per_page: page_size,
          sort: active_sort,
          order: active_order,
          signal: controller.signal,
        }),
        timeout,
        aborted,
      ]);
      if (request_generation !== generation || controller.signal.aborted) {
        return;
      }
      if (
        result.page !== page ||
        result.page_size !== page_size ||
        !Number.isInteger(result.total_entries) ||
        !Number.isInteger(result.total_pages)
      ) {
        throw new Error("The server returned invalid page metadata.");
      }
      if (dataset_initialized) {
        if (
          result.total_entries !== total_entries ||
          result.total_pages !== total_pages ||
          result.revision !== revision
        ) {
          reset_dataset(active_data_key);
          return;
        }
      } else if (page === 1) {
        total_entries = result.total_entries;
        total_pages = result.total_pages;
        revision = result.revision;
        dataset_initialized = true;
        set_virtualizer_options();
      } else {
        reset_dataset(active_data_key);
        return;
      }

      page_cache.set(page, result.rows);
      rows_version += 1;
      failed_pages.delete(page);
      retry_attempts.delete(page);
      const retry_timer = retry_timers.get(page);
      if (retry_timer != null) {
        clearTimeout(retry_timer);
        retry_timers.delete(page);
      }
      evict_distant_pages();
      refresh_virtual_items();
    } catch (error: unknown) {
      if (
        request_generation !== generation ||
        (controller.signal.aborted && !is_retryable(error)) ||
        is_abort_error(error)
      ) {
        return;
      }
      failed_pages.set(page, error);
      refresh_virtual_items();
    } finally {
      remove_abort_listener?.();
      if (timeout_timer != null) {
        clearTimeout(timeout_timer);
      }
      if (pending_pages.get(page) === controller) {
        pending_pages.delete(page);
      }
      if (request_generation === generation) {
        update_visible_pages();
        schedule_refresh();
      }
    }
  }

  function retry_visible_pages(): void {
    for (const page of visible_pages) {
      const timer = retry_timers.get(page);
      if (timer != null) {
        clearTimeout(timer);
        retry_timers.delete(page);
      }
      retry_attempts.delete(page);
      failed_pages.delete(page);
      queue_page(page, 0);
    }
    failed_visible_page = null;
    loading_message = _("Loading…");
    pump_page_queue();
  }

  function refresh_virtual_items(): void {
    set_virtualizer_options();
    const virtualizer = active_virtualizer();
    if (!virtualizer) {
      return;
    }
    virtual_items = virtualizer.getVirtualItems();
    virtual_total_size = virtualizer.getTotalSize();
    const range = virtualizer.calculateRange();
    visible_range = range
      ? { startIndex: range.startIndex, endIndex: range.endIndex }
      : null;
    update_visible_pages();
    evict_distant_pages();
  }

  function schedule_refresh(): void {
    if (destroyed || refresh_frame != null || refresh_timeout != null) {
      return;
    }
    if (typeof window.requestAnimationFrame !== "function") {
      refresh_virtual_items();
      return;
    }

    const refresh = () => {
      if (refresh_frame != null) {
        window.cancelAnimationFrame(refresh_frame);
      }
      if (refresh_timeout != null) {
        clearTimeout(refresh_timeout);
      }
      refresh_frame = undefined;
      refresh_timeout = undefined;
      if (destroyed) {
        return;
      }
      refresh_virtual_items();
    };

    refresh_frame = window.requestAnimationFrame(refresh);
    refresh_timeout = setTimeout(refresh, 40);
  }

  function reset_dataset(data_key: string, reset_scroll = false): void {
    generation += 1;
    for (const controller of pending_pages.values()) {
      controller.abort();
    }
    pending_pages.clear();
    queued_pages.clear();
    for (const timer of retry_timers.values()) {
      clearTimeout(timer);
    }
    retry_timers.clear();
    page_cache.clear();
    rows_version += 1;
    failed_pages.clear();
    retry_attempts.clear();
    visible_pages = new Set();
    active_data_key = data_key;
    total_entries = 0;
    total_pages = 0;
    revision = "";
    dataset_initialized = false;
    current_page = 1;
    failed_visible_page = null;
    loading_message = _("Loading…");
    desktop_virtualizer_instance?.measure();
    window_virtualizer_instance?.measure();
    set_virtualizer_options();
    if (reset_scroll) {
      active_virtualizer()?.scrollToOffset(0, { behavior: "instant" });
      if (using_window_scroller) {
        window.scrollTo({ top: 0, behavior: "instant" });
      } else {
        const scroller = explicit_scroller ?? article_scroller;
        if (scroller) {
          scroller.scrollTop = 0;
        }
      }
    }
    queue_page(1, 0);
    pump_page_queue();
    schedule_refresh();
  }

  $effect(() => {
    const next_query_key = queryKey;
    const next_reload_key = reloadKey;
    const next_initial_sort = initialSort;
    const next_initial_order = initialOrder;
    untrack(() => {
      const query_changed =
        !initialized_effect || !Object.is(next_query_key, active_query_key);
      const initial_sort_changed =
        !initialized_effect ||
        next_initial_sort !== applied_initial_sort ||
        next_initial_order !== applied_initial_order;
      const changed =
        !initialized_effect ||
        !Object.is(next_query_key, active_query_key) ||
        !Object.is(next_reload_key, active_reload_key) ||
        initial_sort_changed;
      if (changed) {
        initialized_effect = true;
        active_query_key = next_query_key;
        active_reload_key = next_reload_key;
        if (initial_sort_changed) {
          applied_initial_sort = next_initial_sort;
          applied_initial_order = next_initial_order;
          active_sort = next_initial_sort;
          active_order = next_initial_order;
        }
        reset_dataset(
          JSON.stringify([next_query_key, active_sort, active_order]),
          query_changed || initial_sort_changed,
        );
      }
    });
  });

  function change_sort(column: string): void {
    const order =
      column === active_sort && active_order === "asc" ? "desc" : "asc";
    if (column === active_sort && order === active_order) {
      return;
    }
    active_sort = column;
    active_order = order;
    reset_dataset(JSON.stringify([queryKey, column, order]), true);
  }

  function measure_row(element: HTMLTableRowElement, index: number) {
    element.dataset.index = index.toString();
    element.dataset.pagedTableIndex = index.toString();
    active_virtualizer()?.measureElement(element);
    return {
      update(next_index: number) {
        element.dataset.index = next_index.toString();
        element.dataset.pagedTableIndex = next_index.toString();
        active_virtualizer()?.measureElement(element);
      },
    };
  }

  function on_row_keydown(row_data: T, event: KeyboardEvent): void {
    if (
      onRowClick &&
      (event.key === "Enter" || event.key === " ") &&
      event.target === event.currentTarget
    ) {
      event.preventDefault();
      onRowClick(row_data, event as unknown as MouseEvent);
    }
  }

  onMount(() => {
    destroyed = false;
    explicit_scroller =
      table?.closest<HTMLElement>("[data-report-scroll]") ?? undefined;
    article_scroller = table?.closest<HTMLElement>("article") ?? undefined;
    using_window_scroller =
      explicit_scroller == null && window.innerWidth <= mobile_breakpoint;
    const unsubscribe_desktop = desktop_virtualizer.subscribe((virtualizer) => {
      desktop_virtualizer_instance = virtualizer;
      schedule_refresh();
    });
    const unsubscribe_window = window_virtualizer.subscribe((virtualizer) => {
      window_virtualizer_instance = virtualizer;
      schedule_refresh();
    });
    set_virtualizer_options(true);
    const mutation_observer = new MutationObserver(() => {
      set_virtualizer_options();
    });
    const mutation_roots = new Set(
      [explicit_scroller, article_scroller].filter(
        (element): element is HTMLElement => element != null,
      ),
    );
    for (const mutation_root of mutation_roots) {
      mutation_observer.observe(mutation_root, {
        childList: true,
        subtree: true,
      });
    }
    const on_resize = () => {
      const use_window =
        explicit_scroller == null && window.innerWidth <= mobile_breakpoint;
      if (use_window !== using_window_scroller) {
        using_window_scroller = use_window;
        active_virtualizer()?.measure();
      }
      set_virtualizer_options();
      schedule_refresh();
    };
    window.addEventListener("resize", on_resize, { passive: true });
    return () => {
      destroyed = true;
      window.removeEventListener("resize", on_resize);
      mutation_observer.disconnect();
      if (refresh_frame != null) {
        window.cancelAnimationFrame(refresh_frame);
      }
      if (refresh_timeout != null) {
        clearTimeout(refresh_timeout);
      }
      refresh_frame = undefined;
      refresh_timeout = undefined;
      generation += 1;
      for (const controller of pending_pages.values()) {
        controller.abort();
      }
      pending_pages.clear();
      queued_pages.clear();
      visible_pages.clear();
      for (const timer of retry_timers.values()) {
        clearTimeout(timer);
      }
      retry_timers.clear();
      active_virtualizer()?.measureElement(null);
      unsubscribe_desktop();
      unsubscribe_window();
    };
  });

  let rendered_items = $derived.by(() => {
    const version = rows_version;
    return virtual_items.map((item) => ({
      item,
      data: row_at(item.index),
      version,
    }));
  });
  let first_item = $derived(virtual_items[0]);
  let last_item = $derived(virtual_items.at(-1));
  let top_padding = $derived(
    first_item == null ? 0 : Math.max(0, first_item.start - scroll_margin()),
  );
  let bottom_padding = $derived(
    last_item == null
      ? 0
      : Math.max(0, virtual_total_size - (last_item.end - scroll_margin())),
  );

  $effect(() => {
    const current_items = rendered_items;
    const current_table = table;
    untrack(() => {
      const virtualizer = active_virtualizer();
      if (!current_table || !virtualizer) {
        return;
      }
      // TanStack keeps element observers for rows it measured. Let it discard
      // detached rows, then register the current virtual window again.
      virtualizer.measureElement(null);
      if (current_items.length === 0) {
        return;
      }
      for (const element of current_table.querySelectorAll<HTMLTableRowElement>(
        "tbody tr[data-index]",
      )) {
        virtualizer.measureElement(element);
      }
    });
  });
</script>

<div class="paged-table-count">
  {#if loading_message === "" && dataset_initialized}
    <span>
      {format(_("%(count)s rows"), {
        count: total_entries.toLocaleString(),
      })}
    </span>
  {/if}
</div>

<div
  class="paged-table-status"
  class:has-message={loading_message !== ""}
  class:window-scrolling={using_window_scroller}
  aria-live="polite"
  role="status"
>
  {#if loading_message !== ""}
    <div
      class="journal-page-status-content"
      class:is-loading={failed_visible_page == null}
    >
      {#if failed_visible_page == null}
        <span class="journal-page-spinner" aria-hidden="true"></span>
      {:else}
        <svg
          class="journal-page-status-icon"
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          aria-hidden="true"
        >
          <circle cx="8" cy="8" r="6" stroke="currentColor" />
          <path d="M8 4.5v4" stroke="currentColor" stroke-linecap="round" />
          <circle cx="8" cy="11" r="0.75" fill="currentColor" />
        </svg>
      {/if}
      <span class="journal-page-status-label">{loading_message}</span>
      {#if failed_visible_page != null}
        <button
          class="journal-page-retry"
          type="button"
          aria-label={_("Retry loading this page")}
          onclick={retry_visible_pages}
        >
          {_("Retry")}
        </button>
      {/if}
    </div>
  {/if}
</div>
<div
  class="paged-table-status-space"
  class:visible={using_window_scroller}
  aria-hidden="true"
></div>
<p class="paged-table-print-note">
  {_("Print output includes only currently mounted rows.")}
</p>

<table
  bind:this={table}
  aria-label={ariaLabel}
  aria-busy="true"
  style="overflow-anchor:none"
>
  <thead>
    <tr>
      {#each columns as column (column.key)}
        <th
          class={column.className}
          aria-sort={column.key === active_sort
            ? active_order === "asc"
              ? "ascending"
              : "descending"
            : "none"}
        >
          <button
            type="button"
            onclick={() => {
              change_sort(column.key);
            }}
          >
            {column.label}
            {#if column.key === active_sort}
              <span aria-hidden="true"
                >{active_order === "asc" ? "▲" : "▼"}</span
              >
            {/if}
          </button>
        </th>
      {/each}
    </tr>
  </thead>
  <tbody bind:this={body}>
    {#if !dataset_initialized}
      {#each Array.from({ length: 8 }, (_, index) => index) as index (index)}
        <tr class="paged-table-skeleton" aria-hidden="true">
          {#each columns as column (column.key)}<td><span></span></td>{/each}
        </tr>
      {/each}
    {:else if total_entries === 0}
      <tr
        ><td class="paged-table-empty" colspan={Math.max(columns.length, 1)}
          >{_("No rows found.")}</td
        ></tr
      >
    {:else}
      {#if top_padding > 0}
        <tr class="paged-table-spacer" aria-hidden="true"
          ><td
            colspan={Math.max(columns.length, 1)}
            style={`height:${top_padding.toString()}px`}
          ></td></tr
        >
      {/if}
      {#each rendered_items as { item, data }, position (item.index)}
        {@const previous_item = rendered_items[position - 1]?.item}
        {#if previous_item != null && item.start > previous_item.end}
          <tr
            class="paged-table-spacer"
            data-paged-table-gap
            aria-hidden="true"
          >
            <td
              colspan={Math.max(columns.length, 1)}
              style={`height:${(item.start - previous_item.end).toString()}px`}
            ></td>
          </tr>
        {/if}
        {#if data !== undefined}
          <tr
            use:measure_row={item.index}
            class={rowClass?.(data)}
            data-row-key={row_key_at(item.index)}
            title={rowTitle?.(data)}
            draggable={onRowDragStart != null}
            tabindex={onRowClick == null ? undefined : 0}
            onclick={onRowClick == null
              ? undefined
              : (event) => {
                  onRowClick(data, event);
                }}
            onkeydown={onRowClick == null
              ? undefined
              : (event) => {
                  on_row_keydown(data, event);
                }}
            ondragstart={onRowDragStart == null
              ? undefined
              : (event) => {
                  onRowDragStart(data, event);
                }}
          >
            {@render row(data)}
          </tr>
        {:else}
          <tr
            class="paged-table-skeleton"
            aria-hidden="true"
            style={`height:${item.size.toString()}px`}
          >
            {#each columns as column (column.key)}<td><span></span></td>{/each}
          </tr>
        {/if}
      {/each}
      {#if bottom_padding > 0}
        <tr class="paged-table-spacer" aria-hidden="true"
          ><td
            colspan={Math.max(columns.length, 1)}
            style={`height:${bottom_padding.toString()}px`}
          ></td></tr
        >
      {/if}
    {/if}
  </tbody>
</table>

<style>
  .paged-table-count {
    min-height: 1.5rem;
    font-size: 0.9rem;
    color: var(--text-muted, #666);
  }

  .paged-table-status {
    position: sticky;
    top: 0;
    z-index: 2;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    min-height: 2.5rem;
    margin: 0;
    pointer-events: none;
    background: transparent;
  }

  .paged-table-status-space {
    display: none;
  }

  .paged-table-status > :global(.journal-page-status-content) {
    pointer-events: auto;
  }

  .paged-table-status.window-scrolling {
    position: fixed;
    right: 0.5rem;
    left: 3.25rem;
    padding: 0.25rem;
  }

  .paged-table-status-space.visible {
    display: block;
    height: 2.5rem;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    table-layout: auto;
    overflow-anchor: none;
  }

  thead {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--table-header-background, #f4f4f4);
  }

  .paged-table-status.has-message ~ table thead {
    top: 2.5rem;
  }

  th {
    font-weight: 600;
    text-align: left;
  }

  th button {
    width: 100%;
    padding: 0.55rem 0.65rem;
    font: inherit;
    color: inherit;
    text-align: inherit;
    cursor: pointer;
    background: transparent;
    border: 0;
  }

  tbody tr {
    border-bottom: 1px solid var(--table-border, #e5e5e5);
  }

  tbody tr[tabindex="0"] {
    cursor: pointer;
  }

  tbody tr[tabindex="0"]:hover,
  tbody tr[tabindex="0"]:focus-visible {
    background: var(--table-row-hover, #f5f7fa);
  }

  .paged-table-spacer,
  .paged-table-spacer td {
    padding: 0;
    line-height: 0;
    border: 0;
  }

  .paged-table-skeleton td {
    height: 2.25rem;
    padding: 0.4rem 0.65rem;
  }

  .paged-table-skeleton span {
    display: block;
    width: min(72%, 24rem);
    height: 0.7rem;
    background: linear-gradient(90deg, #ededed 20%, #f6f6f6 50%, #ededed 80%);
    background-size: 200% 100%;
    border-radius: 0.25rem;
    animation: paged-table-shimmer 1.3s linear infinite;
  }

  .paged-table-skeleton:nth-child(2n) span {
    width: min(44%, 17rem);
  }

  .paged-table-empty {
    padding: 1.25rem;
    color: var(--text-muted, #666);
    text-align: center;
  }

  @keyframes paged-table-shimmer {
    to {
      background-position: -200% 0;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .paged-table-skeleton span {
      animation: none;
    }
  }

  .paged-table-print-note {
    display: none;
  }

  @media print {
    .paged-table-status,
    .paged-table-status-space,
    .paged-table-count {
      display: none;
    }

    .paged-table-print-note {
      display: block;
    }

    .paged-table-spacer,
    .paged-table-skeleton {
      display: none;
    }
  }
</style>
