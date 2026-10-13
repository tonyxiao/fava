// Load only the renderer, chart types and interactions used by interval charts.

import { BarChart, LineChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { getInstanceByDom, init, use } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";

use([
  BarChart,
  LineChart,
  AriaComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  SVGRenderer,
]);

export { getInstanceByDom, init };
