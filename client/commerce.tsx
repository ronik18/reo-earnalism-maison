import { useEffect, useRef, useState } from "react";
import { mountIsland } from "./lifecycle";
import { api, t, errorText, locale, readBootstrap } from "./api";
import {
  offerSnapshotKey,
  validCheckout,
  accessGranted,
  orderStatusKey,
  checkoutReturnPath,
  type Money,
  type Checkout,
} from "./commerce-state";
interface Offer {
  offer_id: string;
  version: number;
  name: string;
  availability: string;
  price: Money | null;
  terms_version: string;
  terms_summary: string;
}
interface Order {
  order_id: string;
  status: string;
  fulfillment_status: string;
  amount: Money;
  checkout: Checkout | null;
  return_path?: string;
  expires_at?: string;
}
interface Callback {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}
interface Widget {
  open: () => void;
  on: (event: string, callback: () => void) => void;
}
declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => Widget;
  }
}
let sdk: Promise<void> | undefined;
function loadSDK() {
  return (sdk ??= new Promise<void>((resolve, reject) => {
    if (window.Razorpay) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    const timeout = setTimeout(() => {
      script.remove();
      sdk = undefined;
      reject(new Error("checkout_unavailable"));
    }, 15000);
    script.onload = () => {
      clearTimeout(timeout);
      resolve();
    };
    script.onerror = () => {
      clearTimeout(timeout);
      script.remove();
      sdk = undefined;
      reject(new Error("checkout_unavailable"));
    };
    document.head.append(script);
  }));
}
function Commerce() {
  const bootstrap = readBootstrap<{order_id?: string; return_path?: string}>("commerce-bootstrap");
  const checkoutPage = !!bootstrap.order_id;
  const [online, setOnline] = useState(navigator.onLine);
  const authenticated = !!document.body.dataset.memberId;
  const [offers, setOffers] = useState<Offer[] | undefined>(),
    [status, setStatus] = useState(""),
    [order, setOrder] = useState<Order>(),
    [busy, setBusy] = useState(false);
  const pendingOrderKey =
    "maison.checkout.order:" + (document.body.dataset.memberId || "guest");
  const keys = useRef(new Map<string, string>()),
    active = useRef(true);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); };
  }, []);
  useEffect(() => {
    active.current = true;
    try {
      const pending = bootstrap.order_id || sessionStorage.getItem(pendingOrderKey);
      if (pending && /^[a-f0-9-]{36}$/i.test(pending)) {
        setBusy(true);
        void api<Order>("/commerce/orders/" + pending)
          .then((value) => {
            if (active.current) setOrder(value);
          })
          .catch((error) => {
            if (
              error instanceof Error &&
              "status" in error &&
              [403, 404].includes(Number(error.status))
            )
              sessionStorage.removeItem(pendingOrderKey);
            if (active.current) setStatus(errorText(error));
          })
          .finally(() => {
            if (active.current) setBusy(false);
          });
      }
    } catch {}

    if (authenticated && !checkoutPage) api<{ items: Offer[] }>("/commerce/offers")
      .then((data) => {
        if (active.current) setOffers(data.items);
      })
      .catch((error) => {
        if (active.current) {
          setOffers([]);
          setStatus(errorText(error));
        }
      });
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (
      !order ||
      !["creating", "created", "pending", "paid"].includes(order.status) ||
      accessGranted(order)
    )
      return;
    let cancelled = false,
      attempts = 0;
    const timer = setInterval(() => {
      if (++attempts >= 20) clearInterval(timer);
      if (!navigator.onLine) return;
      void api<Order>("/commerce/orders/" + order.order_id)
        .then((value) => {
          if (!cancelled) setOrder(value);
        })
        .catch((error) => {
          if (!cancelled) setStatus(errorText(error));
        });
    }, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [order?.order_id, order?.status, order?.fulfillment_status]);
  async function create(offer: Offer) {
    setBusy(true);
    try {
      const snapshot = offerSnapshotKey(offer);
      const storageKey =
        "maison.checkout.retry:" +
        (document.body.dataset.memberId || "guest") +
        ":" +
        snapshot;
      let stored: string | null = null;
      try {
        stored = sessionStorage.getItem(storageKey);
      } catch {}
      const key = keys.current.get(snapshot) || stored || crypto.randomUUID();
      try { sessionStorage.setItem(storageKey, key); } catch {}
      keys.current.set(snapshot, key);
      const result = await api<Order>("/commerce/orders", {
        method: "POST",
        key,
        body: {
          offer_id: offer.offer_id,
          offer_version: offer.version,
          terms_version: offer.terms_version,
          return_path: checkoutReturnPath(bootstrap.return_path,locale),
        },
      });
      setOrder(result);
      try { sessionStorage.setItem(pendingOrderKey, result.order_id); sessionStorage.removeItem(storageKey); } catch {}
      keys.current.delete(snapshot);
      setStatus("");
      window.location.assign(`/${locale}/checkout/${result.order_id}/`);
    } catch (error) {
      setStatus(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  async function pay() {
    if (!online || !order || !validCheckout(order.checkout, order.amount)) return;
    setBusy(true);
    try {
      await loadSDK();
      const checkout = order.checkout;
      const widget = new window.Razorpay!({
        key: checkout.public_key_id,
        order_id: checkout.provider_order_id,
        amount: checkout.amount.amount_minor,
        currency: checkout.amount.currency,
        name: checkout.name,
        description: checkout.description,
        handler: (callback: Callback) => {
          void api<Order>(`/commerce/orders/${order.order_id}/verify`, {
            method: "POST",
            key: crypto.randomUUID(),
            body: callback,
          })
            .then((result) => {
              if (active.current) {
                setOrder(result);
                setStatus(
                  accessGranted(result)
                    ? t("payment_confirmed")
                    : t(orderStatusKey(result)),
                );
              }
            })
            .catch((error) => setStatus(errorText(error)))
            .finally(() => { if (active.current) setBusy(false); });
        },
        modal: {
          ondismiss: () => {
            if (active.current) {setStatus(t("payment_pending"));setBusy(false);}
          },
        },
      });
      widget.on("payment.failed", () => {if (active.current) {setStatus(t("payment_not_completed"));setBusy(false);}});
      widget.open();
    } catch (error) {
      setStatus(errorText(error));
      setBusy(false);
    }
  }
  return (
    <section aria-busy={busy}>
      <p role="status" aria-live="polite">{status}</p>
      {!online ? <p className="notice">{t("purchase_online_only")}</p> : null}
      {!authenticated ? <div className="empty-state"><h2>{t("pass_guest_title")}</h2><p>{t("pass_guest_help")}</p><a className="button" href={`/${locale}/sign-in/?return_to=${encodeURIComponent(`/${locale}/pass/`)}`}>{t("sign_in")}</a></div> : null}
      {checkoutPage && !order && !busy ? <div className="empty-state"><p>{t("order_unavailable")}</p><button onClick={() => window.location.reload()}>{t("retry")}</button><a href={`/${locale}/pass/`}>{t("choose_another_offer")}</a></div> : null}
      {!authenticated || checkoutPage ? null : offers === undefined ? (
        <p>{t("loading")}</p>
      ) : !offers.length ? (
        <p>{t("no_offer")}</p>
      ) : (
        offers.map((offer) => (
          <article className="offer-card" key={offer.offer_id}>
            <h2>{offer.name}</h2>
            <p>{offer.terms_summary}</p>
            <p className="fine">{t("fixed_duration_notice")}</p>
            {offer.price ? (
              <p>
                {new Intl.NumberFormat(locale, {
                  style: "currency",
                  currency: offer.price.currency,
                }).format(offer.price.amount_minor / 100)}
              </p>
            ) : null}
            <button
              disabled={
                busy || !online ||
                !!order ||
                offer.availability !== "available" ||
                !offer.price
              }
              onClick={() => void create(offer)}
            >
              {t("continue_checkout")}
            </button>
          </article>
        ))
      )}
      {order ? (
        <section>
          <h2>{t("order_status")}</h2>
          <p role="status">{t(orderStatusKey(order))}</p>
          <p>{new Intl.NumberFormat(locale, {style:"currency", currency:order.amount.currency}).format(order.amount.amount_minor / 100)}</p>
          {accessGranted(order) ? <a className="button" href={checkoutReturnPath(order.return_path,locale)}>{t("return_to_content")}</a> : null}
          <p>
            {t("order_reference")}: {order.order_id}
          </p>
          {validCheckout(order.checkout, order.amount) ? (
            <button disabled={busy || !online} onClick={() => void pay()}>
              {t("pay_securely")}
            </button>
          ) : null}
          <button
            disabled={busy || !online}
            onClick={() =>
              void api<Order>("/commerce/orders/" + order.order_id)
                .then(setOrder)
                .catch((error) => setStatus(errorText(error)))
            }
          >
            {t("refresh_status")}
          </button>
          {!validCheckout(order.checkout, order.amount) && !accessGranted(order) && !["failed","cancelled","expired","refunded"].includes(order.status) ? <p className="fine">{t("checkout_provider_unavailable")}</p> : null}
          {accessGranted(order)||["failed","cancelled","expired","refunded"].includes(order.status)?<a href={`/${locale}/pass/`} onClick={()=>{try { sessionStorage.removeItem(pendingOrderKey); } catch {}}}>{t("choose_another_offer")}</a>:null}
        </section>
      ) : null}
    </section>
  );
}
export function mount() {
  mountIsland(document.getElementById("commerce-island"), () => <Commerce />);
}
mount();
