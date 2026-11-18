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
  return order.status === "paid" && order.fulfillment_status === "fulfilled";
}

export function offerSnapshotKey(offer: {
  offer_id: string;
  version: number;
  terms_version: string;
}): string {
  return JSON.stringify([offer.offer_id, offer.version, offer.terms_version]);
}
