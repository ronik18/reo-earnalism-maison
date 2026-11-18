import { useEffect, useRef, useState } from "react";
import { api, errorText, locale, readBootstrap, session, t } from "./api";
import { mountIsland } from "./lifecycle";

type Choice = { locale: string; theme: string; interests: string[]; goal: string };
type Boot = { return_to?: string; authenticated?: boolean };
const localKey = "maison.guest.preferences";
const say = (en: string, bn: string) => locale === "bn" ? bn : en;
const houses = ["classics", "golpo", "learn", "interview", "series", "collections"];
function destination(boot: Boot, preferredLocale?: string) {
  try { const url = new URL(boot.return_to || `/${locale}/`, location.origin); if (url.origin === location.origin && !url.pathname.includes("sign-in") && !url.pathname.includes("welcome")) return (preferredLocale && ["en", "bn"].includes(preferredLocale) ? url.pathname.replace(/^\/(en|bn)(?=\/)/, "/" + preferredLocale) : url.pathname) + url.search + url.hash; } catch { /* safe home fallback */ }
  return `/${locale}/`;
}
function Onboarding({ boot }: { boot: Boot }) {
  const [step, setStep] = useState(0);
  const [choice, setChoice] = useState<Choice>(() => ({ locale, theme: ["light", "dark", "true_black"].find(value => document.body.classList.contains("theme-" + value)) || "dark", interests: [], goal: "relax" }));
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [finished, setFinished] = useState(false);
  const [returning, setReturning] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { try { const saved = JSON.parse(localStorage.getItem(localKey) || "null"); if (saved && ["en", "bn"].includes(saved.locale) && ["light", "dark", "true_black"].includes(saved.theme)) { setChoice({ locale:saved.locale, theme:saved.theme, interests:Array.isArray(saved.interests)?saved.interests.filter((x:string)=>houses.includes(x)):[], goal:["relax","learn","interview"].includes(saved.goal)?saved.goal:"relax" }); setReturning(true); } } catch { setStatus(say("Browser storage is unavailable. You can still skip and browse.", "ব্রাউজারে সংরক্ষণ করা যাচ্ছে না। তবুও এড়িয়ে সংগ্রহ দেখতে পারবেন।")); } }, []);
  useEffect(() => { heading.current?.focus({preventScroll:true}); }, [step, finished]);
  function previewTheme(theme:string) { setChoice({ ...choice, theme }); document.body.classList.remove("theme-light", "theme-dark", "theme-true_black"); document.body.classList.add("theme-"+theme); }
  async function finish() {
    setBusy(true); setStatus("");
    let saved = false;
    try { localStorage.setItem(localKey, JSON.stringify(choice)); saved = true; } catch { setStatus(say("Your choices could not be saved on this browser. Continue is still available.", "এই ব্রাউজারে পছন্দ সংরক্ষণ করা যায়নি। তবুও এগিয়ে যেতে পারবেন।")); }
    if (boot.authenticated) { try { const identity = await session(); if (!identity.authenticated) throw new Error("session"); const prefs = await api<{ version:number }>("/me/preferences"); await api("/me/preferences", { method:"PATCH", version:prefs.version, body:choice }); saved=true; setStatus(t("saved_server")); } catch (e) { setStatus(errorText(e) + " " + say("Continue now; account sync can be retried from Settings.", "এখন এগিয়ে যান; পছন্দের পাতা থেকে অ্যাকাউন্টে সংরক্ষণ আবার চেষ্টা করতে পারবেন।")); } }
    setBusy(false); setFinished(true);
    if (saved && !boot.authenticated) setStatus(say("Your choices are saved on this browser.", "এই ব্রাউজারে আপনার পছন্দ রাখা হয়েছে।"));
  }
  const titles = [say("Make yourself at home.", "নিজের মতো সাজিয়ে নিন।"), say("Follow your curiosity.", "কৌতূহলের পথে চলুন।"), say("What brings you here?", "কোন টানে এখানে এসেছেন?")];
  return <section className="onboarding-panel narrow" aria-busy={busy}>
    <p className="eyebrow">{say("Your Maison · a personal beginning", "আপনার মেজঁ · নিজের মতো শুরু")}</p>
    <h1 ref={heading} tabIndex={-1}>{finished?say("Your next chapter awaits.", "পরের অধ্যায় অপেক্ষায়।"):titles[step]}</h1>
    {returning && !finished && <p className="notice">{say("Welcome back. Review your choices or continue browsing.", "আবার স্বাগতম। পছন্দ দেখে নিন অথবা সংগ্রহ দেখতে এগিয়ে যান।")}</p>}
    {!finished && <><ol className="onboarding-steps" aria-label={say("Setup steps", "সাজানোর ধাপ")}>{[say("Comfort", "স্বাচ্ছন্দ্য"),say("Interests", "পছন্দ"),say("Purpose", "উদ্দেশ্য")].map((label,i)=><li key={label} aria-current={i===step?"step":undefined}>{i+1}. {label}</li>)}</ol>
    {step===0 && <><fieldset><legend>{t("interface_language")}</legend>{[["en","English"],["bn","বাংলা"]].map(([value,label])=><label className="choice-card" key={value}><input type="radio" name="welcome-locale" checked={choice.locale===value} onChange={()=>setChoice({...choice,locale:value})}/>{label}</label>)}</fieldset><fieldset><legend>{t("theme")}</legend>{["light","dark","true_black"].map(value=><label className="choice-card" key={value}><input type="radio" name="welcome-theme" checked={choice.theme===value} onChange={()=>previewTheme(value)}/>{t(value==="true_black"?"black":value)}</label>)}</fieldset></>}
    {step===1 && <fieldset><legend>{say("Choose any Houses. You can change these later.", "পছন্দের বিভাগ বেছে নিন। পরে বদলাতে পারবেন।")}</legend><div className="form-grid">{houses.map(value=><label className="choice-card" key={value}><input type="checkbox" checked={choice.interests.includes(value)} onChange={()=>setChoice({...choice,interests:choice.interests.includes(value)?choice.interests.filter(x=>x!==value):[...choice.interests,value]})}/>{t(value)}</label>)}</div></fieldset>}
    {step===2 && <fieldset><legend>{say("Choose a direction, without a daily obligation.", "প্রতিদিনের বাধ্যবাধকতা ছাড়া একটি পথ বেছে নিন।")}</legend>{[["relax",say("Find a moment of calm", "শান্তির একটু সময়")],["learn",say("Learn something new", "নতুন কিছু শিখি")],["interview",say("Prepare for my next role", "পরের কাজের প্রস্তুতি")]].map(([value,label])=><label className="choice-card" key={value}><input type="radio" name="welcome-goal" checked={choice.goal===value} onChange={()=>setChoice({...choice,goal:value})}/>{label}</label>)}</fieldset>}
    <div className="actions">{step>0 && <button disabled={busy} onClick={()=>setStep(step-1)}>{t("back")}</button>}{step<2?<button className="button" onClick={()=>setStep(step+1)}>{t("continue")}</button>:<button className="button" disabled={busy} onClick={()=>void finish()}>{busy?t("saving"):say("Keep my choices", "পছন্দ রাখুন")}</button>}<a className="text-link" href={destination(boot)}>{say("Skip for now", "এখন এড়িয়ে যান")}</a></div></>}
    {status && <p role="status" className="notice">{status}</p>}
    {finished && <div className="actions"><a className="button" href={destination(boot,choice.locale)}>{t("continue")}</a><button onClick={()=>{setFinished(false);setStep(0);}}>{say("Review choices", "পছন্দ আবার দেখুন")}</button></div>}
    <p className="muted">{say("No account is needed to explore. Edition language always stays separate from interface language.", "সংগ্রহ দেখতে অ্যাকাউন্ট দরকার নেই। বইয়ের ভাষা ইন্টারফেসের ভাষা থেকে আলাদা থাকে।")}</p>
  </section>;
}
export function mount() { mountIsland(document.getElementById("onboarding-island"), ()=><Onboarding boot={readBootstrap<Boot>("onboarding-bootstrap")}/>); }
mount();
