import { highlightSpan } from "./sentences";

const NAME = "follow-sentence";
const PARAGRAPH = "follow-paragraph";
type Registry = { set(name: string, value: unknown): void; delete(name: string): void };
const registry = (): Registry | undefined => (globalThis as { CSS?: { highlights?: Registry } }).CSS?.highlights;

function textNodes(el: Element): Text[] {
  const nodes: Text[] = [];
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n as Text);
  return nodes;
}

/** Remove whatever the last call drew. Never touches the text, only the wrapper elements it added. */
export function clearFollow(root: ParentNode = document) {
  registry()?.delete(NAME);
  registry()?.delete(PARAGRAPH);
  root.querySelectorAll<HTMLElement>("mark.follow-sentence,mark.follow-paragraph").forEach((mark) => {
    const parent = mark.parentNode;
    mark.replaceWith(...Array.from(mark.childNodes));
    parent?.normalize();
  });
}

/**
 * Highlight [start,end) (code points, null for all) of `el`'s text. Uses the CSS Custom Highlight API when the
 * browser has it (no DOM change at all); otherwise wraps the covered text in <mark> elements by splitting text
 * nodes. The text content of `el` is identical either way.
 */
export function drawFollow(el: HTMLElement, range: [number, number] | null): (() => DOMRect) | undefined {
  clearFollow(el.ownerDocument);
  const [start, end] = highlightSpan(el.textContent || "", range);
  const kind = range ? NAME : PARAGRAPH;
  const nodes = textNodes(el);
  const reg = registry();
  const HighlightCtor = (globalThis as { Highlight?: new (...r: Range[]) => unknown }).Highlight;
  if (reg && HighlightCtor) {
    const dom = document.createRange();
    let seen = 0;
    let started = false;
    for (const node of nodes) {
      const length = node.data.length;
      if (!started && start <= seen + length) { dom.setStart(node, Math.max(0, start - seen)); started = true; }
      if (started && end <= seen + length) { dom.setEnd(node, Math.max(0, end - seen)); break; }
      seen += length;
    }
    if (!started) return undefined;
    reg.set(kind, new HighlightCtor(dom));
    return () => dom.getBoundingClientRect();
  }
  let seen = 0;
  const marks: HTMLElement[] = [];
  for (const node of nodes) {
    const length = node.data.length;
    const from = Math.max(start - seen, 0);
    const to = Math.min(end - seen, length);
    seen += length;
    if (to <= from) continue;
    const middle = from > 0 ? node.splitText(from) : node;
    if (to - from < middle.data.length) middle.splitText(to - from);
    const mark = document.createElement("mark");
    mark.className = kind;
    middle.replaceWith(mark);
    mark.append(middle);
    marks.push(mark);
  }
  return marks.length ? () => marks[0].getBoundingClientRect() : undefined;
}
