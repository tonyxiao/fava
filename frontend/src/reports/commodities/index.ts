import { get_commodity_report } from "../../api/index.ts";
import type { CommodityReport } from "../../api/validators.ts";
import { _ } from "../../i18n.ts";
import {
  type FiltersConversionInterval,
  get_url_filters,
} from "../../stores/filters.ts";
import { Route } from "../route.ts";
import CommoditiesSvelte from "./Commodities.svelte";

export interface CommoditiesReportProps {
  filters: FiltersConversionInterval;
  initialReport: CommodityReport;
}

export const commodities = new Route<CommoditiesReportProps>(
  "commodities",
  CommoditiesSvelte,
  async (url) => {
    const filters = get_url_filters(url);
    const initialReport = await get_commodity_report({
      ...filters,
      page: 1,
      per_page: 1,
      sort: "date",
      order: "desc",
      include_overview: true,
    });
    return { filters, initialReport };
  },
  () => _("Commodities"),
);
