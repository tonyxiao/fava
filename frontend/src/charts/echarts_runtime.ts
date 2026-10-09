// Load only the renderer, chart types and interactions used by interval charts.
import { getInstanceByDom, init, use } from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  AriaComponent,
  BrushComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  ToolboxComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
use([
  BarChart,
  LineChart,
  AriaComponent,
  BrushComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  ToolboxComponent,
  SVGRenderer,
]);
export { getInstanceByDom, init };
