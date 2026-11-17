import { _ } from "../../i18n.ts";
import type { FiltersConversionInterval } from "../../stores/filters.ts";
import { get_url_filters } from "../../stores/filters.ts";
import { Route } from "../route.ts";
import Transactions from "./Transactions.svelte";

export interface TransactionsReportProps {
  filters: FiltersConversionInterval;
}

export const transactions = new Route<TransactionsReportProps>(
  "transactions",
  Transactions,
  (url: URL) => ({ filters: get_url_filters(url) }),
  () => _("Transactions (Experimental)"),
);
