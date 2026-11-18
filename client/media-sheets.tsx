import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { api, errorText, t } from "./api";
import { validReturnPath } from "./state";

export function MediaSheet({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const previousFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const restoreFocus = () => {
    const target = previousFocus.current;
    previousFocus.current = null;
    if (target?.isConnected) target.focus({ preventScroll: true });
  };
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      element.showModal();
    }
    if (!open && element.open) element.close();
  }, [open]);
  useEffect(() => {
    const closeForNavigation = () => { if (dialog.current?.open) { dialog.current.close(); onCloseRef.current(); } };
    window.addEventListener("maison:before-navigate", closeForNavigation);
    return () => { window.removeEventListener("maison:before-navigate", closeForNavigation); restoreFocus(); };
  }, []);
  return <dialog ref={dialog} className="maison-dialog media-sheet" aria-labelledby={titleId} onClose={() => { restoreFocus(); if (open) onClose(); }}>
    <div className="dialog-heading"><h2 id={titleId}>{title}</h2><button type="button" onClick={() => dialog.current?.close()}>{t("close")}</button></div>
    {children}
  </dialog>;
}

interface Offer { offer_id: string; name: string; availability: string; price: { amount_minor: number; currency: string } | null; terms_summary: string }
export function PreviewBoundary({ editionId, format, authenticated, titleUrl, signInUrl, passUrl, open, onClose, onRetry }: {
  editionId: string; format: "reader" | "audio"; authenticated: boolean; titleUrl: string; signInUrl: string; passUrl: string; open: boolean; onClose: () => void; onRetry: () => void;
}) {
  const [offers, setOffers] = useState<Offer[] | undefined>();
  const [status, setStatus] = useState("");
  const [online, setOnline] = useState(navigator.onLine);
  const [entitled, setEntitled] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const changed = () => setOnline(navigator.onLine);
    window.addEventListener("online", changed); window.addEventListener("offline", changed);
    return () => { window.removeEventListener("online", changed); window.removeEventListener("offline", changed); };
  }, []);
  useEffect(() => {
    setEntitled(false);
    if (!open || !authenticated || !online) return;
    let active = true;
    setOffers(undefined); setStatus("");
    void Promise.all([
      api<{items: Offer[]}>("/commerce/offers"),
      api<{items: {edition_id: string | null; scope: string; formats: string[]; status: string; valid_from: string}[]}>("/me/entitlements"),
    ]).then(([offerResult, access]) => {
      if (!active) return;
      setOffers(offerResult.items.filter(item => item.availability === "available" && item.price !== null));
      setEntitled(access.items.some(item => item.status === "active" && Date.parse(item.valid_from) <= Date.now() && item.formats.includes(format) && (item.edition_id === editionId || item.scope === "platform")));
    }).catch(error => { if (active) { setStatus(errorText(error)); setOffers([]); } });
    return () => { active = false; };
  }, [open, authenticated, online, editionId, format, attempt]);
  return <MediaSheet open={open} title={t("preview_end")} onClose={onClose}>
    <p>{t("preview_boundary_help")}</p>
    {!online ? <p className="notice">{t("preview_offline")}</p> : !authenticated ? <a className="button" href={validReturnPath(signInUrl)}>{t("sign_in")}</a> : <>
      {entitled ? <><p>{t("preview_access_retry")}</p><button onClick={onRetry}>{t("retry")}</button></> : offers === undefined ? <p role="status">{t("loading")}</p> : offers.length ? <><p>{t("preview_offer_help")}</p><ul>{offers.map(offer => <li key={offer.offer_id}><strong>{offer.name}</strong><p>{offer.terms_summary}</p></li>)}</ul><a className="button" href={validReturnPath(passUrl)}>{t("view_available_offers")}</a></> : <p>{t("preview_no_offer")}</p>}
      <p role="status">{status}</p>{status ? <button type="button" onClick={() => setAttempt(value => value + 1)}>{t("retry")}</button> : null}
    </>}
    <div className="actions"><button onClick={onClose}>{t("keep_preview")}</button><a className="button secondary" href={validReturnPath(titleUrl)}>{t("back_to_title")}</a></div>
  </MediaSheet>;
}

export function FormatSwitch({open, onClose, busy, status, onExact, chapterUrl, target}: {open: boolean; onClose: () => void; busy: boolean; status: string; onExact: () => void; chapterUrl: string; target: "reader" | "audio"}) {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => { const changed = () => setOnline(navigator.onLine); window.addEventListener("online", changed); window.addEventListener("offline", changed); return () => {window.removeEventListener("online", changed); window.removeEventListener("offline", changed);}; }, []);
  return <MediaSheet open={open} title={t("switch_format")} onClose={onClose}>
    <p>{t("switch_format_help")}</p>
    {!online ? <p className="notice">{t("switch_offline_unavailable")}</p> : <button disabled={busy} onClick={onExact}>{t(target === "reader" ? "switch_to_read" : "switch_to_listen")}</button>}
    <p role="status" aria-live="polite">{status}</p>
    <p>{t("switch_chapter_choice")}</p><a className="button secondary" href={validReturnPath(chapterUrl)}>{t(target === "reader" ? "read_from_chapter" : "listen_from_start")}</a>
    <button onClick={onClose}>{t("cancel")}</button>
  </MediaSheet>;
}
