import { useEffect, useState } from "react";
import { api, errorText, locale, session, t } from "./api";
import { activeMember, books, type LocalBook } from "./offline";
import { mountIsland } from "./lifecycle";
const say = (en:string,bn:string) => locale === "bn" ? bn : en;
interface Card { edition_id:string; title:string; locale:string; creators:string[]; formats:string[]; cover?:{url:string;alt:string}|null }
interface Progress { format:string; location: null | { unit_id:string; anchor_id?:string; offset_chars?:number; position_ms?:number }; updated_at:string|null }
interface Resume { card:Card; progress:Progress }
function resumeURL(item:Resume) {
  const { card, progress } = item, loc = progress.location;
  if (!loc || !card.formats.includes(progress.format)) return `/${locale}/titles/${card.edition_id}/`;
  if (progress.format === "reader") return `/${locale}/read/${card.edition_id}/${encodeURIComponent(loc.unit_id)}/?` + new URLSearchParams({anchor:loc.anchor_id || "",offset:String(loc.offset_chars || 0)});
  if (progress.format === "audio") return `/${locale}/listen/${card.edition_id}/?` + new URLSearchParams({unit_id:loc.unit_id,position_ms:String(loc.position_ms || 0)});
  return `/${locale}/watch/${card.edition_id}/?` + new URLSearchParams({unit_id:loc.unit_id,position_ms:String(loc.position_ms || 0)});
}
function Home() {
  const [continuing,setContinuing] = useState<Resume[]>([]), [downloaded,setDownloaded] = useState<LocalBook[]>([]);
  const [status,setStatus] = useState(""), [loading,setLoading] = useState(true), [reload,setReload] = useState(0);
  useEffect(()=>{ let current=true; setLoading(true);setStatus("");
    async function load() {
      const member = document.body.dataset.memberId || "";
      try { if (member && await activeMember()===member) { const local=await books(member); if(current)setDownloaded(local.filter(b=>b.state==="ready" && b.license.status==="active" && Date.parse(b.license.valid_until)>Date.now() && b.last_seen<=Date.now()+60000)); } } catch { /* Local storage is optional; server continue remains available. */ }
      if (!navigator.onLine) { if(current)setStatus(say("Offline. Only previously downloaded, licensed items can open.","অফলাইন। আগে ডাউনলোড করা বৈধ অনুমতির বইই খুলতে পারবেন।"));return; }
      const identity=await session(true);
      if (!identity.authenticated || identity.member?.member_id!==member) { if(current)setStatus(t("sign_in_save"));return; }
      const data=await api<{continue:Resume[]}>("/me/vault");
      if(current)setContinuing(data.continue.filter(item=>item.progress.location).slice(0,6));
    }
    void load().catch(e=>{if(current)setStatus(errorText(e));}).finally(()=>{if(current)setLoading(false);});
    const online=()=>setReload(x=>x+1);window.addEventListener("online",online);
    return()=>{current=false;window.removeEventListener("online",online);};
  },[reload]);
  return <section className="member-home" aria-labelledby="member-home-heading" aria-busy={loading}>
    <div className="section-heading"><div><p className="eyebrow">{say("A little space, just for you", "শুধু আপনার জন্য একটু জায়গা")}</p><h2 id="member-home-heading">{t("your_place")}</h2></div><a href={`/${locale}/vault/`}>{t("vault")}</a></div>
    {downloaded.length>0 && <section className="downloaded-first"><h3>{say("Ready on this device", "এই যন্ত্রে প্রস্তুত")}</h3><p>{say("Local licenses are checked again when you open a download.", "ডাউনলোড খুললে স্থানীয় অনুমতি আবার যাচাই করা হবে।")}</p><ul>{downloaded.map(book=><li key={book.key}><a href={`/${locale}/vault/downloads/`}>{book.title} · {t(book.license.format)}</a></li>)}</ul></section>}
    {loading && <p role="status">{t("loading")}</p>}
    {status && <div className="notice" role="status"><p>{status}</p><button onClick={()=>setReload(x=>x+1)}>{t("retry")}</button></div>}
    {!loading && !status && continuing.length===0 && <div className="empty-state"><h3>{say("Begin anywhere. Return here.", "যেখানেই শুরু করুন, এখানেই ফিরুন।")}</h3><p>{say("Your saved reading or listening place will appear here. Discover a title below to begin.", "পড়া বা শোনার সংরক্ষিত জায়গা এখানে দেখা যাবে। শুরু করতে নিচে বই খুঁজুন।")}</p></div>}
    <div className="book-grid">{continuing.map(item=><article className="book-row" key={item.card.edition_id+item.progress.format}>{item.card.cover && <img src={item.card.cover.url} alt={item.card.cover.alt} width="100" height="150" loading="lazy"/>}<div><p className="eyebrow">{t(item.progress.format)}</p><h3 lang={item.card.locale}><a href={resumeURL(item)}>{item.card.title}</a></h3><p>{item.card.creators.join(", ")}</p>{item.card.formats.includes(item.progress.format)?<a className="button secondary" href={resumeURL(item)}>{t("continue")}</a>:<p>{t("unreleased_format")}</p>}</div></article>)}</div>
  </section>;
}
export function mount() { mountIsland(document.getElementById("home-island"),()=> <Home/>); }
mount();
