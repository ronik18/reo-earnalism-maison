import test from "node:test";
import assert from "node:assert/strict";
import {
  codePointOffset,
  samePosition,
  pageCount,
  sleepDeadline,
  timerExpired,
  measuredSeek,
  validReturnPath,
} from "./state.ts";
test("Unicode selection offsets use code points, including Bengali and astral characters", () => {
  assert.equal(codePointOffset("আ🌸লো", 3), 2);
  assert.equal(codePointOffset("A🌸B", 3), 2);
});
test("Intentional rereading is a distinct semantic location", () => {
  const a = {
    format: "reader" as const,
    unit_id: "u",
    anchor_id: "a",
    offset_chars: 3,
  };
  assert.equal(samePosition(a, { ...a, offset_chars: 0 }), false);
  assert.equal(samePosition(a, { ...a }), true);
});
test("Pagination tolerates an unmeasured viewport and includes the last column", () => {
  assert.equal(pageCount(0, 0), 1);
  assert.equal(pageCount(1250, 600), 2);
});
test("Sleep uses an elapsed monotonic deadline, not wall-clock changes", () => {
  const d = sleepDeadline(5, 100);
  assert.equal(d, 300100);
  assert.equal(timerExpired(d, 300099), false);
  assert.equal(timerExpired(d, 300100), true);
  assert.equal(sleepDeadline(0, 100), undefined);
});
test("Exact format switching rejects overlapping or out-of-bounds maps", () => {
  const rows = [
    { unit_id: "u", anchor_id: "a", start_ms: 0, end_ms: 200 },
    { unit_id: "u", anchor_id: "b", start_ms: 200, end_ms: 400 },
  ];
  assert.equal(measuredSeek(rows, "b", 500), 200);
  assert.equal(
    measuredSeek([{ ...rows[0], end_ms: 600 }], "a", 500),
    undefined,
  );
  assert.equal(
    measuredSeek([rows[0], { ...rows[1], start_ms: 100 }], "b", 500),
    undefined,
  );
  assert.equal(measuredSeek(rows, "missing", 500), undefined);
});
test("Player return links canonicalize legacy UI paths without changing the edition", () => {
  assert.equal(validReturnPath("https://evil.invalid/"), " /en/".trim());
  assert.equal(validReturnPath("//evil.invalid/"), "/en/");
  assert.equal(
    validReturnPath("/bn/read/book/?anchor=a"),
    "/en/read/book/?anchor=a",
  );
});
import { planEnqueue, nextBatch } from "./queue-state.ts";
test("Offline queue coalesces only unsent progress and never drops notes or uncertain writes", () => {
  const progress = {
    operation_id: "p1",
    kind: "progress.set",
    edition_id: "e",
    location: { format: "reader" },
  };
  const note = {
    operation_id: "n1",
    kind: "annotation.create",
    annotation: { note_text: "keep" },
  };
  const old = [
    { operation: progress, attempted: false },
    { operation: note, attempted: false },
  ];
  const updated = planEnqueue(old, { ...progress, operation_id: "p2" });
  assert.deepEqual(
    updated.map((x) => x.operation.operation_id),
    ["n1", "p2"],
  );
  assert.equal(
    planEnqueue([{ operation: progress, attempted: true }], {
      ...progress,
      operation_id: "p2",
    }).length,
    2,
  );
});
test("Offline queue enforces bounds and forbids financial or staff operations", () => {
  assert.throws(() =>
    planEnqueue([], { operation_id: "x", kind: "payment.create" }),
  );
  assert.throws(() =>
    planEnqueue(
      Array.from({ length: 500 }, (_, i) => ({
        operation: { operation_id: String(i), kind: "annotation.create" },
        attempted: false,
      })),
      { operation_id: "n", kind: "annotation.create" },
    ),
  );
  assert.throws(() =>
    planEnqueue([], {
      operation_id: "large",
      kind: "annotation.create",
      text: "x".repeat(2097152),
    }),
  );
});
test("Sync batch skips blocked conflicts and respects the API100-operation boundary", () => {
  const rows = Array.from({ length: 120 }, (_, i) => ({
    operation: { operation_id: String(i), kind: "saved.set" },
    attempted: false,
    blocked: i === 0,
  }));
  assert.equal(nextBatch(rows).length, 100);
  assert.equal(nextBatch(rows)[0].operation.operation_id, "1");
});

