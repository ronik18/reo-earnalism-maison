import { useEffect, useRef, useState } from "react";
import { mountIsland } from "./lifecycle";
import { api, ApiError, errorText, readBootstrap, session, t } from "./api";
import { validReturnPath } from "./state";
import { approvedStreamURL, type StreamGrant } from "./media-state";
import { loadStreamSDK, type StreamPlayerAPI, type StreamFactory } from "./stream-sdk";

interface Chapter { asset_id: string; unit_id: string; duration_ms: number; title: string }
interface Boot {
  edition_id: string; edition_revision_id: string; title: string; locale: string;
  enabled: boolean; authenticated?: boolean; stream_customer_host?: string;
  asset_id?: string; unit_id?: string; duration_ms?: number; start_asset_id?: string;
  chapters?: Chapter[]; reader_url?: string; player_url?: string; sign_in_url?: string;
}
interface Progress { version: number; location?: { unit_id: string; position_ms: number } }
interface Source { url: string; chapter: Chapter; generation: number; at: number; resume: boolean }
function Video({boot}: {boot: Boot}) {
  const chapters = boot.chapters || (boot.asset_id && boot.unit_id && boot.duration_ms ? [{asset_id:boot.asset_id,unit_id:boot.unit_id,duration_ms:boot.duration_ms,title:boot.title}] : []);
  const [online, setOnline] = useState(navigator.onLine), [status, setStatus] = useState(""), [busy, setBusy] = useState(false);
  const [source, setSource] = useState<Source>(), [index, setIndex] = useState(0), [conflict, setConflict] = useState(false);
  const iframe = useRef<HTMLIFrameElement>(null), player = useRef<StreamPlayerAPI | undefined>(undefined), factory = useRef<StreamFactory | undefined>(undefined);
  const active = useRef(0), position = useRef(0), playing = useRef(false), progress = useRef<Progress | undefined>(undefined);
  const pending = useRef<{key:string;version:number;body:unknown} | undefined>(undefined);
  const mounted = useRef(true), loading = useRef(false), saving = useRef(false), conflicting = useRef(false), errorRetried = useRef(false);
  const generation = useRef(0), renewAt = useRef(Infinity), lastSaved = useRef(performance.now()), controller = useRef<AbortController | undefined>(undefined);
  const path = `/me/progress/${boot.edition_id}/video`;
  const chapter = chapters[index];
  function point(c = chapters[active.current]) {
    const value = player.current?.currentTime;
    return {unit_id:c?.unit_id,position_ms:Math.max(0,Math.min(c?.duration_ms || 0,Number.isFinite(value) ? Math.round(value! * 1000) : position.current))};
  }
  async function save(c = chapters[active.current], at = point(c).position_ms, keepalive = false) {
    if (!c || !progress.current || saving.current || conflicting.current) return;
    saving.current = true;
    if (!pending.current) {
      const key = crypto.randomUUID();
      pending.current = {key,version:progress.current.version,body:{operation_id:key,edition_revision_id:boot.edition_revision_id,location:{format:"video",unit_id:c.unit_id,position_ms:at},occurred_at:new Date().toISOString()}};
    }
    try {
      progress.current = await api<Progress>(path,{method:"PUT",...pending.current,keepalive});
      pending.current = undefined; lastSaved.current = performance.now();
    } catch(error) {
      if (error instanceof ApiError && error.status === 412) {conflicting.current = true;if(mounted.current)setConflict(true);}
      throw error;
    } finally { saving.current = false; }
  }
  async function load(i: number, at?: number, resume = false, manual = false) {
    if (!boot.enabled || !navigator.onLine || loading.current || !chapters[i]) return;
    if (!boot.stream_customer_host || !/^customer-[a-z0-9]+\.cloudflarestream\.com$/.test(boot.stream_customer_host)) {setStatus(t("media_changed"));return;}
    loading.current = true; setBusy(true); setStatus("");
    if (manual) errorRetried.current = false;
    const run = ++generation.current;
    controller.current?.abort(); const abort = new AbortController(); controller.current = abort;
    try {
      const [sdk, identity] = await Promise.all([loadStreamSDK(),session()]);
      factory.current = sdk;
      if (!progress.current) {
        const latest = await api<Progress>(path,{signal:abort.signal}); progress.current = latest;
        const desired = boot.start_asset_id ? chapters.findIndex(c=>c.asset_id===boot.start_asset_id) : at === undefined ? chapters.findIndex(c=>c.unit_id===latest.location?.unit_id) : -1;
        if (desired >= 0) i = desired;
        at ??= latest.location?.unit_id===chapters[i].unit_id ? latest.location.position_ms : 0;
      }
      const c = chapters[i];
      if (!player.current) {active.current = i;setIndex(i);position.current = Math.max(0,Math.min(c.duration_ms,at || 0));}
      const grant = await api<StreamGrant>("/media/grants",{method:"POST",key:crypto.randomUUID(),signal:abort.signal,body:{asset_id:c.asset_id,purpose:"online",device_id:identity.device_id}});
      const url = approvedStreamURL(grant,c.asset_id,boot.edition_revision_id,Date.now(),boot.stream_customer_host);
      if (!url || grant.duration_ms !== c.duration_ms) throw new Error("media_changed");
      if (!mounted.current || run !== generation.current) return;
      const remaining = Date.parse(grant.expires_at)-Date.now();
      renewAt.current = performance.now()+Math.max(250,remaining-Math.min(15000,remaining/3));
      if (resume && player.current && chapters[active.current]?.asset_id === c.asset_id) at = point(c).position_ms;
      active.current = i; setIndex(i); position.current = Math.max(0,Math.min(c.duration_ms,at || 0));
      setSource({url,chapter:c,generation:run,at:position.current,resume});
    } catch(error) {
      if (!mounted.current || run !== generation.current || abort.signal.aborted) return;
      playing.current = false; renewAt.current = Infinity; setSource(undefined); setStatus(errorText(error));
    } finally { if (run===generation.current) {loading.current = false;if(mounted.current)setBusy(false);} }
  }
  async function recover() {
    if (loading.current || !navigator.onLine) return;
    if (errorRetried.current) {playing.current=false;renewAt.current=Infinity;setSource(undefined);setStatus(t("media_retry"));return;}
    errorRetried.current = true;
    await load(active.current,point().position_ms,playing.current);
  }
  useEffect(()=>{
    if (!source || !iframe.current || !factory.current) return;
    const sdk = factory.current(iframe.current); player.current = sdk; sdk.controls = true;
    let restored = false;
    const restore = () => {
      if (restored || !mounted.current || generation.current!==source.generation || !Number.isFinite(sdk.duration) || sdk.duration<=0) return;
      restored = true; sdk.currentTime = Math.min(source.at/1000,sdk.duration);
      if (source.resume) void sdk.play().catch(()=>setStatus(t("media_retry")));
    };
    const store = () => {position.current = Math.max(0,Math.min(source.chapter.duration_ms,Math.round((sdk.currentTime || 0)*1000)));};
    const update = () => {store();if(performance.now()-lastSaved.current>=15000)void save(source.chapter,position.current).catch(e=>{if(mounted.current)setStatus(errorText(e));});};
    const paused = () => {playing.current=false;store();void save(source.chapter,position.current).catch(e=>{if(mounted.current)setStatus(errorText(e));});};
    const play = () => {playing.current=true;if(performance.now()>=renewAt.current)void load(active.current,point().position_ms,true);};
    const error = () => {void recover();};
    const handlers: [string,()=>void][] = [["loadedmetadata",restore],["canplay",restore],["timeupdate",update],["play",play],["pause",paused],["ended",paused],["error",error]];
    for(const [event,handler] of handlers)sdk.addEventListener(event,handler);
    const fallback = window.setTimeout(restore,1000);
    return()=>{clearTimeout(fallback);for(const[event,handler]of handlers)sdk.removeEventListener(event,handler);sdk.pause();if(player.current===sdk)player.current=undefined;};
  },[source]);
  useEffect(()=>{
    mounted.current = true;
    const network = () => {setOnline(navigator.onLine);if(!navigator.onLine){position.current=point().position_ms;playing.current=false;setSource(undefined);}};
    const hidden = () => {if(document.hidden)void save(undefined,undefined,true).catch(()=>{});else if(playing.current&&performance.now()>=renewAt.current)void load(active.current,point().position_ms,true);};
    const leaving = () => {void save(undefined,undefined,true).catch(()=>{});};
    const timer = window.setInterval(()=>{if(playing.current&&navigator.onLine&&performance.now()>=renewAt.current)void load(active.current,point().position_ms,true);},1000);
    window.addEventListener("online",network);window.addEventListener("offline",network);document.addEventListener("visibilitychange",hidden);window.addEventListener("pagehide",leaving);window.addEventListener("maison:before-navigate",leaving);
    return()=>{mounted.current=false;generation.current++;controller.current?.abort();clearInterval(timer);window.removeEventListener("online",network);window.removeEventListener("offline",network);document.removeEventListener("visibilitychange",hidden);window.removeEventListener("pagehide",leaving);window.removeEventListener("maison:before-navigate",leaving);};
  },[]);
  async function choose(i:number) {try {await save();if(!conflicting.current)await load(i,0,playing.current,true);}catch(error){setStatus(errorText(error));}}
  async function resolve(useLocal:boolean) {
    setBusy(true);
    try {
      if (!useLocal) player.current?.pause();
      progress.current=await api<Progress>(path);pending.current=undefined;
      if(useLocal){conflicting.current=false;await save();}
      else {const i=chapters.findIndex(c=>c.unit_id===progress.current?.location?.unit_id);conflicting.current=false;await load(Math.max(0,i),progress.current.location?.position_ms || 0,false,true);}
      if(!conflicting.current){setConflict(false);setStatus(t("saved_server"));}
    }catch(error){setStatus(errorText(error));}finally{setBusy(false);}
  }
  return <section className="video-room" aria-labelledby="video-title">
    <p className="eyebrow">{t("video")}</p><h1 id="video-title" lang={boot.locale}>{boot.title}</h1>
    {source && online ? <iframe ref={iframe} title={chapter?.title || boot.title} src={source.url} referrerPolicy="no-referrer" allow="autoplay; fullscreen; picture-in-picture" allowFullScreen className="stream-frame" /> : <div className="media-unavailable"><h2>{t(!online?"video_offline_title":"video_unavailable_title")}</h2><p>{t(!online?"video_offline_help":"video_unavailable_help")}</p></div>}
    <p role="status" aria-live="polite">{busy?t("loading"):status}</p>
    {boot.enabled && chapter && online ? <button disabled={busy||conflict} onClick={()=>void load(active.current,progress.current?point().position_ms:undefined,playing.current,true)}>{t(source?"retry":"watch")}</button> : null}
    {boot.authenticated===false && boot.sign_in_url ? <a className="button" href={validReturnPath(boot.sign_in_url)}>{t("sign_in")}</a>:null}
    {conflict?<div className="notice"><p>{t("conflict")}</p><button disabled={busy} onClick={()=>void resolve(false)}>{t("use_server")}</button><button disabled={busy} onClick={()=>void resolve(true)}>{t("resolve_keep_local")}</button></div>:null}
    {chapters.length>1?<ol className="unit-list">{chapters.map((c,i)=><li key={c.asset_id}><button disabled={busy||conflict} aria-current={i===index?"true":undefined} onClick={()=>void choose(i)}>{c.title}</button></li>)}</ol>:null}
    <p className="notice">{t("video_caption_status")}</p><p>{t("video_pip_help")}</p>
    <div className="actions">{boot.reader_url?<a className="button secondary" href={validReturnPath(boot.reader_url)}>{t("reader")}</a>:null}{boot.player_url?<a className="button secondary" href={validReturnPath(boot.player_url)}>{t("audio")}</a>:null}</div>
  </section>;
}
export function mount(){const host=document.getElementById("video-island");if(host)mountIsland(host,()=> <Video boot={readBootstrap<Boot>("video-bootstrap")} />);}
mount();
