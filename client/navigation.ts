import { refreshCatalogue } from "./api";
import {
  internalPageURL,
  preservePlayer,
  trustedIslandModule,
  sameShellBuild,
  LatestNavigation,
} from "./navigation-state";
declare global {
  interface Window {
    maisonEnhance?: () => void;
  }
}
const trustedBundleURL = import.meta.url;
const navigationLifetime = new LatestNavigation();
let enhancedHistory = false;
export async function navigatePage(url: URL, pop = false) {
  const controller = navigationLifetime.begin();
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "text/html" },
    });
    const html = await response.text(),
      next = new DOMParser().parseFromString(html, "text/html");
    if (!navigationLifetime.current(controller)) return;
    if (
      document.body.dataset.memberId !== next.body.dataset.memberId ||
      !preservePlayer(
        document.body.dataset.member,
        next.body.dataset.member,
        response.status,
        response.headers.get("Content-Type") || "",
      ) ||
      (response.redirected && new URL(response.url).pathname !== url.pathname)
    ) {
      location.assign(url);
      return;
    }
    const persistent = document.getElementById("persistent-media");
    const player = persistent?.querySelector<HTMLElement>(
      "[data-persistent-player]",
    );
    const incomingModules = Array.from(
      next.querySelectorAll<HTMLScriptElement>('script[type="module"][src]'),
    ).map((script) => new URL(script.getAttribute("src")!, url).href);
    const nextShell = incomingModules.find((src) =>
      /^shell-[a-z0-9]+\.js$/i.test(
        new URL(src).pathname.split("/").pop() || "",
      ),
    );
    if (
      !persistent?.isConnected ||
      !player?.isConnected ||
      !nextShell ||
      !sameShellBuild(nextShell, trustedBundleURL) ||
      incomingModules.some((src) => !trustedIslandModule(src, trustedBundleURL))
    ) {
      location.assign(url);
      return;
    }
    const modules = incomingModules.filter((src) => src !== nextShell);
    const lifecycle = await import("./lifecycle");
    if (!navigationLifetime.current(controller)) return;
    enhancedHistory = true;
    history.scrollRestoration = "manual";
    if (!pop) {
      history.replaceState(
        { ...history.state, maisonScroll: [scrollX, scrollY] },
        "",
        location.href,
      );
      history.pushState({ maison: true }, "", url);
    }
    window.dispatchEvent(new CustomEvent("maison:before-navigate"));
    lifecycle.disposePage();
    for (const node of Array.from(document.body.childNodes))
      if (node !== persistent) node.remove();
    for (const node of Array.from(next.body.childNodes)) {
      if (node instanceof HTMLElement && node.id === "persistent-media")
        continue;
      if (node instanceof HTMLScriptElement && node.src) continue;
      document.body.insertBefore(document.importNode(node, true), persistent);
    }
    document.body.className = next.body.className + " has-persistent-player";
    document.body.lang = next.body.lang;
    document.body.dataset.member = next.body.dataset.member;
    document.body.dataset.memberId = next.body.dataset.memberId;
    document.body.dataset.offlineEnabled = next.body.dataset.offlineEnabled;
    document.documentElement.lang = next.documentElement.lang;
    document.documentElement.dataset.uiLocale =
      next.documentElement.dataset.uiLocale;
    document.title = next.title;
    const robots = document.querySelector('meta[name="robots"]');
    if (robots)
      robots.setAttribute(
        "content",
        next.querySelector('meta[name="robots"]')?.getAttribute("content") ||
          "noindex,nofollow",
      );
    if (
      !persistent.isConnected ||
      !player.isConnected ||
      !persistent.contains(player)
    ) {
      location.assign(url);
      return;
    }
    refreshCatalogue();
    window.maisonEnhance?.();
    for (const src of modules) {
      const module = await import(src);
      if (!navigationLifetime.current(controller)) return;
      module.mount?.();
    }
    window.dispatchEvent(new CustomEvent("maison:navigated"));
    document.querySelector<HTMLElement>("main")?.focus({ preventScroll: true });
    const saved = pop ? history.state?.maisonScroll : undefined;
    if (saved) window.scrollTo(saved[0], saved[1]);
    else if (url.hash)
      document
        .getElementById(decodeURIComponent(url.hash.slice(1)))
        ?.scrollIntoView();
    else window.scrollTo(0, 0);
  } catch {
    if (navigationLifetime.current(controller)) location.assign(url);
  } finally {
    navigationLifetime.finish(controller);
  }
}
document.addEventListener("click", (event) => {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey ||
    !document.querySelector("[data-persistent-player]")
  )
    return;
  const link = (event.target as Element)?.closest<HTMLAnchorElement>("a[href]");
  if (
    !link ||
    (link.target && link.target !== "_self") ||
    link.hasAttribute("download") ||
    link.rel.includes("external")
  )
    return;
  const url = internalPageURL(link.href, location.href);
  if (!url) return;
  event.preventDefault();
  void navigatePage(url);
});
window.addEventListener("popstate", () => {
  if (document.querySelector("[data-persistent-player]"))
    void navigatePage(new URL(location.href), true);
  else if (enhancedHistory) location.reload();
});

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (
    event.defaultPrevented ||
    !(form instanceof HTMLFormElement) ||
    form.method.toLowerCase() !== "get" ||
    (form.target && form.target !== "_self") ||
    !document.querySelector("[data-persistent-player]")
  )
    return;
  const url = internalPageURL(form.action, location.href);
  if (!url) return;
  const data = new FormData(form);
  url.search = new URLSearchParams(
    [...data.entries()].filter(
      (row): row is [string, string] => typeof row[1] === "string",
    ),
  ).toString();
  event.preventDefault();
  void navigatePage(url);
});
let scrollFrame = 0;
window.addEventListener(
  "scroll",
  () => {
    if (scrollFrame || !document.querySelector("[data-persistent-player]"))
      return;
    scrollFrame = requestAnimationFrame(() => {
      scrollFrame = 0;
      history.replaceState(
        { ...history.state, maisonScroll: [scrollX, scrollY] },
        "",
        location.href,
      );
    });
  },
  { passive: true },
);
