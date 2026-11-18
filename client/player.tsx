import { useEffect, useRef, useState } from "react";
import { mountIsland, closePlayer } from "./lifecycle";
import { api, ApiError, errorText, readBootstrap, session, t } from "./api";
import { sleepDeadline, timerExpired, validReturnPath } from "./state";
interface Chapter {
  asset_id: string;
  unit_id: string;
  duration_ms: number;
  sha256: string;
  quality_kbps: number;
  title: string;
}
interface Boot {
  edition_id: string;
  edition_revision_id: string;
  title: string;
  locale: string;
  chapters: Chapter[];
  reader_url: string;
  anchor_id?: string;
  start_asset_id?: string;
  start_ms?: number;
}
interface Grant {
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
  const [speed, setSpeed] = useState(1);
  const [mini, setMini] = useState(false);
  const [, setLocaleVersion] = useState(0);
  const [position, setPosition] = useState(0);
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
  const chapter = boot.chapters[index];
  const path = `/me/progress/${boot.edition_id}/audio`;
  async function persist(keepalive = false) {
    const element = audio.current,
      c = boot.chapters[activeChapter.current];
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
    const c = boot.chapters[i];
    if (!c) return;
    setBusy(true);
    try {
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
      if (
        next.asset_id !== c.asset_id ||
        next.edition_revision_id !== boot.edition_revision_id ||
        next.sha256 !== c.sha256 ||
        next.duration_ms !== c.duration_ms ||
        next.quality_kbps !== c.quality_kbps
      )
        throw new Error(t("media_changed"));
      const el = audio.current!;
      grant.current = next;
      activeChapter.current = i;
      setIndex(i);
      el.src = next.url;
      el.playbackRate = speed;
      el.currentTime = Math.max(0, Math.min(at / 1000, c.duration_ms / 1000));
      if (autoplay) await el.play();
      setStatus("");
      return true;
    } catch (e) {
      setStatus(errorText(e));
      audio.current?.pause();
      return false;
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    const navigated = () => {
      setMini(true);
      setLocaleVersion((value) => value + 1);
    };
    window.addEventListener("maison:navigated", navigated);
    let cancelled = false;
    api<Progress>(path)
      .then((p) => {
        if (cancelled) return;
        progress.current = p;
        const found = boot.chapters.findIndex((c) =>
          boot.start_asset_id
            ? c.asset_id === boot.start_asset_id
            : c.unit_id === p.location?.unit_id,
        );
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
      navigator.mediaSession.metadata = new MediaMetadata({
        title: boot.title,
      });
      navigator.mediaSession.setActionHandler("play", () => {
        void audio.current?.play().catch((e) => setStatus(errorText(e)));
      });
      navigator.mediaSession.setActionHandler("pause", () =>
        audio.current?.pause(),
      );
      navigator.mediaSession.setActionHandler("seekbackward", () => {
        if (audio.current)
          audio.current.currentTime = Math.max(
            0,
            audio.current.currentTime - 15,
          );
      });
      navigator.mediaSession.setActionHandler("seekforward", () => {
        if (audio.current)
          audio.current.currentTime = Math.min(
            audio.current.duration,
            audio.current.currentTime + 15,
          );
      });
    }
    return () => {
      cancelled = true;
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
        ] as MediaSessionAction[])
          navigator.mediaSession.setActionHandler(key, null);
    };
  }, []);
  useEffect(() => {
    if (audio.current) audio.current.playbackRate = speed;
  }, [speed]);
  async function nextChapter(i: number) {
    if (busy) return;
    try {
      await persist();
      await load(i, 0, playing);
    } catch (e) {
      setStatus(errorText(e));
    }
  }
  async function retryExpired() {
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
            asset_id: chapter.asset_id,
            position_ms: Math.round((audio.current?.currentTime || 0) * 1000),
          },
          to_format: "reader",
        },
      });
      await persist();
      audio.current?.pause();
      if (mapped.outcome === "mapped" && mapped.to_location) {
        const p = mapped.to_location;
        window.location.assign(
          validReturnPath(
            `${boot.reader_url}${p.unit_id}/?anchor=${encodeURIComponent(p.anchor_id)}&offset=${p.offset_chars}`,
          ),
        );
      } else setStatus(t("switch_unmapped"));
    } catch (e) {
      setStatus(errorText(e));
    }
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
        onPlay={() => setPlaying(true)}
        onPause={() => {
          setPlaying(false);
          void persist().catch((e) => setStatus(errorText(e)));
        }}
        onTimeUpdate={() => {
          const el = audio.current;
          if (el) setPosition(el.currentTime);
        }}
        onEnded={() => {
          void persist()
            .then(() => {
              if (endChapter.current) {
                endChapter.current = false;
                setSleep("off");
                setStatus(t("sleep_finished"));
              } else if (index + 1 < boot.chapters.length)
                void load(index + 1, 0, true);
            })
            .catch((e) => setStatus(errorText(e)));
        }}
        onError={() => {
          void retryExpired();
        }}
      />
      <p role="status" aria-live="polite">
        {status}
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
        <label>
          {t("playback_speed")}
          <select
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
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
        <button disabled={busy} onClick={() => void switchToRead()}>
          {t("switch_to_read")}
        </button>
        <a href={validReturnPath(boot.reader_url + chapter.unit_id + "/")}>
          {t("read_from_chapter")}
        </a>
      </div>
      <ol className="unit-list" hidden={mini}>
        {boot.chapters.map((c, i) => (
          <li key={c.asset_id}>
            <button
              disabled={busy}
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
    current.dataset.editionId !== boot.edition_id
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
  document.getElementById("persistent-media")!.append(host);
  document.body.classList.add("has-persistent-player");
  mountIsland(
    host,
    () => <Player boot={readBootstrap<Boot>("player-bootstrap")} />,
    true,
  );
}
mount();
