/* Maison progressive enhancement. All saved/finished/result states require server acknowledgement. */
window.maisonEnhance = () => {
  'use strict';
  const ui = JSON.parse(document.getElementById('ui-catalogue')?.textContent || '{}');
  const locale = document.documentElement.dataset.uiLocale || 'en';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const make = (tag, text, cls) => { const node = document.createElement(tag); if (text) node.textContent = text; if (cls) node.className = cls; return node; };
  const status = (id, message) => { const node = document.getElementById(id); if (node) node.textContent = message || ''; };
  let sessionPromise;
  const pendingMutations = new Map();
  async function mutationKey(identity, method, path, body, version) {
    const input=JSON.stringify([method,path,body === undefined ? null : body,version === undefined ? null : version]);
    const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(input)))].map(x=>x.toString(16).padStart(2,'0')).join('');
    const storageKey='maison.pending.'+identity+'.'+hash;
    let key=pendingMutations.get(storageKey);
    try {const stored=JSON.parse(sessionStorage.getItem(storageKey)||'null'); if(stored && Date.now()-stored.created_at<86400000)key=stored.key;} catch(_){}
    key ||= crypto.randomUUID();pendingMutations.set(storageKey,key);
    try {sessionStorage.setItem(storageKey,JSON.stringify({key,created_at:Date.now()}));}catch(_){}
    return {key,storageKey};
  }
  const session = () => sessionPromise ||= fetch('/api/v1/session', {credentials:'same-origin', cache:'no-store'}).then(async response => { if (!response.ok) throw new Error(ui.service_unavailable); return response.json(); }).catch(error => {sessionPromise = null; throw error;});
  class ApiError extends Error { constructor(body, code) {super(ui[body.code] || ui[({authentication_required:'sign_in_save',email_verification_required:'email_unverified',rights_unavailable:'not_authorized',territory_unavailable:'not_authorized',access_denied:'not_authorized',entitlement_required:'not_authorized',content_unavailable:'not_found',temporarily_unavailable:'service_unavailable',validation_error:'invalid_input',invalid_filter:'invalid_input'})[body.code]] || (code === 401 ? ui.sign_in_save : code === 412 ? ui.version_conflict : ui.error)); this.status = code; this.body = body;} }
  async function api(path, {method='GET', body, version, key, signal} = {}) {
    const headers = {'Accept':'application/json'}; let pending;
    if (method !== 'GET') { const current = await session(); headers['X-CSRFToken'] = current.csrf_token; if(!key)pending=await mutationKey(current.member?.member_id || 'anonymous',method,path,body,version);headers['Idempotency-Key'] = key || pending.key; }
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (version !== undefined) headers['If-Match'] = `"v${version}"`;
    const response = await fetch('/api/v1' + path, {method, headers, credentials:'same-origin', cache:'no-store', body:body === undefined ? undefined : JSON.stringify(body), signal});
    const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) throw new ApiError(data, response.status);
    if(pending){pendingMutations.delete(pending.storageKey);try{sessionStorage.removeItem(pending.storageKey);}catch(_){}}
    return data;
  }
  function failure(id, error) {status(id, navigator.onLine ? (error.message || ui.error) : ui.offline);}
  async function busy(button, action, id) {if (button) button.disabled = true; try {return await action();} catch (error) {failure(id, error);} finally {if (button) button.disabled = false;}}
  const showConnection = () => {const node = $('#connection-status'); if (node) node.hidden = navigator.onLine;};
  window.maisonConnectionController?.abort(); window.maisonConnectionController=new AbortController();
  window.addEventListener('online', showConnection,{signal:window.maisonConnectionController.signal}); window.addEventListener('offline', showConnection,{signal:window.maisonConnectionController.signal}); showConnection();
  $$('form').forEach(form => {form.addEventListener('invalid', event => {if (event.target.setCustomValidity) event.target.setCustomValidity(ui.invalid_input);}, true); form.addEventListener('input', event => event.target.setCustomValidity?.(''));});

  const dialogTriggers = new WeakMap();
  function openDialog(dialog, trigger) {dialogTriggers.set(dialog, trigger || document.activeElement); dialog.showModal();}
  function closeDialog(dialog) {dialog.close(); dialogTriggers.get(dialog)?.focus({preventScroll:true});}
  $$('[data-open-dialog]').forEach(button => button.addEventListener('click', () => openDialog(document.getElementById(button.dataset.openDialog), button)));
  $$('[data-close-dialog]').forEach(button => button.addEventListener('click', () => closeDialog(button.closest('dialog'))));

  let preferenceData;
  const preferences = async () => preferenceData ||= await api('/me/preferences');
  async function savePreferences(changes) {const old = await preferences(); preferenceData = await api('/me/preferences', {method:'PATCH', body:changes, version:old.version}); return preferenceData;}
  function applyAccountPreferences(prefs) {document.body.classList.remove('theme-light','theme-dark','theme-true_black'); document.body.classList.add('theme-' + prefs.theme); document.body.classList.toggle('reduced-motion', !!prefs.reduced_motion);}

  const saveButton = $('[data-save-edition]');
  if (saveButton) {
    let isSaved = false;
    const saveRetry=make('button',ui.retry);saveRetry.type='button';saveRetry.hidden=true;saveButton.after(saveRetry);
    async function loadSaved(){saveButton.disabled=true;saveRetry.hidden=true;try {let cursor=null;const visited=new Set();isSaved=false;do{const page=await api('/me/saved-items'+(cursor?'?cursor='+encodeURIComponent(cursor):''));isSaved ||= (page.items||[]).some(item=>(item.edition_id||item.edition?.edition_id)===saveButton.dataset.saveEdition);cursor=page.next_cursor||null;if(cursor&&visited.has(cursor))throw new Error(ui.service_unavailable);if(cursor)visited.add(cursor);}while(cursor&&!isSaved);saveButton.textContent=isSaved?ui.remove_saved:ui.save;saveButton.setAttribute('aria-pressed',String(isSaved));saveButton.disabled=false;status('save-status','');}catch(error){failure('save-status',error);saveRetry.hidden=false;}}
    saveRetry.addEventListener('click',()=>void loadSaved());void loadSaved();
    saveButton.addEventListener('click', () => busy(saveButton, async () => {await api('/me/saved-items/' + saveButton.dataset.saveEdition, {method:isSaved ? 'DELETE' : 'PUT', body:isSaved ? undefined : {}}); isSaved = !isSaved; saveButton.textContent = isSaved ? ui.remove_saved : ui.save; saveButton.setAttribute('aria-pressed', String(isSaved)); status('save-status', ui.saved_server);}, 'save-status'));
  }

  const say = (en, bn) => locale === 'bn' ? bn : en;
  const editionCache = new Map();
  async function editionCard(editionId, extraAction, knownCard) {
    let edition = knownCard;
    if (!edition) {
      if (!editionCache.has(editionId)) editionCache.set(editionId, api('/catalog/editions/' + editionId + '?locale=' + locale).catch(async error => {
        if(error.status===404) {try{return await api('/staff/draft-editions/'+editionId);}catch(staffError){if(![403,404].includes(staffError.status))throw staffError;}}
        else if(error.status!==403)throw error;
        return {title:ui.not_available,unavailable:true};
      }).catch(error=>{editionCache.delete(editionId);throw error;}));
      edition = await editionCache.get(editionId);
    }
    const article = make('article',null,'book-row'), content=make('div');
    if(edition.cover) {const cover=make('img');cover.src=edition.cover.url;cover.alt=edition.cover.alt;cover.width=100;cover.height=150;cover.loading='lazy';article.append(cover);}
    const heading = make('h2');
    if(edition.unavailable) heading.textContent=ui.not_available;
    else {const link=make('a',edition.title);link.href=`/${locale}/titles/${editionId}/`;heading.append(link);}
    if(edition.locale)heading.lang=edition.locale;
    content.append(heading);if(edition.creators)content.append(make('p',edition.creators.join(', ')));
    if(edition.unavailable)content.append(make('p',say('This title may have been withdrawn or is unavailable here. Your list membership is preserved.','বইটি প্রত্যাহৃত হয়েছে অথবা এখানে পাওয়া যাচ্ছে না। তালিকায় বইটি রাখা আছে।')));
    if(extraAction)content.append(extraAction);article.append(content);return article;
  }
  function nextPage(path,cursor) {const url=new URL(path,location.origin);if(cursor)url.searchParams.set('cursor',cursor);return url.pathname+url.search;}
  const vault = $('#vault-content');
  if (vault) {
    const tab = vault.dataset.tab, target = $('#vault-items'), retry=$('#vault-retry'), more=$('#vault-more');
    let pending=false, cursor=null, seen=new Set();
    async function loadVault(append=false) {
      if(pending)return;pending=true;vault.setAttribute('aria-busy','true');retry.hidden=true;more.disabled=true;status('vault-status',ui.loading);
      try {
        const path=tab==='lists'?'/me/lists':tab==='finished'?'/me/vault?section=finished':'/me/saved-items';
        const data=await api(nextPage(path,append?cursor:null));
        if(!append){target.replaceChildren();seen=new Set();}
        const items=tab==='finished'?(data.finished||[]):(data.items||[]);
        for(const item of items){
          const id=tab==='lists'?item.list_id:(item.edition_id||item.edition?.edition_id||item.card?.edition_id);
          if(!id||seen.has(id))continue;seen.add(id);
          if(tab==='lists') {const article=make('article',null,'book-row'),link=make('a',item.name);link.href=`/${locale}/vault/lists/${id}/`;article.append(link);target.append(article);}
          else {
            const actions=make('div',null,'actions');
            if(tab==='saved') {const remove=make('button',ui.remove_saved);remove.addEventListener('click',()=>busy(remove,async()=>{await api('/me/saved-items/'+id,{method:'DELETE'});seen.delete(id);remove.closest('article')?.remove();status('vault-status',seen.size?ui.saved_server:ui.no_saved);},'vault-status'));actions.append(remove);}
            target.append(await editionCard(id,actions,item.card));
          }
        }
        const previous=cursor;cursor=data.next_cursor||null;more.hidden=!cursor||(append&&previous===cursor);
        status('vault-status',seen.size?'':tab==='finished'?ui.no_finished:tab==='saved'?ui.no_saved:ui.empty);
      } catch(error){failure('vault-status',error);retry.hidden=false;}
      finally{pending=false;vault.setAttribute('aria-busy','false');more.disabled=false;}
    }
    retry.addEventListener('click',()=>void loadVault());more.addEventListener('click',()=>void loadVault(true));void loadVault();
    $('#create-list-form')?.addEventListener('submit',event => {event.preventDefault();const form=event.currentTarget;if(form.dataset.busy)return;form.dataset.busy='true';form.dataset.pendingKey ||= crypto.randomUUID();busy($('button',form),async()=>{if(!navigator.onLine)throw new Error(ui.offline);await api('/me/lists',{method:'POST',key:form.dataset.pendingKey,body:{name:new FormData(form).get('name')}});delete form.dataset.pendingKey;form.reset();await loadVault();status('vault-status',ui.saved_server);},'vault-status').finally(()=>delete form.dataset.busy);});
  }
  const listNode = $('#personal-list');
  if (listNode) {
    const path='/me/lists/'+listNode.dataset.listId, retry=$('#list-retry'), more=$('#list-more'), controls=$('#list-controls');let list,pending=false,visible=20;
    async function renderList(){
      $('#list-title').textContent=list.name;$('#rename-list-form input').value=list.name;
      const target=$('#list-items');target.replaceChildren();
      for(const [index,id] of list.edition_ids.slice(0,visible).entries()) {
        const actions=make('div',null,'actions');
        for(const [label,delta] of [[ui.move_up,-1],[ui.move_down,1]]) {const button=make('button',label);button.type='button';button.disabled=index+delta<0||index+delta>=list.edition_ids.length;button.setAttribute('aria-label',label+' · '+(index+1));button.addEventListener('click',()=>void mutate(async()=>{const order=[...list.edition_ids];[order[index],order[index+delta]]=[order[index+delta],order[index]];await api(path+'/order',{method:'PUT',version:list.version,body:{edition_ids:order}});},index+delta));actions.append(button);}
        const remove=make('button',ui.remove);remove.type='button';remove.addEventListener('click',()=>void mutate(()=>api(path+'/items/'+id,{method:'DELETE',version:list.version}),Math.min(index,list.edition_ids.length-2)));actions.append(remove);
        target.append(await editionCard(id,actions));
      }
      more.hidden=visible>=list.edition_ids.length;status('list-status',list.edition_ids.length?'':ui.empty_list);
    }
    async function loadList(){list=await api(path);await renderList();}
    async function mutate(action,focusIndex){
      if(pending)return;pending=true;controls.disabled=true;retry.hidden=true;listNode.setAttribute('aria-busy','true');status('list-status',ui.saving);
      try{if(!navigator.onLine)throw new Error(ui.offline);const result=await action();if(result===false)return;await loadList();status('list-status',ui.saved_server);}
      catch(error){if(error.status===412){await loadList().catch(()=>{});status('list-status',ui.version_conflict);}else failure('list-status',error);retry.hidden=false;}
      finally{pending=false;controls.disabled=false;listNode.setAttribute('aria-busy','false');if(Number.isInteger(focusIndex))$$('#list-items article')[Math.max(0,focusIndex)]?.querySelector('button:not(:disabled)')?.focus();}
    }
    async function refresh(){if(pending)return;pending=true;controls.disabled=true;listNode.setAttribute('aria-busy','true');status('list-status',ui.loading);try{await loadList();retry.hidden=true;}catch(error){failure('list-status',error);retry.hidden=false;}finally{pending=false;controls.disabled=!list;listNode.setAttribute('aria-busy','false');}}
    retry.addEventListener('click',()=>void refresh());more.addEventListener('click',async()=>{if(pending)return;pending=true;controls.disabled=true;visible+=20;try{await renderList();}catch(error){failure('list-status',error);}finally{pending=false;controls.disabled=false;}});void refresh();
    $('#rename-list-form').addEventListener('submit',event=>{event.preventDefault();const name=new FormData(event.currentTarget).get('name');void mutate(()=>api(path,{method:'PATCH',version:list.version,body:{name}}));});
    $('#add-list-item-form').addEventListener('submit',event=>{event.preventDefault();const id=new FormData(event.currentTarget).get('edition_id');void mutate(()=>api(path+'/items/'+id,{method:'PUT',version:list.version,body:{}}));});
    $('#delete-list').addEventListener('click',()=>void mutate(async()=>{await api(path,{method:'DELETE',version:list.version});window.location.assign(`/${locale}/vault/?tab=lists`);return false;}));
  }
  const share=$('[data-share-title]');
  if(share)share.addEventListener('click',()=>busy(share,async()=>{const url=new URL(location.pathname,location.origin).href;try{if(navigator.share){await navigator.share({title:share.dataset.shareTitle,url});status('share-status',ui.shared_title);}else if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(url);status('share-status',ui.link_copied);}else{const output=$('#share-status');output.replaceChildren();const link=make('a',url);link.href=url;output.append(link);}}catch(error){if(error.name!=='AbortError')throw error;}},'share-status'));
  const search=$('.search-form');
  if(search){let composing=false;const query=$('input[name=q]',search);query?.addEventListener('compositionstart',()=>composing=true);query?.addEventListener('compositionend',()=>composing=false);search.addEventListener('submit',event=>{if(composing){event.preventDefault();event.stopImmediatePropagation();}},true);}

  const filterForm = $('#save-filter-form');
  if (filterForm) {
    async function showFilters() {const prefs = await preferences(), target = $('#saved-filter-list'); target.replaceChildren(); for (const [index,item] of (prefs.saved_filters || []).entries()) {const wrapper = make('div',null,'actions'), link = make('a',item.name), params = new URLSearchParams({...item.filters,q:item.query || ''}); if (params.has('locale')) {params.set('content_locale',params.get('locale'));params.delete('locale');} link.href=`/${locale}/search/?${params}`; const remove = make('button',ui.remove); remove.addEventListener('click',() => busy(remove,async () => {await savePreferences({saved_filters:prefs.saved_filters.filter((_,i) => i!==index)});await showFilters();},'filter-status')); wrapper.append(link,remove);target.append(wrapper);}}
    showFilters().catch(error => failure('filter-status',error));
    filterForm.addEventListener('submit',event => {event.preventDefault();busy($('button',filterForm),async () => {const prefs = await preferences(), values = new URLSearchParams(window.location.search), filters = {}; for (const key of ['house','format','level','topic','access','duration_min','duration_max','recency_days']) {const value=values.get(key);if(value)filters[key]=['duration_min','duration_max','recency_days'].includes(key)?Number(value):value;} if(values.get('content_locale'))filters.locale=values.get('content_locale'); if ((prefs.saved_filters || []).length>=20) throw new Error(ui.invalid_input); await savePreferences({saved_filters:[...(prefs.saved_filters || []),{name:new FormData(filterForm).get('name'),query:values.get('q')||'',filters}]}); filterForm.reset(); await showFilters();status('filter-status',ui.saved_server);},'filter-status');});
  }

};
window.maisonEnhance();