import { meaningfulSelection } from "./state";
test("Passage capture rejects blank browser selections but retains Bengali text", () => {
  assert.equal(meaningfulSelection("\n\t \u00a0\u200b"), false);
  assert.equal(meaningfulSelection("The Giant"), true);
  assert.equal(meaningfulSelection("বাগান"), true);
});

import { newestProgress, progressConflictDecision } from "./state";
test("A delayed GET cannot regress a confirmed progress PUT snapshot", () => {
  const location = {
    format: "reader" as const,
    unit_id: "unit",
    anchor_id: "anchor",
    offset_chars: 4,
  };
  const put = { version: 9, location, last_operation_id: "own-write" };
  const staleGet = {
    version: 8,
    location: { ...location, offset_chars: 0 },
    last_operation_id: "old-write",
  };
  assert.equal(newestProgress(put, staleGet), put);
  assert.equal(newestProgress(undefined, staleGet), staleGet);
  assert.equal(newestProgress(staleGet, put), put);
});
test("Progress conflicts distinguish an accepted position, own late writes and another device", () => {
  const position = {
    format: "reader" as const,
    unit_id: "unit",
    anchor_id: "anchor",
    offset_chars: 4,
  };
  const latest = {
    version: 9,
    location: { ...position, offset_chars: 0 },
    last_operation_id: "own-write",
  };
  assert.equal(
    progressConflictDecision(latest, position, new Set(["own-write"])),
    "retry_own",
  );
  assert.equal(
    progressConflictDecision(
      { ...latest, last_operation_id: "other-device" },
      position,
      new Set(["own-write"]),
    ),
    "conflict",
  );
  assert.equal(
    progressConflictDecision(
      { ...latest, last_operation_id: null },
      position,
      new Set(["own-write"]),
    ),
    "conflict",
  );
  assert.equal(
    progressConflictDecision(
      { ...latest, location: position, last_operation_id: "other-device" },
      position,
      new Set(),
    ),
    "already_saved",
  );
});

