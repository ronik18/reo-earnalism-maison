import test from "node:test";
import assert from "node:assert/strict";
import {
  codePointOffset,
  samePosition,
  pageCount,
  sleepRemaining,
  fadeGain,
  FADE_MS,
  afterPartEnds,
  clockLabel,
  positionLabel,
  sleepTick,
  activeMarkerIndex,
  placeTitle,
  measuredSeek,
  validReturnPath,
  splitTitleSlot,
  initialReaderTheme,
  progressFraction,
  minutesRemaining,
  headingsFor,
  toolbarHidden,
  toolbarPinned,
  READER_FONT_SIZES,
  stepFont,
  alignmentOptions,
  effectiveAlignment,
  READER_WIDTHS,
  widthMeasure,
  PREFERENCE_SAVE_MS,
  createDebouncedSaver,
  stepLeading,
  radioKeyTarget,
  createSaveQueue,
  observedPosition,
} from "./state.ts";
import { readFileSync } from "node:fs";
import { wrapTextSpan } from "./follow-dom.ts";
import {
  splitSentences,
  currentHighlight,
  autoscrollAllowed,
  isUserScroll,
  mapFetchPlan,
  mapFailed,
  MAP_RETRY_MS,
  MAP_RETRY_MAX_MS,
  highlightSpan,
  utf16Index,
  domOffset,
  storedOffset,
  crlfIndexes,
  followScrollDelta,
  type FollowMap,
} from "./sentences.ts";
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
test("test_sleep_counts_playback_time_not_wall_time", () => {
  // 5 minute timer set after 100 s of listening; only listening time moves the clock.
  assert.equal(sleepRemaining(100000, 100000, 300000), 300000);
  assert.equal(sleepRemaining(100000 + 60000, 100000, 300000), 240000);
  assert.equal(sleepRemaining(100000 + 300000, 100000, 300000), 0);
  assert.equal(sleepRemaining(100000 + 400000, 100000, 300000), 0);
  assert.equal(sleepRemaining(50000, 100000, 300000), 300000);
  assert.equal(sleepRemaining(0, 0, Number.NaN), Infinity);
});
test("test_fade_is_15s_linear", () => {
  assert.equal(FADE_MS, 15000);
  assert.equal(fadeGain(60000), 1);
  assert.equal(fadeGain(15000), 1);
  assert.equal(fadeGain(7500), 0.5);
  assert.equal(fadeGain(3750), 0.25);
  assert.equal(fadeGain(0), 0);
  assert.equal(fadeGain(-5), 0);
  assert.equal(fadeGain(Infinity), 1);
});
test("test_end_of_part_on_last_part_stops", () => {
  assert.equal(afterPartEnds(2, 3, true), "stop");
  assert.equal(afterPartEnds(2, 3, false), "stop");
  assert.equal(afterPartEnds(0, 3, true), "stop");
  assert.equal(afterPartEnds(0, 3, false), "advance");
  assert.equal(afterPartEnds(0, 1, false), "stop");
});
test("clock and position labels are mm:ss after the title", () => {
  assert.equal(clockLabel(0), "00:00");
  assert.equal(clockLabel(65432), "01:05");
  assert.equal(clockLabel(3725000), "62:05");
  assert.equal(clockLabel(-4), "00:00");
  assert.equal(positionLabel("Chapter Two", 125000), "Chapter Two, 02:05");
  assert.equal(positionLabel("", 5000), "00:05");
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
    "/en/independent-account/",
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

import { orderStatusKey } from "./commerce-state";
test("Checkout reflects server terminal states without granting pending or refunded access", () => {
  assert.equal(
    orderStatusKey({ status: "paid", fulfillment_status: "granted" }),
    "payment_confirmed",
  );
  for (const fulfillment_status of [
    "pending",
    "refund_pending",
    "refunded",
    "review",
    "fulfilled",
  ]) {
    assert.equal(accessGranted({ status: "paid", fulfillment_status }), false);
    assert.equal(
      orderStatusKey({ status: "paid", fulfillment_status }),
      fulfillment_status === "refund_pending"
        ? "payment_refund_pending"
        : fulfillment_status === "refunded"
          ? "order_refunded"
          : "payment_access_pending",
    );
  }
  for (const status of ["failed", "cancelled", "expired", "refunded"]) {
    assert.equal(
      orderStatusKey({ status, fulfillment_status: "pending" }),
      "order_" + status,
    );
  }
});

// Media capabilities remain bound to their actual format and exact edition revision.
import "./media-state.test.ts";

import { checkoutReturnPath } from "./commerce-state";
test("Checkout retains exact content return in the shared English journey", () => {
  assert.equal(
    checkoutReturnPath("/en/read/book/unit/?anchor=p1&offset=12", "bn"),
    "/en/read/book/unit/?anchor=p1&offset=12",
  );
  for (const path of [
    "https://other.test/en/read/book/",
    "//other.test/en/read/book/",
    "/en/sign-out/",
    "/en/checkout/order/",
  ])
    assert.equal(checkoutReturnPath(path, "bn"), "/en/vault/");
});

import { approvedFinancialPDFURL } from "./billing-state.ts";
test("Financial PDF grants remain fresh and bound to their local document route", () => {
  const now = Date.now(),
    origin = "https://maison.example",
    path = "/api/v1/commerce/credit-notes/note/file";
  const grant = {
    url: origin + path + "?token=fixture",
    expires_at: new Date(now + 120000).toISOString(),
    content_type: "application/pdf",
    sha256: "a".repeat(64),
    bytes: 100,
  };
  assert.equal(approvedFinancialPDFURL(grant, path, origin, now), grant.url);
  assert.equal(
    approvedFinancialPDFURL(
      grant,
      "/api/v1/commerce/invoices/invoice/file",
      origin,
      now,
    ),
    undefined,
  );
  for (const override of [
    { url: origin + "/en/sign-in/" },
    { url: "http://private.example/document" },
    { url: "https://user:secret@private.example/document" },
    { url: grant.url + "#token" },
    { expires_at: new Date(now).toISOString() },
    { expires_at: new Date(now + 126000).toISOString() },
    { sha256: "bad" },
    { content_type: "text/html" },
  ])
    assert.equal(
      approvedFinancialPDFURL({ ...grant, ...override }, path, origin, now),
      undefined,
    );
  assert.equal(
    approvedFinancialPDFURL(
      { ...grant, url: "https://private.example/retained.pdf?signed=fixture" },
      path,
      origin,
      now,
    ),
    "https://private.example/retained.pdf?signed=fixture",
  );
});

test("Stream renewal primes playback before real metadata and seeks once after load", async () => {
  const original = globalThis.document;
  globalThis.document = {
    getElementById: () => null,
    documentElement: { dataset: {} },
  } as unknown as Document;
  try {
    const { streamRestoration } = await import("./video");
    let plays = 0,
      position = 0,
      current = true,
      restored = 0;
    const sdk = {
      duration: 180,
      paused: true,
      controls: true,
      get currentTime() {
        return position;
      },
      set currentTime(value: number) {
        position = value;
      },
      play: () => {
        plays++;
        return Promise.resolve();
      },
      pause: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
    };
    const lifecycle = streamRestoration(
      sdk,
      155000,
      true,
      () => current,
      () => assert.fail("Unexpected playback failure"),
      () => {
        restored++;
      },
    );
    lifecycle.prime();
    assert.equal(plays, 1);
    assert.equal(position, 0);
    assert.equal(lifecycle.ready(), false);
    lifecycle.metadata();
    assert.equal(position, 155);
    assert.equal(restored, 1);
    position = 157;
    lifecycle.metadata();
    assert.equal(position, 157);
    assert.equal(restored, 1);
    current = false;
    const stale = streamRestoration(
      sdk,
      80000,
      true,
      () => current,
      () => {},
      () => assert.fail("Stale iframe restored"),
    );
    stale.prime();
    stale.metadata();
    assert.equal(plays, 1);
    assert.equal(position, 157);
    const paused = streamRestoration(
      sdk,
      80000,
      false,
      () => true,
      () => {},
      () => {},
    );
    paused.prime();
    assert.equal(plays, 1);
    paused.metadata();
    assert.equal(position, 80);
  } finally {
    globalThis.document = original;
  }
});

import { downloadLicensePages } from "./download-pages.ts";
test("Download reconciliation includes licenses after the first page", async () => {
  const calls: string[] = [];
  const local = [{ license_id: "older-saved-book" }];
  const remote = await downloadLicensePages<{ license_id: string }>(
    async (path) => {
      calls.push(path);
      return calls.length === 1
        ? { items: [{ license_id: "new-book" }], next_cursor: "older+page/=" }
        : { items: local, next_cursor: null };
    },
  );
  assert.deepEqual(calls, [
    "/me/downloads",
    "/me/downloads?cursor=older%2Bpage%2F%3D",
  ]);
  assert.equal(
    local.filter(
      (book) => !remote.some((row) => row.license_id === book.license_id),
    ).length,
    0,
  );
});
test("A failed later download-license page yields no partial reconciliation snapshot", async () => {
  let calls = 0,
    reconciled = false;
  await assert.rejects(async () => {
    await downloadLicensePages(async () => {
      if (++calls === 2) throw new Error("connection lost");
      return { items: [{ license_id: "new-book" }], next_cursor: "next" };
    });
    reconciled = true;
  }, /connection lost/);
  assert.equal(calls, 2);
  assert.equal(reconciled, false);
});
test("Download-license pagination rejects a repeated cursor before reconciliation", async () => {
  let calls = 0;
  await assert.rejects(
    downloadLicensePages(async () => {
      calls++;
      return { items: [], next_cursor: "same" };
    }),
    /download_failed/,
  );
  assert.equal(calls, 2);
});

test("Legacy UI return links preserve content language, query and anchor in the English journey", () => {
  assert.equal(
    validReturnPath(
      "/bn/read/book/unit/?content_locale=bn&anchor=p1#selection",
      "bn",
    ),
    "/en/read/book/unit/?content_locale=bn&anchor=p1#selection",
  );
  assert.equal(
    checkoutReturnPath("/bn/read/book/unit/?anchor=p1", "bn"),
    "/en/read/book/unit/?anchor=p1",
  );
  assert.equal(validReturnPath("//other.test/bn/read/book/", "bn"), "/en/");
});

import {
  rememberSpeed,
  recallSpeed,
  mediaMetadataFor,
  seekTarget,
  withRendition,
} from "./state";
test("test_speed_is_remembered_and_clamped", () => {
  const store = new Map<string, string>();
  (globalThis as any).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
  };
  assert.equal(recallSpeed(), 1);
  rememberSpeed(1.5);
  assert.equal(store.get("maison.player.rate"), "1.5");
  assert.equal(recallSpeed(), 1.5);
  rememberSpeed(5);
  assert.equal(recallSpeed(), 2);
  rememberSpeed(0.1);
  assert.equal(recallSpeed(), 0.75);
  store.set("maison.player.rate", "junk");
  assert.equal(recallSpeed(), 1);
  store.set("maison.player.rate", "9");
  assert.equal(recallSpeed(), 2);
  (globalThis as any).localStorage = {
    getItem() {
      throw new Error("blocked");
    },
    setItem() {
      throw new Error("blocked");
    },
  };
  assert.equal(recallSpeed(), 1);
  assert.doesNotThrow(() => rememberSpeed(1.25));
  delete (globalThis as any).localStorage;
});
test("test_media_metadata_has_author_part_and_artwork", () => {
  const m = mediaMetadataFor(
    { title: "Book", author: "A. Writer", cover_url: "/c.webp" },
    { title: "Chapter 2" },
  );
  assert.equal(m.title, "Chapter 2");
  assert.equal(m.artist, "A. Writer");
  assert.equal(m.album, "Book");
  assert.equal(m.artwork.length, 1);
  assert.equal(m.artwork[0].src, "/c.webp");
  assert.deepEqual(
    mediaMetadataFor({ title: "Book" }, { title: "" }).artwork,
    [],
  );
  assert.equal(m.artwork[0].sizes, undefined);
  assert.equal(
    mediaMetadataFor(
      {
        title: "Book",
        cover_url: "/c.webp",
        cover_width: 600,
        cover_height: 900,
      },
      { title: "x" },
    ).artwork[0].sizes,
    "600x900",
  );
  assert.equal(
    mediaMetadataFor({ title: "Book" }, { title: "" }).title,
    "Book",
  );
});
test("test_media_metadata_omits_artist_without_author", () => {
  const m = mediaMetadataFor({ title: "Book" }, { title: "Part" });
  assert.equal("artist" in m, false);
  assert.equal(
    mediaMetadataFor({ title: "Book", author: "" }, { title: "Part" }).artist,
    undefined,
  );
});
test("test_rendition_swap_changes_asset_not_unit", () => {
  const unit = {
    asset_id: "a48",
    unit_id: "u1",
    title: "One",
    quality_kbps: 48,
    sha256: "x",
    duration_ms: 1000,
  };
  const out = withRendition(unit, {
    asset_id: "a96",
    quality_kbps: 96,
    sha256: "y",
    duration_ms: 1010,
  });
  assert.deepEqual(
    [
      out.asset_id,
      out.unit_id,
      out.title,
      out.quality_kbps,
      out.sha256,
      out.duration_ms,
    ],
    ["a96", "u1", "One", 96, "y", 1010],
  );
  assert.equal(withRendition(unit, undefined), unit);
  assert.equal(unit.asset_id, "a48");
});
test("test_seek_back_15_forward_30_clamp_to_bounds", () => {
  assert.equal(seekTarget(100, -15, 600), 85);
  assert.equal(seekTarget(100, 30, 600), 130);
  assert.equal(seekTarget(10, -15, 600), 0);
  assert.equal(seekTarget(590, 30, 600), 600);
  assert.equal(seekTarget(5, 30, NaN), 35);
  assert.equal(seekTarget(5, -15, Infinity), 0);
});

const base = {
  paused: false,
  ended: false,
  elapsedMs: 250,
  playedMs: 0,
  timer: undefined,
  endOfPart: false,
  unitMs: 600000,
  currentMs: 0,
  rate: 1,
};
test("sleepTick does not count paused or ended time", () => {
  const timer = { setAt: 0, ms: 60000 };
  assert.equal(
    sleepTick({ ...base, timer, paused: true, elapsedMs: 1000 }).playedMs,
    0,
  );
  assert.equal(
    sleepTick({ ...base, timer, ended: true, elapsedMs: 1000 }).playedMs,
    0,
  );
  assert.equal(
    sleepTick({ ...base, timer, paused: true, elapsedMs: 1000 }).action,
    "none",
  );
  assert.equal(sleepTick({ ...base, timer, elapsedMs: 250 }).playedMs, 250);
});
test("sleepTick caps one tick at 2000 ms so a long system sleep cannot stop the timer at once", () => {
  const timer = { setAt: 0, ms: 60000 };
  const r = sleepTick({ ...base, timer, elapsedMs: 3600000, playedMs: 10000 });
  assert.equal(r.playedMs, 12000);
  assert.equal(r.action, "none");
});
test("sleepTick: a minutes timer fades over the last 15 s and stops at 0", () => {
  const timer = { setAt: 0, ms: 60000 };
  assert.deepEqual(sleepTick({ ...base, timer, playedMs: 30000 }), {
    playedMs: 30250,
    action: "none",
    gain: 1,
  });
  const mid = sleepTick({ ...base, timer, playedMs: 52250 });
  assert.equal(mid.action, "fade");
  assert.equal(mid.gain, 0.5);
  const last = sleepTick({ ...base, timer, playedMs: 59750 });
  assert.equal(last.action, "stop");
  assert.equal(last.gain, 1);
  assert.equal(fadeGain(0), 0);
});
test("sleepTick: end of part fades in real time and stops at the end", () => {
  const eop = { ...base, endOfPart: true, unitMs: 100000, rate: 2 };
  assert.equal(sleepTick({ ...eop, currentMs: 50000 }).action, "none");
  // 15 s of media left at 2x is 7.5 s of real time: half of the fade remains.
  const mid = sleepTick({ ...eop, currentMs: 85000 });
  assert.equal(mid.action, "fade");
  assert.equal(mid.gain, 0.5);
  const end = sleepTick({ ...eop, currentMs: 100000 });
  assert.equal(end.action, "stop");
  assert.equal(end.gain, 1);
});
test("sleepTick with no timer or after cancel leaves the volume alone", () => {
  assert.deepEqual(sleepTick({ ...base, currentMs: 599000 }), {
    playedMs: 250,
    action: "none",
    gain: 1,
  });
});
test("active marker and place titles", () => {
  const markers = [
    { title: "One", start_ms: 0 },
    { title: "Two", start_ms: 60000 },
  ];
  assert.equal(activeMarkerIndex(markers, 59999), 0);
  assert.equal(activeMarkerIndex(markers, 60000), 1);
  assert.equal(activeMarkerIndex(undefined, 5), -1);
  assert.equal(activeMarkerIndex([{ title: "Late", start_ms: 10 }], 5), -1);
  assert.equal(placeTitle({ title: "Part", markers }, 61000), "Two");
  assert.equal(placeTitle({ title: "Part", markers }, 0), "One");
  assert.equal(placeTitle({ title: "Part" }, 61000), "Part");
  assert.equal(placeTitle(undefined, 5), "");
  assert.equal(
    positionLabel(placeTitle({ title: "Part", markers }, 61000), 61000),
    "Two, 01:01",
  );
});

const sentenceMap = (anchor: string): FollowMap => ({
  asset_id: "a",
  segments: [
    {
      anchor_id: anchor,
      start_ms: 0,
      end_ms: 1000,
      start_offset_chars: 0,
      end_offset_chars: 17,
      sentence_index: 0,
    },
    {
      anchor_id: anchor,
      start_ms: 1000,
      end_ms: 2500,
      start_offset_chars: 17,
      end_offset_chars: 35,
      sentence_index: 1,
    },
    {
      anchor_id: "unmeasured",
      start_ms: 2500,
      end_ms: 4000,
      start_offset_chars: 0,
      end_offset_chars: 60,
    },
  ],
});
test("test_split_matches_golden: client sentence offsets equal the shared Python golden", () => {
  const golden = JSON.parse(
    readFileSync("contracts/sentence-split-golden.json", "utf8"),
  );
  assert.ok(golden.cases.length >= 12);
  for (const c of golden.cases) {
    assert.deepEqual(splitSentences(c.text), c.offsets, c.name);
    // the golden is BMP-only, so UTF-16 indices and Python code points coincide
    assert.ok(
      ![...c.text].some((ch: string) => ch.codePointAt(0)! > 0xffff),
      c.name,
    );
    const spans = splitSentences(c.text);
    assert.deepEqual(
      spans.map(([a, b]) =>
        c.text.slice(a, b).split(/\s+/).filter(Boolean).join(" "),
      ),
      c.sentences,
      c.name,
    );
  }
});
test("code-point offsets from the API become UTF-16 indices for text with astral characters", () => {
  assert.equal(utf16Index("A🌸B", 2), 3);
  assert.equal(utf16Index("আমি", 2), 2);
  assert.deepEqual(highlightSpan("A🌸B. C", [2, 4]), [3, 5]);
  assert.deepEqual(highlightSpan("abc", null), [0, 3]);
  assert.deepEqual(highlightSpan("abc", [2, 2]), [0, 3]);
});
test("test_highlight_sentence_at_time", () => {
  const maps = [sentenceMap("p1")];
  assert.deepEqual(currentHighlight(maps, null, 0), {
    anchorId: "p1",
    range: [0, 17],
  });
  assert.deepEqual(currentHighlight(maps, null, 999), {
    anchorId: "p1",
    range: [0, 17],
  });
  assert.deepEqual(currentHighlight(maps, "p1", 1000), {
    anchorId: "p1",
    range: [17, 35],
  });
  assert.deepEqual(currentHighlight(maps, null, 4000), {
    anchorId: null,
    range: null,
  });
});
test("test_unmeasured_anchor_falls_back_to_paragraph", () => {
  const maps = [sentenceMap("p1")];
  assert.deepEqual(currentHighlight(maps, "p1", 3000), {
    anchorId: "unmeasured",
    range: null,
  });
  const paragraphOnly: FollowMap = {
    segments: [
      {
        anchor_id: "p9",
        start_ms: 0,
        end_ms: 500,
        start_offset_chars: 0,
        end_offset_chars: 40,
      },
    ],
  };
  assert.deepEqual(currentHighlight([paragraphOnly], null, 100), {
    anchorId: "p9",
    range: null,
  });
});
test("test_no_autoscroll_within_5s_of_user_scroll", () => {
  assert.equal(autoscrollAllowed(10_000, undefined), true);
  assert.equal(autoscrollAllowed(10_000, 6_000), false);
  assert.equal(autoscrollAllowed(10_000, 5_001), false);
  assert.equal(autoscrollAllowed(10_000, 5_000), true);
});

test("test_user_scroll_classification: page turns, horizontal keys and foreign scroll events count; the reader's own do not", () => {
  const now = 10_000;
  for (const type of ["wheel", "touchmove", "page-button"])
    assert.equal(isUserScroll(type, undefined, now, 0), true, type);
  for (const key of [
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "PageUp",
    "PageDown",
    "Home",
    "End",
    " ",
  ])
    assert.equal(isUserScroll("keydown", key, now, 0), true, key);
  assert.equal(isUserScroll("keydown", "a", now, 0), false);
  assert.equal(isUserScroll("keydown", undefined, now, 0), false);
  assert.equal(isUserScroll("scroll", undefined, now, 0), true); // scrollbar drag
  assert.equal(isUserScroll("scroll", undefined, now, now + 100), false); // caused by the reader's own scrollTo
  assert.equal(isUserScroll("click", undefined, now, 0), false);
});
function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
test("follow highlight uses a token, is not a note colour, and keeps 4.5:1 text contrast on every reader theme", () => {
  const css = readFileSync("static/maison/app.css", "utf8");
  const rule = css.slice(css.indexOf("::highlight(follow-sentence)"));
  assert.ok(!/#[0-9a-f]{3,6}/i.test(rule), "no raw hex in the follow rules");
  assert.match(rule, /background:var\(--follow-bg\)/);
  const notes = ["gold", "mint", "rose", "lavender"].map(
    (n) => new RegExp(`mark\\.${n}\\{background:(#[0-9a-f]{6})`).exec(css)![1],
  );
  for (const theme of [
    "paper",
    "light",
    "sepia",
    "ink",
    "dark",
    "true_black",
  ]) {
    const bg = new RegExp(
      `\\.reader-${theme}[^{]*\\{[^}]*--follow-bg:(#[0-9a-f]{6})`,
    ).exec(css)?.[1];
    const surface = new RegExp(
      `\\.reader-${theme}[^{]*\\{background:(#[0-9a-f]{3,6});color:(#[0-9a-f]{6})`,
    ).exec(css);
    assert.ok(bg && surface, theme);
    assert.ok(
      contrast(surface![2], bg!) >= 4.5,
      `${theme} text on follow tint`,
    );
    assert.ok(!notes.includes(bg!), `${theme} differs from the note colours`);
  }
});
// A tiny fake of the text pieces the fallback splits: a parent holds an ordered list of text pieces and mark wrappers.
class FakeText {
  constructor(
    public data: string,
    public parent: { kids: (FakeText | FakeMark)[] },
  ) {}
  splitText(offset: number): FakeText {
    const rest = new FakeText(this.data.slice(offset), this.parent);
    this.data = this.data.slice(0, offset);
    this.parent.kids.splice(this.parent.kids.indexOf(this) + 1, 0, rest);
    return rest;
  }
}
class FakeMark {
  constructor(
    public kind: string,
    public kids: FakeText[],
  ) {}
}
const flat = (kids: (FakeText | FakeMark)[]): string =>
  kids.map((k) => (k instanceof FakeText ? k.data : flat(k.kids))).join("");
test("fallback drawing across an annotation mark keeps the text; clearing restores the original structure", () => {
  // "alpha " + <mark gold>beta gamma</mark> + " delta."  (the paragraph after the annotation effect)
  const root: { kids: (FakeText | FakeMark)[] } = { kids: [] };
  const note = new FakeMark("gold", []);
  const inner = new FakeText(
    "beta gamma",
    note as unknown as { kids: (FakeText | FakeMark)[] },
  );
  note.kids.push(inner);
  root.kids.push(
    new FakeText("alpha ", root),
    note,
    new FakeText(" delta.", root),
  );
  const text = flat(root.kids);
  const pieces = [root.kids[0] as FakeText, inner, root.kids[2] as FakeText];
  const wrapped: FakeText[] = [];
  const count = wrapTextSpan(pieces, 3, 20, (piece) => {
    const mark = new FakeMark("follow-sentence", [piece]);
    const holder = piece.parent;
    holder.kids.splice(
      holder.kids.indexOf(piece),
      1,
      mark as unknown as FakeText,
    );
    piece.parent = mark as unknown as { kids: (FakeText | FakeMark)[] };
    wrapped.push(piece);
  });
  assert.equal(count, 3);
  assert.equal(flat(root.kids), text);
  assert.equal(wrapped.map((p) => p.data).join(""), text.slice(3, 20));
  // clear: unwrap every follow mark, then merge adjacent text pieces (what Node.normalize does)
  const unwrap = (kids: (FakeText | FakeMark)[]): (FakeText | FakeMark)[] =>
    kids.flatMap((k) =>
      k instanceof FakeMark
        ? k.kind.startsWith("follow")
          ? unwrap(k.kids)
          : [Object.assign(k, { kids: unwrap(k.kids) as FakeText[] })]
        : [k],
    );
  const merge = (kids: (FakeText | FakeMark)[]) =>
    kids.reduce<(FakeText | FakeMark)[]>((out, k) => {
      const last = out[out.length - 1];
      if (k instanceof FakeText && last instanceof FakeText)
        last.data += k.data;
      else
        out.push(
          k instanceof FakeMark
            ? Object.assign(k, { kids: merge(k.kids) as FakeText[] })
            : k,
        );
      return out;
    }, []);
  const cleared = merge(unwrap(root.kids));
  assert.equal(flat(cleared), text);
  assert.deepEqual(
    cleared.map((k) =>
      k instanceof FakeText ? k.data : `${k.kind}:${flat(k.kids)}`,
    ),
    ["alpha ", "gold:beta gamma", " delta."],
  );
});

test("test_map_fetch_backoff: a failure does not refetch at once, retries after the backoff, and asks the player only after success", () => {
  const t0 = 1_000_000;
  assert.equal(mapFetchPlan(undefined, t0), "fetch");
  assert.equal(mapFetchPlan("loading", t0), "wait");
  assert.equal(mapFetchPlan({ maps: [] }, t0), "use");
  const failed = mapFailed(undefined, t0);
  assert.equal(failed.failures, 1);
  assert.equal(mapFetchPlan(failed, t0), "wait"); // the replayed playback event must not refetch
  assert.equal(mapFetchPlan(failed, t0 + MAP_RETRY_MS - 1), "wait");
  assert.equal(mapFetchPlan(failed, t0 + MAP_RETRY_MS), "fetch"); // exactly one refetch after the backoff
  const again = mapFailed(failed, t0 + MAP_RETRY_MS);
  assert.equal(again.failures, 2);
  assert.equal(mapFetchPlan(again, t0 + MAP_RETRY_MS + MAP_RETRY_MS), "wait"); // doubled
  assert.equal(
    mapFetchPlan(again, t0 + MAP_RETRY_MS + 2 * MAP_RETRY_MS),
    "fetch",
  );
  let f = failed;
  for (let i = 0; i < 20; i++) f = mapFailed(f, t0);
  assert.equal(mapFetchPlan(f, t0 + MAP_RETRY_MAX_MS - 1), "wait");
  assert.equal(mapFetchPlan(f, t0 + MAP_RETRY_MAX_MS), "fetch"); // capped
});

test("a saved Light or Sepia theme is never switched to dark by the system setting", () => {
  assert.equal(initialReaderTheme("light", true), "light");
  assert.equal(initialReaderTheme("sepia", true), "sepia");
  assert.equal(initialReaderTheme("true_black", false), "true_black");
});
test("with nothing saved the system dark setting picks dark, otherwise light", () => {
  assert.equal(initialReaderTheme(null, true), "dark");
  assert.equal(initialReaderTheme(null, false), "light");
  assert.equal(initialReaderTheme("bogus", true), "dark");
});
test("the account value system is not a saved choice", () => {
  assert.equal(initialReaderTheme("system", true), "dark");
  assert.equal(initialReaderTheme("system", false), "light");
});

test("progressFraction is the scrolled share, clamped, 0 when nothing scrolls", () => {
  assert.equal(progressFraction(0, 2000, 1000), 0);
  assert.equal(progressFraction(500, 2000, 1000), 0.5);
  assert.equal(progressFraction(1000, 2000, 1000), 1);
  assert.equal(progressFraction(1400, 2000, 1000), 1);
  assert.equal(progressFraction(-20, 2000, 1000), 0);
  assert.equal(progressFraction(0, 800, 1000), 0);
});

test("minutesRemaining rounds up at 900 characters a minute", () => {
  assert.equal(minutesRemaining(0), 0);
  assert.equal(minutesRemaining(1), 1);
  assert.equal(minutesRemaining(900), 1);
  assert.equal(minutesRemaining(901), 2);
  assert.equal(minutesRemaining(1800, 600), 3);
  assert.equal(minutesRemaining(-5), 0);
});

test("headingsFor lists the rendered h2 chapter headings with their anchor ids", () => {
  const html =
    '<p id="anchor-a">x</p><h2 id="anchor-b" data-anchor="b">প্রথম <em>পরিচ্ছেদ</em></h2><h2 id="anchor-c" data-anchor="c">Two &amp; three</h2><h3 id="z">no</h3>';
  assert.deepEqual(headingsFor(html), [
    { id: "anchor-b", text: "প্রথম পরিচ্ছেদ" },
    { id: "anchor-c", text: "Two & three" },
  ]);
  assert.deepEqual(headingsFor("<p>none</p>"), []);
});

test("toolbarHidden hides on scroll down, returns on scroll up, never while focused or near the top", () => {
  assert.equal(toolbarHidden(false, 100, 300, false), true);
  assert.equal(toolbarHidden(true, 300, 280, false), false);
  assert.equal(toolbarHidden(false, 100, 300, true), false);
  assert.equal(toolbarHidden(true, 300, 310, true), false);
  assert.equal(toolbarHidden(false, 0, 40, false), false);
  assert.equal(toolbarHidden(true, 300, 301, false), true); // a 1 px jitter changes nothing
  assert.equal(toolbarHidden(false, 300, 302, false), false);
  assert.equal(toolbarHidden(true, 300, 40, false), false); // back at the top
});

test("reader toolbar CSS: 2px gold hairline, transform, no transition under reduced motion", () => {
  const css = readFileSync("static/maison/room/room.css", "utf8");
  assert.match(css, /\.reader-progress[^{]*\{[^}]*height:2px/);
  assert.match(css, /\.reader-progress[^{]*\{[^}]*var\(--gold/);
  assert.match(css, /\.reader-toolbar\.is-hidden[^{]*\{[^}]*transform:translateY\(-100%\)/);
  assert.match(css, /\.reader-toolbar:has\(:focus-visible\)[^{]*\{[^}]*transform:none/);
  assert.match(css, /prefers-reduced-motion:\s*reduce\)\s*\{[^@]*\.reader-toolbar\{[^}]*transition:none/);
  assert.match(css, /body\.reduced-motion \.reader-toolbar[^{]*\{[^}]*transition:none/);
});

test("the toolbar is pinned only by keyboard focus, not by a tap's leftover focus", () => {
  assert.equal(toolbarPinned(true, true), true);
  assert.equal(toolbarPinned(true, false), false);
  assert.equal(toolbarPinned(false, true), false);
  assert.equal(toolbarHidden(false, 100, 300, toolbarPinned(true, false)), true);
  assert.equal(toolbarHidden(false, 100, 300, toolbarPinned(true, true)), false);
});

test("test_font_stepper_walks_allowed_sizes_and_clamps", () => {
  assert.deepEqual([...READER_FONT_SIZES], [16, 20, 23, 26, 30]);
  assert.equal(stepFont(20, 1), 23);
  assert.equal(stepFont(23, 1), 26);
  assert.equal(stepFont(20, -1), 16);
  assert.equal(stepFont(30, 1), 30);
  assert.equal(stepFont(16, -1), 16);
  assert.equal(stepFont(21, 1), 23); // an off-list size snaps to the nearest allowed size first
  assert.equal(stepFont(Number.NaN, 1), 23); // unusable input starts from the 20 default
});

test("test_justify_hidden_for_bengali", () => {
  assert.deepEqual(alignmentOptions("en"), ["start", "justify"]);
  assert.deepEqual(alignmentOptions("bn"), ["start"]);
  assert.equal(effectiveAlignment("justify", "bn"), "start");
  assert.equal(effectiveAlignment("justify", "en"), "justify");
});

test("test_width_narrow_medium_wide_map_to_55_65_72ch", () => {
  assert.deepEqual(READER_WIDTHS.map((w) => [w.value, w.label, w.measure]), [
    ["compact", "narrow", "55ch"],
    ["comfortable", "medium", "65ch"],
    ["wide", "wide", "72ch"],
  ]);
  assert.equal(widthMeasure("compact"), "55ch");
  assert.equal(widthMeasure("nonsense"), "65ch");
});

test("test_changes_apply_live_and_save_debounced_500ms", () => {
  assert.equal(PREFERENCE_SAVE_MS, 500);
  const timers = new Map<number, { fn: () => void; ms: number }>();
  let next = 1;
  const saved: unknown[] = [];
  const saver = createDebouncedSaver<{ n: number }>(
    (v) => saved.push(v),
    PREFERENCE_SAVE_MS,
    (fn, ms) => { timers.set(next, { fn, ms }); return next++; },
    (id) => { timers.delete(id as number); },
  );
  saver.schedule({ n: 1 });
  saver.schedule({ n: 2 });
  saver.schedule({ n: 3 });
  assert.equal(timers.size, 1); // rapid steps collapse into one pending save
  assert.equal([...timers.values()][0].ms, 500);
  assert.deepEqual(saved, []); // nothing sent before the pause
  const [firedId, fired] = [...timers.entries()][0];
  timers.delete(firedId);
  fired.fn();
  assert.deepEqual(saved, [{ n: 3 }]); // only the latest value is sent
  saver.schedule({ n: 4 });
  saver.cancel();
  assert.equal(timers.size, 0);
});

test("reading comfort sheet has live controls and no Save button", () => {
  const source = readFileSync("client/reader.tsx", "utf8");
  assert.match(source, /className="media-sheet--bottom"|media-sheet--bottom/);
  assert.match(source, /role="radiogroup"/);
  assert.doesNotMatch(source, /keep_settings/);
  assert.doesNotMatch(source, /saveSettings/);
  const css = readFileSync("static/maison/room/room.css", "utf8");
  assert.match(css, /\.media-sheet--bottom[^{]*\{[^}]*\}/);
  assert.match(css, /max-width:640px\)\s*\{[^@]*\.media-sheet--bottom\{[^}]*margin:auto 0 0/);
});

test("stepLeading moves in 0.05 steps within the locale floor and 2.4", () => {
  assert.equal(stepLeading(1.65, 1, "en"), 1.7);
  assert.equal(stepLeading(1.5, -1, "en"), 1.5);
  assert.equal(stepLeading(1.8, -1, "bn"), 1.8);
  assert.equal(stepLeading(1.5, 1, "bn"), 1.8); // below the Bengali floor snaps up
  assert.equal(stepLeading(2.4, 1, "en"), 2.4);
  assert.equal(stepLeading(1.7, -1, "en"), 1.65);
});

test("radio keys move and wrap, Home and End jump, other keys are ignored", () => {
  assert.equal(radioKeyTarget("ArrowRight", 4, 5), 0);
  assert.equal(radioKeyTarget("ArrowDown", 1, 5), 2);
  assert.equal(radioKeyTarget("ArrowLeft", 0, 5), 4);
  assert.equal(radioKeyTarget("ArrowUp", 3, 5), 2);
  assert.equal(radioKeyTarget("Home", 3, 5), 0);
  assert.equal(radioKeyTarget("End", 1, 5), 4);
  assert.equal(radioKeyTarget("Tab", 1, 5), undefined);
  assert.equal(radioKeyTarget("ArrowRight", 0, 0), undefined);
});

type Prefs = { a: number; b: number; c: number };
const tick = () => new Promise((r) => setImmediate(r));

test("save queue: one in flight, later values coalesce, conflict refetches and retries once", async () => {
  const sent: Array<Partial<Prefs>> = [];
  const release: Array<() => void> = [];
  let active = 0;
  let maxActive = 0;
  const queue = createSaveQueue<Prefs>({
    initial: { a: 0, b: 0, c: 0 },
    send: (changes) => new Promise<void>((resolve) => {
      active++; maxActive = Math.max(maxActive, active); sent.push(changes);
      release.push(() => { active--; resolve(); });
    }),
    isConflict: () => false,
    refresh: async () => {},
  });
  const done = queue.push({ a: 1, b: 0, c: 0 });
  queue.push({ a: 2, b: 0, c: 0 }); queue.push({ a: 3, b: 0, c: 0 });
  assert.deepEqual(sent, [{ a: 1 }]);
  assert.equal(queue.inFlight(), true);
  release.shift()!();
  await tick();
  assert.deepEqual(sent, [{ a: 1 }, { a: 3 }]); // 2 was coalesced away
  release.shift()!();
  await done;
  assert.equal(maxActive, 1);
  assert.equal(queue.inFlight(), false);

  const log: string[] = [];
  let calls = 0;
  const errors: unknown[] = [];
  const retrying = createSaveQueue<Prefs>({
    initial: { a: 0, b: 0, c: 0 },
    send: async (changes) => { log.push("send" + JSON.stringify(changes)); if (calls++ === 0) throw "conflict"; },
    isConflict: (e) => e === "conflict",
    refresh: async () => { log.push("refresh"); },
    onError: (e) => errors.push(e),
  });
  await retrying.push({ a: 7, b: 0, c: 0 });
  assert.deepEqual(log, ['send{"a":7}', "refresh", 'send{"a":7}']);
  assert.deepEqual(errors, []);

  const failing = createSaveQueue<Prefs>({
    initial: { a: 0, b: 0, c: 0 },
    send: async () => { throw "conflict"; },
    isConflict: () => true,
    refresh: async () => {},
    onError: (e) => errors.push(e),
  });
  await failing.push({ a: 1, b: 0, c: 0 }); // the retry fails too: reported once, not looped
  assert.deepEqual(errors, ["conflict"]);
  assert.deepEqual(failing.dirty(), ["a"]); // still unsaved: the next change carries it again
});

test("save queue sends only the keys this tab changed since its last successful save", async () => {
  const sent: Array<Partial<Prefs>> = [];
  const queue = createSaveQueue<Prefs>({
    initial: { a: 1, b: 1, c: 1 },
    send: async (changes) => { sent.push(changes); },
    isConflict: () => false,
    refresh: async () => {},
  });
  await queue.push({ a: 2, b: 1, c: 1 });
  await queue.push({ a: 2, b: 5, c: 1 });
  assert.deepEqual(sent, [{ a: 2 }, { b: 5 }]); // a was acknowledged, so the second save carries b alone
  assert.deepEqual(queue.dirty(), []);
  await queue.push({ a: 2, b: 5, c: 1 }); // nothing changed: nothing is sent (the server refuses an empty PATCH)
  assert.equal(sent.length, 2);
});

test("after a conflict a stale tab re-sends only its own changes and takes the other device's values", async () => {
  const sent: Array<Partial<Prefs>> = [];
  const merged: Array<Partial<Prefs>> = [];
  let conflictOnce = true;
  const queue = createSaveQueue<Prefs>({
    initial: { a: 1, b: 1, c: 1 },
    send: async (changes) => {
      sent.push(changes);
      if (conflictOnce) { conflictOnce = false; throw "conflict"; }
    },
    isConflict: (e) => e === "conflict",
    // Another device changed b and c while this tab was open.
    refresh: async () => ({ a: 1, b: 9, c: 8 }),
    onMerge: (theirs) => merged.push(theirs),
  });
  await queue.push({ a: 4, b: 1, c: 1 });
  assert.deepEqual(sent, [{ a: 4 }, { a: 4 }]); // never b or c: the stale 1s would revert the other device
  assert.deepEqual(merged, [{ b: 9, c: 8 }]); // the screen takes the other device's settings
  // The merged values are now the base: a later change to a sends a alone, not the stale b/c.
  await queue.push({ a: 5, b: 9, c: 8 });
  assert.deepEqual(sent.at(-1), { a: 5 });
});

test("a change pushed during the conflict retry is saved, not dropped", async () => {
  const sent: Array<Partial<Prefs>> = [];
  let call = 0;
  let releaseRetry: () => void = () => {};
  const queue = createSaveQueue<Prefs>({
    initial: { a: 0, b: 0, c: 0 },
    send: (changes) => {
      sent.push(changes);
      call++;
      if (call === 1) return Promise.reject("conflict");
      if (call === 2) return new Promise<void>((resolve) => { releaseRetry = resolve; });
      return Promise.resolve();
    },
    isConflict: (e) => e === "conflict",
    refresh: async () => {},
  });
  const done = queue.push({ a: 1, b: 0, c: 0 });
  await tick(); await tick();
  assert.deepEqual(sent, [{ a: 1 }, { a: 1 }]); // the retry is in flight
  queue.push({ a: 1, b: 2, c: 0 }); // pushed while the retry is in flight
  releaseRetry();
  await done;
  assert.deepEqual(sent, [{ a: 1 }, { a: 1 }, { b: 2 }]);
  assert.deepEqual(queue.dirty(), []);
});

test("a page-hide flush sends the pending change at once with keepalive", async () => {
  const timers = new Map<number, () => void>();
  let id = 1;
  const sent: Array<{ changes: Partial<Prefs>; keepalive: boolean; value: Prefs }> = [];
  const queue = createSaveQueue<Prefs>({
    initial: { a: 0, b: 0, c: 0 },
    send: async (changes, context) => { sent.push({ changes, ...context }); },
    isConflict: () => false,
    refresh: async () => {},
  });
  const saver = createDebouncedSaver<Prefs>(
    (value) => void queue.push(value),
    PREFERENCE_SAVE_MS,
    (fn) => { timers.set(id, fn); return id++; },
    (t) => { timers.delete(t as number); },
  );
  saver.schedule({ a: 0, b: 3, c: 0 }); // the 500 ms pause has not passed when the page is hidden
  assert.equal(flushPreferenceSave(saver, queue, { a: 0, b: 3, c: 0 }), true);
  // send ran synchronously inside pagehide (no await before it), with keepalive, and the timer is gone.
  assert.deepEqual(sent, [{ changes: { b: 3 }, keepalive: true, value: { a: 0, b: 3, c: 0 } }]);
  assert.equal(timers.size, 0);
  assert.equal(saver.pending(), false);
  assert.equal(flushPreferenceSave(saver, queue, { a: 0, b: 3, c: 0 }), false); // nothing pending: nothing sent
  assert.equal(sent.length, 1);
  await tick();
  // A later ordinary save is not keepalive.
  await queue.push({ a: 1, b: 3, c: 0 });
  assert.deepEqual(sent.at(-1), { changes: { a: 1 }, keepalive: false, value: { a: 1, b: 3, c: 0 } });
});

test("the signed-out page-hide flush keeps the change on this device", () => {
  const store = new Map<string, string>();
  const queue = createSaveQueue<Prefs>({
    initial: { a: 0, b: 0, c: 0 },
    // The reader's signed-out send: the whole value goes to localStorage, synchronously.
    send: async (_changes, { value }) => { store.set("maison.reader.preferences", JSON.stringify(value)); },
    isConflict: () => false,
    refresh: async () => {},
  });
  const saver = createDebouncedSaver<Prefs>((value) => void queue.push(value), PREFERENCE_SAVE_MS, () => 1, () => {});
  saver.schedule({ a: 0, b: 0, c: 6 });
  flushPreferenceSave(saver, queue, { a: 0, b: 0, c: 6 });
  assert.deepEqual(JSON.parse(store.get("maison.reader.preferences")!), { a: 0, b: 0, c: 6 }); // written before any await
});

test("splitTitleSlot leaves the title slot between the two halves", () => {
  assert.deepEqual(
    splitTitleSlot("Sign in free to finish {title} \u2014 your place is kept"),
    ["Sign in free to finish ", " \u2014 your place is kept"],
  );
  assert.deepEqual(splitTitleSlot("No slot"), ["No slot", ""]);
});

import { runListenSwitch, runWatchSwitch, runReadSwitch, listenFallback, flushPreferenceSave } from "./state.ts";
import { annotationSpan } from "./sentences.ts";

test("the toolbar Listen action sends the current anchor and opens the player at the returned position", async () => {
  const calls: Array<{ path: string; body: Record<string, unknown> }> = [];
  const went: string[] = [];
  const order: string[] = [];
  const position = { format: "reader", unit_id: "u1", anchor_id: "a-42", offset_chars: 17 } as never;
  const outcome = await runListenSwitch({
    call: async (path, body) => {
      calls.push({ path, body });
      order.push("call");
      return { outcome: "mapped", to_location: { format: "audio", unit_id: "u1", position_ms: 61500 } };
    },
    editionRevisionId: "rev-1",
    position,
    playerUrl: "/en/listen/e1/",
    save: async () => { order.push("save"); },
    go: (url) => { order.push("go"); went.push(url); },
  });
  assert.equal(outcome, "mapped");
  assert.equal(calls[0].path, "/content/switch-position");
  assert.deepEqual(calls[0].body, { edition_revision_id: "rev-1", from_location: position, to_format: "audio" });
  assert.deepEqual(went, ["/en/listen/e1/?unit_id=u1&position_ms=61500"]);
  assert.deepEqual(order, ["call", "save", "go"]);
});

test("an unmapped Listen switch stays on the page", async () => {
  const went: string[] = [];
  const outcome = await runListenSwitch({
    call: async () => ({ outcome: "unmapped" }),
    editionRevisionId: "rev-1",
    position: { format: "reader", unit_id: "u1", anchor_id: "a", offset_chars: 0 } as never,
    playerUrl: "/en/listen/e1/",
    save: async () => {},
    go: (url) => went.push(url),
  });
  assert.equal(outcome, "unmapped");
  assert.deepEqual(went, []);
});

// What the HTML parser leaves in a text node: CRLF and a lone CR each become one LF.
const parsed = (stored: string) => stored.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

test("a Listen switch whose call fails reports failed instead of dead-ending", async () => {
  const went: string[] = [];
  const errors: unknown[] = [];
  let saved = 0;
  const outcome = await runListenSwitch({
    call: async () => { throw new Error("network"); },
    editionRevisionId: "rev-1",
    position: { format: "reader", unit_id: "u1", anchor_id: "a", offset_chars: 0 } as never,
    playerUrl: "/en/listen/e1/",
    save: async () => { saved++; },
    go: (url) => went.push(url),
    onError: (e) => errors.push(e),
  });
  assert.equal(outcome, "failed"); // the reader then opens the sheet with the chapter start
  assert.deepEqual(went, []);
  assert.equal(errors.length, 1);
  assert.equal(saved, 0);
});

test("a failed or conflicting position save does not block a mapped Listen switch", async () => {
  for (const failure of [new Error("network"), Object.assign(new Error("conflict"), { status: 412 })]) {
    const went: string[] = [];
    const errors: unknown[] = [];
    const outcome = await runListenSwitch({
      call: async () => ({ outcome: "mapped", to_location: { format: "audio", unit_id: "u1", position_ms: 1200 } }),
      editionRevisionId: "rev-1",
      position: { format: "reader", unit_id: "u1", anchor_id: "a", offset_chars: 3 } as never,
      playerUrl: "/en/listen/e1/",
      save: async () => { throw failure; },
      go: (url) => went.push(url),
      onError: (e) => errors.push(e),
    });
    assert.equal(outcome, "mapped");
    assert.deepEqual(went, ["/en/listen/e1/?unit_id=u1&position_ms=1200"]); // the page-hide save retries the position
    assert.deepEqual(errors, [failure]);
  }
  // Unmapped with a failing save still reaches the sheet (outcome unmapped), never a thrown dead end.
  const outcome = await runListenSwitch({
    call: async () => ({ outcome: "unmapped" }),
    editionRevisionId: "rev-1",
    position: { format: "reader", unit_id: "u1", anchor_id: "a", offset_chars: 0 } as never,
    playerUrl: "/en/listen/e1/",
    save: async () => { throw new Error("network"); },
    go: () => assert.fail("must not navigate"),
  });
  assert.equal(outcome, "unmapped");
});

test("listenFallback: a failed or unmapped switch opens the sheet when the reader has one, else follows the link", () => {
  assert.equal(listenFallback("mapped", true), "none");
  assert.equal(listenFallback("unmapped", true), "sheet");
  assert.equal(listenFallback("failed", true), "sheet");
  assert.equal(listenFallback("unmapped", false), "link");
  assert.equal(listenFallback("failed", false), "link");
});

test("storedOffset inverts domOffset: page offsets from a selection go back to stored-text offsets", () => {
  const cases: Array<[string, string]> = [
    ["CRLF", "Morning fog lifts slowly.\r\nThe miller opens the gate.\r\nWater rushes under the wheel."],
    ["CR CR LF", "One line.\r\r\nTwo lines. Three.\r\r\nFour."],
    ["no CR", "Plain text with no carriage return. Second sentence."],
    ["Bengali + astral", "\u0986\u09ae\u09bf \ud83c\udf38.\r\n\u09a4\u09c1\u09ae\u09bf\u0964 Yes."],
  ];
  for (const [label, stored] of cases) {
    const crlf = crlfIndexes(stored);
    const page = parsed(stored);
    const storedPoints = Array.from(stored);
    const pagePoints = Array.from(page);
    // Every page offset round-trips page -> stored -> page.
    for (let d = 0; d <= pagePoints.length; d++)
      assert.equal(domOffset(storedOffset(d, crlf), crlf), d, `${label}: page ${d}`);
    // Every stored offset that is not between a CR and its LF round-trips stored -> page -> stored.
    for (let s = 0; s <= storedPoints.length; s++) {
      if (crlf.includes(s - 1)) continue;
      assert.equal(storedOffset(domOffset(s, crlf), crlf), s, `${label}: stored ${s}`);
    }
    // A selection of each sentence on the page quotes exactly that sentence from the stored text.
    for (const [start, end] of splitSentences(page)) {
      const a = Array.from(page.slice(0, start)).length, b = Array.from(page.slice(0, end)).length;
      const quote = storedPoints.slice(storedOffset(a, crlf), storedOffset(b, crlf)).join("");
      assert.equal(parsed(quote), pagePoints.slice(a, b).join(""), `${label}: quote ${a}-${b}`);
    }
  }
  // The paragraph's full page length maps to its full stored length.
  const stored = "A.\r\nB.\r\r\nC.";
  assert.equal(storedOffset(Array.from(parsed(stored)).length, crlfIndexes(stored)), Array.from(stored).length);
  // Unsorted indexes from a caller still map correctly.
  assert.equal(storedOffset(5, [5, 1]), 7); // the CR at 1 moves 5 to 6, which passes the CR at 5
  assert.equal(storedOffset(5), 5);
});

test("annotationSpan draws a stored annotation range at the right page characters", () => {
  const stored = "Morning fog lifts slowly.\r\nThe miller opens the gate.";
  const crlf = crlfIndexes(stored);
  const page = Array.from(parsed(stored));
  const start = stored.indexOf("The"), end = stored.indexOf(" the gate");
  const span = annotationSpan([start, end], crlf, page.length)!;
  assert.equal(page.slice(span[0], span[1]).join(""), "The miller opens");
  assert.equal(annotationSpan([start, end], [], page.length)!.length, 2);
  assert.equal(annotationSpan([5, 5], crlf, page.length), null); // empty
  assert.equal(annotationSpan([0, stored.length + 4], crlf, page.length), null); // past the paragraph
});


test("CRLF: stored-text sentence offsets map onto the parsed page text without shifting", () => {
  const stored = "Morning fog lifts slowly.\r\nThe miller opens the gate. Water rushes under the wheel.";
  const page = parsed(stored);
  const crlf = crlfIndexes(stored);
  assert.deepEqual(crlf, [25]);
  const sentences = splitSentences(stored); // the server's partition, in stored code points
  assert.equal(sentences.length, 3);
  for (const [start, end] of sentences) {
    const [a, b] = highlightSpan(page, [start, end], crlf);
    assert.equal(page.slice(a, b), parsed(stored.slice(start, end)));
  }
  // Unmapped, the CRLF shifts every later sentence one character late (the browser defect this fixes).
  const [s, e] = sentences[1];
  const [a, b] = highlightSpan(page, [s, e]);
  assert.equal(page.slice(a, b), "he miller opens the gate. W");
  // An offset between the CR and its LF lands on the LF; offsets before the CRLF are unchanged.
  assert.equal(domOffset(26, crlf), 25);
  assert.equal(domOffset(25, crlf), 25);
  assert.equal(domOffset(10, crlf), 10);
  assert.equal(domOffset(stored.length, crlf), page.length);
});

test("lone CR keeps its length; several CRLFs and astral text map together", () => {
  const cr = "Children race along the bank.\rTheir shouts carry far. Nobody minds the noise.";
  assert.deepEqual(crlfIndexes(cr), []);
  for (const [start, end] of splitSentences(cr)) {
    const [a, b] = highlightSpan(parsed(cr), [start, end], crlfIndexes(cr));
    assert.equal(parsed(cr).slice(a, b), parsed(cr.slice(start, end)));
  }
  const mixed = "One 🌸.\r\nTwo.\rThree.\r\n\r\nFour.";
  const crlf = crlfIndexes(mixed);
  assert.equal(crlf.length, 3);
  const page = parsed(mixed);
  const points = Array.from(mixed);
  for (const [start, end] of splitSentences(mixed)) {
    // splitSentences gives UTF-16 indices; the server's offsets are code points.
    const cpStart = Array.from(mixed.slice(0, start)).length;
    const cpEnd = Array.from(mixed.slice(0, end)).length;
    const [a, b] = highlightSpan(page, [cpStart, cpEnd], crlf);
    assert.equal(page.slice(a, b), parsed(points.slice(cpStart, cpEnd).join("")));
  }
});

test("follow-along scroll centres the sentence in the band between the toolbar and the docked player", () => {
  const band = { top: 61, bottom: 567 };
  assert.equal(followScrollDelta({ top: 200, bottom: 228 }, band), 0); // already visible
  // Under the docked player (the browser report: 704-732 with the player at 567): centred in the band.
  const delta = followScrollDelta({ top: 704, bottom: 732 }, band);
  assert.equal(704 - delta + 14, Math.round((61 + 567) / 2));
  assert.ok(704 - delta >= band.top && 732 - delta <= band.bottom);
  // Under the toolbar: scrolled up into the band.
  assert.ok(followScrollDelta({ top: 40, bottom: 68 }, band) < 0);
  // Taller than the band: its top goes to the band top.
  assert.equal(followScrollDelta({ top: 600, bottom: 1300 }, band), 539);
});

test("the scroll observer keeps an exact restored place until the reader scrolls by hand", () => {
  const exact = { format: "reader" as const, unit_id: "u", anchor_id: "a", offset_chars: 90 };
  assert.equal(observedPosition(exact, "u", "b", true), exact); // held after a jump
  assert.equal(observedPosition(exact, "u", "a", false), exact); // same paragraph keeps its offset
  assert.deepEqual(observedPosition(exact, "u", "b", false), { format: "reader", unit_id: "u", anchor_id: "b", offset_chars: 0 });
});

const watchPosition = { format: "reader", unit_id: "u1", anchor_id: "a-9", offset_chars: 4 } as never;

test("the toolbar Watch action sends the exact anchor and offset and opens the film at the mapped position", async () => {
  const calls: Array<{ path: string; body: Record<string, unknown> }> = [];
  const went: string[] = [];
  const outcome = await runWatchSwitch({
    call: async (path, body) => {
      calls.push({ path, body });
      return { outcome: "mapped", to_location: { format: "video", unit_id: "u1", position_ms: 83250 } };
    },
    editionRevisionId: "rev-1",
    position: watchPosition,
    videoUrl: "/en/watch/e1/",
    save: async () => {},
    go: (url) => went.push(url),
  });
  assert.equal(outcome, "mapped");
  assert.equal(calls[0].path, "/content/switch-position");
  assert.deepEqual(calls[0].body, { edition_revision_id: "rev-1", from_location: watchPosition, to_format: "video" });
  assert.deepEqual(went, ["/en/watch/e1/?unit_id=u1&position_ms=83250"]);
});

test("an unmapped Watch switch does not navigate, so the caller follows the part-start link", async () => {
  for (const unmapped of [{ outcome: "unmapped" }, { outcome: "unreleased" }, { outcome: "feature_disabled" },
    { outcome: "mapped", to_location: { format: "audio", unit_id: "u1", position_ms: 5 } },
    { outcome: "mapped", to_location: { format: "video", unit_id: "u1" } }]) {
    const went: string[] = [];
    const outcome = await runWatchSwitch({
      call: async () => unmapped,
      editionRevisionId: "rev-1", position: watchPosition, videoUrl: "/en/watch/e1/",
      save: async () => {}, go: (url) => went.push(url),
    });
    assert.equal(outcome, "unmapped", JSON.stringify(unmapped));
    assert.deepEqual(went, []);
  }
});

test("a failed Watch switch reports failed, saves nothing and does not navigate", async () => {
  const went: string[] = [], errors: unknown[] = [];
  let saved = 0;
  const outcome = await runWatchSwitch({
    call: async () => { throw new Error("network"); },
    editionRevisionId: "rev-1", position: watchPosition, videoUrl: "/en/watch/e1/",
    save: async () => { saved++; }, go: (url) => went.push(url), onError: (e) => errors.push(e),
  });
  assert.equal(outcome, "failed");
  assert.deepEqual(went, []);
  assert.equal(errors.length, 1);
  assert.equal(saved, 0);
});

test("a failing position save does not stop a mapped Watch switch", async () => {
  const went: string[] = [];
  const outcome = await runWatchSwitch({
    call: async () => ({ outcome: "mapped", to_location: { format: "video", unit_id: "u1", position_ms: 0 } }),
    editionRevisionId: "rev-1", position: watchPosition, videoUrl: "/en/watch/e1/",
    save: async () => { throw new Error("conflict"); }, go: (url) => went.push(url),
  });
  assert.equal(outcome, "mapped");
  assert.deepEqual(went, ["/en/watch/e1/?unit_id=u1&position_ms=0"]);
});

test("Watch to Read sends the film position and opens the reader at the mapped anchor and offset", async () => {
  const calls: Array<Record<string, unknown>> = [];
  const went: string[] = [];
  const deps = {
    editionRevisionId: "rev-1", unitId: "u1", positionMs: 12345.6,
    readerUnitUrl: (unit: string) => `/en/read/e1/${unit}/`,
    go: (url: string) => went.push(url),
  };
  assert.equal(await runReadSwitch({
    ...deps,
    call: async (_p, body) => { calls.push(body); return { outcome: "mapped", to_location: { format: "reader", unit_id: "u2", anchor_id: "a 7", offset_chars: 31 } }; },
  }), "mapped");
  assert.deepEqual(calls[0], { edition_revision_id: "rev-1", from_location: { format: "video", unit_id: "u1", position_ms: 12346 }, to_format: "reader" });
  assert.deepEqual(went, ["/en/read/e1/u2/?anchor=a+7&offset=31"]);
  assert.equal(await runReadSwitch({ ...deps, call: async () => ({ outcome: "unmapped" }) }), "unmapped");
  assert.equal(await runReadSwitch({ ...deps, call: async () => { throw new Error("x"); } }), "failed");
  assert.equal(went.length, 1);
});
