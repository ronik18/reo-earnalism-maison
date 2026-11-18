import { useEffect, useRef, useState } from "react";
import { mountIsland } from "./lifecycle";
import { api, errorText, readBootstrap, session, t } from "./api";
import { validReturnPath } from "./state";
import { approvedStreamURL, type StreamGrant } from "./media-state";

interface Boot {
  edition_id: string; edition_revision_id: string; title: string; locale: string;
  enabled: boolean; asset_id?: string; reader_url?: string; player_url?: string;
}
function Video({boot}: {boot: Boot}) {
  const [online, setOnline] = useState(navigator.onLine);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<string>();
  const iframe = useRef<HTMLIFrameElement>(null);
  useEffect(() => {
    const changed = () => { setOnline(navigator.onLine); if (!navigator.onLine) setSource(undefined); };
    window.addEventListener("online",changed); window.addEventListener("offline",changed);
    return () => { window.removeEventListener("online",changed); window.removeEventListener("offline",changed); };
  }, []);
  async function load() {
    if (!boot.enabled || !boot.asset_id || !navigator.onLine) return;
    setBusy(true); setStatus("");
    try {
      const identity = await session();
      const grant = await api<StreamGrant>("/media/grants",{method:"POST",key:crypto.randomUUID(),body:{asset_id:boot.asset_id,purpose:"online",device_id:identity.device_id}});
      const url = approvedStreamURL(grant, boot.asset_id, boot.edition_revision_id);
      if (!url) throw new Error("media_changed");
      setSource(url);
    } catch(error) { setSource(undefined); setStatus(errorText(error)); }
    finally { setBusy(false); }
  }
  return <section className="video-room" aria-labelledby="video-title">
    <p className="eyebrow">{t("video")}</p><h1 id="video-title" lang={boot.locale}>{boot.title}</h1>
    {source && online ? <iframe ref={iframe} title={boot.title} src={source} allow="autoplay; fullscreen; picture-in-picture" allowFullScreen className="stream-frame" /> : <div className="media-unavailable"><h2>{t(!online ? "video_offline_title" : "video_unavailable_title")}</h2><p>{t(!online ? "video_offline_help" : "video_unavailable_help")}</p></div>}
    <p role="status" aria-live="polite">{status}</p>
    {boot.enabled && boot.asset_id && online ? <button disabled={busy} onClick={() => void load()}>{t(source ? "retry" : "watch")}</button> : null}
    <p className="notice">{t("video_caption_status")}</p><p>{t("video_pip_help")}</p>
    <div className="actions">{boot.reader_url ? <a className="button secondary" href={validReturnPath(boot.reader_url)}>{t("reader")}</a> : null}{boot.player_url ? <a className="button secondary" href={validReturnPath(boot.player_url)}>{t("audio")}</a> : null}</div>
  </section>;
}
export function mount() { const host=document.getElementById("video-island"); if(host) mountIsland(host,()=> <Video boot={readBootstrap<Boot>("video-bootstrap")} />); }
mount();
