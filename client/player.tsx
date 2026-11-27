import { approvedAudioURL, approvedAudioPreviewURL, type AudioPreviewDescriptor } from "./media-state";
import { PreviewBoundary, FormatSwitch } from "./media-sheets";
import { useEffect, useRef, useState } from "react";
import { mountIsland, closePlayer } from "./lifecycle";
import { api, ApiError, errorText, readBootstrap, session, t } from "./api";
import { IconButton } from "./icon-button";
import { mediaMetadataFor, recallSpeed, rememberSpeed, seekTarget, sleepDeadline, timerExpired, validReturnPath } from "./state";
interface Rendition {
  asset_id: string;
  quality_kbps: number;
  duration_ms: number;
  sha256: string;
}
/** One audio unit, carrying the rendition chosen for the listener plus every prepared rendition. */
interface Chapter extends Rendition {
  unit_id: string;
  title: string;
  markers?: { title: string; start_ms: number }[];
  renditions?: Rendition[];
}
interface Boot {
  edition_id: string;
  edition_revision_id: string;
  title: string;
  locale: string;
  author?: string;
  cover_url?: string;
  chapters: Chapter[];
  reader_url: string;
  reader_available?: boolean;
  anchor_id?: string;
  start_asset_id?: string;
  start_ms?: number;
  free_access?: boolean;
  authenticated?: boolean;
  preview?: AudioPreviewDescriptor;
  title_url?: string;
  sign_in_url?: string;
  pass_url?: string;
  full_player_url?: string;
}
interface Grant {
  transport: string;
  content_type: string;
  asset_id: string;
  edition_revision_id: string;
  url: string;
  expires_at: string;
  sha256: string;
  duration_ms: number;
  quality_kbps: number;
}
interface Progress {
  version: number;
  location?: { unit_id: string; position_ms: number };
}
function Player({ boot }: { boot: Boot }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [speed, setSpeed] = useState(recallSpeed);
  const [mini, setMini] = useState(false);
  const [, setLocaleVersion] = useState(0);
  const [position, setPosition] = useState(0);
  const [boundaryOpen, setBoundaryOpen] = useState(false);
  const [switchOpen, setSwitchOpen] = useState(false);
  const [buffering, setBuffering] = useState(false);
  const [completion, setCompletion] = useState<{ version: number; is_complete: boolean }>();
  const pendingCompletion = useRef<{key:string;version:number;body:{operation_id:string;edition_revision_id:string;is_complete:boolean}} | undefined>(undefined);
  const [sleep, setSleep] = useState("off");
  const grant = useRef<Grant | undefined>(undefined);
  const progress = useRef<Progress | undefined>(undefined);
  const pending = useRef<
    { key: string; version: number; body: unknown } | undefined
  >(undefined);
  const deadline = useRef<number | undefined>(undefined);
  const endChapter = useRef(false);
  const lastSaved = useRef(0);
  const renewal = useRef(false);
  const activeChapter = useRef(0);
  const saving = useRef(false);
  const conflictRef = useRef(false);
  const [conflict, setConflict] = useState(false);
  const [, setOverrides] = useState<Record<string, Rendition>>({});
  const overridesRef = useRef<Record<string, Rendition>>({});
  const actions = useRef({ previous: () => {}, next: () => {} });
  /** The unit at `i` with any rendition the listener switched to. */
  function unitAt(i: number): Chapter | undefined {
    const base = boot.chapters[i];
    return base && overridesRef.current[base.unit_id] ? { ...base, ...overridesRef.current[base.unit_id] } : base;
  }
  const chapter = unitAt(index) as Chapter;
  const path = `/me/progress/${boot.edition_id}/audio`;
  const fullPlayerPath = useRef(location.pathname);
  const mounted = useRef(true);
  const loadGeneration = useRef(0);
  const previewEnded = useRef(false);
  const previewRenewed = useRef(false);
  async function persist(keepalive = false) {
    const element = audio.current,
      c = unitAt(activeChapter.current);
    if (boot.preview || boot.authenticated === false) return;
    if (
      !element ||
      !c ||
      !progress.current ||
      saving.current ||
      conflictRef.current
    )
      return;
    saving.current = true;
    try {
      const at = Math.min(
        c.duration_ms,
        Math.max(0, Math.round(element.currentTime * 1000)),
      );
      pending.current ??= {
        key: crypto.randomUUID(),
        version: progress.current.version,
        body: null,
      };
      if (pending.current.body === null)
        pending.current.body = {
          operation_id: pending.current.key,
          edition_revision_id: boot.edition_revision_id,
          location: { format: "audio", unit_id: c.unit_id, position_ms: at },
          occurred_at: new Date().toISOString(),
        };
      progress.current = await api<Progress>(path, {
        method: "PUT",
        ...pending.current,
        keepalive,
      });
      pending.current = undefined;
      lastSaved.current = performance.now();
    } catch (error) {
      if (error instanceof ApiError && error.status === 412) {
        conflictRef.current = true;
        setConflict(true);
      }
      throw error;
    } finally {
      saving.current = false;
    }
  }
  async function resolveProgress(useLocal: boolean) {
    setBusy(true);
    try {
      const latest = await api<Progress>(path);
      progress.current = latest;
      pending.current = undefined;
      if (useLocal) {
        conflictRef.current = false;
        await persist();
      } else {
        const at = boot.chapters.findIndex(
          (chapter) => chapter.unit_id === latest.location?.unit_id,
        );
        if (
          !(await load(
            Math.max(0, at),
            latest.location?.position_ms || 0,
            false,
          ))
        )
          return;
        conflictRef.current = false;
      }
      setConflict(false);
      setStatus(t("saved_server"));
    } catch (error) {
      setStatus(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  async function load(i: number, at = 0, autoplay = false) {
    const c = unitAt(i);
    if (!c) return;
    const generation = ++loadGeneration.current;
    setBusy(true);
    try {
      if (boot.preview) {
        const source = approvedAudioPreviewURL(boot.preview, boot.edition_revision_id, location.origin);
        if (!source || i !== 0 || boot.preview.asset_id !== c.asset_id || boot.preview.unit_id !== c.unit_id || boot.preview.duration_ms !== c.duration_ms) throw new Error("media_changed");
        const el = audio.current!;
        previewEnded.current = false;
        el.src = source;
        el.currentTime = Math.max(0, Math.min(at, boot.preview.duration_ms) / 1000);
        el.playbackRate = speed;
        if (autoplay) await el.play();
        return true;
      }
      const identity = await session();
      const next = await api<Grant>("/media/grants", {
        method: "POST",
        key: crypto.randomUUID(),
        body: {
          asset_id: c.asset_id,
          purpose: "online",
          device_id: identity.device_id,
          quality_kbps: c.quality_kbps,
        },
      });
      if (!mounted.current || generation !== loadGeneration.current) return false;
      const source = approvedAudioURL(next, c, boot.edition_revision_id, location.origin);
      if (!source) throw new Error("media_changed");
      const el = audio.current!;
      grant.current = next;
      activeChapter.current = i;
      setIndex(i);
      el.src = source;
      el.playbackRate = speed;
      el.currentTime = Math.max(0, Math.min(at / 1000, c.duration_ms / 1000));
      if (autoplay) await el.play();
      setStatus("");
      return true;
    } catch (e) {
      if (!mounted.current || generation !== loadGeneration.current) return false;
      setStatus(errorText(e));
      audio.current?.pause();
      return false;
    } finally {
      if (mounted.current && generation === loadGeneration.current) setBusy(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    const navigated = () => {
      setMini(location.pathname !== fullPlayerPath.current);
      setBoundaryOpen(false);
      setSwitchOpen(false);
      setLocaleVersion((value) => value + 1);
    };
    window.addEventListener("maison:navigated", navigated);
    let cancelled = false;
    if (!boot.preview && boot.authenticated !== false) void api<{version:number;is_complete:boolean}>(`/me/completion/${boot.edition_id}/audio`).then(value => {if(!cancelled) setCompletion(value);}).catch(error => setStatus(errorText(error)));
    (boot.preview ? Promise.resolve<Progress>({version: 0}) : boot.authenticated === false ? Promise.reject(new Error("not_authorized")) : api<Progress>(path))
      .then((p) => {
        if (cancelled) return;
        progress.current = p;
        const found = boot.chapters.findIndex((c) =>
          boot.start_asset_id
            ? c.asset_id === boot.start_asset_id || !!c.renditions?.some((r) => r.asset_id === boot.start_asset_id)
            : c.unit_id === p.location?.unit_id,
        );
        const startUnit = boot.chapters[found];
        const startRendition = boot.start_asset_id && startUnit?.asset_id !== boot.start_asset_id ? startUnit?.renditions?.find((r) => r.asset_id === boot.start_asset_id) : undefined;
        if (startUnit && startRendition) setRendition(startUnit.unit_id, startRendition);
        void load(
          Math.max(0, found),
          boot.start_asset_id
            ? boot.start_ms || 0
            : p.location?.position_ms || 0,
          false,
        );
      })
      .catch((e) => setStatus(errorText(e)));
    const timer = window.setInterval(() => {
      const el = audio.current;
      if (!el) return;
      if (timerExpired(deadline.current, performance.now())) {
        el.pause();
        deadline.current = undefined;
        setSleep("off");
        setStatus(t("sleep_finished"));
      }
      if (!el.paused && performance.now() - lastSaved.current >= 15000)
        void persist().catch((e) => setStatus(errorText(e)));
    }, 1000);
    const hidden = () => {
      if (document.hidden) void persist(true).catch(() => {});
    };
    document.addEventListener("visibilitychange", hidden);
    if ("mediaSession" in navigator) {
      const session = navigator.mediaSession;
      session.setActionHandler("play", () => {
        void audio.current?.play().catch((e) => setStatus(errorText(e)));
      });
      session.setActionHandler("pause", () => audio.current?.pause());
      session.setActionHandler("seekbackward", () => skip(-15));
      session.setActionHandler("seekforward", () => skip(30));
      session.setActionHandler("seekto", (details) => {
        if (audio.current && typeof details.seekTime === "number" && Number.isFinite(details.seekTime)) audio.current.currentTime = seekTarget(0, details.seekTime, durationBound());
      });
    }
    return () => {
      cancelled = true;
      mounted.current = false;
      loadGeneration.current++;
      window.removeEventListener("maison:navigated", navigated);
      clearInterval(timer);
      document.removeEventListener("visibilitychange", hidden);
      audio.current?.pause();
      if ("mediaSession" in navigator)
        for (const key of [
          "play",
          "pause",
          "seekbackward",
          "seekforward",
          "seekto",
          "previoustrack",
          "nexttrack",
        ] as MediaSessionAction[])
          navigator.mediaSession.setActionHandler(key, null);
    };
  }, []);
  useEffect(() => {
    if (audio.current) audio.current.playbackRate = speed;
  }, [speed]);
  actions.current = { previous: () => void nextChapter(index - 1), next: () => void nextChapter(index + 1) };
  useEffect(() => {
    if (!("mediaSession" in navigator) || !chapter) return;
    const session = navigator.mediaSession;
    if ("MediaMetadata" in window) session.metadata = new MediaMetadata(mediaMetadataFor(boot, chapter));
    session.setActionHandler("previoustrack", index > 0 ? () => actions.current.previous() : null);
    session.setActionHandler("nexttrack", index < boot.chapters.length - 1 ? () => actions.current.next() : null);
  }, [index, chapter?.asset_id, chapter?.title]);
  /** Upper bound in seconds for seeking: the sample clip, else this unit's rendition. */
  function durationBound(): number {
    const ms = boot.preview ? boot.preview.duration_ms : unitAt(activeChapter.current)?.duration_ms;
    return ms ? ms / 1000 : NaN;
  }
  function skip(delta: number) {
    const el = audio.current;
    if (el) el.currentTime = seekTarget(el.currentTime, delta, durationBound());
  }
  function syncPositionState() {
    const el = audio.current;
    if (!el || !("mediaSession" in navigator) || !navigator.mediaSession.setPositionState) return;
    const duration = Number.isFinite(el.duration) && el.duration > 0 ? el.duration : durationBound();
    if (!Number.isFinite(duration) || duration <= 0) return;
    try {
      navigator.mediaSession.setPositionState({ duration, playbackRate: el.playbackRate || 1, position: Math.min(duration, Math.max(0, el.currentTime)) });
    } catch { /* the browser rejected an inconsistent state; the next update corrects it */ }
  }
  function setRendition(unitId: string, rendition: Rendition | undefined) {
    const next = { ...overridesRef.current };
    if (rendition) next[unitId] = rendition; else delete next[unitId];
    overridesRef.current = next;
    setOverrides(next);
  }
  async function toggleCompletion() {
    if (!completion || busy || boot.preview) return;
    setBusy(true);
    if (!pendingCompletion.current) {
      const key = crypto.randomUUID();
      pendingCompletion.current = {key, version:completion.version, body:{operation_id:key,edition_revision_id:boot.edition_revision_id,is_complete:!completion.is_complete}};
    }
    try {
      setCompletion(await api<{version:number;is_complete:boolean}>(`/me/completion/${boot.edition_id}/audio`, {method:"PUT",...pendingCompletion.current}));
      pendingCompletion.current = undefined;
      setStatus(t("saved_server"));
    } catch(error) {
      if (error instanceof ApiError && error.status === 412) {
        pendingCompletion.current = undefined;
        setCompletion(await api<{version:number;is_complete:boolean}>(`/me/completion/${boot.edition_id}/audio`).catch(() => completion));
      }
      setStatus(errorText(error));
    }
    finally {setBusy(false);}
  }
  async function chooseQuality(value: number) {
    const target = chapter.renditions?.find((candidate) => candidate.quality_kbps === value);
    if (!target || target.asset_id === chapter.asset_id || busy) return;
    const previous = overridesRef.current[chapter.unit_id];
    try {
      await persist();
      setRendition(chapter.unit_id, target);
      if (!(await load(index, Math.round((audio.current?.currentTime || 0) * 1000), playing))) setRendition(chapter.unit_id, previous);
    } catch (error) {
      setRendition(chapter.unit_id, previous);
      setStatus(errorText(error));
    }
  }
  async function nextChapter(i: number) {
    if (busy) return;
    if (boot.preview) previewRenewed.current = false;
    try {
      await persist();
      await load(i, 0, playing);
    } catch (e) {
      setStatus(errorText(e));
    }
  }
  async function retryExpired() {
    if (boot.preview) {
      if (renewal.current || previewRenewed.current) { setStatus(t("media_retry")); return; }
      previewRenewed.current = true;
      renewal.current = true;
      try {
        await load(0, Math.round((audio.current?.currentTime || 0) * 1000), playing);
      } finally { renewal.current = false; }
      return;
    }
    if (
      renewal.current ||
      !grant.current ||
      Date.parse(grant.current.expires_at) > Date.now()
    ) {
      setStatus(t("media_retry"));
      return;
    }
    renewal.current = true;
    try {
      await load(
        activeChapter.current,
        Math.round((audio.current?.currentTime || 0) * 1000),
        playing,
      );
    } finally {
      renewal.current = false;
    }
  }
  async function switchToRead() {
    setBusy(true);
    try {
      const mapped = await api<{
        outcome: string;
        to_location?: {
          unit_id: string;
          anchor_id: string;
          offset_chars: number;
        };
      }>("/content/switch-position", {
        method: "POST",
        key: crypto.randomUUID(),
        body: {
          edition_revision_id: boot.edition_revision_id,
          from_location: {
            format: "audio",
            unit_id: chapter.unit_id,
            position_ms: Math.round((audio.current?.currentTime || 0) * 1000),
          },
          to_format: "reader",
        },
      });
      if (mapped.outcome === "mapped" && mapped.to_location) {
        await persist();
        audio.current?.pause();
        const p = mapped.to_location;
        window.location.assign(
          validReturnPath(
            `${boot.reader_url}${p.unit_id}/?anchor=${encodeURIComponent(p.anchor_id)}&offset=${p.offset_chars}`,
          ),
        );
      } else setStatus(t("switch_unmapped"));
    } catch (e) {
      setStatus(errorText(e));
    } finally { setBusy(false); }
  }
  if (!chapter) return <p className="notice">{t("not_available")}</p>;
  return (
    <section
      className={"player-panel" + (mini ? " player-mini" : "")}
      aria-label={t("audio")}
    >
      <header>
        <div>
          <p className="eyebrow">{t("audio")}</p>
          <h1 lang={boot.locale}>{boot.title}</h1>
          <p lang={boot.locale}>{chapter.title}</p>
        </div>
        <button onClick={() => setMini((v) => !v)} aria-expanded={!mini}>
          {t(mini ? "expand_player" : "minimize_player")}
        </button>
      </header>
      <button
        onClick={() => {
          void persist(true)
            .catch(() => {})
            .finally(() => closePlayer());
        }}
      >
        {t("close_player")}
      </button>
      <audio
        ref={audio}
        controls
        preload="metadata"
        aria-label={chapter.title}
        onPlay={() => { setPlaying(true); if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "playing"; }}
        onRateChange={syncPositionState}
        onLoadedMetadata={syncPositionState}
        onWaiting={() => setBuffering(true)}
        onCanPlay={() => setBuffering(false)}
        onPlaying={() => setBuffering(false)}
        onPause={() => {
          setPlaying(false);
          if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "paused";
          void persist().catch((e) => setStatus(errorText(e)));
        }}
        onSeeking={() => {
          const el = audio.current;
          if (el && boot.preview && el.currentTime * 1000 > boot.preview.duration_ms) el.currentTime = boot.preview.duration_ms / 1000;
        }}
        onTimeUpdate={() => {
          const el = audio.current;
          if (el) {
            setPosition(el.currentTime);
            syncPositionState();
            if (boot.preview && el.currentTime * 1000 >= boot.preview.duration_ms) {
              el.pause();
              if (el.currentTime * 1000 > boot.preview.duration_ms) el.currentTime = boot.preview.duration_ms / 1000;
              if (!previewEnded.current) { previewEnded.current = true; setBoundaryOpen(true); }
            }
          }
        }}
        onEnded={() => {
          if (boot.preview) { if (!previewEnded.current) { previewEnded.current = true; setBoundaryOpen(true); } return; }
          void persist()
            .then(() => {
              if (endChapter.current) {
                endChapter.current = false;
                setSleep("off");
                setStatus(t("sleep_finished"));
              } else {
                if (index + 1 < boot.chapters.length) void load(index + 1, 0, true);
              }
            })
            .catch((e) => setStatus(errorText(e)));
        }}
        onError={() => {
          void retryExpired();
        }}
      />
      <div className="player-skip">
        <IconButton label={t("back_15_seconds")} icon="i-skip-back-15" disabled={busy} onClick={() => skip(-15)} />
        <IconButton label={t("forward_30_seconds")} icon="i-skip-forward-30" disabled={busy} onClick={() => skip(30)} />
      </div>
      <p role="status" aria-live="polite">
        {buffering ? t("buffering") : status}
      </p>
      {conflict ? (
        <div className="notice">
          <p>{t("conflict")}</p>
          <button disabled={busy} onClick={() => void resolveProgress(false)}>
            {t("use_server")}
          </button>
          <button
            disabled={busy}
            onClick={() => void resolveProgress(true)}
            aria-label={t("resolve_keep_local")}
          >
            {t("use_local")}
          </button>
        </div>
      ) : null}
      <div className="player-options" hidden={mini}>
        {!boot.preview && (chapter.renditions?.length ?? 0) > 1 ? <label>{t("audio_quality")}<select value={chapter.quality_kbps} disabled={busy} onChange={e => void chooseQuality(Number(e.target.value))}>{chapter.renditions!.map(candidate => <option key={candidate.asset_id} value={candidate.quality_kbps}>{candidate.quality_kbps} kbps</option>)}</select></label> : null}
        {completion && !boot.preview ? <button disabled={busy} aria-pressed={completion.is_complete} onClick={() => void toggleCompletion()}>{t(completion.is_complete ? "uncomplete" : "complete")}</button> : null}
        <label>
          {t("playback_speed")}
          <select
            value={speed}
            onChange={(e) => {
              const rate = Number(e.target.value);
              setSpeed(rate);
              rememberSpeed(rate);
            }}
          >
            {[0.75, 1, 1.25, 1.5, 1.75, 2].map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("sleep_timer")}
          <select
            value={sleep}
            onChange={(e) => {
              setSleep(e.target.value);
              endChapter.current = e.target.value === "chapter";
              deadline.current = sleepDeadline(
                Number(e.target.value),
                performance.now(),
              );
            }}
          >
            <option value="off">{t("off")}</option>
            {[5, 15, 30, 60].map((m) => (
              <option key={m} value={m}>
                {m} {t("minutes")}
              </option>
            ))}
            <option value="chapter">{t("end_of_chapter")}</option>
          </select>
        </label>
        {boot.reader_available !== false ? <><button disabled={busy || !!boot.preview} onClick={() => { setStatus(""); setSwitchOpen(true); }}>
          {t("switch_to_read")}
        </button>
        <a href={validReturnPath(boot.reader_url + chapter.unit_id + "/")}>
          {t("read_from_chapter")}
        </a></> : null}
      </div>
      <FormatSwitch open={switchOpen} onClose={() => setSwitchOpen(false)} busy={busy} status={status} onExact={() => void switchToRead()} chapterUrl={boot.reader_url + chapter.unit_id + "/"} target="reader" />
      {boot.preview ? <><button onClick={() => setBoundaryOpen(true)}>{t("preview_end_options")}</button><PreviewBoundary editionId={boot.edition_id} format="audio" freeAccess={boot.free_access === true} authenticated={boot.authenticated === true} titleUrl={boot.title_url || `/${document.documentElement.dataset.uiLocale || "en"}/titles/${boot.edition_id}/`} signInUrl={boot.sign_in_url || `/${document.documentElement.dataset.uiLocale || "en"}/sign-in/?return_to=${encodeURIComponent(location.pathname + location.search)}`} passUrl={boot.pass_url || `/${document.documentElement.dataset.uiLocale || "en"}/pass/`} open={boundaryOpen} onClose={() => setBoundaryOpen(false)} onRetry={() => location.assign(validReturnPath(boot.full_player_url || location.pathname + location.search))} /></> : null}
      <ol className="unit-list" hidden={mini}>
        {boot.chapters.map((c, i) => (
          <li key={c.asset_id}>
            <button
              disabled={busy || (!!boot.preview && i !== 0)}
              aria-current={i === index ? "true" : undefined}
              onClick={() => void nextChapter(i)}
            >
              {c.title}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
export function mount() {
  const host = document.getElementById("player-island");
  if (!host) return;
  const current = document.querySelector<HTMLElement>(
    "[data-persistent-player]",
  );
  const boot = readBootstrap<Boot>("player-bootstrap");
  if (
    current &&
    current !== host &&
    (current.dataset.editionId !== boot.edition_id || current.dataset.revisionId !== boot.edition_revision_id || current.dataset.preview !== String(!!boot.preview))
  )
    closePlayer();
  else if (current && current !== host) {
    host.replaceWith(
      Object.assign(document.createElement("p"), {
        textContent: t("player_continues"),
      }),
    );
    return;
  }
  host.dataset.persistentPlayer = "true";
  host.dataset.editionId = boot.edition_id;
  host.dataset.revisionId = boot.edition_revision_id;
  host.dataset.preview = String(!!boot.preview);
  document.getElementById("persistent-media")!.append(host);
  document.body.classList.add("has-persistent-player");
  mountIsland(
    host,
    () => <Player boot={readBootstrap<Boot>("player-bootstrap")} />,
    true,
  );
}
mount();
