/* Maison progressive enhancement. All saved/finished/result states require server acknowledgement. */
(() => {
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
  window.addEventListener('online', showConnection); window.addEventListener('offline', showConnection); showConnection();
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
    api('/me/saved-items').then(page => {isSaved = (page.items || []).some(item => (item.edition_id || item.edition?.edition_id) === saveButton.dataset.saveEdition); saveButton.textContent = isSaved ? ui.remove_saved : ui.save; saveButton.setAttribute('aria-pressed', String(isSaved));}).catch(error => failure('save-status', error));
    saveButton.addEventListener('click', () => busy(saveButton, async () => {await api('/me/saved-items/' + saveButton.dataset.saveEdition, {method:isSaved ? 'DELETE' : 'PUT', body:isSaved ? undefined : {}}); isSaved = !isSaved; saveButton.textContent = isSaved ? ui.remove_saved : ui.save; saveButton.setAttribute('aria-pressed', String(isSaved)); status('save-status', ui.saved_server);}, 'save-status'));
  }

  async function editionCard(editionId, extraAction) {let edition; try {edition = await api('/catalog/editions/' + editionId + '?locale=' + locale + '&territory=IN');} catch (_) {try {edition=await api('/staff/draft-editions/'+editionId);} catch (_) {edition = {title:ui.not_available};}} const article = make('article'); const link = make('a',edition.title); link.href = `/${locale}/titles/${editionId}/`; const heading = make('h2'); heading.append(link); article.append(heading); if (extraAction) article.append(extraAction); return article;}
  const vault = $('#vault-content');
  if (vault) {
    const tab = vault.dataset.tab, target = $('#vault-items');
    async function loadVault() {target.replaceChildren(); if (tab === 'lists') {const data = await api('/me/lists'); for (const list of data.items || []) {const article = make('article'), link = make('a',list.name); link.href = `/${locale}/vault/lists/${list.list_id}/`; article.append(link); target.append(article);} status('vault-status',data.items?.length ? '' : ui.empty);} else {const data = await api(tab === 'finished' ? '/me/vault' : '/me/saved-items'); const items = tab === 'finished' ? (data.finished || []) : (data.items || []); for (const item of items.slice(0,20)) target.append(await editionCard(item.edition_id || item.edition?.edition_id || item.card?.edition_id)); status('vault-status',items.length ? '' : tab === 'finished' ? ui.no_finished : ui.no_saved);}}
    loadVault().catch(error => failure('vault-status',error));
    $('#create-list-form')?.addEventListener('submit',event => {event.preventDefault(); const form = event.currentTarget; form.dataset.pendingKey ||= crypto.randomUUID(); busy($('button',form),async () => {await api('/me/lists',{method:'POST',key:form.dataset.pendingKey,body:{name:new FormData(form).get('name')}}); delete form.dataset.pendingKey; form.reset(); await loadVault(); status('vault-status',ui.saved_server);},'vault-status');});
  }
  const listNode = $('#personal-list');
  if (listNode) {
    const path = '/me/lists/' + listNode.dataset.listId; let list;
    async function loadList() {list = await api(path); $('#list-title').textContent = list.name; $('#rename-list-form input').value = list.name; const target = $('#list-items'); target.replaceChildren(); for (const [index, id] of list.edition_ids.entries()) {const actions = make('div',null,'actions'); for (const [label,delta] of [[ui.move_up,-1],[ui.move_down,1]]) {const button = make('button',label); button.disabled = index+delta<0 || index+delta>=list.edition_ids.length; button.addEventListener('click',() => busy(button,async () => {const order = [...list.edition_ids]; [order[index],order[index+delta]]=[order[index+delta],order[index]]; await api(path+'/order',{method:'PUT',version:list.version,body:{edition_ids:order}}); await loadList();},'list-status')); actions.append(button);} const remove = make('button',ui.remove); remove.addEventListener('click',() => busy(remove,async () => {await api(path+'/items/'+id,{method:'DELETE',version:list.version}); await loadList();},'list-status')); actions.append(remove); target.append(await editionCard(id,actions));} status('list-status',list.edition_ids.length ? '' : ui.empty_list);}
    loadList().catch(error => failure('list-status',error));
    $('#rename-list-form').addEventListener('submit',event => {event.preventDefault();busy($('button',event.currentTarget),async () => {await api(path,{method:'PATCH',version:list.version,body:{name:new FormData(event.currentTarget).get('name')}});await loadList();},'list-status');});
    $('#add-list-item-form').addEventListener('submit',event => {event.preventDefault();busy($('button',event.currentTarget),async () => {await api(path+'/items/'+new FormData(event.currentTarget).get('edition_id'),{method:'PUT',version:list.version,body:{}});await loadList();},'list-status');});
    $('#delete-list').addEventListener('click',event => busy(event.currentTarget,async () => {await api(path,{method:'DELETE',version:list.version});window.location.assign(`/${locale}/vault/?tab=lists`);},'list-status'));
  }

  const filterForm = $('#save-filter-form');
  if (filterForm) {
    async function showFilters() {const prefs = await preferences(), target = $('#saved-filter-list'); target.replaceChildren(); for (const [index,item] of (prefs.saved_filters || []).entries()) {const wrapper = make('div',null,'actions'), link = make('a',item.name), params = new URLSearchParams({...item.filters,q:item.query || ''}); if (params.has('locale')) {params.set('content_locale',params.get('locale'));params.delete('locale');} link.href=`/${locale}/search/?${params}`; const remove = make('button',ui.remove); remove.addEventListener('click',() => busy(remove,async () => {await savePreferences({saved_filters:prefs.saved_filters.filter((_,i) => i!==index)});await showFilters();},'filter-status')); wrapper.append(link,remove);target.append(wrapper);}}
    showFilters().catch(error => failure('filter-status',error));
    filterForm.addEventListener('submit',event => {event.preventDefault();busy($('button',filterForm),async () => {const prefs = await preferences(), values = new URLSearchParams(window.location.search), filters = {}; for (const key of ['house','format','level','topic','access','duration_min','duration_max','recency_days']) {const value=values.get(key);if(value)filters[key]=['duration_min','duration_max','recency_days'].includes(key)?Number(value):value;} filters.locale=values.get('content_locale') || locale; if ((prefs.saved_filters || []).length>=20) throw new Error(ui.invalid_input); await savePreferences({saved_filters:[...(prefs.saved_filters || []),{name:new FormData(filterForm).get('name'),query:values.get('q')||'',filters}]}); filterForm.reset(); await showFilters();status('filter-status',ui.saved_server);},'filter-status');});
  }

})();
