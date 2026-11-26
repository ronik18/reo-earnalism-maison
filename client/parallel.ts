// Side-by-side read-along (revenue plan Step 3.2). The server renders the aligned pair only when it
// is offered; this switch shows or hides the companion column. The edition being read keeps its
// anchors, progress and annotations; the companion text is display only.
const KEY = "maison.reader.parallel";

export function parallelPreference(raw: string | null): boolean {
  return raw === "on";
}

export function parallelRoles(on: boolean) {
  return on
    ? { table: "table", row: "row", head: "columnheader", cell: "cell" }
    : null;
}

export function setupParallel(doc: Document = document) {
  const toggle = doc.getElementById("parallel-toggle");
  const reader = doc.getElementById("reader");
  const text = doc.getElementById("reading-text");
  if (!toggle || !reader || !text || !text.hasAttribute("data-parallel")) return;
  const apply = (on: boolean) => {
    const roles = parallelRoles(on);
    reader.dataset.parallel = on ? "on" : "off";
    toggle.setAttribute("aria-pressed", String(on));
    const set = (el: Element, role?: string) => {
      if (role) el.setAttribute("role", role);
      else el.removeAttribute("role");
    };
    set(text, roles?.table);
    if (on) text.setAttribute("aria-labelledby", "parallel-caption");
    else text.removeAttribute("aria-labelledby");
    text.querySelectorAll("[data-parallel-row]").forEach((row) => set(row, roles?.row));
    text.querySelectorAll("[data-parallel-head]").forEach((head) => set(head, roles?.head));
    text.querySelectorAll<HTMLElement>(".parallel-cell").forEach((cell) => {
      set(cell, roles?.cell);
      if (cell.hasAttribute("data-companion")) cell.hidden = !on;
    });
    text.querySelectorAll<HTMLElement>(".parallel-head").forEach((head) => (head.hidden = !on));
  };
  let on = false;
  try {
    on = parallelPreference(localStorage.getItem(KEY));
  } catch {}
  apply(on);
  toggle.hidden = false;
  toggle.addEventListener("click", () => {
    on = !on;
    apply(on);
    try {
      localStorage.setItem(KEY, on ? "on" : "off");
    } catch {}
  });
}
