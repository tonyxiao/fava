import type { Attachment } from "svelte/attachments";

/** A tooltip, a light wrapper around a `<div>` that's added to the `<body>` */
export class Tooltip {
  private div: HTMLDivElement;

  constructor() {
    this.div = document.createElement("div");
    this.div.className = "tooltip top";
  }

  init(node: HTMLElement): void {
    node.appendChild(this.div);
  }

  /** Set the tooltip content. */
  content(nodes: (Node | string)[]): void {
    this.div.replaceChildren(...nodes);
  }

  /** Keep the complete tooltip inside the viewport, including near chart edges. */
  position(left: number, top: number): void {
    const parent = this.div.parentElement?.getBoundingClientRect();
    const anchorX = (parent?.left ?? 0) + left;
    const anchorY = (parent?.top ?? 0) + top;
    const box = this.div.getBoundingClientRect();
    const x = Math.max(
      8,
      Math.min(anchorX - box.width / 2, window.innerWidth - box.width - 8),
    );
    const above = anchorY - box.height - 12;
    const preferredY = above >= 8 ? above : anchorY + 12;
    const y = Math.max(
      8,
      Math.min(preferredY, window.innerHeight - box.height - 8),
    );
    this.div.style.opacity = "1";
    this.div.style.left = `${String(Math.round(x))}px`;
    this.div.style.top = `${String(Math.round(y))}px`;
  }

  /** Hide the tooltip. */
  hide(): void {
    this.div.style.opacity = "0";
  }

  /**
   * Svelte attachment to have the given element act on mouse to show a tooltip.
   *
   * The tooltip will be positioned at the cursor and is given a tooltip getter
   * per element.
   */
  following(getter: () => (Node | string)[]): Attachment<SVGElement> {
    return (node) => {
      const mouseenter = () => {
        this.content(getter());
      };
      const mousemove = (event: MouseEvent) => {
        const parent = this.div.parentElement?.getBoundingClientRect();
        this.position(
          event.clientX - (parent?.left ?? 0),
          event.clientY - (parent?.top ?? 0),
        );
      };
      const hide = this.hide.bind(this);

      node.addEventListener("mouseenter", mouseenter);
      node.addEventListener("mousemove", mousemove);
      node.addEventListener("mouseleave", hide);

      return () => {
        node.removeEventListener("mouseenter", mouseenter);
        node.removeEventListener("mousemove", mousemove);
        node.removeEventListener("mouseleave", hide);
      };
    };
  }
}

/** Some small utilities to create tooltip contents. */
export const domHelpers = {
  /** Create a <br> element. */
  br: () => document.createElement("br"),
  /** Create a <em> element with the given content. */
  em: (content) => {
    const em = document.createElement("em");
    em.textContent = content;
    return em;
  },
} satisfies Record<string, (x: string) => HTMLElement>;

export type TooltipContent = (HTMLElement | string)[];

/**
 * A function to find the closest node to the pointer.
 *
 * Returns the position of the node, the node itself, and a function to create
 * the content to show in the tooltip for it.
 */
export type TooltipFindNode = (
  x_pointer: number,
  y_pointer: number,
) =>
  | [x: number, y: number, node: unknown, content: () => TooltipContent]
  | undefined;
