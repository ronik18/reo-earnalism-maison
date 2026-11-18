import { createRoot, type Root } from "react-dom/client";
import { type ReactNode } from "react";
import { IslandLifetime } from "./lifetime-state";
const lifetime = new IslandLifetime<HTMLElement, Root>();
export function mountIsland(
  host: HTMLElement | null,
  render: () => ReactNode,
  persistent = false,
) {
  if (!host || lifetime.roots.has(host)) return;
  const root = createRoot(host);
  lifetime.add(host, root, persistent);
  root.render(render());
}
export function disposePage() {
  lifetime.disposePage();
}
export function closePlayer() {
  lifetime.closePersistent((host) => host.remove());
  document.body.classList.remove("has-persistent-player");
  history.scrollRestoration="auto";
}
