import "./navigation";
import { flushQueue } from "./queue";
import { api, session } from "./api";
import { books, purge, removeBook, setIdentity, type License } from "./offline";
async function validate() {
  try {
    const identity = await session(true);
    if (!identity.authenticated || !identity.member || !identity.device_id) {
      await purge();
      return;
    }
    await setIdentity(identity.member.member_id, identity.device_id);
    await flushQueue().catch(() => {});
    const local = await books(identity.member.member_id);
    if (local.length) {
      const response = await api<{ items: License[] }>("/me/downloads");
      for (const item of local)
        if (
          !response.items.some(
            (l) =>
              l.license_id === item.license.license_id &&
              l.status === "active" &&
              Date.parse(l.valid_until) > Date.now(),
          )
        )
          await removeBook(item);
    }
  } catch {
    /* Offline access remains bounded by the previously issued license; no authorization is extended. */
  }
}
if (document.body.dataset.member === "true") void validate();
window.addEventListener("online", () => {
  void validate();
});
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches("[data-sign-out]"))
    return;
  event.preventDefault();
  void purge().finally(() => form.submit());
});
if (
  "serviceWorker" in navigator &&
  document.body.dataset.offlineEnabled === "true"
)
  void navigator.serviceWorker
    .register("/maison-sw.js", { scope: "/" })
    .catch(() => {});

// Retry only bounded queued writes; blocked conflicts remain for explicit resolution.
setInterval(() => {
  if (document.visibilityState === "visible" && navigator.onLine)
    void flushQueue().catch(() => {});
}, 30000);

// Appearance is the only local Settings fallback; server mutations are never queued here.
function localAppearance() {
  try {
    const guest = document.body.dataset.member !== "true" ? JSON.parse(localStorage.getItem("maison.guest.preferences") || "null") : null;
    const saved = JSON.parse(localStorage.getItem("maison.local-appearance") || "null") || guest;
    if (saved && ["light", "dark", "true_black"].includes(saved.theme)) {
      document.body.classList.remove("theme-light", "theme-dark", "theme-true_black");
      document.body.classList.add("theme-" + saved.theme);
      if (typeof saved.reduced_motion === "boolean") document.body.classList.toggle("reduced-motion", saved.reduced_motion);
    }
  } catch { /* Browsing remains available when local storage is unavailable. */ }
}
localAppearance();
window.addEventListener("maison:navigated", localAppearance);
