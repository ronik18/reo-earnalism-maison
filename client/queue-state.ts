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
