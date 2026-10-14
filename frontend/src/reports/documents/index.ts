import { _ } from "../../i18n.ts";
import { get_url_filters } from "../../stores/filters.ts";
import { Route } from "../route.ts";
import Documents from "./Documents.svelte";

export interface DocumentsReportProps {
  filters: ReturnType<typeof get_url_filters>;
}

export const documents = new Route(
  "documents",
  Documents,
  (url: URL) => ({ filters: get_url_filters(url) }),
  () => _("Documents"),
);