import { recoverNote } from "./queue-state";
import { IslandLifetime } from "./lifetime-state";
import { internalPageURL, preservePlayer } from "./navigation-state";
import { validCheckout, accessGranted } from "./commerce-state";
test("Queued note retry preserves uncertain payload and IDs; explicit edit creates new IDs", () => {
  const original = {
    operation: {
      operation_id: "old-op",
      kind: "annotation.create",
      occurred_at: "2026-11-18T00:00:00Z",
      annotation: {
        annotation_id: "old-note",
        kind: "note",
        note_text: "original",
      },
    },
    attempted: true,
    blocked: true,
    problem: "invalid_anchor",
  };
  const other = {
    operation: { operation_id: "other", kind: "progress.set" },
    attempted: false,
  };
  const retried = recoverNote([original, other], "old-op", "retry");
  assert.equal(retried[0].operation, original.operation);
  assert.equal(retried[0].attempted, true);
  assert.equal(retried[0].blocked, false);
  assert.equal(retried[1], other);
  const edited = recoverNote([original, other], "old-op", "replace", {
    operation_id: "new-op",
    annotation_id: "new-note",
    note_text: "edited",
    occurred_at: "2026-11-18T01:00:00Z",
  });
  assert.equal(edited[1].operation.operation_id, "new-op");
  assert.equal(
    (edited[1].operation.annotation as { annotation_id: string }).annotation_id,
    "new-note",
  );
  assert.equal(edited[1].attempted, false);
  assert.equal(original.operation.annotation.note_text, "original");
  assert.deepEqual(recoverNote([original, other], "old-op", "delete"), [other]);
  assert.throws(() =>
    recoverNote([{ ...original, blocked: false }], "old-op", "replace", {
      operation_id: "x",
      annotation_id: "y",
      note_text: "edited",
      occurred_at: "now",
    }),
  );
});
test("SSR page disposal retains exactly the live audio island until explicit close", () => {
  let pageStops = 0,
    audioStops = 0,
    removed = "";
  const lifetime = new IslandLifetime<string, { unmount: () => void }>();
  const audio = { unmount: () => audioStops++ };
  lifetime.add("page", { unmount: () => pageStops++ });
  lifetime.add("audio", audio, true);
  lifetime.disposePage();
  assert.equal(pageStops, 1);
  assert.equal(audioStops, 0);
  assert.equal(lifetime.roots.get("audio")?.root, audio);
  lifetime.disposePage();
  assert.equal(audioStops, 0);
  lifetime.closePersistent((host) => (removed = host));
  assert.equal(audioStops, 1);
  assert.equal(removed, "audio");
  assert.equal(lifetime.roots.size, 0);
});
test("Persistent navigation preserves auth boundaries and native hash/external links", () => {
  const base = "https://example.test/en/listen/book/";
  assert.equal(internalPageURL("/bn/explore/", base)?.pathname, "/bn/explore/");
  for (const path of [
    "https://other.test/en/",
    "/admin/",
    "/api/v1/session",
    "/en/sign-out/",
    "/bn/email-sign-in/",
    "#chapter",
  ]) {
    assert.equal(internalPageURL(path, base), undefined);
  }
  assert.equal(
    preservePlayer("true", "true", 200, "text/html; charset=utf-8"),
    true,
  );
  assert.equal(preservePlayer("true", "false", 200, "text/html"), false);
  assert.equal(preservePlayer("true", "true", 403, "text/html"), false);
});
test("Checkout cannot claim access from a callback or mismatched descriptor", () => {
  const amount = { amount_minor: 500, currency: "INR" };
  const checkout = {
    provider: "razorpay",
    public_key_id: "rzp_test_abc123",
    provider_order_id: "order_abc123",
    amount,
    name: "Earnalism",
    description: "Test",
  };
  assert.equal(validCheckout(checkout, amount), true);
  assert.equal(
    validCheckout(
      { ...checkout, amount: { ...amount, amount_minor: 1 } },
      amount,
    ),
    false,
  );
  assert.equal(validCheckout(null, amount), false);
  assert.equal(
    accessGranted({ status: "paid", fulfillment_status: "pending" }),
    false,
  );
  assert.equal(
    accessGranted({ status: "paid", fulfillment_status: "granted" }),
    true,
  );
});

import { trustedIslandModule, sameShellBuild } from "./navigation-state";
test("Island modules follow the trusted bundle CDN directory and deployment shell", () => {
  const cdn =
    "https://assets.example.test/releases/maison/dist/shell-ABC123.js";
  assert.equal(
    trustedIslandModule(
      "https://assets.example.test/releases/maison/dist/reader-XYZ789.js",
      cdn,
    ),
    true,
  );
  assert.equal(
    trustedIslandModule(
      "https://app.example.test/static/maison/dist/reader-XYZ789.js",
      cdn,
    ),
    false,
  );
  for (const src of [
    "https://evil.test/releases/maison/dist/reader.js",
    "https://assets.example.test/releases/other/reader.js",
    "https://assets.example.test/releases/maison/dist/nested/reader.js",
    "https://assets.example.test/releases/maison/dist/%2e%2e/reader.js",
    "https://user:password@assets.example.test/releases/maison/dist/reader.js",
    "https://assets.example.test/releases/maison/dist/reader.js?redirect=evil",
  ]) {
    assert.equal(trustedIslandModule(src, cdn), false);
  }
  assert.equal(sameShellBuild(cdn, cdn), true);
  assert.equal(
    sameShellBuild(
      "https://assets.example.test/releases/maison/dist/shell-NEW123.js",
      cdn,
    ),
    false,
  );
  assert.equal(
    sameShellBuild(
      "https://assets.example.test/releases/new/dist/shell-ABC123.js",
      cdn,
    ),
    false,
  );
  assert.equal(
    trustedIslandModule(
      "http://localhost:8009/static/maison/dist/reader-XYZ789.js",
      "http://localhost:8009/static/maison/dist/shell-ABC123.js",
    ),
    true,
  );
});

