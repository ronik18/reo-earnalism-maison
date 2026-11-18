import { validReturnPath } from "./state";
export interface Money {
  amount_minor: number;
  currency: string;
}
export interface Checkout {
  provider: string;
  public_key_id: string;
  provider_order_id: string;
  amount: Money;
  name: string;
  description: string;
}
export function validCheckout(
  checkout: Checkout | null,
  amount: Money,
): checkout is Checkout {
  return (
    !!checkout &&
    checkout.provider === "razorpay" &&
    /^rzp_(test|live)_[A-Za-z0-9]+$/.test(checkout.public_key_id) &&
    /^order_[A-Za-z0-9]+$/.test(checkout.provider_order_id) &&
    Number.isSafeInteger(amount.amount_minor) &&
    amount.amount_minor > 0 &&
    checkout.amount.amount_minor === amount.amount_minor &&
    checkout.amount.currency === amount.currency
  );
}
export function accessGranted(order: {
  status: string;
  fulfillment_status: string;
}): boolean {
  return order.status === "paid" && order.fulfillment_status === "granted";
}

export function offerSnapshotKey(offer: {
  offer_id: string;
  version: number;
  terms_version: string;
}): string {
  return JSON.stringify([offer.offer_id, offer.version, offer.terms_version]);
}

export function orderStatusKey(order: {status:string;fulfillment_status:string}): string {
  if (accessGranted(order)) return "payment_confirmed";
  if (order.fulfillment_status === "refund_pending") return "payment_refund_pending";
  if (order.fulfillment_status === "refunded" || order.status === "refunded") return "order_refunded";
  if (order.status === "paid") return "payment_access_pending";
  return ["failed", "cancelled", "expired"].includes(order.status) ? "order_" + order.status : "payment_pending";
}

export function checkoutReturnPath(value: string | undefined, locale="en"):string {
  if (!value) return `/${locale}/vault/`;
  const path=validReturnPath(value,locale);
  return /^\/(en|bn)\/(checkout|sign-in|sign-up|sign-out|password-reset)(\/|\?|$)/.test(path) || path===`/${locale}/` ? `/${locale}/vault/` : path;
}
