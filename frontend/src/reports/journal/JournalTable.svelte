<script lang="ts">
  import {
    createVirtualizer,
    createWindowVirtualizer,
    defaultRangeExtractor,
    type SvelteVirtualizer,
    type VirtualItem,
  } from "@tanstack/svelte-virtual";
  import { onMount, untrack } from "svelte";

  import { get_journal_page } from "../../api/index.ts";
  import { _ } from "../../i18n.ts";
  import { get_el } from "../../lib/dom.ts";
  import { FetchHTTPError } from "../../lib/fetch.ts";
  import { log_error } from "../../log.ts";
  import { is_supported_datatransfer } from "../../modals/document-upload.ts";
  import { is_loading } from "../../router.ts";
  import type { FiltersConversionInterval } from "../../stores/filters.ts";
  import {
    type JournalSort,
    journal_show,
    journal_sort,
  } from "../../stores/journal.ts";
  import { get_account_from_url } from "../accounts/index.ts";
  import { handle_journal_click } from "./click_handler.ts";
  import JournalFilters from "./JournalFilters.svelte";
  import JournalHeaders from "./JournalHeaders.svelte";
  import type { JournalSortColumn } from "./sort.ts";

  const page_size = 200;
  const estimated_row_height = 52;
  const overscan = 12;
  const page_buffer = 1;
  const max_concurrent_pages = 3;
  const max_automatic_retries = 2;
  const request_timeout_ms = 10_000;
  const retry_delay_ms = 400;
  const prefetch_idle_ms = 180;
  const known_entry_types = new Set([
    "open",
    "close",
    "transaction",
    "cleared",
    "pending",
    "other",
    "balance",
    "note",
    "document",
    "discovered",
    "linked",
    "pad",
    "query",
    "custom",
    "budget",
  ]);

  interface Props {
    account?: string;
    filters: FiltersConversionInterval;
    show_change_and_balance: boolean;
  }

  let { account, filters, show_change_and_balance }: Props = $props();

  let ol: HTMLOListElement | undefined = $state();
  let status_message = $state(_("Loading journal entries…"));
  let retry_page = $state<number | null>(null);
  let total_entries = 0;
  let total_pages = 0;
  let revision = "";
  let dataset_initialized = false;
  let current_page = 1;
  let generation = 0;
  let destroyed = false;
  let desktop_scroller: HTMLElement | undefined;
  let using_window_scroller = false;
  let active_key = "";
  let active_filters: FiltersConversionInterval | undefined;
  let previous_balance_columns: boolean | undefined;

  // These caches are mutated imperatively; view updates happen only in
  // refresh_window, so Svelte's reactive collection wrappers add no value.
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const pages = new Map<number, HTMLLIElement[]>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const pending_pages = new Map<number, AbortController>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const failed_pages = new Map<number, unknown>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const retry_attempts = new Map<number, number>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const retry_timers = new Map<number, ReturnType<typeof setTimeout>>();
  let prefetch_timer: ReturnType<typeof setTimeout> | undefined;
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const queued_pages = new Map<number, number>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  let visible_pages = new Set<number>();
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const placeholder_rows = new Map<number, HTMLLIElement>();
  const gap_spacers: HTMLLIElement[] = [];
  // eslint-disable-next-line svelte/prefer-svelte-reactivity
  const expanded_rows = new Set<string>();
  let top_spacer: HTMLLIElement | undefined;
  let bottom_spacer: HTMLLIElement | undefined;
  let refresh_frame: number | undefined;

  let desktop_virtualizer_instance:
    SvelteVirtualizer<HTMLElement, HTMLLIElement> | undefined;
  let window_virtualizer_instance:
    SvelteVirtualizer<Window, HTMLLIElement> | undefined;
  type TanStackRange = NonNullable<
    ReturnType<SvelteVirtualizer<HTMLElement, HTMLLIElement>["calculateRange"]>
  >;

  const extract_virtual_range = (
    range: Parameters<typeof defaultRangeExtractor>[0],
  ): number[] => {
    const indexes = defaultRangeExtractor(range);
    const active = document.activeElement;
    const focused_row =
      active instanceof Element
        ? active.closest<HTMLLIElement>("li[data-journal-index]")
        : null;
    const focused_index = Number(focused_row?.dataset.journalIndex);
    if (
      Number.isInteger(focused_index) &&
      focused_index >= 0 &&
      focused_index < range.count &&
      !indexes.includes(focused_index)
    ) {
      indexes.push(focused_index);
      indexes.sort((left, right) => left - right);
    }
    return indexes;
  };

  const desktop_virtualizer = createVirtualizer<HTMLElement, HTMLLIElement>({
    count: 0,
    enabled: false,
    estimateSize: () => estimated_row_height,
    getItemKey: (index) => index,
    getScrollElement: () => desktop_scroller ?? null,
    indexAttribute: "data-index",
    onChange: () => {
      schedule_refresh_window();
    },
    overscan,
    rangeExtractor: extract_virtual_range,
    useAnimationFrameWithResizeObserver: true,
  });
  const window_virtualizer = createWindowVirtualizer<HTMLLIElement>({
    count: 0,
    enabled: false,
    estimateSize: () => estimated_row_height,
    getItemKey: (index) => index,
    indexAttribute: "data-index",
    onChange: () => {
      schedule_refresh_window();
    },
    overscan,
    rangeExtractor: extract_virtual_range,
    useAnimationFrameWithResizeObserver: true,
  });

  function visible_entry_types(show: string[]): string[] {
    return show.filter((type) => known_entry_types.has(type));
  }

  function is_abort_error(error: unknown): boolean {
    return error instanceof DOMException && error.name === "AbortError";
  }

  function component_is_active(): boolean {
    return !destroyed;
  }

  function entry_rows(html: string): HTMLLIElement[] {
    const template = document.createElement("template");
    template.innerHTML = html;
    return [...template.content.children].filter(
      (element): element is HTMLLIElement => element instanceof HTMLLIElement,
    );
  }

  function make_spacer(height: number): HTMLLIElement {
    const spacer = document.createElement("li");
    spacer.className = "journal-virtual-spacer";
    spacer.setAttribute("aria-hidden", "true");
    spacer.style.height = `${Math.max(0, height).toString()}px`;
    return spacer;
  }

  function reconcile_children(parent: HTMLOListElement, next: Node[]): void {
    const desired = new Set(next);
    for (const child of [...parent.children]) {
      if (!desired.has(child)) {
        child.remove();
      }
    }
    for (const [index, node] of next.entries()) {
      const current = parent.children.item(index);
      if (current !== node) {
        parent.insertBefore(node, current);
      }
    }
  }

  function spacer_at(slot: number, height: number): HTMLLIElement {
    let spacer = gap_spacers[slot];
    if (!spacer) {
      spacer = make_spacer(0);
      gap_spacers[slot] = spacer;
    }
    spacer.style.height = `${Math.max(0, height).toString()}px`;
    return spacer;
  }

  function set_spacer_height(spacer: HTMLLIElement, height: number): void {
    spacer.style.height = `${Math.max(0, height).toString()}px`;
  }

  function row_at(index: number): HTMLLIElement | undefined {
    const page = Math.floor(index / page_size) + 1;
    return pages.get(page)?.[index - (page - 1) * page_size];
  }

  function placeholder_at(index: number): HTMLLIElement {
    let placeholder = placeholder_rows.get(index);
    if (!placeholder) {
      placeholder = document.createElement("li");
      placeholder.className = "journal-virtual-placeholder";
      placeholder.setAttribute("aria-hidden", "true");
      placeholder_rows.set(index, placeholder);
    }
    placeholder.dataset.index = index.toString();
    return placeholder;
  }

  function row_key(row: HTMLLIElement): string | undefined {
    const href = row.querySelector<HTMLAnchorElement>(".datecell a")?.href;
    if (href == null || href === "") {
      return undefined;
    }
    const hash = new URL(href).hash;
    return hash.startsWith("#context-") ? hash.slice(9) : undefined;
  }

  function scroll_margin(): number {
    if (!ol) {
      return 0;
    }
    if (using_window_scroller) {
      return ol.getBoundingClientRect().top + window.scrollY;
    }
    return desktop_scroller
      ? ol.getBoundingClientRect().top -
          desktop_scroller.getBoundingClientRect().top +
          desktop_scroller.scrollTop -
          desktop_scroller.clientTop
      : 0;
  }

  function active_virtualizer():
    | SvelteVirtualizer<HTMLElement, HTMLLIElement>
    | SvelteVirtualizer<Window, HTMLLIElement>
    | undefined {
    return using_window_scroller
      ? window_virtualizer_instance
      : desktop_virtualizer_instance;
  }

  function active_virtual_items(): VirtualItem[] {
    return using_window_scroller
      ? (window_virtualizer_instance?.getVirtualItems() ?? [])
      : (desktop_virtualizer_instance?.getVirtualItems() ?? []);
  }

  function active_virtual_range(): TanStackRange | null {
    return using_window_scroller
      ? (window_virtualizer_instance?.calculateRange() ?? null)
      : (desktop_virtualizer_instance?.calculateRange() ?? null);
  }

  function remeasure_preserving_anchor(): void {
    const virtualizer = active_virtualizer();
    if (!virtualizer) {
      schedule_refresh_window();
      return;
    }

    const range = virtualizer.calculateRange();
    const anchor = range
      ? virtualizer
          .getVirtualItems()
          .find((item) => item.index === range.startIndex)
      : undefined;

    virtualizer.measure();
    // Rebuild cached measurements and spacer DOM before asking for the new
    // offset. getOffsetForIndex reads the current measurements cache, and the
    // browser must also see the updated total height before scrollToOffset.
    refresh_window();
    if (anchor != null) {
      virtualizer.scrollToIndex(anchor.index, { align: "start" });
    }
    schedule_refresh_window();
  }

  function set_virtualizer_options(): void {
    const margin = scroll_margin();
    desktop_virtualizer_instance?.setOptions({
      count: total_entries,
      enabled: !using_window_scroller,
      onChange: () => {
        schedule_refresh_window();
      },
      scrollMargin: margin,
    });
    window_virtualizer_instance?.setOptions({
      count: total_entries,
      enabled: using_window_scroller,
      onChange: () => {
        schedule_refresh_window();
      },
      scrollMargin: margin,
    });
  }

  function update_busy_state(): void {
    if (ol) {
      ol.setAttribute(
        "aria-busy",
        pending_pages.size > 0 ||
          queued_pages.size > 0 ||
          [...retry_timers.keys()].some(page_is_visible)
          ? "true"
          : "false",
      );
    }
  }

  function is_retryable_error(error: unknown): boolean {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      return true;
    }
    if (error instanceof FetchHTTPError) {
      return (
        error.status === 408 || error.status === 429 || error.status >= 500
      );
    }
    return error instanceof TypeError;
  }

  function page_is_visible(page: number): boolean {
    return page === current_page || visible_pages.has(page);
  }

  function schedule_page_retry(page: number): void {
    const error = failed_pages.get(page);
    const attempts = retry_attempts.get(page) ?? 0;
    if (
      error == null ||
      !is_retryable_error(error) ||
      attempts >= max_automatic_retries ||
      retry_timers.has(page)
    ) {
      return;
    }
    // Mark this failure streak without spending an attempt until a request
    // starts. Queued retries can become obsolete during another fast scroll.
    retry_attempts.set(page, attempts);
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
        if (retry_page === page) {
          retry_page = null;
        }
        queue_page(page, 0);
        pump_page_queue();
      },
      retry_delay_ms * 2 ** attempts,
    );
    retry_timers.set(page, timer);
  }

  function update_visible_page_demand(range: TanStackRange): void {
    const first_page = Math.floor(range.startIndex / page_size) + 1;
    const last_page = Math.floor(range.endIndex / page_size) + 1;
    current_page = first_page;
    visible_pages = new Set(
      Array.from(
        { length: last_page - first_page + 1 },
        (_, offset) => first_page + offset,
      ),
    );

    // Keep only the latest viewport's queued work. Active requests are allowed
    // to finish so quick scroll changes do not abort and restart the same page.
    for (const page of queued_pages.keys()) {
      if (!visible_pages.has(page)) {
        queued_pages.delete(page);
      }
    }
    for (const page of visible_pages) {
      const priority = Math.abs(page - current_page);
      queue_page(page, priority);
      if (failed_pages.has(page)) {
        update_retry_state(page);
      }
    }
    if (retry_page != null && !visible_pages.has(retry_page)) {
      retry_page = null;
    }
    // Loading feedback follows the viewport, including when all request slots
    // are still occupied by pages the user has scrolled past.
    status_message =
      retry_page != null
        ? _("Could not load journal entries.")
        : [...visible_pages].some((page) => !pages.has(page))
          ? _("Loading journal entries…")
          : "";
    update_busy_state();
    pump_page_queue();
    schedule_prefetch_after_idle();
  }

  function queue_page(page: number, priority: number): void {
    if (
      destroyed ||
      page < 1 ||
      (total_pages > 0 && page > total_pages) ||
      pages.has(page) ||
      pending_pages.has(page) ||
      failed_pages.has(page)
    ) {
      return;
    }
    const existing_priority = queued_pages.get(page);
    if (existing_priority == null || priority < existing_priority) {
      queued_pages.set(page, priority);
    }
  }

  function schedule_prefetch_after_idle(): void {
    if (destroyed) {
      return;
    }
    if (prefetch_timer != null) {
      clearTimeout(prefetch_timer);
    }
    prefetch_timer = setTimeout(() => {
      prefetch_timer = undefined;
      if (active_virtualizer()?.isScrolling === true) {
        return;
      }
      if (
        [...visible_pages].some(
          (page) =>
            !pages.has(page) ||
            pending_pages.has(page) ||
            failed_pages.has(page),
        )
      ) {
        return;
      }
      queue_page(current_page - page_buffer, 100);
      queue_page(current_page + page_buffer, 100);
      pump_page_queue();
    }, prefetch_idle_ms);
  }

  function pump_page_queue(): void {
    while (pending_pages.size < max_concurrent_pages && queued_pages.size > 0) {
      const next_page = [...queued_pages.entries()].sort(
        ([page_a, priority_a], [page_b, priority_b]) =>
          priority_a - priority_b ||
          Math.abs(page_a - current_page) - Math.abs(page_b - current_page),
      )[0];
      if (next_page == null) {
        break;
      }
      const [page] = next_page;
      queued_pages.delete(page);
      if (!pages.has(page) && !pending_pages.has(page)) {
        void load_page(page, generation);
      }
    }
    update_busy_state();
  }

  function update_retry_state(page: number): void {
    const error = failed_pages.get(page);
    if (!page_is_visible(page)) {
      return;
    }
    if (error != null && is_retryable_error(error)) {
      schedule_page_retry(page);
      if (retry_timers.has(page)) {
        return;
      }
    }
    retry_page = page;
    status_message = _("Could not load journal entries.");
  }

  function retry_failed_page(page: number): void {
    const pages_to_retry = new Set([
      page,
      ...[...visible_pages].filter((visible) => failed_pages.has(visible)),
    ]);
    for (const missing_page of pages_to_retry) {
      const timer = retry_timers.get(missing_page);
      if (timer != null) {
        clearTimeout(timer);
        retry_timers.delete(missing_page);
      }
      retry_attempts.delete(missing_page);
      failed_pages.delete(missing_page);
      queue_page(missing_page, 0);
    }
    retry_page = null;
    status_message = _("Loading journal entries…");
    pump_page_queue();
  }

  async function load_page(
    page: number,
    request_generation: number,
  ): Promise<void> {
    if (destroyed || page < 1 || (total_pages > 0 && page > total_pages)) {
      return;
    }
    if (pages.has(page) || pending_pages.has(page)) {
      return;
    }

    const controller = new AbortController();
    const attempts = retry_attempts.get(page);
    if (attempts != null) {
      retry_attempts.set(page, attempts + 1);
    }
    pending_pages.set(page, controller);
    update_busy_state();
    if (page === current_page) {
      status_message = _("Loading journal entries…");
    }

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
          "Journal page request timed out.",
          "TimeoutError",
        );
        controller.abort(error);
        reject(error);
      }, request_timeout_ms);
    });

    try {
      const result = await Promise.race([
        get_journal_page({
          ...filters,
          ...(account != null ? { a: account } : {}),
          page,
          per_page: page_size,
          order: $journal_sort[1],
          sort: $journal_sort[0],
          show: visible_entry_types([...$journal_show].sort()).join(","),
          signal: controller.signal,
        }),
        timeout,
        aborted,
      ]);
      if (request_generation !== generation || controller.signal.aborted) {
        return;
      }
      if (dataset_initialized) {
        if (
          result.total_entries !== total_entries ||
          result.page_size !== page_size ||
          result.revision !== revision
        ) {
          // A new server revision invalidates cached rows and measurements.
          reset_dataset(active_key, true);
          return;
        }
      } else if (page === 1) {
        total_entries = result.total_entries;
        total_pages = result.total_pages;
        revision = result.revision;
        dataset_initialized = true;
        set_virtualizer_options();
      } else {
        reset_dataset(active_key, true);
        return;
      }
      pages.set(result.page, entry_rows(result.journal));
      failed_pages.delete(result.page);
      retry_attempts.delete(result.page);
      const timer = retry_timers.get(result.page);
      if (timer != null) {
        clearTimeout(timer);
        retry_timers.delete(result.page);
      }
      if (retry_page == null || retry_page === result.page) {
        retry_page = null;
        status_message = "";
      }
      refresh_window();
    } catch (error: unknown) {
      const timed_out =
        error instanceof DOMException && error.name === "TimeoutError";
      if (
        request_generation !== generation ||
        (!timed_out && (controller.signal.aborted || is_abort_error(error)))
      ) {
        return;
      }
      failed_pages.set(page, error);
      log_error(`Failed to fetch journal page ${page.toString()}`, error);
      update_retry_state(page);
      refresh_window();
    } finally {
      remove_abort_listener?.();
      if (timeout_timer != null) {
        clearTimeout(timeout_timer);
      }
      if (pending_pages.get(page) === controller) {
        pending_pages.delete(page);
      }
      if (component_is_active()) {
        update_busy_state();
        pump_page_queue();
        schedule_prefetch_after_idle();
      }
    }
  }

  function evict_distant_pages(anchor_page: number): void {
    const active = document.activeElement;
    const focused_row =
      active instanceof Element
        ? active.closest<HTMLLIElement>("li[data-journal-index]")
        : null;
    const focused_page = focused_row
      ? Math.floor(Number(focused_row.dataset.journalIndex) / page_size) + 1
      : null;

    for (const page of pages.keys()) {
      if (
        Math.abs(page - anchor_page) > page_buffer + 2 &&
        page !== focused_page
      ) {
        pages.delete(page);
      }
    }
  }

  function refresh_window(): void {
    if (!ol) {
      return;
    }
    update_busy_state();
    if (!dataset_initialized) {
      const loading = document.createElement("li");
      loading.className = "journal-virtual-message";
      loading.textContent = status_message || _("Loading journal entries…");
      reconcile_children(ol, [loading]);
      return;
    }
    if (total_entries === 0) {
      const empty = document.createElement("li");
      empty.className = "journal-virtual-message";
      empty.textContent = _("No journal entries match these filters.");
      reconcile_children(ol, [empty]);
      return;
    }

    const range = active_virtual_range();
    const virtual_items = active_virtual_items();
    if (range) {
      update_visible_page_demand(range);
      evict_distant_pages(current_page);
    }
    if (virtual_items.length === 0) {
      schedule_prefetch_after_idle();
      return;
    }

    const margin = scroll_margin();
    const first_item = virtual_items.at(0);
    const last_item = virtual_items.at(-1);
    const virtualizer = active_virtualizer();
    if (first_item == null || last_item == null || virtualizer == null) {
      return;
    }
    top_spacer ??= make_spacer(0);
    set_spacer_height(top_spacer, first_item.start - margin);
    let gap_spacer_slot = 0;
    const nodes: Node[] = [top_spacer];
    const rendered_rows: HTMLLIElement[] = [];
    let previous_end = first_item.start;
    for (const item of virtual_items) {
      const gap = item.start - previous_end;
      if (gap > 0) {
        nodes.push(spacer_at(gap_spacer_slot++, gap));
      }
      const row = row_at(item.index);
      if (row) {
        row.dataset.journalIndex = item.index.toString();
        row.dataset.index = item.index.toString();
        const key = row_key(row);
        row.classList.toggle(
          "show-full-entry",
          key != null && expanded_rows.has(key),
        );
        nodes.push(row);
        rendered_rows.push(row);
      } else {
        const placeholder = placeholder_at(item.index);
        placeholder.style.height = `${item.size.toString()}px`;
        nodes.push(placeholder);
      }
      previous_end = item.end;
    }
    bottom_spacer ??= make_spacer(0);
    set_spacer_height(
      bottom_spacer,
      virtualizer.getTotalSize() - (last_item.end - margin),
    );
    nodes.push(bottom_spacer);
    reconcile_children(ol, nodes);

    for (const row of rendered_rows) {
      virtualizer.measureElement(row);
    }
    // TanStack drops observers and cached element references after eviction.
    virtualizer.measureElement(null);
    for (const [index, placeholder] of placeholder_rows) {
      if (!placeholder.isConnected) {
        placeholder_rows.delete(index);
      }
    }
  }

  function schedule_refresh_window(): void {
    if (destroyed || refresh_frame != null) {
      return;
    }
    if (typeof window.requestAnimationFrame !== "function") {
      refresh_window();
      return;
    }
    refresh_frame = window.requestAnimationFrame(() => {
      refresh_frame = undefined;
      refresh_window();
    });
  }

  function reset_dataset(key: string, refresh = false): void {
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
    if (prefetch_timer != null) {
      clearTimeout(prefetch_timer);
      prefetch_timer = undefined;
    }
    pages.clear();
    failed_pages.clear();
    retry_attempts.clear();
    placeholder_rows.clear();
    visible_pages.clear();
    active_key = key;
    total_entries = 0;
    total_pages = 0;
    revision = "";
    dataset_initialized = false;
    current_page = 1;
    retry_page = null;
    status_message = _("Loading journal entries…");
    desktop_virtualizer_instance?.measure();
    window_virtualizer_instance?.measure();
    set_virtualizer_options();
    if (refresh && ol) {
      refresh_window();
    }
    queue_page(1, 0);
    pump_page_queue();
  }

  $effect(() => {
    const sort = $journal_sort;
    const show = visible_entry_types([...$journal_show].sort());
    const current_filters = filters;
    const current_account = account;
    const key = JSON.stringify({
      sort,
      show,
      current_filters,
      current_account,
    });
    untrack(() => {
      const filters_replaced = current_filters !== active_filters;
      if (key !== active_key || filters_replaced) {
        active_filters = current_filters;
        reset_dataset(key, active_key !== "");
      }
    });
  });

  $effect(() => {
    // The optional balance/change columns can alter the rendered row layout.
    if (previous_balance_columns !== show_change_and_balance) {
      previous_balance_columns = show_change_and_balance;
      schedule_refresh_window();
    }
  });

  let previous_detail_visibility: string | undefined;
  $effect(() => {
    const show = $journal_show;
    const detail_visibility = show
      .filter((type) => type === "metadata" || type === "postings")
      .sort()
      .join(",");
    untrack(() => {
      if (previous_detail_visibility === undefined) {
        previous_detail_visibility = detail_visibility;
      } else if (previous_detail_visibility !== detail_visibility) {
        previous_detail_visibility = detail_visibility;
        remeasure_preserving_anchor();
      }
    });
  });

  onMount(() => {
    destroyed = false;
    desktop_scroller = ol?.closest<HTMLElement>("article") ?? undefined;
    using_window_scroller = window.innerWidth <= 767;
    const unsubscribe_desktop = desktop_virtualizer.subscribe((virtualizer) => {
      desktop_virtualizer_instance = virtualizer;
      schedule_refresh_window();
    });
    const unsubscribe_window = window_virtualizer.subscribe((virtualizer) => {
      window_virtualizer_instance = virtualizer;
      schedule_refresh_window();
    });
    set_virtualizer_options();

    const on_resize = () => {
      const use_window = window.innerWidth <= 767;
      if (use_window !== using_window_scroller) {
        using_window_scroller = use_window;
        active_virtualizer()?.measure();
      }
      set_virtualizer_options();
      schedule_refresh_window();
    };
    window.addEventListener("resize", on_resize, { passive: true });
    refresh_window();
    return () => {
      destroyed = true;
      window.removeEventListener("resize", on_resize);
      if (refresh_frame != null) {
        window.cancelAnimationFrame(refresh_frame);
        refresh_frame = undefined;
      }
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
      if (prefetch_timer != null) {
        clearTimeout(prefetch_timer);
      }
      active_virtualizer()?.measureElement(null);
      unsubscribe_desktop();
      unsubscribe_window();
    };
  });

  /** Set drag metadata so a transaction row can accept a document drop. */
  function ondragenter(event: DragEvent): void {
    const closest_element = get_el(event.target);
    const description = closest_element?.closest(".description");
    const li = description?.closest("li");
    if (
      description instanceof Element &&
      li &&
      is_supported_datatransfer(event.dataTransfer)
    ) {
      const account_name = [...li.querySelectorAll("a")]
        .map((link) => new URL(link.href))
        .map(get_account_from_url)
        .find((result) => result.is_ok)?.value;
      if (account_name != null) {
        description.setAttribute("data-account-name", account_name);
        description.classList.add("dragover");
        event.preventDefault();
        const date_link = description
          .closest(".journal > li")
          ?.querySelector<HTMLAnchorElement>(".datecell a");
        if (date_link != null) {
          const hash = new URL(date_link.href).hash;
          if (hash.startsWith("#context-")) {
            description.setAttribute("data-entry-date", date_link.textContent);
            description.setAttribute("data-entry-hash", hash.slice(9));
          }
        }
      }
    }
  }

  function set_sort_column(column: JournalSortColumn): void {
    const sort: JournalSort = [
      column,
      $journal_sort[0] === column && $journal_sort[1] === "asc"
        ? "desc"
        : "asc",
    ];
    $journal_sort = sort;
  }

  function on_journal_click(event: MouseEvent): void {
    const target = get_el(event.target);
    const row = target?.closest<HTMLLIElement>("li[data-journal-index]");
    handle_journal_click(event);
    if (row) {
      const key = row_key(row);
      if (key == null) {
        return;
      }
      if (row.classList.contains("show-full-entry")) {
        expanded_rows.add(key);
      } else {
        expanded_rows.delete(key);
      }
      schedule_refresh_window();
    }
  }
</script>

<JournalFilters />
<JournalHeaders
  disabled={$is_loading}
  {show_change_and_balance}
  {set_sort_column}
/>
<p class="journal-print-note">
  {_(
    "Print output includes only the journal entries currently loaded in this view.",
  )}
</p>
<div class="journal-page-status-space" aria-hidden="true"></div>
<div
  class="journal-page-status"
  class:has-message={status_message !== ""}
  aria-live="polite"
  role="status"
>
  {#if status_message !== ""}
    <div
      class="journal-page-status-content"
      class:is-loading={retry_page == null}
    >
      {#if retry_page == null}
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
      <span class="journal-page-status-label">{status_message}</span>
      {#if retry_page != null}
        <button
          class="journal-page-retry"
          type="button"
          aria-label={_("Retry loading journal page")}
          onclick={() => {
            if (retry_page != null) {
              retry_failed_page(retry_page);
            }
          }}
        >
          {_("Retry")}
        </button>
      {/if}
    </div>
  {/if}
</div>
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<ol
  class={[
    "flex-table",
    "journal",
    "journal-entries",
    ...$journal_show.map((show) => `show-${show}`),
  ]}
  bind:this={ol}
  onclick={on_journal_click}
  {ondragenter}
></ol>
