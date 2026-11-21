import {useEffect,useState,useRef,type FormEvent} from 'react';
import {mountIsland} from './lifecycle';
import {api,errorText,session,ApiError,readBootstrap} from './api';
type Policy={jurisdiction:string;purpose:string;notice_version:string;method:string};
type Grant=Policy&{authorization_id:string;prospective_subject_id:string;status:string;version:number;expires_at:string|null;child_bound:boolean;claim_submitted:boolean};
const purposeLabel=(purpose:string)=>({'account_processing':'Create or renew a reader account','privacy_access':'Request a specifically authorized data export','privacy_delete':'Request a specifically authorized account deletion'}[purpose]||'Account permission');
const active=(row:Grant)=>row.status==='authorized'&&(!row.expires_at||Date.parse(row.expires_at)>Date.now());
function Guardian(){
 const indiaFirst=readBootstrap<{india_first?:boolean}>('guardian-bootstrap').india_first===true;
 const requestForm=useRef<HTMLFormElement|null>(null);
 const [renewalSource,setRenewalSource]=useState<string|null>(null);
 const capability=useRef<{id:string;subject:string;token:string;expires:string}|null>(null);
 const [claimId,setClaimId]=useState<string|null>(null),[privacy,setPrivacy]=useState<{id:string;grant:string;status:string;kind?:string}|null>(null);
 const [policies,setPolicies]=useState<Policy[]>([]),[rows,setRows]=useState<Grant[]>([]),[busy,setBusy]=useState(false),[message,setMessage]=useState('Checking your account permissions…');
 async function load(){
  const p=await api<{items:Policy[]}>('/me/guardian/policies');setPolicies(p.items);
  const r=await api<{items:Grant[];next_cursor?:string}>('/me/guardian/authorizations');const all=[...r.items];let cursor=r.next_cursor;const seen=new Set<string>();
  while(cursor){if(seen.has(cursor))throw new Error('Pagination unavailable');seen.add(cursor);const next=await api<{items:Grant[];next_cursor?:string}>('/me/guardian/authorizations?cursor='+encodeURIComponent(cursor));all.push(...next.items);cursor=next.next_cursor;}
  setRows(all);setMessage(p.items.length?(indiaFirst?'Read the explanation above, then record permission for the account or specific request.':'Choose the exact purpose and route reviewed for your circumstances.'):'Account permissions are unavailable. Do not enter a child’s details. Confirm your own sign-in and verified mailbox first.');
 }
 useEffect(()=>{load().catch(e=>setMessage(errorText(e)));},[]);
 async function beginClaim(row:Grant){
  setBusy(true);try{const c=await api<{capability:string;expires_at:string}>(`/me/guardian/authorizations/${row.authorization_id}/claim-capability`,{method:'POST',body:{}});capability.current={id:row.authorization_id,subject:row.prospective_subject_id,token:c.capability,expires:c.expires_at};setClaimId(row.authorization_id);setMessage('Permission checked. Complete this reader’s account details within five minutes.');}catch(e){setMessage(errorText(e));}finally{setBusy(false);}
 }
 async function claim(e:FormEvent<HTMLFormElement>){
  e.preventDefault();const c=capability.current;if(!c||busy)return;
  if(Date.parse(c.expires)<=Date.now()){capability.current=null;setClaimId(null);setMessage('The account form expired. Check permission again before entering details.');return;}
  const form=e.currentTarget,d=new FormData(form);setBusy(true);
  try{
   const r=await fetch(`/api/v1/me/guardian/authorizations/${c.id}/claim`,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRFToken':(await session()).csrf_token,'X-Guardian-Claim':c.token},body:JSON.stringify({email:d.get('email'),password:d.get('password'),display_name:d.get('display_name'),locale:'en',password_purpose_consent:d.get('password_purpose_consent')==='on',password_purpose_version:'password-account-v1',...(indiaFirst?{subject_confirmed:d.get('subject_confirmed')==='on'?c.subject:'',guardian_permission:d.get('guardian_permission')==='on',account_notice_version:'india-account-v1'}:{})})});
   const body=await r.json().catch(()=>({}));if(!r.ok)throw new ApiError(r.status,body);
   form.reset();capability.current=null;setClaimId(null);await load();setMessage('Account request accepted. Mailbox verification is still required. You are not signed in as the younger reader.');
  }catch(e){form.reset();capability.current=null;setClaimId(null);try{await load();}catch{}setMessage(errorText(e)+' Details were cleared. Check the request status before retrying.');}finally{setBusy(false);}
 }
 async function request(e:FormEvent<HTMLFormElement>){
  e.preventDefault();const data=new FormData(e.currentTarget),p=policies[Number(data.get('policy'))];if(!p||busy)return;setBusy(true);
  try{await api('/me/guardian/authorizations',{method:'POST',body:{jurisdiction:p.jurisdiction,purpose:p.purpose,notice_version:p.notice_version,method:p.method,...((indiaFirst?renewalSource:data.get('source_authorization_id'))?{source_authorization_id:indiaFirst?renewalSource:data.get('source_authorization_id')}:{}),...(indiaFirst?{parent_declared_adult:data.get('parent_declared_adult')==='on',guardian_permission:data.get('guardian_permission')==='on',account_notice_version:'india-account-v1',account_terms_consent:data.get('account_terms_consent')==='on'}:{})},key:crypto.randomUUID()});setRenewalSource(null);await load();setMessage(indiaFirst?(renewalSource?'Your permission is renewed for the same reader account. If mailbox verification is still pending, check that account’s mailbox.':'Your electronic permission is recorded. For a new reader, continue with Create this reader’s account.'):'Request recorded for independent review. No child account or permission has been created.');}catch(e){setMessage(errorText(e));}finally{setBusy(false);}
 }
 async function withdraw(row:Grant){
  capability.current=null;setClaimId(null);setBusy(true);try{await api(`/me/guardian/authorizations/${row.authorization_id}/withdraw`,{method:'POST',body:{expected_version:row.version},key:crypto.randomUUID()});await load();setMessage('Permission withdrawn. The managed reader’s authorized account sessions have ended. Retained records are not instantly erased.');}catch(e){setMessage(errorText(e));}finally{setBusy(false);}
 }
 async function rights(row:Grant){
  if(!window.confirm(row.purpose==='privacy_delete'?'Request deletion of the specifically authorized account? Applicable holds will still be respected.':'Request the specifically authorized data export?'))return;
  setBusy(true);try{const r=await api<{privacy_request_id:string;status:string}>(`/me/guardian/authorizations/${row.authorization_id}/privacy-requests`,{method:'POST',body:{kind:row.purpose==='privacy_delete'?'delete':'export',confirm:true},key:crypto.randomUUID()});setPrivacy({id:r.privacy_request_id,grant:row.authorization_id,status:r.status,kind:row.purpose==='privacy_access'?'export':'delete'});setMessage('Privacy request queued. Completion is not yet confirmed.');}catch(e){setMessage(errorText(e));}finally{setBusy(false);}
 }
 async function downloadPrivacy(){
  if(!privacy)return;setBusy(true);try{const r=await api<{url:string}>(`/me/guardian/authorizations/${privacy.grant}/privacy-requests/${privacy.id}/download`,{method:'POST',body:{}});const u=new URL(r.url,location.origin);if(u.protocol!=='https:'&&u.origin!==location.origin)throw new Error('Unavailable download');const response=await fetch(u.href,{credentials:u.origin===location.origin?'same-origin':'omit',cache:'no-store'});if(!response.ok)throw new Error('Unavailable download');const blob=await response.blob();const object=URL.createObjectURL(blob);const a=document.createElement('a');a.href=object;a.download='earnalism-authorized-data.json';a.click();setTimeout(()=>URL.revokeObjectURL(object),1000);}catch(e){setMessage(errorText(e));}finally{setBusy(false);}
 }
 async function refreshPrivacy(){if(!privacy)return;setBusy(true);try{const r=await api<{status:string}>(`/me/guardian/authorizations/${privacy.grant}/privacy-requests/${privacy.id}`);setPrivacy({...privacy,status:r.status});}catch(e){setMessage(errorText(e));}finally{setBusy(false);}}
 return <section aria-labelledby="guardian-requests-heading">
  <h2 id="guardian-requests-heading">Your account permissions</h2>
  <p role="status" aria-live="polite">{message}</p>
  <p>Use your own verified parent or guardian account. Changes require a recently confirmed sign-in. <a href="/en/sign-in/?return_to=%2Fen%2Fguardian%2F">Confirm your sign-in</a>.</p>
  {policies.length>0&&<form ref={requestForm} onSubmit={request} aria-busy={busy} tabIndex={-1}>
   {renewalSource&&<div className="notice"><h3>Renew permission for the selected reader account</h3><p>The existing reader account is reused. Confirm your current permission below; do not enter the reader’s email or password again.</p><button type="button" onClick={()=>{setRenewalSource(null);requestForm.current?.reset();}}>Cancel renewal</button></div>}
   <label>What would you like to authorize?<select name="policy" required>{policies.map((p,i)=><option key={i} value={i}>{purposeLabel(p.purpose)}</option>)}</select></label>
   {!indiaFirst&&<label>Reader account<select name="source_authorization_id"><option value="">A new reader account</option>{rows.filter(r=>r.child_bound&&r.purpose==='account_processing').map((r,i)=><option key={r.authorization_id} value={r.authorization_id}>Your authorized reader account {i+1}</option>)}</select></label>}
   {indiaFirst?<>
    <label className="check-label"><input name="parent_declared_adult" type="checkbox" required/>I am 18 or older.</label>
    <label className="check-label"><input name="guardian_permission" type="checkbox" required/>I am the reader’s parent or legal guardian, have authority to act for them and give permission for the selected account purpose.</label>
    <label className="check-label"><input name="account_terms_consent" type="checkbox" required/>I agree to the service terms and consent to the necessary account processing described above and in the privacy notice, including overseas processing by Render and Neon in Singapore and the described Cloudflare and Google Workspace services for the requested account and reading features.</label>
    <p><a href="/en/terms/">Service terms</a> · <a href="/en/privacy/">Privacy notice and withdrawal</a>. Do not enter a child’s details until this permission is recorded. Optional analytics and marketing are not included.</p>
   </>:<p>This requests independent review. It is not proof of parental authority. Do not include names, birthdays, documents or private reading notes.</p>}
   <button disabled={busy}>{indiaFirst?(renewalSource?'Renew my permission':'Record my permission'):'Request review'}</button>
  </form>}
  {claimId&&<form onSubmit={claim} autoComplete="off" aria-busy={busy}>
   <h3>Create this reader’s account</h3><p>Use only the details of the younger reader intended by the permission you just recorded. No date of birth or identification document is requested. Use a separate email address or alias you manage for this reader. It must differ from your own account email; an existing account is never linked by guessing an email.</p>
   <label>Reader display name<input name="display_name" required maxLength={80}/></label>
   <label>Reader account email<input name="email" type="email" required autoComplete="off"/></label>
   <label>Reader account password<input name="password" type="password" required autoComplete="new-password" minLength={12}/></label>
   {indiaFirst&&<><label className="check-label"><input name="subject_confirmed" type="checkbox" required/>These details belong to the same younger reader for whom I recorded this account permission.</label><label className="check-label"><input name="guardian_permission" type="checkbox" required/>As their parent or legal guardian, I authorize this specific account’s sign-in, security and requested reading features, including the described overseas processing. I have read the account privacy notice.</label></>}
   <label className="check-label"><input name="password_purpose_consent" type="checkbox" required/>I agree to password processing for this specifically authorized account.</label>
   <p><a href="/en/privacy/">Read the privacy notice and withdrawal options</a>. Password processing is separate from optional analytics and marketing.</p>
   <button disabled={busy}>Create this reader’s account</button><button type="button" onClick={()=>{capability.current=null;setClaimId(null);}}>Cancel</button>
  </form>}
  {privacy&&<section><h3>Privacy request</h3><p role="status">Status: {privacy.status}</p><button disabled={busy} onClick={refreshPrivacy}>Refresh request status</button>{privacy.status==='completed'&&privacy.kind==='export'&&<button disabled={busy} onClick={downloadPrivacy}>Download authorized export</button>}</section>}
  {rows.map((row,index)=><article className="notice" key={row.authorization_id}>
   <h3>{purposeLabel(row.purpose)} · {index+1}</h3><p className="fine">Permission reference: {row.authorization_id.slice(0,8)}</p><p>{row.expires_at&&Date.parse(row.expires_at)<=Date.now()?'expired':row.status}. {row.child_bound?'A verified account is bound to this permission.':row.claim_submitted?'Account request submitted. Check the reader account mailbox to continue.':'No verified reader account is bound.'}</p>
   {row.expires_at?<p>Expires <time dateTime={row.expires_at}>{new Date(row.expires_at).toLocaleString('en',{dateStyle:'medium',timeStyle:'short'})}</time>.</p>:<p>Continues until withdrawn or superseded, subject to the account and permission rules.</p>}
   {active(row)&&!row.child_bound&&!row.claim_submitted&&row.purpose==='account_processing'&&<button disabled={busy} onClick={()=>beginClaim(row)}>Create this reader’s account</button>}
   {active(row)&&row.child_bound&&['privacy_access','privacy_delete'].includes(row.purpose)&&<button disabled={busy} onClick={()=>rights(row)}>{row.purpose==='privacy_delete'?'Request authorized deletion':'Request authorized export'}</button>}
   {indiaFirst&&row.purpose==='account_processing'&&(row.child_bound||row.claim_submitted)&&(row.status==='withdrawn'||(row.expires_at&&Date.parse(row.expires_at)<=Date.now()))&&<button disabled={busy} onClick={()=>{capability.current=null;setClaimId(null);setRenewalSource(row.authorization_id);requestForm.current?.reset();requestForm.current?.scrollIntoView({block:'start',behavior:'auto'});requestForm.current?.focus();}}>Renew permission</button>}
   {!['withdrawn','rejected'].includes(row.status)&&<button disabled={busy} onClick={()=>withdraw(row)}>Withdraw this permission</button>}
  </article>)}
  {indiaFirst&&<p>For correction, disputed authority or a specifically scoped data request, contact <a href="mailto:sales@reoenterprise.org">sales@reoenterprise.org</a>. Readers can use their own <a href="/en/settings/">account privacy controls</a>. Parent permission alone does not disclose private notes.</p>}
  {indiaFirst&&<p>Already 18 or older and ready to use your account independently? <a href="/en/independent-account/">Continue with your own permission</a>.</p>}
 </section>;
}
mountIsland(document.getElementById('guardian-island'),()=> <Guardian/>);
