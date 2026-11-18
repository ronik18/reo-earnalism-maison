export interface QueuedOperation {
  operation_id: string;
  kind: string;
  [key: string]: unknown;
}
export interface QueuedWrite {
  operation: QueuedOperation;
  attempted: boolean;
  blocked?: boolean;
  problem?: string;
}
const allowed = new Set([
  "progress.set",
  "annotation.create",
  "annotation.patch",
  "annotation.delete",
  "saved.set",
]);
export function planEnqueue(
  existing: QueuedWrite[],
  operation: QueuedOperation,
  attempted = false,
): QueuedWrite[] {
  if (!allowed.has(operation.kind) || !operation.operation_id)
    throw new Error("invalid_input");
  if (existing.some((x) => x.operation.operation_id === operation.operation_id))
    return existing;
  let rows = existing;
  if (operation.kind === "progress.set" && !attempted)
    rows = rows.filter(
      (x) =>
        x.attempted ||
        x.blocked ||
        x.operation.kind !== "progress.set" ||
        x.operation.edition_id !== operation.edition_id ||
        (x.operation.location as { format?: string })?.format !==
          (operation.location as { format?: string })?.format,
    );
  const result = [...rows, { operation, attempted }];
  if (
    result.length > 500 ||
    new TextEncoder().encode(JSON.stringify(result)).byteLength > 2097152
  )
    throw new Error("sync_queue_full");
  return result;
}
export function nextBatch(rows: QueuedWrite[]): QueuedWrite[] {
  const result: QueuedWrite[] = [];
  for (const item of rows) {
    if (item.blocked) continue;
    const trial = [...result, item];
    if (
      trial.length > 100 ||
      new TextEncoder().encode(
        JSON.stringify({ operations: trial.map((x) => x.operation) }),
      ).byteLength >
        240 * 1024
    )
      break;
    result.push(item);
  }
  return result;
}

export function recoverNote(
  rows: QueuedWrite[],
  id: string,
  action: "retry" | "delete" | "replace",
  replacement?: {
    operation_id: string;
    annotation_id: string;
    note_text: string;
    occurred_at: string;
  },
): QueuedWrite[] {
  const row = rows.find((row) => row.operation.operation_id === id);
  if (!row || row.operation.kind !== "annotation.create")
    throw new Error("invalid_input");
  if (action === "delete") return rows.filter((item) => item !== row);
  if (action === "retry")
    return rows.map((item) =>
      item === row ? { ...item, blocked: false, problem: undefined } : item,
    );
  if (
    !row.blocked ||
    !replacement ||
    !replacement.note_text.trim() ||
    new TextEncoder().encode(replacement.note_text).length > 8192
  )
    throw new Error("invalid_input");
  const annotation = row.operation.annotation as Record<string, unknown>;
  const operation = {
    ...row.operation,
    operation_id: replacement.operation_id,
    occurred_at: replacement.occurred_at,
    annotation: {
      ...annotation,
      annotation_id: replacement.annotation_id,
      kind: "note",
      note_text: replacement.note_text,
    },
  };
  return planEnqueue(
    rows.filter((item) => item !== row),
    operation,
  );
}
