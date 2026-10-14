import { _ } from "../../i18n.ts";
import { get_url_filters } from "../../stores/filters.ts";
import { Route } from "../route.ts";
import Events from "./Events.svelte";

export interface EventsReportProps {
  filters: ReturnType<typeof get_url_filters>;
}

export const events = new Route<EventsReportProps>(
  "events",
  Events,
  (url: URL) => ({ filters: get_url_filters(url) }),
  () => _("Events"),
);
