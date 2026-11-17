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
test("Player return links remain on a local locale route", () => {
  assert.equal(validReturnPath("https://evil.invalid/"), " /en/".trim());
  assert.equal(validReturnPath("//evil.invalid/"), "/en/");
  assert.equal(
    validReturnPath("/bn/read/book/?anchor=a"),
    "/bn/read/book/?anchor=a",
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