import { LatestNavigation } from "./navigation-state";
import { offerSnapshotKey } from "./commerce-state";
test("A later navigation aborts the stale fetch without cancelling the new page", () => {
  const navigation = new LatestNavigation();
  const first = navigation.begin(),
    second = navigation.begin();
  assert.equal(first.signal.aborted, true);
  assert.equal(navigation.current(first), false);
  assert.equal(navigation.current(second), true);
  navigation.finish(first);
  assert.equal(navigation.current(second), true);
  navigation.finish(second);
  assert.equal(navigation.current(second), false);
});
test("Checkout retry identity is scoped to the immutable offer and terms snapshot", () => {
  const offer = { offer_id: "book", version: 1, terms_version: "terms1" };
  assert.equal(offerSnapshotKey(offer), offerSnapshotKey({ ...offer }));
  assert.notEqual(
    offerSnapshotKey(offer),
    offerSnapshotKey({ ...offer, offer_id: "other" }),
  );
  assert.notEqual(
    offerSnapshotKey(offer),
    offerSnapshotKey({ ...offer, version: 2 }),
  );
  assert.notEqual(
    offerSnapshotKey(offer),
    offerSnapshotKey({ ...offer, terms_version: "terms2" }),
  );
});

import {orderStatusKey} from "./commerce-state";
test("Checkout reflects server terminal states without granting pending or refunded access", () => {
  assert.equal(orderStatusKey({status:"paid",fulfillment_status:"granted"}),"payment_confirmed");
  for (const fulfillment_status of ["pending","refund_pending","refunded","review","fulfilled"]) {
    assert.equal(accessGranted({status:"paid",fulfillment_status}),false);
    assert.equal(orderStatusKey({status:"paid",fulfillment_status}),fulfillment_status === "refund_pending" ? "payment_refund_pending" : fulfillment_status === "refunded" ? "order_refunded" : "payment_access_pending");
  }
  for (const status of ["failed","cancelled","expired","refunded"]) {
    assert.equal(orderStatusKey({status,fulfillment_status:"pending"}),"order_"+status);
  }
});

// Media capabilities remain bound to their actual format and exact edition revision.
import "./media-state.test.ts";

import {checkoutReturnPath} from "./commerce-state";
test("Checkout retains exact content return in the shared English journey",()=>{
  assert.equal(checkoutReturnPath("/en/read/book/unit/?anchor=p1&offset=12","bn"),"/en/read/book/unit/?anchor=p1&offset=12");
  for (const path of ["https://other.test/en/read/book/","//other.test/en/read/book/","/en/sign-out/","/en/checkout/order/"]) assert.equal(checkoutReturnPath(path,"bn"),"/en/vault/");
});

import {approvedFinancialPDFURL} from "./billing-state.ts";
test("Financial PDF grants remain fresh and bound to their local document route",()=>{
 const now=Date.now(),origin="https://maison.example",path="/api/v1/commerce/credit-notes/note/file";
 const grant={url:origin+path+"?token=fixture",expires_at:new Date(now+120000).toISOString(),content_type:"application/pdf",sha256:"a".repeat(64),bytes:100};
 assert.equal(approvedFinancialPDFURL(grant,path,origin,now),grant.url);
 assert.equal(approvedFinancialPDFURL(grant,"/api/v1/commerce/invoices/invoice/file",origin,now),undefined);
 for(const override of [{url:origin+"/en/sign-in/"},{url:"http://private.example/document"},{url:"https://user:secret@private.example/document"},{url:grant.url+"#token"},{expires_at:new Date(now).toISOString()},{expires_at:new Date(now+126000).toISOString()},{sha256:"bad"},{content_type:"text/html"}])assert.equal(approvedFinancialPDFURL({...grant,...override},path,origin,now),undefined);
 assert.equal(approvedFinancialPDFURL({...grant,url:"https://private.example/retained.pdf?signed=fixture"},path,origin,now),"https://private.example/retained.pdf?signed=fixture");
});


