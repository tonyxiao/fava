import { equal, ok } from "node:assert/strict";
import { test } from "node:test";

import { Tooltip } from "../src/charts/tooltip.ts";

test("large interval tooltips stay within viewport bounds at chart edges", () => {
  const parent = document.createElement("div");
  document.body.append(parent);
  const tooltip = new Tooltip();
  tooltip.init(parent);
  const div = parent.querySelector<HTMLDivElement>(".tooltip");
  ok(div);
  div.getBoundingClientRect = () => ({ width: 300, height: 240 }) as DOMRect;
  parent.getBoundingClientRect = () => ({ left: 100, top: 100 }) as DOMRect;
  tooltip.position(-90, -90);
  equal(div.style.left, "8px");
  ok(parseInt(div.style.top, 10) >= 8);
  tooltip.position(window.innerWidth, window.innerHeight);
  ok(parseInt(div.style.left, 10) + 300 <= window.innerWidth - 8);
  ok(parseInt(div.style.top, 10) + 240 <= window.innerHeight - 8);
  tooltip.hide();
  equal(div.style.opacity, "0");
  parent.remove();
});
