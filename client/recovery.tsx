import { useEffect, useState } from "react";
import { queued, recoverQueuedNote, flushQueue } from "./queue";
import { type QueuedWrite } from "./queue-state";
import { t, errorText } from "./api";
export function QueueRecovery({ member }: { member: string }) {
  const [rows, setRows] = useState<QueuedWrite[]>([]),
    [status, setStatus] = useState("");
  useEffect(() => {
    let alive = true;
    const refresh = () =>
      void queued(member)
        .then((value) => {
          if (alive)
            setRows(
              value.filter((row) => row.operation.kind === "annotation.create"),
            );
        })
        .catch((error) => setStatus(errorText(error)));
    refresh();
    window.addEventListener("maison:queue-change", refresh);
    return () => {
      alive = false;
      window.removeEventListener("maison:queue-change", refresh);
    };
  }, [member]);
  async function act(action: () => Promise<void>) {
    try {
      await action();
      setStatus("");
    } catch (error) {
      setStatus(errorText(error));
    }
  }
  if (!rows.length) return null;
  return (
    <section aria-label={t("pending_notes")}>
      <h2>{t("pending_notes")}</h2>
      <p role="status">{status}</p>
      {rows.map((row) => (
        <PendingNote
          key={row.operation.operation_id}
          row={row}
          onAction={(action, note) =>
            void act(async () => {
              await recoverQueuedNote(
                member,
                row.operation.operation_id,
                action,
                note,
              );
              if (action !== "delete") await flushQueue();
            })
          }
        />
      ))}
    </section>
  );
}
function PendingNote({
  row,
  onAction,
}: {
  row: QueuedWrite;
  onAction: (action: "retry" | "delete" | "replace", note?: string) => void;
}) {
  const annotation = row.operation.annotation as Record<string, unknown>,
    [editing, setEditing] = useState(false),
    [note, setNote] = useState(String(annotation.note_text || ""));
  function exportNote() {
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            {
              schema_version: 1,
              operation: row.operation,
              problem: row.problem || null,
            },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "maison-note-" + row.operation.operation_id + ".json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <article>
      <p>{String(annotation.note_text || t("highlight_pending"))}</p>
      <p>{t(row.blocked ? "note_needs_review" : "saved_on_device")}</p>
      <div className="actions">
        <button onClick={() => onAction("retry")}>{t("retry")}</button>
        <button onClick={exportNote}>{t("export_note")}</button>
        {row.blocked ? (
          <button onClick={() => setEditing(!editing)}>{t("edit_note")}</button>
        ) : null}
        <button
          onClick={() => {
            if (window.confirm(t("delete_local_note_confirm")))
              onAction("delete");
          }}
        >
          {t("delete_local_note")}
        </button>
      </div>
      {editing ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onAction("replace", note);
            setEditing(false);
          }}
        >
          <label>
            {t("note")}
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              required
            />
          </label>
          <p>{t("replace_note_help")}</p>
          <button type="submit">{t("replace_note")}</button>
        </form>
      ) : null}
    </article>
  );
}
