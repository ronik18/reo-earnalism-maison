import { useEffect, useRef, useState } from "react";
import { mountIsland } from "./lifecycle";
import { api, t, errorText, locale } from "./api";
import {
  offerSnapshotKey,
  validCheckout,
  accessGranted,
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
  const [offers, setOffers] = useState<Offer[] | undefined>(),
    [status, setStatus] = useState(""),
    [order, setOrder] = useState<Order>(),
    [busy, setBusy] = useState(false);
  const pendingOrderKey =
    "maison.checkout.order:" + (document.body.dataset.memberId || "guest");
  const keys = useRef(new Map<string, string>()),
    active = useRef(true);
  useEffect(() => {
    active.current = true;
    try {
      const pending = sessionStorage.getItem(pendingOrderKey);
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

    api<{ items: Offer[] }>("/commerce/offers")
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
      !["creating", "pending", "paid"].includes(order.status) ||
      accessGranted(order)
    )
      return;
    let cancelled = false,
      attempts = 0;
    const timer = setInterval(() => {
      if (++attempts >= 20) clearInterval(timer);
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
      sessionStorage.setItem(storageKey, key);
      keys.current.set(snapshot, key);
      const result = await api<Order>("/commerce/orders", {
        method: "POST",
        key,
        body: {
          offer_id: offer.offer_id,
          offer_version: offer.version,
          terms_version: offer.terms_version,
          return_path: `/${locale}/pass/`,
        },
      });
      setOrder(result);
      sessionStorage.setItem(pendingOrderKey, result.order_id);
      sessionStorage.removeItem(storageKey);
      keys.current.delete(snapshot);
      setStatus("");
    } catch (error) {
      setStatus(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  async function pay() {
    if (!order || !validCheckout(order.checkout, order.amount)) return;
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
                    : t("payment_pending"),
                );
              }
            })
            .catch((error) => setStatus(errorText(error)));
        },
        modal: {
          ondismiss: () => {
            if (active.current) setStatus(t("payment_pending"));
          },
        },
      });
      widget.on("payment.failed", () => setStatus(t("payment_not_completed")));
      widget.open();
    } catch (error) {
      setStatus(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <p role="status">{status}</p>
      {offers === undefined ? (
        <p>{t("loading")}</p>
      ) : !offers.length ? (
        <p>{t("no_offer")}</p>
      ) : (
        offers.map((offer) => (
          <article key={offer.offer_id}>
            <h2>{offer.name}</h2>
            <p>{offer.terms_summary}</p>
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
                busy ||
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
          <p>
            {accessGranted(order)
              ? t("payment_confirmed")
              : t("payment_pending")}
          </p>
          <p>
            {t("order_reference")}: {order.order_id}
          </p>
          {validCheckout(order.checkout, order.amount) ? (
            <button disabled={busy} onClick={() => void pay()}>
              {t("pay_securely")}
            </button>
          ) : null}
          <button
            disabled={busy}
            onClick={() =>
              void api<Order>("/commerce/orders/" + order.order_id)
                .then(setOrder)
                .catch((error) => setStatus(errorText(error)))
            }
          >
            {t("refresh_status")}
          </button>
          {accessGranted(order)||["failed","cancelled","expired","refunded"].includes(order.status)?<button onClick={()=>{sessionStorage.removeItem(pendingOrderKey);setOrder(undefined)}}>{t("choose_another_offer")}</button>:null}
        </section>
      ) : null}
    </section>
  );
}
export function mount() {
  mountIsland(document.getElementById("commerce-island"), () => <Commerce />);
}
mount();
