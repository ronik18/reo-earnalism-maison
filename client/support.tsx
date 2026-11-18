import {useEffect,useRef,useState,type FormEvent} from 'react';
import {api,errorText,locale,t} from './api';
import {mountIsland} from './lifecycle';
function Support(){
 const [online,setOnline]=useState(navigator.onLine),[busy,setBusy]=useState(false),[accepted,setAccepted]=useState(false),[message,setMessage]=useState('');
 const pending=useRef(false);
 useEffect(()=>{const update=()=>setOnline(navigator.onLine);window.addEventListener('online',update);window.addEventListener('offline',update);return()=>{window.removeEventListener('online',update);window.removeEventListener('offline',update);};},[]);
 async function submit(event:FormEvent<HTMLFormElement>){
  event.preventDefault();if(pending.current||!navigator.onLine||accepted)return;
  pending.current=true;setBusy(true);setMessage('');const data=new FormData(event.currentTarget);
  try{await api('/contact',{method:'POST',body:{email:data.get('email'),locale,category:data.get('category'),message:data.get('message')}});setAccepted(true);setMessage(t('support_accepted'));}catch(e){setMessage(errorText(e)+' '+t('support_uncertain'));}finally{pending.current=false;setBusy(false);}
 }
 return <details className="support-form"><summary>{t('contact_support')}</summary><p>{t('support_help')}</p>{!online?<p className="notice">{t('account_online_only')}</p>:null}<form onSubmit={e=>void submit(e)} aria-busy={busy}><fieldset disabled={busy||accepted}><label>{t('email')}<input name="email" type="email" autoComplete="email" maxLength={254} required/></label><label>{t('support_category')}<select name="category">{['account','billing','content','accessibility','privacy','other'].map(value=><option key={value} value={value}>{t('support_'+value)}</option>)}</select></label><label>{t('support_message')}<textarea name="message" minLength={10} maxLength={5000} rows={5} required/></label><button className="button" disabled={!online}>{t(busy?'sending':'send_request')}</button></fieldset></form><p role="status">{message}</p></details>;
}
export function mount(){mountIsland(document.getElementById('support-island'),()=> <Support/>);}
mount();
