import { PreviewBoundary, FormatSwitch } from "./media-sheets";
import { QueueRecovery } from "./recovery";
import { enqueue, queued, discardQueuedProgress } from "./queue";
import { setIdentity } from "./offline";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";
import { mountIsland } from "./lifecycle";
import {
  api,
  ApiError,
  errorText,
  readBootstrap,
  t,
  type Preferences,
} from "./api";
import {
  newestProgress,
  progressConflictDecision,
  meaningfulSelection,
  samePosition,
  pageCount,
  type Position,
} from "./state";
interface Boot {
  edition_id: string;
  edition_revision_id: string;
  unit_id: string;
  content_locale: string;
  authenticated: boolean;
  member_id?: string;
  device_id?: string;
  anchor: string;
  offset_chars: number;
  next_unit_url?: string;
  previous_unit_url?: string;
  player_url?: string;
  preview?: boolean;
  title_url?: string;
  sign_in_url?: string;
  pass_url?: string;
}
interface Progress {
  version: number;
  last_operation_id?: string | null;
  location?: Position;
}
interface Completion {
  version: number;
  is_complete: boolean;
}
interface Range {
  unit_id: string;
  start_anchor_id: string;
  start_offset_chars: number;
  end_anchor_id: string;
  end_offset_chars: number;
  offset_unit: "unicode_code_point";
}
interface Annotation {
  annotation_id: string;
  edition_revision_id: string;
  version: number;
  quoted_text: string;
  note_text: string | null;
  color: string;
  anchor_status: string;
  range: Range;
}
const defaultPreferences = {
  reader_font_size: 20,
  reader_line_height: 1.65,
  reader_margins: "comfortable",
  reader_alignment: "start",
  reader_theme: "light",
  reader_typeface: "serif",
  reader_layout: "scroll",
};
function Reader({ boot }: { boot: Boot }) {
  const fullReader = boot.authenticated && !boot.preview;
  const reading = document.getElementById("reading-text")!;
  const reader = document.getElementById("reader")!;
  const paragraphs = useRef(
    Array.from(reading.querySelectorAll<HTMLElement>("[data-anchor]")).map(
      (node) => ({
        node,
        anchor: node.dataset.anchor!,
        text: node.textContent || "",
      }),
    ),
  );
  const position = useRef<Position>({
    format: "reader",
    unit_id: boot.unit_id,
    anchor_id: paragraphs.current[0]?.anchor || "",
    offset_chars: 0,
  });
  const progress = useRef<Progress | undefined>(undefined);
  const operationScope = `maison.progress.operations:${boot.member_id}:${boot.edition_id}`;
  const ownOperations = useRef<Set<string>>(new Set());
  function rememberOperation(id: string) {
    ownOperations.current.add(id);
    try {
      sessionStorage.setItem(
        operationScope,
        JSON.stringify([...ownOperations.current].slice(-100)),
      );
    } catch {}
  }
  function acceptProgress(value: Progress) {
    progress.current = newestProgress(progress.current, value);
  }
  useEffect(() => {
    try {
      ownOperations.current = new Set(
        JSON.parse(sessionStorage.getItem(operationScope) || "[]"),
      );
    } catch {}
  }, []);
  const pending = useRef<
    { body: unknown; key: string; version: number } | undefined
  >(undefined);
  const saving = useRef(false);
  const hydrated = useRef(false);
  const interacted = useRef(false);
  const [status, setStatus] = useState("");
  const [boundaryOpen, setBoundaryOpen] = useState(false);
  const [switchOpen, setSwitchOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [completion, setCompletion] = useState<Completion>();
  const pendingCompletion = useRef<
    { key: string; version: number; body: unknown } | undefined
  >(undefined);
  const [notes, setNotes] = useState<Annotation[]>([]);
  const [pendingNotes, setPendingNotes] = useState<string[]>([]);
  const [conflict, setConflict] = useState(false);
  const conflictRef = useRef(false);
  const conflictPosition = useRef<Position | undefined>(undefined);
  const [preferences, setPreferences] = useState<Partial<Preferences>>(() => {
    try {
      const prefs = {
        ...defaultPreferences,
        ...JSON.parse(
          localStorage.getItem("maison.reader.preferences") || "{}",
        ),
      };
      prefs.reader_line_height = Math.max(
        prefs.reader_line_height,
        boot.content_locale === "bn" ? 1.8 : 1.5,
      );
      return prefs;
    } catch {
      return defaultPreferences;
    }
  });
  const preferenceVersion = useRef<number | undefined>(undefined);
  const [settingsStatus, setSettingsStatus] = useState("");
  const settings = useRef<HTMLDialogElement>(null);
  const noteDialog = useRef<HTMLDialogElement>(null);
  const selection = useRef<{ range: Range; quote: string } | undefined>(
    undefined,
  );
  const [quote, setQuote] = useState("");
  const [passage, setPassage] = useState(paragraphs.current[0]?.anchor || "");
  const [noteStatus, setNoteStatus] = useState("");
  const pendingNote = useRef<string | undefined>(undefined);
  const [pages, setPages] = useState({ current: 1, total: 1 });
  const progressPath = `/me/progress/${boot.edition_id}/reader`;
  const completePath = `/me/completion/${boot.edition_id}/reader`;
  function jump(p?: Position) {
    if (!p) return;
    const item = paragraphs.current.find((n) => n.anchor === p.anchor_id);
    if (item) {
      position.current = p;
      item.node.scrollIntoView({ block: "start", behavior: "instant" });
    }
  }
  async function loadNotes() {
    if (!fullReader) return;
    const response = await api<{ items: Annotation[] }>(
      `/me/annotations?edition_revision_id=${boot.edition_revision_id}`,
    );
    setNotes(
      response.items.filter(
        (n) => n.edition_revision_id === boot.edition_revision_id,
      ),
    );
  }
  async function savePosition(keepalive = false) {
    if (
      !fullReader ||
      !position.current.anchor_id ||
      saving.current ||
      !hydrated.current
    )
      return;
    saving.current = true;
    try {
      if (!progress.current)
        progress.current = await api<Progress>(progressPath);
      if (
        !pending.current &&
        samePosition(progress.current.location, position.current)
      ) {
        setStatus(t("saved_server"));
        return;
      }
      setStatus(t("saving"));
      pending.current ??= {
        key: crypto.randomUUID(),
        version: progress.current.version,
        body: null,
      };
      if (pending.current.body === null)
        pending.current.body = {
          operation_id: pending.current.key,
          edition_revision_id: boot.edition_revision_id,
          location: { ...position.current },
          occurred_at: new Date().toISOString(),
        };
      if (!navigator.onLine && boot.member_id) {
        await enqueue(boot.member_id, {
          ...(pending.current.body as Record<string, unknown>),
          operation_id: pending.current.key,
          kind: "progress.set",
          base_version: pending.current.version,
          edition_id: boot.edition_id,
        });
        pending.current = undefined;
        setStatus(t("saved_on_device"));
        return;
      }
      rememberOperation(pending.current.key);
      acceptProgress(
        await api<Progress>(progressPath, {
          method: "PUT",
          ...pending.current,
          keepalive,
        }),
      );
      pending.current = undefined;
      setStatus(t("saved_server"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 412) {
        const latest = await api<Progress>(progressPath);
        const attempted = (
          pending.current?.body as { location?: Position } | undefined
        )?.location;
        try {
          for (const id of JSON.parse(
            sessionStorage.getItem(operationScope) || "[]",
          ))
            ownOperations.current.add(id);
        } catch {}
        const decision = progressConflictDecision(
          latest,
          attempted,
          ownOperations.current,
        );
        if (decision === "already_saved") {
          acceptProgress(latest);
          pending.current = undefined;
          setStatus(t("saved_server"));
          return;
        }
        if (decision === "retry_own" && pending.current) {
          // A previous request from this browser completed after our snapshot. Retry once against its confirmed version.
          const retryKey = crypto.randomUUID();
          const retryBody = {
            ...(pending.current.body as Record<string, unknown>),
            operation_id: retryKey,
          };
          pending.current = {
            key: retryKey,
            version: latest.version,
            body: retryBody,
          };
          rememberOperation(retryKey);
          try {
            acceptProgress(
              await api<Progress>(progressPath, {
                method: "PUT",
                ...pending.current,
                keepalive,
              }),
            );
            pending.current = undefined;
            setStatus(t("saved_server"));
            return;
          } catch (retryError) {
            if (!(retryError instanceof ApiError && retryError.status === 412))
              throw retryError;
          }
        }
        conflictPosition.current = { ...position.current };
        conflictRef.current = true;
        setConflict(true);
        setStatus(t("conflict"));
      } else setStatus(t("unsaved"));
      throw e;
    } finally {
      saving.current = false;
    }
  }
  useEffect(() => {
    if (!fullReader || !boot.member_id || !boot.device_id) return;
    let alive = true;
    const refresh = () => {
      void queued(boot.member_id!).then((rows) => {
        if (alive)
          setPendingNotes(
            rows
              .filter((row) => row.operation.kind === "annotation.create")
              .map((row) =>
                String(
                  (row.operation.annotation as Record<string, unknown>)
                    ?.note_text || t("highlight_pending"),
                ),
              ),
          );
      });
    };
    void setIdentity(boot.member_id, boot.device_id)
      .then(refresh)
      .catch(() => {});
    window.addEventListener("maison:queue-change", refresh);
    const synced = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (
        detail?.results?.some(
          (result: { operation_id: string; outcome: string }) =>
            result.outcome === "conflict" &&
            detail.operations.some(
              (operation: {
                operation_id: string;
                kind: string;
                edition_id: string;
              }) =>
                operation.operation_id === result.operation_id &&
                operation.kind === "progress.set" &&
                operation.edition_id === boot.edition_id,
            ),
        )
      ) {
        conflictPosition.current = { ...position.current };
        conflictRef.current = true;
        setConflict(true);
        setStatus(t("conflict"));
      }
      refresh();
      void loadNotes().catch(() => {});
      void api<Progress>(progressPath)
        .then((value) => {
          acceptProgress(value);
        })
        .catch(() => {});
    };
    window.addEventListener("maison:sync", synced);
    return () => {
      alive = false;
      window.removeEventListener("maison:queue-change", refresh);
      window.removeEventListener("maison:sync", synced);
    };
  }, []);
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        const first = visible[0]?.target as HTMLElement | undefined;
        if (first)
          position.current = {
            format: "reader",
            unit_id: boot.unit_id,
            anchor_id: first.dataset.anchor!,
            offset_chars: 0,
          };
      },
      { rootMargin: "-15% 0px -55% 0px" },
    );
    paragraphs.current.forEach((p) => observer.observe(p.node));
    const measure = () =>
      setPages({
        current:
          Math.floor(reading.scrollLeft / (reading.clientWidth + 50)) + 1,
        total: pageCount(reading.scrollWidth, reading.clientWidth),
      });
    const resize = new ResizeObserver(measure);
    resize.observe(reading);
    reading.addEventListener("scroll", measure, { passive: true });
    if (boot.anchor)
      jump({
        ...position.current,
        anchor_id: boot.anchor,
        offset_chars: boot.offset_chars || 0,
      });
    if (fullReader) {
      Promise.all([
        api<Progress>(progressPath),
        api<Completion>(completePath),
        api<Preferences>("/me/preferences"),
      ])
        .then(([saved, finished, prefs]) => {
          acceptProgress(saved);
          setCompletion(finished);
          preferenceVersion.current = prefs.version;
          setPreferences({
            ...prefs,
            reader_line_height: Math.max(
              prefs.reader_line_height,
              boot.content_locale === "bn" ? 1.8 : 1.5,
            ),
          });
          if (!boot.anchor && saved.location?.unit_id === boot.unit_id)
            jump(saved.location);
          hydrated.current = true;
        })
        .catch((e) => setStatus(errorText(e)));
      loadNotes().catch((e) => setStatus(errorText(e)));
    }
    const timer = window.setInterval(() => {
      if (
        fullReader &&
        !document.hidden &&
        navigator.onLine &&
        progress.current &&
        hydrated.current &&
        interacted.current &&
        !samePosition(progress.current.location, position.current) &&
        !conflictRef.current
      )
        void savePosition().catch(() => {});
    }, 15000);
    const visibility = () => {
      if (
        document.hidden &&
        hydrated.current &&
        interacted.current &&
        !samePosition(progress.current?.location, position.current)
      )
        void savePosition(true).catch(() => {});
    };
    const interaction = () => {
      interacted.current = true;
    };
    for (const event of ["wheel", "touchmove", "keydown"])
      reading.addEventListener(event, interaction, { passive: true });
    document.addEventListener("visibilitychange", visibility);
    const trigger = document.getElementById("reader-settings-trigger");
    const show = () => settings.current?.showModal();
    trigger?.addEventListener("click", show);
    return () => {
      observer.disconnect();
      resize.disconnect();
      clearInterval(timer);
      reading.removeEventListener("scroll", measure);
      for (const event of ["wheel", "touchmove", "keydown"])
        reading.removeEventListener(event, interaction);
      document.removeEventListener("visibilitychange", visibility);
      trigger?.removeEventListener("click", show);
    };
  }, []);
  useEffect(() => {
    const leading = Math.max(
      Number(preferences.reader_line_height) || 1.65,
      boot.content_locale === "bn" ? 1.8 : 1.5,
    );
    reader.style.setProperty(
      "--reader-size",
      `${Number(preferences.reader_font_size) || 20}px`,
    );
    reader.style.setProperty("--reader-leading", String(leading));
    reader.style.setProperty(
      "--reader-measure",
      (
        { compact: "55ch", comfortable: "65ch", wide: "72ch" } as Record<
          string,
          string
        >
      )[preferences.reader_margins || "comfortable"],
    );
    reader.style.setProperty(
      "--reader-alignment",
      preferences.reader_alignment || "start",
    );
    for (const name of ["light", "paper", "sepia", "dark", "ink", "true_black"])
      reader.classList.remove("reader-" + name);
    reader.classList.add("reader-" + (preferences.reader_theme || "light"));
    reader.classList.toggle("sans", preferences.reader_typeface === "sans");
    reader.dataset.layout = preferences.reader_layout || "scroll";
  }, [preferences]);
  useEffect(() => {
    paragraphs.current.forEach((p) => {
      const chars = Array.from(p.text);
      const fragment = document.createDocumentFragment();
      let cursor = 0;
      const records = notes
        .filter(
          (n) =>
            n.range.start_anchor_id === p.anchor &&
            n.range.end_anchor_id === p.anchor &&
            n.anchor_status !== "orphaned",
        )
        .sort(
          (a, b) => a.range.start_offset_chars - b.range.start_offset_chars,
        );
      for (const n of records) {
        const start = n.range.start_offset_chars,
          end = n.range.end_offset_chars;
        if (start < cursor || end > chars.length || end <= start) continue;
        fragment.append(
          document.createTextNode(chars.slice(cursor, start).join("")),
        );
        const mark = document.createElement("mark");
        mark.className = ["gold", "mint", "rose", "lavender"].includes(n.color)
          ? n.color
          : "gold";
        mark.textContent = chars.slice(start, end).join("");
        fragment.append(mark);
        cursor = end;
      }
      fragment.append(document.createTextNode(chars.slice(cursor).join("")));
      p.node.replaceChildren(fragment);
    });
  }, [notes]);
  function selectParagraph(anchor: string) {
    const p =
      paragraphs.current.find((p) => p.anchor === anchor) ||
      paragraphs.current[0];
    if (!p) return;
    selection.current = {
      range: {
        unit_id: boot.unit_id,
        start_anchor_id: p.anchor,
        start_offset_chars: 0,
        end_anchor_id: p.anchor,
        end_offset_chars: Array.from(p.text).length,
        offset_unit: "unicode_code_point",
      },
      quote: p.text,
    };
    setPassage(p.anchor);
    setQuote(p.text);
  }
  function captureSelection() {
    const s = window.getSelection();
    if (!s?.rangeCount || s.isCollapsed || !meaningfulSelection(s.toString()))
      return false;
    const r = s.getRangeAt(0);
    function point(node: Node, offset: number) {
      const p = (
        node.nodeType === Node.ELEMENT_NODE
          ? (node as Element)
          : node.parentElement
      )?.closest<HTMLElement>("[data-anchor]");
      if (!p || !reading.contains(p)) return;
      const range = document.createRange();
      range.selectNodeContents(p);
      range.setEnd(node, offset);
      return {
        anchor: p.dataset.anchor!,
        offset: Array.from(range.toString()).length,
      };
    }
    const start = point(r.startContainer, r.startOffset),
      end = point(r.endContainer, r.endOffset);
    if (!start || !end) return false;
    selection.current = {
      range: {
        unit_id: boot.unit_id,
        start_anchor_id: start.anchor,
        start_offset_chars: start.offset,
        end_anchor_id: end.anchor,
        end_offset_chars: end.offset,
        offset_unit: "unicode_code_point",
      },
      quote: s.toString(),
    };
    setQuote(s.toString());
    setPassage(start.anchor);
    return true;
  }
  useEffect(() => {
    const capture = () => {
      captureSelection();
    };
    reading.addEventListener("pointerup", capture);
    reading.addEventListener("keyup", capture);
    return () => {
      reading.removeEventListener("pointerup", capture);
      reading.removeEventListener("keyup", capture);
    };
  }, []);
  async function act(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (e) {
      setStatus(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function saveSettings(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSettingsStatus("");
    try {
      if (fullReader) {
        const currentVersion =
          preferenceVersion.current ??
          (await api<Preferences>("/me/preferences")).version;
        const p = await api<Preferences>("/me/preferences", {
          method: "PATCH",
          version: currentVersion,
          body: Object.fromEntries(
            Object.entries(preferences).filter(([key]) =>
              key.startsWith("reader_"),
            ),
          ),
          key: crypto.randomUUID(),
        });
        preferenceVersion.current = p.version;
        setPreferences(p);
      } else
        localStorage.setItem(
          "maison.reader.preferences",
          JSON.stringify(preferences),
        );
      settings.current?.close();
    } catch (e) {
      setSettingsStatus(errorText(e));
    }
  }
  function pref<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    setPreferences((p) => ({ ...p, [key]: value }));
  }
  async function switchToListen() {
    await act(async () => {
      const result = await api<{
        outcome: string;
        to_location?: { asset_id: string; position_ms: number };
      }>("/content/switch-position", {
        method: "POST",
        key: crypto.randomUUID(),
        body: {
          edition_revision_id: boot.edition_revision_id,
          from_location: position.current,
          to_format: "audio",
        },
      });
      await savePosition();
      if (result.outcome === "mapped" && result.to_location)
        window.location.assign(
          boot.player_url +
            `?asset=${result.to_location.asset_id}&position_ms=${result.to_location.position_ms}`,
        );
      else setStatus(t("switch_unmapped_audio"));
    });
  }
  const paginated = preferences.reader_layout === "paginated";
  return (
    <>
      <nav className="unit-navigation" aria-label={t("contents")}>
        {!boot.preview && boot.previous_unit_url ? (
          <a
            href={boot.previous_unit_url}
            onClick={() => {
              void savePosition(true).catch(() => {});
            }}
          >
            {t("previous_chapter")}
          </a>
        ) : null}
        {!boot.preview && boot.next_unit_url ? (
          <a
            href={boot.next_unit_url}
            onClick={() => {
              void savePosition(true).catch(() => {});
            }}
          >
            {t("next_chapter")}
          </a>
        ) : null}
        {fullReader && boot.player_url ? (
          <button disabled={busy} onClick={() => { setStatus(""); setSwitchOpen(true); }}>
            {t("switch_to_listen")}
          </button>
        ) : null}
      </nav>
      <div
        className="reader-page-controls"
        id="reader-page-controls"
        hidden={!paginated}
      >
        <button
          id="previous-reading-page"
          disabled={pages.current <= 1}
          onClick={() =>
            reading.scrollBy({
              left: -(reading.clientWidth + 50),
              behavior: "instant",
            })
          }
        >
          {t("back")}
        </button>
        <output id="reading-page-status">
          {t("page")} {pages.current} / {pages.total}
        </output>
        <button
          id="next-reading-page"
          disabled={pages.current >= pages.total}
          onClick={() =>
            reading.scrollBy({
              left: reading.clientWidth + 50,
              behavior: "instant",
            })
          }
        >
          {t("continue")}
        </button>
      </div>
      {fullReader ? (
        <>
          <div className="reader-actions">
            <button
              id="annotate-selection"
              onClick={() => {
                if (
                  !captureSelection() &&
                  !meaningfulSelection(selection.current?.quote || "")
                )
                  selectParagraph(position.current.anchor_id);
                noteDialog.current?.showModal();
              }}
            >
              {t("annotate")}
            </button>
            <button
              id="save-position"
              disabled={busy}
              onClick={() => act(() => savePosition())}
            >
              {t("use_local")}
            </button>
            <button
              id="complete-reading"
              aria-pressed={!!completion?.is_complete}
              disabled={busy || !completion}
              onClick={() =>
                act(async () => {
                  const old =
                    completion ?? (await api<Completion>(completePath));
                  pendingCompletion.current ??= {
                    key: crypto.randomUUID(),
                    version: old.version,
                    body: null,
                  };
                  if (pendingCompletion.current.body === null)
                    pendingCompletion.current.body = {
                      operation_id: pendingCompletion.current.key,
                      is_complete: !old.is_complete,
                    };
                  setCompletion(
                    await api<Completion>(completePath, {
                      method: "PUT",
                      ...pendingCompletion.current,
                    }),
                  );
                  pendingCompletion.current = undefined;
                  setStatus(t("saved_server"));
                })
              }
            >
              {t(completion?.is_complete ? "uncomplete" : "complete")}
            </button>
          </div>
          <p
            id="reader-status"
            className="save-status"
            role="status"
            aria-live="polite"
          >
            {status}
            {pendingNotes.map((note, index) => (
              <span key={index} className="pending-note">
                {t("saved_on_device")}: {note}
              </span>
            ))}
          </p>
          {boot.member_id ? <QueueRecovery member={boot.member_id} /> : null}
          <div id="progress-conflict" className="notice" hidden={!conflict}>
            <p>{t("conflict")}</p>
            <button
              id="use-server"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  progress.current = await api<Progress>(progressPath);
                  if (boot.member_id)
                    await discardQueuedProgress(
                      boot.member_id,
                      boot.edition_id,
                    );
                  pending.current = undefined;
                  jump(progress.current.location);
                  conflictRef.current = false;
                  setConflict(false);
                  setStatus(t("saved_server"));
                })
              }
            >
              {t("use_server")}
            </button>
            <button
              id="use-local"
              aria-label={t("resolve_keep_local")}
              disabled={busy}
              onClick={() =>
                act(async () => {
                  progress.current = await api<Progress>(progressPath);
                  if (boot.member_id)
                    await discardQueuedProgress(
                      boot.member_id,
                      boot.edition_id,
                    );
                  pending.current = undefined;
                  position.current =
                    conflictPosition.current || position.current;
                  await savePosition();
                  conflictRef.current = false;
                  setConflict(false);
                })
              }
            >
              {t("use_local")}
            </button>
          </div>
          <section className="annotation-list">
            <h2>{t("annotations")}</h2>
            <div id="annotations">
              {notes.length ? (
                notes.map((note) => (
                  <article key={note.annotation_id}>
                    <blockquote>{note.quoted_text}</blockquote>
                    {note.note_text ? <p>{note.note_text}</p> : null}
                    <button
                      onClick={() =>
                        jump({
                          format: "reader",
                          unit_id: note.range.unit_id,
                          anchor_id: note.range.start_anchor_id,
                          offset_chars: note.range.start_offset_chars,
                        })
                      }
                    >
                      {t("jump")}
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        act(async () => {
                          await api("/me/annotations/" + note.annotation_id, {
                            method: "DELETE",
                            version: note.version,
                            key: crypto.randomUUID(),
                          });
                          await loadNotes();
                        })
                      }
                    >
                      {t("delete_note")}
                    </button>
                  </article>
                ))
              ) : (
                <p>{t("no_annotations")}</p>
              )}
            </div>
          </section>
        </>
      ) : null}
      {boot.preview ? <section className="preview-boundary" aria-label={t("preview_end")}><p>{t("preview_end")}</p><button onClick={() => setBoundaryOpen(true)}>{t("continue_beyond_preview")}</button><PreviewBoundary editionId={boot.edition_id} format="reader" authenticated={boot.authenticated} titleUrl={boot.title_url || `/${document.documentElement.dataset.uiLocale || "en"}/titles/${boot.edition_id}/`} signInUrl={boot.sign_in_url || `/${document.documentElement.dataset.uiLocale || "en"}/sign-in/?return_to=${encodeURIComponent(location.pathname + location.search)}`} passUrl={boot.pass_url || `/${document.documentElement.dataset.uiLocale || "en"}/pass/`} open={boundaryOpen} onClose={() => setBoundaryOpen(false)} onRetry={() => location.reload()} /></section> : null}
      {fullReader && boot.player_url ? <FormatSwitch open={switchOpen} onClose={() => setSwitchOpen(false)} busy={busy} status={status} onExact={() => void switchToListen()} chapterUrl={boot.player_url + `?unit_id=${boot.unit_id}`} target="audio" /> : null}
      <dialog
        ref={settings}
        id="reading-settings"
        className="maison-dialog"
        aria-labelledby="settings-title"
      >
        <div className="dialog-heading">
          <h2 id="settings-title">{t("reader_settings")}</h2>
          <button onClick={() => settings.current?.close()}>
            {t("close")}
          </button>
        </div>
        <form id="reading-settings-form" onSubmit={saveSettings}>
          <div className="form-grid">
            <label>
              {t("text_size")}
              <select
                name="reader_font_size"
                value={preferences.reader_font_size}
                onChange={(e) =>
                  pref("reader_font_size", Number(e.target.value))
                }
              >
                {[16, 20, 23, 26, 30].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              {t("typeface")}
              <select
                name="reader_typeface"
                value={preferences.reader_typeface}
                onChange={(e) => pref("reader_typeface", e.target.value)}
              >
                <option value="serif">
                  {boot.content_locale === "bn"
                    ? "Noto Serif Bengali"
                    : "Source Serif 4"}
                </option>
                <option value="sans">
                  {boot.content_locale === "bn"
                    ? "Noto Sans Bengali"
                    : "DM Sans"}
                </option>
              </select>
            </label>
            <label>
              {t("leading")}
              <input
                name="reader_line_height"
                type="number"
                min={boot.content_locale === "bn" ? 1.8 : 1.5}
                max="2.4"
                step="0.05"
                value={preferences.reader_line_height}
                onChange={(e) =>
                  pref("reader_line_height", Number(e.target.value))
                }
              />
            </label>
            {(
              [
                "reader_margins",
                "reader_alignment",
                "reader_layout",
                "reader_theme",
              ] as const
            ).map((key, index) => {
              const values = [
                ["compact", "comfortable", "wide"],
                ["start", "justify"],
                ["scroll", "paginated"],
                ["light", "sepia", "dark", "true_black"],
              ][index];
              return (
                <label key={key}>
                  {t(["margins", "alignment", "layout", "theme"][index])}
                  <select
                    name={key}
                    value={preferences[key]}
                    onChange={(e) => pref(key, e.target.value)}
                  >
                    {values.map((v) => (
                      <option key={v} value={v}>
                        {(
                          {
                            compact: "55ch",
                            comfortable: "65ch",
                            wide: "72ch",
                          } as Record<string, string>
                        )[v] ||
                          t(
                            (
                              {
                                start: "align_start",
                                justify: "align_justify",
                                light: "paper",
                                dark: "ink",
                                true_black: "black",
                              } as Record<string, string>
                            )[v] || v,
                          )}
                      </option>
                    ))}
                  </select>
                </label>
              );
            })}
          </div>
          <p className="fine" id="preference-ownership">
            {t(fullReader ? "preferences_account" : "local_settings")}
          </p>
          <button className="button" type="submit">
            {t("keep_settings")}
          </button>
          <p role="status" id="settings-status">
            {settingsStatus}
          </p>
        </form>
      </dialog>
      {fullReader ? (
        <dialog
          ref={noteDialog}
          id="annotation-dialog"
          className="maison-dialog"
          aria-labelledby="annotation-title"
        >
          <div className="dialog-heading">
            <h2 id="annotation-title">{t("annotate")}</h2>
            <button onClick={() => noteDialog.current?.close()}>
              {t("close")}
            </button>
          </div>
          <form
            id="annotation-form"
            onSubmit={async (e) => {
              e.preventDefault();
              const form = e.currentTarget;
              try {
                if (!selection.current)
                  selectParagraph(position.current.anchor_id);
                const data = new FormData(form),
                  note = String(data.get("note_text") || "");
                if (new TextEncoder().encode(note).length > 8192)
                  throw new Error(t("invalid_input"));
                pendingNote.current ??= crypto.randomUUID();
                const annotation = {
                  annotation_id: pendingNote.current,
                  edition_revision_id: boot.edition_revision_id,
                  kind: note ? "note" : "highlight",
                  range: selection.current!.range,
                  color: data.get("color"),
                  note_text: note || null,
                };
                const locallyQueued = !navigator.onLine && !!boot.member_id;
                if (locallyQueued)
                  await enqueue(boot.member_id!, {
                    operation_id: pendingNote.current,
                    kind: "annotation.create",
                    annotation,
                    occurred_at: new Date().toISOString(),
                  });
                else
                  await api("/me/annotations", {
                    method: "POST",
                    key: pendingNote.current,
                    body: annotation,
                  });
                pendingNote.current = undefined;
                form.reset();
                noteDialog.current?.close();
                if (!locallyQueued) await loadNotes();
                setStatus(
                  t(locallyQueued ? "saved_on_device" : "saved_server"),
                );
                setNoteStatus("");
              } catch (error) {
                setNoteStatus(errorText(error));
              }
            }}
          >
            <p>{t("select_passage")}</p>
            <label htmlFor="annotation-passage">{t("passage")}</label>
            <select
              id="annotation-passage"
              value={passage}
              onChange={(e) => selectParagraph(e.target.value)}
            >
              {paragraphs.current.map((p, index) => (
                <option key={p.anchor} value={p.anchor}>
                  {index + 1}. {p.text.slice(0, 90)}
                </option>
              ))}
            </select>
            <blockquote id="annotation-quote" lang={boot.content_locale}>
              {quote}
            </blockquote>
            <fieldset>
              <legend>{t("highlight_color")}</legend>
              <div className="radio-options">
                {["gold", "mint", "rose", "lavender"].map((color) => (
                  <label key={color}>
                    <input
                      type="radio"
                      name="color"
                      value={color}
                      defaultChecked={color === "gold"}
                    />
                    {t(color)}
                  </label>
                ))}
              </div>
            </fieldset>
            <label htmlFor="note-text">{t("note_optional")}</label>
            <textarea
              id="note-text"
              name="note_text"
              maxLength={8192}
              rows={4}
            />
            <button className="button" type="submit">
              {t("save_note")}
            </button>
            <p id="annotation-status" role="status">
              {noteStatus}
            </p>
          </form>
        </dialog>
      ) : null}
    </>
  );
}
export function mount() {
  document.querySelector<HTMLElement>("[data-preview-fallback]")?.setAttribute("hidden", "");
  mountIsland(document.getElementById("reader-controls"), () => (
    <Reader boot={readBootstrap<Boot>("reader-bootstrap")} />
  ));
}
mount();