test("Stream renewal primes playback before real metadata and seeks once after load", async()=>{
  const original=globalThis.document;
  globalThis.document={getElementById:()=>null,documentElement:{dataset:{}}} as unknown as Document;
  try {
    const {streamRestoration}=await import("./video");
    let plays=0,position=0,current=true,restored=0;
    const sdk={duration:180,paused:true,controls:true,get currentTime(){return position},set currentTime(value:number){position=value},play:()=>{plays++;return Promise.resolve()},pause:()=>{},addEventListener:()=>{},removeEventListener:()=>{}};
    const lifecycle=streamRestoration(sdk,155000,true,()=>current,()=>assert.fail("Unexpected playback failure"),()=>{restored++});
    lifecycle.prime();assert.equal(plays,1);assert.equal(position,0);assert.equal(lifecycle.ready(),false);
    lifecycle.metadata();assert.equal(position,155);assert.equal(restored,1);
    position=157;lifecycle.metadata();assert.equal(position,157);assert.equal(restored,1);
    current=false;const stale=streamRestoration(sdk,80000,true,()=>current,()=>{},()=>assert.fail("Stale iframe restored"));stale.prime();stale.metadata();assert.equal(plays,1);assert.equal(position,157);
    const paused=streamRestoration(sdk,80000,false,()=>true,()=>{},()=>{});paused.prime();assert.equal(plays,1);paused.metadata();assert.equal(position,80);
  } finally {globalThis.document=original;}
});

import { downloadLicensePages } from "./download-pages.ts";
test("Download reconciliation includes licenses after the first page", async () => {
  const calls: string[] = [];
  const local = [{license_id:"older-saved-book"}];
  const remote = await downloadLicensePages<{license_id:string}>(async path => {
    calls.push(path);
    return calls.length === 1 ? {items:[{license_id:"new-book"}],next_cursor:"older+page/="} : {items:local,next_cursor:null};
  });
  assert.deepEqual(calls,["/me/downloads","/me/downloads?cursor=older%2Bpage%2F%3D"]);
  assert.equal(local.filter(book => !remote.some(row => row.license_id === book.license_id)).length,0);
});
test("A failed later download-license page yields no partial reconciliation snapshot", async () => {
  let calls=0, reconciled=false;
  await assert.rejects(async()=>{
    await downloadLicensePages(async()=>{
      if(++calls===2)throw new Error("connection lost");
      return {items:[{license_id:"new-book"}],next_cursor:"next"};
    });
    reconciled=true;
  },/connection lost/);
  assert.equal(calls,2);assert.equal(reconciled,false);
});
test("Download-license pagination rejects a repeated cursor before reconciliation", async () => {
  let calls=0;
  await assert.rejects(downloadLicensePages(async()=>{
    calls++;return {items:[],next_cursor:"same"};
  }),/download_failed/);
  assert.equal(calls,2);
});


test("Legacy UI return links preserve content language, query and anchor in the English journey",()=>{
 assert.equal(validReturnPath("/bn/read/book/unit/?content_locale=bn&anchor=p1#selection","bn"),"/en/read/book/unit/?content_locale=bn&anchor=p1#selection");
 assert.equal(checkoutReturnPath("/bn/read/book/unit/?anchor=p1","bn"),"/en/read/book/unit/?anchor=p1");
 assert.equal(validReturnPath("//other.test/bn/read/book/","bn"),"/en/");
});
