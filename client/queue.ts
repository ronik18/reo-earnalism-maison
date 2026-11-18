import { api, session } from "./api";
import { activeMember, database, store } from "./offline";
import {
  recoverNote,
  planEnqueue,
  nextBatch,
  type QueuedOperation,
  type QueuedWrite,
} from "./queue-state";
interface Queue {
  key: string;
  rows: QueuedWrite[];
}
let flushing = false;
async function change(
  member: string,
  mutate: (rows: QueuedWrite[]) => QueuedWrite[],
): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("meta", "readwrite"),
        object = tx.objectStore("meta"),
        identity = object.get("identity");
      identity.onsuccess = () => {
        if (identity.result?.member !== member) {
          tx.abort();
          return;
        }
        const request = object.get("queue:" + member);
        request.onsuccess = () => {
          try {
            object.put({
              key: "queue:" + member,
              rows: mutate(request.result?.rows || []),
            });
          } catch (e) {
            reject(e);
            tx.abort();
          }
        };
      };
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(new Error("sync_identity_changed"));
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}
export async function queued(member: string) {
  return (
    (await store<Queue>("meta", (s) => s.get("queue:" + member)))?.rows || []
  );
}
export async function enqueue(
  member: string,
  operation: QueuedOperation,
  attempted = false,
) {
  await change(member, (rows) => planEnqueue(rows, operation, attempted));
  window.dispatchEvent(new CustomEvent("maison:queue-change"));
}
export async function discardQueuedProgress(member: string, editionId: string) {
  await change(member, (rows) =>
    rows.filter(
      (r) =>
        r.operation.kind !== "progress.set" ||
        r.operation.edition_id !== editionId,
    ),
  );
  window.dispatchEvent(new CustomEvent("maison:queue-change"));
}
export async function flushQueue() {
  if (flushing || !navigator.onLine) return;
  flushing = true;
  try {
    const identity = await session(true);
    const member = identity.member?.member_id;
    if (
      !identity.authenticated ||
      !member ||
      !identity.device_id ||
      (await activeMember()) !== member
    )
      return;
    const batch = nextBatch(await queued(member));
    if (!batch.length) return;
    for (const row of batch) {
      if (row.operation.kind !== "progress.set") continue;
      try {
        const key = `maison.progress.operations:${member}:${row.operation.edition_id}`;
        const ids: string[] = JSON.parse(sessionStorage.getItem(key) || "[]");
        sessionStorage.setItem(
          key,
          JSON.stringify(
            [...new Set([...ids, row.operation.operation_id])].slice(-100),
          ),
        );
      } catch {}
    }
    const ids = new Set(batch.map((x) => x.operation.operation_id));
    await change(member, (rows) =>
      rows.map((x) =>
        ids.has(x.operation.operation_id) ? { ...x, attempted: true } : x,
      ),
    );
    const result = await api<{
      results: {
        operation_id: string;
        outcome: string;
        problem?: { code: string };
      }[];
    }>("/me/sync", {
      method: "POST",
      key: crypto.randomUUID(),
      body: {
        device_id: identity.device_id,
        operations: batch.map((x) => x.operation),
      },
    });
    const accepted = new Set(
      result.results
        .filter((x) => x.outcome === "applied" || x.outcome === "replayed")
        .map((x) => x.operation_id),
    );
    await change(member, (rows) =>
      rows
        .filter((x) => !accepted.has(x.operation.operation_id))
        .map((x) => {
          const status = result.results.find(
            (r) => r.operation_id === x.operation.operation_id,
          );
          return status && ["conflict", "rejected"].includes(status.outcome)
            ? {
                ...x,
                blocked: true,
                problem: status.problem?.code || status.outcome,
              }
            : x;
        }),
    );
    window.dispatchEvent(
      new CustomEvent("maison:sync", {
        detail: {
          results: result.results,
          operations: batch.map((x) => x.operation),
        },
      }),
    );
    window.dispatchEvent(new CustomEvent("maison:queue-change"));
  } finally {
    flushing = false;
  }
}

export async function recoverQueuedNote(
  member: string,
  id: string,
  action: "retry" | "delete" | "replace",
  note?: string,
) {
  await change(member, (rows) =>
    recoverNote(
      rows,
      id,
      action,
      action === "replace"
        ? {
            operation_id: crypto.randomUUID(),
            annotation_id: crypto.randomUUID(),
            note_text: note || "",
            occurred_at: new Date().toISOString(),
          }
        : undefined,
    ),
  );
  window.dispatchEvent(new CustomEvent("maison:queue-change"));
}
