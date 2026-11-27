import { PreviewBoundary, PreviewEnding, FormatSwitch, MediaSheet } from "./media-sheets";
import { QueueRecovery } from "./recovery";
import { enqueue, queued, discardQueuedProgress } from "./queue";
import { setIdentity } from "./offline";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from "react";
import { mountIsland } from "./lifecycle";
import { clearFollow, drawFollow } from "./follow-dom";
import {
  autoscrollAllowed,
  currentHighlight,
  isUserScroll,
  mapFailed,
  mapFetchPlan,
  type MapEntry,
  OWN_SCROLL_MS,
  PLAYBACK_EVENT,
  PLAYBACK_REQUEST_EVENT,
  type FollowMap,
  type PlaybackDetail,
} from "./sentences";
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
  createSaveQueue,
  radioKeyTarget,
  stepLeading,
  leadingFloor,
} from "./state";
interface Boot {
  edition_id: string;
  edition_revision_id: string;
  unit_id: string;
  content_locale: string;
  free_access?: boolean;
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
  edition_title?: string;
  remaining_minutes?: number | null;
  formats?: { listen?: boolean; watch?: boolean };
  listen_sign_in_url?: string;
  watch_sign_in_url?: string;
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
function prefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}
const defaultPreferences = {
  reader_font_size: 20,
  reader_line_height: 1.65,
  reader_margins: "comfortable",
  reader_alignment: "start",
  reader_theme: "system",
  reader_typeface: "serif",
  reader_layout: "scroll",
};
function RadioGroup({ labelledBy, className, value, options, onSelect }: {
  labelledBy: string;
  className: string;
  value: string;
  options: Array<{ value: string; className: string; content: ReactNode }>;
  onSelect: (value: string) => void;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const checked = Math.max(options.findIndex((o) => o.value === value), 0);
  return (
    <div className={className} role="radiogroup" aria-labelledby={labelledBy}>
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => { refs.current[i] = el; }}
          type="button"
          role="radio"
          aria-checked={i === checked}
          tabIndex={i === checked ? 0 : -1}
          className={o.className}
          onClick={() => onSelect(o.value)}
          onKeyDown={(e) => {
            const to = radioKeyTarget(e.key, i, options.length);
            if (to === undefined) return;
            e.preventDefault();
            onSelect(options[to].value);
            refs.current[to]?.focus();
          }}
        >
          {o.content}
        </button>
      ))}
    </div>
  );
}
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
      const stored = JSON.parse(
        localStorage.getItem("maison.reader.preferences") || "{}",
      );
      const prefs = { ...defaultPreferences, ...stored };
      prefs.reader_theme =
        document.body.dataset.readerThemeSaved ||
        (["light", "sepia", "dark", "true_black"].includes(stored.reader_theme)
          ? stored.reader_theme
          : "system");
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
  const [comfortOpen, setComfortOpen] = useState(false);
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
    const show = () => setComfortOpen(true);
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
      widthMeasure(preferences.reader_margins),
    );
    reader.style.setProperty(
      "--reader-alignment",
      effectiveAlignment(preferences.reader_alignment, boot.content_locale),
    );
    for (const name of ["light", "paper", "sepia", "dark", "ink", "true_black"])
      reader.classList.remove("reader-" + name);
    const theme = initialReaderTheme(preferences.reader_theme, prefersDark());
    reader.classList.add("reader-" + theme);
    for (const name of ["light", "sepia", "dark", "true_black"])
      document.body.classList.remove("reader-theme-" + name);
    document.body.classList.add("reader-theme-" + theme);
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
  /** Follow-along: the sentence (or paragraph) the persistent player is narrating, drawn without changing the text. */
  const [follow, setFollow] = useState<{
    anchor: string;
    range: [number, number] | null;
    playing: boolean;
  }>();
  const followNow = useRef(follow);
  /** Maps by the asset actually playing; null once the server said that rendition has none. */
  const followMaps = useRef<Map<string, MapEntry>>(new Map());
  const [followUnavailable, setFollowUnavailable] = useState(false);
  const lastUserScroll = useRef<number | undefined>(undefined);
  const ownScrollUntil = useRef(0);
  const noteUserScroll = (type: string, key?: string) => {
    if (isUserScroll(type, key, Date.now(), ownScrollUntil.current))
      lastUserScroll.current = Date.now();
  };
  const ownScroll = () => {
    ownScrollUntil.current = Date.now() + OWN_SCROLL_MS;
  };
  useEffect(() => {
    if (!fullReader || !boot.player_url) return;
    let cancelled = false;
    const heard = (event: Event) => {
      const d = (event as CustomEvent<PlaybackDetail | undefined>).detail;
      if (
        !d ||
        d.closed ||
        d.edition_id !== boot.edition_id ||
        d.unit_id !== boot.unit_id
      ) {
        followNow.current = undefined;
        setFollow(undefined);
        setFollowUnavailable(false);
        return;
      }
      const entry = followMaps.current.get(d.asset_id);
      const plan = mapFetchPlan(entry, Date.now());
      if (plan === "fetch") {
        followMaps.current.set(d.asset_id, "loading");
        api<{ maps: (FollowMap & { asset_id: string })[] }>(
          `/content/mappings/${boot.edition_revision_id}?unit_id=${boot.unit_id}&asset_id=${d.asset_id}`,
        )
          .then((r) => {
            const mine = r.maps.filter((m) => m.asset_id === d.asset_id);
            followMaps.current.set(d.asset_id, {
              maps: mine.length ? mine : null,
            });
            if (!cancelled)
              window.dispatchEvent(new Event(PLAYBACK_REQUEST_EVENT)); // only after a successful load
          })
          .catch(() =>
            followMaps.current.set(d.asset_id, mapFailed(entry, Date.now())),
          ); // backs off; no replay request
        return;
      }
      if (
        plan === "wait" ||
        !entry ||
        entry === "loading" ||
        "failures" in entry
      )
        return;
      const known = entry.maps as FollowMap[] | null;
      setFollowUnavailable(known === null);
      if (known === null) {
        followNow.current = undefined;
        setFollow(undefined);
        return;
      }
      const before = followNow.current;
      const now = currentHighlight(known, before?.anchor ?? null, d.ms);
      if (!now.anchorId) return; // before the first segment or in a silent gap: keep what is shown
      if (
        before &&
        before.anchor === now.anchorId &&
        before.playing === d.playing &&
        before.range?.[0] === now.range?.[0] &&
        before.range?.[1] === now.range?.[1]
      )
        return;
      followNow.current = {
        anchor: now.anchorId,
        range: now.range,
        playing: d.playing,
      };
      setFollow(followNow.current);
    };
    const byHand = (event: Event) =>
      noteUserScroll(event.type, (event as KeyboardEvent).key);
    window.addEventListener(PLAYBACK_EVENT, heard);
    for (const type of ["wheel", "touchmove", "keydown"])
      window.addEventListener(type, byHand, { passive: true });
    window.addEventListener("scroll", byHand, { passive: true, capture: true });
    window.dispatchEvent(new Event(PLAYBACK_REQUEST_EVENT));
    return () => {
      cancelled = true;
      window.removeEventListener(PLAYBACK_EVENT, heard);
      for (const type of ["wheel", "touchmove", "keydown"])
        window.removeEventListener(type, byHand);
      window.removeEventListener("scroll", byHand, { capture: true });
      clearFollow(reading);
    };
  }, []);
  // Immersive toolbar: hides on a scroll down by hand, returns on scroll up, tap or focus. The reader's own
  // follow-along autoscroll (ownScroll, then the scroll event it causes) neither hides nor shows it, so it never
  // fights the audio; only isUserScroll() events count. Focus inside it keeps it shown (keyboard focus only, so a tap does not pin it; CSS :has(:focus-visible) too).
  const [headings] = useState(() => headingsFor(reading.innerHTML));
  const [chaptersOpen, setChaptersOpen] = useState(false);
  useEffect(() => {
    const bar = document.querySelector<HTMLElement>(".reader-toolbar");
    const hairline = document.getElementById("reader-progress");
    const fill = hairline?.firstElementChild as HTMLElement | null;
    const minutes = document.getElementById("reader-minutes");
    const chapters = document.getElementById("reader-chapters-trigger");
    const chars = paragraphs.current.reduce((n, p) => n + p.text.length, 0);
    let lastTop = window.scrollY;
    const measureProgress = () => {
      const paged = reader.dataset.layout === "paginated";
      const fraction = paged
        ? progressFraction(
            reading.scrollLeft,
            reading.scrollWidth,
            reading.clientWidth,
          )
        : progressFraction(
            Math.max(0, window.scrollY - reading.offsetTop),
            reading.offsetHeight,
            window.innerHeight,
          );
      if (fill) fill.style.transform = `scaleX(${fraction})`;
      const left = minutesRemaining(Math.round(chars * (1 - fraction)));
      const pct = Math.round(fraction * 100);
      hairline?.setAttribute("aria-valuenow", String(pct));
      hairline?.setAttribute(
        "aria-valuetext",
        left ? `${pct}%, ${left} ${t("min_left")}` : `${pct}%`,
      );
      if (minutes) minutes.textContent = left ? `${left} ${t("min_left")}` : "";
    };
    const keyboardInside = () => {
      const f = document.activeElement;
      return toolbarPinned(
        !!f && !!bar?.contains(f),
        !!f && f.matches(":focus-visible"),
      );
    };
    const pinned = keyboardInside;
    const measureBar = () =>
      document.documentElement.style.setProperty(
        "--reader-toolbar-h",
        `${bar?.offsetHeight ?? 60}px`,
      );
    measureBar();
    const barSize = bar ? new ResizeObserver(measureBar) : undefined;
    if (bar) barSize?.observe(bar);
    const place = (hidden: boolean) => bar?.classList.toggle("is-hidden", hidden);
    const onScroll = () => {
      measureProgress();
      const top = window.scrollY;
      const mine = !isUserScroll("scroll", undefined, Date.now(), ownScrollUntil.current);
      if (!mine && bar)
        place(
          toolbarHidden(bar.classList.contains("is-hidden"), lastTop, top, pinned()),
        );
      lastTop = top;
    };
    const onTap = () => {
      if (bar?.classList.contains("is-hidden")) place(false);
    };
    const onFocus = () => {
      if (keyboardInside()) place(false);
    };
    const openChapters = () => setChaptersOpen(true);
    if (chapters) chapters.hidden = headings.length === 0;
    measureProgress();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", measureProgress);
    reading.addEventListener("scroll", measureProgress, { passive: true });
    reader.addEventListener("click", onTap);
    bar?.addEventListener("focusin", onFocus);
    chapters?.addEventListener("click", openChapters);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", measureProgress);
      reading.removeEventListener("scroll", measureProgress);
      reader.removeEventListener("click", onTap);
      bar?.removeEventListener("focusin", onFocus);
      chapters?.removeEventListener("click", openChapters);
      barSize?.disconnect();
    };
  }, []);
  function jumpToChapter(id: string) {
    noteUserScroll("page-button"); // a chapter jump is the reader's own choice: follow-along pauses 5 s
    setChaptersOpen(false);
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "instant", block: "start", inline: "start" });
  }
  useEffect(() => {
    if (!follow) return clearFollow(reading);
    const p = paragraphs.current.find((item) => item.anchor === follow.anchor);
    if (!p) return;
    const rect = drawFollow(p.node, follow.range);
    if (
      !follow.playing ||
      !rect ||
      !autoscrollAllowed(Date.now(), lastUserScroll.current)
    )
      return;
    const box = rect();
    if (preferences.reader_layout === "paginated") {
      const page = reading.clientWidth + 50;
      const left =
        Math.floor(
          (box.left -
            reading.getBoundingClientRect().left +
            reading.scrollLeft) /
            page,
        ) * page;
      if (Math.abs(left - reading.scrollLeft) > 1) {
        ownScroll();
        reading.scrollTo({ left, behavior: "instant" });
      }
    } else if (box.top < 0 || box.bottom > window.innerHeight) {
      ownScroll();
      window.scrollBy({
        top: box.top - window.innerHeight * 0.3,
        behavior: "instant",
      });
    }
  }, [follow, notes, preferences.reader_font_size, preferences.reader_margins, preferences.reader_layout, preferences.reader_typeface, preferences.reader_alignment, preferences.reader_line_height]);
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
  const latestPreferences = useRef(preferences);
  latestPreferences.current = preferences;
  const queue = useRef<ReturnType<typeof createSaveQueue<Partial<Preferences>>>>(undefined);
  if (!queue.current)
    queue.current = createSaveQueue<Partial<Preferences>>({
      send: async (next) => {
        if (!fullReader) {
          localStorage.setItem("maison.reader.preferences", JSON.stringify(next));
          return;
        }
        const version =
          preferenceVersion.current ??
          (await api<Preferences>("/me/preferences")).version;
        const p = await api<Preferences>("/me/preferences", {
          method: "PATCH",
          version,
          body: Object.fromEntries(
            Object.entries(latestPreferences.current).filter(([key]) =>
              key.startsWith("reader_"),
            ),
          ),
          key: crypto.randomUUID(),
        });
        preferenceVersion.current = p.version; // only the version; the screen keeps the reader's own values
      },
      isConflict: (e) => e instanceof ApiError && (e.status === 409 || e.status === 412),
      refresh: async () => {
        preferenceVersion.current = (await api<Preferences>("/me/preferences")).version;
      },
      onSaved: () => setSettingsStatus(""),
      onError: (e) => {
        preferenceVersion.current = undefined;
        setSettingsStatus(fullReader ? t("comfort_not_saved") : errorText(e));
      },
    });
  function persistPreferences(next: Partial<Preferences>) {
    return queue.current!.push(next);
  }
  const saver = useRef<ReturnType<typeof createDebouncedSaver<Partial<Preferences>>>>(undefined);
  if (!saver.current)
    saver.current = createDebouncedSaver<Partial<Preferences>>(
      (value) => void persistPreferences(value),
      PREFERENCE_SAVE_MS,
    );
  useEffect(() => () => {
    // leaving the page must not lose the last change
    if (saver.current?.pending()) void persistPreferences(latestPreferences.current);
    saver.current?.cancel();
  }, []);
  function pref<K extends keyof Preferences>(key: K, value: Preferences[K]) {
    if (latestPreferences.current[key] === value) return; // a step against an end stop changes nothing
    const next = { ...latestPreferences.current, [key]: value };
    latestPreferences.current = next;
    setPreferences(next);
    saver.current?.schedule(next);
  }
  async function switchToListen() {
    await act(async () => {
      const result = await api<{
        outcome: string;
        to_location?: { format: "audio"; unit_id: string; position_ms: number };
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
      if (result.outcome === "mapped" && result.to_location?.format === "audio")
        window.location.assign(
          boot.player_url +
            `?unit_id=${result.to_location.unit_id}&position_ms=${result.to_location.position_ms}`,
        );
      else {
        setStatus(t("switch_unmapped_audio"));
        setSwitchOpen(true); // no exact spot: the sheet offers the chapter start instead
      }
    });
  }
  // The toolbar's Listen link is a real link; with scripts on it carries the reader's position first.
  const toolbarListen = useRef(switchToListen);
  toolbarListen.current = switchToListen;
  useEffect(() => {
    const link = document.querySelector<HTMLAnchorElement>('[data-format-switch="audio"], [data-format-switch="listen"]');
    if (!link) return;
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      void toolbarListen.current().catch(() => {});
    };
    link.addEventListener("click", onClick);
    return () => link.removeEventListener("click", onClick);
  }, []);
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
          <button
            disabled={busy}
            onClick={() => {
              setStatus("");
              setSwitchOpen(true);
            }}
          >
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
          onClick={() => {
            noteUserScroll("page-button");
            reading.scrollBy({
              left: -(reading.clientWidth + 50),
              behavior: "instant",
            });
          }}
        >
          {t("back")}
        </button>
        <output id="reading-page-status">
          {t("page")} {pages.current} / {pages.total}
        </output>
        <button
          id="next-reading-page"
          disabled={pages.current >= pages.total}
          onClick={() => {
            noteUserScroll("page-button");
            reading.scrollBy({
              left: reading.clientWidth + 50,
              behavior: "instant",
            });
          }}
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
          {followUnavailable ? (
            <p className="notice" role="status">
              {t("follow_unavailable")}
            </p>
          ) : null}
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
      {boot.preview ? (
        <section className="preview-boundary" aria-label={t("preview_end")}>
          <p>{t("preview_end")}</p>
          {!boot.authenticated ? (
            <PreviewEnding
              title={boot.edition_title || ""}
              lang={boot.content_locale}
              minutes={boot.remaining_minutes}
              formats={boot.formats}
              signInUrl={
                boot.sign_in_url ||
                `/${document.documentElement.dataset.uiLocale || "en"}/sign-in/?return_to=${encodeURIComponent(location.pathname + location.search)}`
              }
              listenUrl={boot.listen_sign_in_url}
              watchUrl={boot.watch_sign_in_url}
            />
          ) : (
            <button onClick={() => setBoundaryOpen(true)}>
              {t("continue_beyond_preview")}
            </button>
          )}
          <PreviewBoundary
            editionId={boot.edition_id}
            format="reader"
            freeAccess={boot.free_access === true}
            authenticated={boot.authenticated}
            titleUrl={
              boot.title_url ||
              `/${document.documentElement.dataset.uiLocale || "en"}/titles/${boot.edition_id}/`
            }
            signInUrl={
              boot.sign_in_url ||
              `/${document.documentElement.dataset.uiLocale || "en"}/sign-in/?return_to=${encodeURIComponent(location.pathname + location.search)}`
            }
            passUrl={
              boot.pass_url ||
              `/${document.documentElement.dataset.uiLocale || "en"}/pass/`
            }
            open={boundaryOpen}
            onClose={() => setBoundaryOpen(false)}
            onRetry={() => location.reload()}
          />
        </section>
      ) : null}
      <MediaSheet
        open={chaptersOpen}
        title={t("chapters")}
        onClose={() => setChaptersOpen(false)}
      >
        <ol className="reader-chapter-list" lang={boot.content_locale}>
          {headings.map((h) => (
            <li key={h.id}>
              <button type="button" onClick={() => jumpToChapter(h.id)}>
                {h.text}
              </button>
            </li>
          ))}
        </ol>
      </MediaSheet>
      {fullReader && boot.player_url ? (
        <FormatSwitch
          open={switchOpen}
          onClose={() => setSwitchOpen(false)}
          busy={busy}
          status={status}
          onExact={() => void switchToListen()}
          chapterUrl={boot.player_url + `?unit_id=${boot.unit_id}`}
          target="audio"
        />
      ) : null}
      <MediaSheet
        open={comfortOpen}
        title={t("reader_settings")}
        onClose={() => setComfortOpen(false)}
        className="media-sheet--bottom"
      >
        <div className="comfort" id="reading-settings">
          <div className="comfort-row" role="group" aria-labelledby="comfort-size">
            <span id="comfort-size" className="comfort-label">{t("text_size")}</span>
            <div className="comfort-stepper">
              <button
                type="button"
                className="comfort-step"
                aria-label={t("smaller_text")}
                aria-disabled={Number(preferences.reader_font_size) <= READER_FONT_SIZES[0]}
                onClick={() => pref("reader_font_size", stepFont(Number(preferences.reader_font_size), -1))}
              >
                <span aria-hidden="true">A−</span>
              </button>
              <output className="comfort-value" aria-live="polite">{Number(preferences.reader_font_size) || 20}</output>
              <button
                type="button"
                className="comfort-step"
                aria-label={t("larger_text")}
                aria-disabled={Number(preferences.reader_font_size) >= READER_FONT_SIZES[READER_FONT_SIZES.length - 1]}
                onClick={() => pref("reader_font_size", stepFont(Number(preferences.reader_font_size), 1))}
              >
                <span aria-hidden="true">A+</span>
              </button>
            </div>
          </div>
          <div className="comfort-row" role="group" aria-labelledby="comfort-leading">
            <span id="comfort-leading" className="comfort-label">{t("leading")}</span>
            <div className="comfort-stepper">
              <button
                type="button"
                className="comfort-step"
                aria-label={t("less_line_spacing")}
                aria-disabled={Number(preferences.reader_line_height) <= leadingFloor(boot.content_locale)}
                onClick={() => pref("reader_line_height", stepLeading(Number(preferences.reader_line_height), -1, boot.content_locale))}
              >
                <span aria-hidden="true">−</span>
              </button>
              <output className="comfort-value">{Math.max(Number(preferences.reader_line_height) || 1.65, leadingFloor(boot.content_locale)).toFixed(2)}</output>
              <button
                type="button"
                className="comfort-step"
                aria-label={t("more_line_spacing")}
                aria-disabled={Number(preferences.reader_line_height) >= 2.4}
                onClick={() => pref("reader_line_height", stepLeading(Number(preferences.reader_line_height), 1, boot.content_locale))}
              >
                <span aria-hidden="true">+</span>
              </button>
            </div>
          </div>
          <div className="comfort-row">
            <span id="comfort-theme" className="comfort-label">{t("theme")}</span>
            <RadioGroup
              labelledBy="comfort-theme"
              className="comfort-swatches"
              value={preferences.reader_theme || "system"}
              onSelect={(v) => pref("reader_theme", v)}
              options={(["system", "light", "sepia", "dark", "true_black"] as const).map((value) => ({
                value,
                className: `comfort-swatch comfort-swatch-${value}`,
                content: (
                  <>
                    <span className="comfort-chip" aria-hidden="true">Aa</span>
                    <span>{t(value === "system" ? "match_device" : value === "true_black" ? "black" : value)}</span>
                  </>
                ),
              }))}
            />
          </div>
          <div className="comfort-row">
            <span id="comfort-width" className="comfort-label">{t("margins")}</span>
            <RadioGroup
              labelledBy="comfort-width"
              className="comfort-segments"
              value={preferences.reader_margins || "comfortable"}
              onSelect={(v) => pref("reader_margins", v)}
              options={READER_WIDTHS.map((w) => ({ value: w.value, className: "comfort-segment", content: t(w.label) }))}
            />
          </div>
          <div className="comfort-row">
            <span id="comfort-align" className="comfort-label">{t("alignment")}</span>
            <RadioGroup
              labelledBy="comfort-align"
              className="comfort-segments"
              value={effectiveAlignment(preferences.reader_alignment, boot.content_locale)}
              onSelect={(v) => pref("reader_alignment", v)}
              options={alignmentOptions(boot.content_locale).map((value) => ({
                value,
                className: "comfort-segment",
                content: t(value === "start" ? "align_start" : "align_justify"),
              }))}
            />
          </div>
          <div className="comfort-row">
            <span id="comfort-face" className="comfort-label">{t("typeface")}</span>
            <RadioGroup
              labelledBy="comfort-face"
              className="comfort-segments"
              value={preferences.reader_typeface || "serif"}
              onSelect={(v) => pref("reader_typeface", v)}
              options={(["serif", "sans"] as const).map((value) => ({
                value,
                className: "comfort-segment",
                content:
                  value === "serif"
                    ? boot.content_locale === "bn" ? "Noto Serif Bengali" : "Source Serif 4"
                    : boot.content_locale === "bn" ? "Noto Sans Bengali" : "DM Sans",
              }))}
            />
          </div>
          <div className="comfort-row">
            <span id="comfort-layout" className="comfort-label">{t("layout")}</span>
            <RadioGroup
              labelledBy="comfort-layout"
              className="comfort-segments"
              value={preferences.reader_layout || "scroll"}
              onSelect={(v) => pref("reader_layout", v)}
              options={(["scroll", "paginated"] as const).map((value) => ({ value, className: "comfort-segment", content: t(value) }))}
            />
          </div>
          <p className="fine" id="preference-ownership">
            {t(fullReader ? "preferences_account" : "local_settings")}
          </p>
          <p role="status" id="settings-status" className="error-notice" hidden={!settingsStatus}>
            {settingsStatus}
          </p>
        </div>
      </MediaSheet>
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
  document
    .querySelector<HTMLElement>("[data-preview-fallback]")
    ?.setAttribute("hidden", "");
  mountIsland(document.getElementById("reader-controls"), () => (
    <Reader boot={readBootstrap<Boot>("reader-bootstrap")} />
  ));
}
mount();
