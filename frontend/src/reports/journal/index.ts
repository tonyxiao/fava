import { _ } from "../../i18n.ts";
import type { FiltersConversionInterval } from "../../stores/filters.ts";
import { get_url_filters } from "../../stores/filters.ts";
import { Route } from "../route.ts";
import Journal from "./Journal.svelte";

export interface JournalReportProps {
  filters: FiltersConversionInterval;
}

export const journal = new Route<JournalReportProps>(
  "journal",
  Journal,
  (url: URL) => ({ filters: get_url_filters(url) }),
  () => _("Journal"),
);
