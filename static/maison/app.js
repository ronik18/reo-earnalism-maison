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

  const bootNode = $('#reader-bootstrap');
  if (bootNode) {
    const boot = JSON.parse(bootNode.textContent);
    const reader = $('#reader'), reading = $('#reading-text'), controls = $('#reading-settings-form');
    const paragraphs = $$('[data-anchor]', reading);
    paragraphs.forEach(p => {p.dataset.originalText = p.textContent;});
    let current = {format:'reader', unit_id:boot.unit_id, anchor_id:paragraphs[0]?.dataset.anchor, offset_chars:0};
    let progress, completion, annotations = [], selectedRange, selectedQuote = '', pendingProgress, pendingCompletion, conflictPosition;
    const progressPath = '/me/progress/' + boot.edition_id + '/reader';
    const completionPath = '/me/completion/' + boot.edition_id + '/reader';
    const jumpTo = location => {const p = paragraphs.find(node => node.dataset.anchor === location?.anchor_id); if (p) {current = location; p.scrollIntoView({block:'start', behavior:'instant'});}};
    const completionButton = $('#complete-reading');
    function showCompletion() {if (completionButton) {completionButton.textContent = completion?.is_complete ? ui.uncomplete : ui.complete; completionButton.setAttribute('aria-pressed', String(!!completion?.is_complete));}}
    function applyReaderPreferences(data) {
      const leading = Math.max(Number(data.reader_line_height || 1.65), boot.content_locale === 'bn' ? 1.8 : 1.5);
      reader.style.setProperty('--reader-size', `${Number(data.reader_font_size || 20)}px`);
      reader.style.setProperty('--reader-leading', leading);
      reader.style.setProperty('--reader-measure', ({compact:'55ch',comfortable:'65ch',wide:'72ch'})[data.reader_margins] || '65ch');
      reader.style.setProperty('--reader-alignment', data.reader_alignment || 'start');
      reader.classList.remove('reader-light','reader-paper','reader-sepia','reader-dark','reader-ink','reader-true_black');
      reader.classList.add('reader-' + (data.reader_theme || 'light')); reader.classList.toggle('sans', data.reader_typeface === 'sans');
      reader.dataset.layout = data.reader_layout || 'scroll';
      $('#reader-page-controls').hidden = reader.dataset.layout !== 'paginated';
      for (const [key, value] of Object.entries(data)) {const input = controls.elements.namedItem(key); if (input) input.value = String(value);}
    }
    const readingPage = () => {const width = reading.clientWidth + 50; status('reading-page-status', `${ui.page} ${Math.floor(reading.scrollLeft/width)+1} / ${Math.max(1,Math.ceil((reading.scrollWidth+50)/width))}`);};
    $('#previous-reading-page').addEventListener('click',()=>{reading.scrollBy({left:-(reading.clientWidth+50),behavior:'instant'});readingPage();});
    $('#next-reading-page').addEventListener('click',()=>{reading.scrollBy({left:reading.clientWidth+50,behavior:'instant'});readingPage();});
    reading.addEventListener('scroll',readingPage,{passive:true});
    let localPrefs = {};
    try {localPrefs = JSON.parse(localStorage.getItem('maison.reader.preferences') || '{}');} catch (_) { /* A storage denial does not block reading. */ }
    applyReaderPreferences(localPrefs);
    if (boot.authenticated) preferences().then(p => {applyAccountPreferences(p); applyReaderPreferences(p); $('#preference-ownership').textContent = ui.preferences_account;}).catch(error => failure('settings-status', error));
    controls.addEventListener('input', () => applyReaderPreferences(Object.fromEntries(new FormData(controls))));
    controls.addEventListener('submit', event => {event.preventDefault(); busy($('button[type=submit]', controls), async () => {const values = Object.fromEntries(new FormData(controls)); values.reader_font_size = Number(values.reader_font_size); values.reader_line_height = Number(values.reader_line_height); if (boot.authenticated) await savePreferences(values); else {try {localStorage.setItem('maison.reader.preferences', JSON.stringify(values));} catch (_) {throw new Error(ui.unsaved);}} closeDialog($('#reading-settings'));}, 'settings-status');});

    const observer = new IntersectionObserver(entries => {for (const entry of entries) if (entry.isIntersecting && current.anchor_id !== entry.target.dataset.anchor) current = {format:'reader',unit_id:boot.unit_id,anchor_id:entry.target.dataset.anchor,offset_chars:0};}, {rootMargin:'-15% 0px -55% 0px'});
    paragraphs.forEach(p => observer.observe(p));
    if (boot.anchor) jumpTo({format:'reader',unit_id:boot.unit_id,anchor_id:boot.anchor,offset_chars:Number(boot.offset_chars || 0)});
    async function savePosition() {
      if (!boot.authenticated || !current.anchor_id) return;
      if (!progress) progress = await api(progressPath);
      status('reader-status', ui.saving);
      pendingProgress ||= {operation_id:crypto.randomUUID(), edition_revision_id:boot.edition_revision_id, location:{...current}, occurred_at:new Date().toISOString()};
      try {progress = await api(progressPath, {method:'PUT', body:pendingProgress, version:progress.version, key:pendingProgress.operation_id}); pendingProgress = null; status('reader-status', ui.saved_server); showCompletion();}
      catch (error) {if (error.status === 412) {conflictPosition = {...current}; $('#progress-conflict').hidden = false; status('reader-status', ui.conflict);} else status('reader-status', ui.unsaved); throw error;}
    }
    if (boot.authenticated) {
      api(progressPath).then(saved => {progress = saved; if (!boot.anchor && saved.location?.unit_id === boot.unit_id) jumpTo(saved.location);}).catch(error => failure('reader-status', error));
      api(completionPath).then(saved => {completion=saved;showCompletion();}).catch(error=>failure('reader-status',error));
      $('#save-position').addEventListener('click', event => busy(event.currentTarget, savePosition, 'reader-status'));
      let saving = false;
      setInterval(async () => {if (document.hidden || saving || !navigator.onLine || !progress || (!pendingProgress && progress.location?.unit_id===current.unit_id && progress.location?.anchor_id===current.anchor_id && progress.location?.offset_chars===current.offset_chars)) return; saving = true; try {await savePosition();} catch (_) {} finally {saving = false;}}, 15000);
      $('#use-server').addEventListener('click', event => busy(event.currentTarget, async () => {progress = await api(progressPath); pendingProgress = null; jumpTo(progress.location); $('#progress-conflict').hidden = true; status('reader-status', ui.saved_server);}, 'reader-status'));
      $('#use-local').addEventListener('click', event => busy(event.currentTarget, async () => {progress = await api(progressPath); pendingProgress = null; current = conflictPosition || current; await savePosition(); $('#progress-conflict').hidden = true;}, 'reader-status'));
      completionButton.addEventListener('click', event => busy(event.currentTarget, async () => {if (!completion) completion=await api(completionPath); if(!pendingCompletion){const key=crypto.randomUUID();pendingCompletion={key,version:completion.version,body:{operation_id:key,is_complete:!completion.is_complete}};}completion=await api(completionPath,{method:'PUT',...pendingCompletion});pendingCompletion=null;showCompletion(); status('reader-status', ui.saved_server);}, 'reader-status'));
      const annotationDialog = $('#annotation-dialog'), quote = $('#annotation-quote'), passage = $('#annotation-passage');
      function fullParagraph(anchor) {const p = paragraphs.find(node => node.dataset.anchor === anchor) || paragraphs[0]; if (!p) return; selectedRange = {unit_id:boot.unit_id,start_anchor_id:p.dataset.anchor,start_offset_chars:0,end_anchor_id:p.dataset.anchor,end_offset_chars:Array.from(p.dataset.originalText).length,offset_unit:'unicode_code_point'}; selectedQuote = p.dataset.originalText; quote.textContent = selectedQuote; passage.value = p.dataset.anchor;}
      function point(node, offset) {const p = (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement)?.closest('[data-anchor]'); if (!p || !reading.contains(p)) return null; const range = document.createRange(); range.selectNodeContents(p); range.setEnd(node, offset); return {p,offset:Array.from(range.toString()).length};}
      function captureSelection() {const selection = window.getSelection(); if (!selection?.rangeCount || selection.isCollapsed) return false; const range = selection.getRangeAt(0), start = point(range.startContainer,range.startOffset), end = point(range.endContainer,range.endOffset); if (!start || !end) return false; selectedRange = {unit_id:boot.unit_id,start_anchor_id:start.p.dataset.anchor,start_offset_chars:start.offset,end_anchor_id:end.p.dataset.anchor,end_offset_chars:end.offset,offset_unit:'unicode_code_point'}; selectedQuote = selection.toString(); return true;}
      reading.addEventListener('pointerup', captureSelection); reading.addEventListener('keyup', captureSelection);
      $('#annotate-selection').addEventListener('click', event => {if (!selectedRange) fullParagraph(current.anchor_id); quote.textContent = selectedQuote; openDialog(annotationDialog,event.currentTarget);});
      passage.addEventListener('change', () => fullParagraph(passage.value));
      function drawHighlights() {
        paragraphs.forEach(p => {p.textContent = p.dataset.originalText; const records = annotations.filter(a => a.range.start_anchor_id === p.dataset.anchor && a.range.end_anchor_id === p.dataset.anchor && a.color && a.anchor_status !== 'orphaned').sort((a,b) => a.range.start_offset_chars-b.range.start_offset_chars); let cursor = 0; const chars = Array.from(p.dataset.originalText), fragment = document.createDocumentFragment(); for (const a of records) {const start = a.range.start_offset_chars, end = a.range.end_offset_chars; if (start < cursor || end > chars.length || end <= start) continue; fragment.append(document.createTextNode(chars.slice(cursor,start).join(''))); fragment.append(make('mark',chars.slice(start,end).join(''),a.color)); cursor = end;} fragment.append(document.createTextNode(chars.slice(cursor).join(''))); p.replaceChildren(fragment);});
      }
      async function loadAnnotations() {const response = await api('/me/annotations?edition_revision_id=' + boot.edition_revision_id); annotations = (response.items || []).filter(a => a.edition_revision_id === boot.edition_revision_id); const target = $('#annotations'); target.replaceChildren(); if (!annotations.length) target.append(make('p',ui.no_annotations)); for (const annotation of annotations) {const article = make('article'); article.append(make('blockquote',annotation.quoted_text)); if (annotation.note_text) article.append(make('p',annotation.note_text)); const jump = make('button',ui.jump); jump.addEventListener('click', () => jumpTo({format:'reader',unit_id:boot.unit_id,anchor_id:annotation.range.start_anchor_id,offset_chars:annotation.range.start_offset_chars})); const remove = make('button',ui.delete_note); remove.addEventListener('click', () => busy(remove,async () => {await api('/me/annotations/' + annotation.annotation_id,{method:'DELETE',version:annotation.version}); await loadAnnotations();},'reader-status')); article.append(jump,remove); target.append(article);} drawHighlights();}
      $('#annotation-form').addEventListener('submit', event => {event.preventDefault(); const form = event.currentTarget; busy($('button[type=submit]',form),async () => {if (!selectedRange) fullParagraph(current.anchor_id); const data = new FormData(form), note = data.get('note_text'); if (new TextEncoder().encode(note).length > 8192) throw new Error(ui.invalid_input); form.dataset.pendingId ||= crypto.randomUUID(); const id = form.dataset.pendingId; await api('/me/annotations',{method:'POST',key:id,body:{annotation_id:id,edition_revision_id:boot.edition_revision_id,kind:note ? 'note' : 'highlight',range:selectedRange,color:data.get('color'),note_text:note || null}}); closeDialog(annotationDialog); delete form.dataset.pendingId; form.reset(); await loadAnnotations(); status('reader-status',ui.saved_server);},'annotation-status');});
      loadAnnotations().catch(error => failure('reader-status',error));
    }
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

  const accountSettings = $('#account-settings-form');
  if (accountSettings) {preferences().then(p => {applyAccountPreferences(p);accountSettings.elements.theme.value=p.theme;accountSettings.elements.reduced_motion.checked=p.reduced_motion;}).catch(error => failure('account-settings-status',error));accountSettings.addEventListener('submit',event => {event.preventDefault();busy($('button',accountSettings),async () => {const p = await savePreferences({theme:accountSettings.elements.theme.value,reduced_motion:accountSettings.elements.reduced_motion.checked});applyAccountPreferences(p);status('account-settings-status',ui.saved_server);},'account-settings-status');});}
  const devices = $('#devices');
  if (devices) {api('/me/devices').then(page => {for(const device of page.items || []) {const row = make('article'), title = make('p',device.label);row.append(title);if (!device.revoked_at) {const button=make('button',ui.revoke_device);button.addEventListener('click',() => busy(button,async () => {await api('/me/devices/'+device.device_id,{method:'DELETE'}); if (device.current) window.location.assign(`/${locale}/sign-in/`);else {button.remove();status('device-status',ui.saved_server);}},'device-status'));row.append(button);}devices.append(row);}}).catch(error => failure('device-status',error));}

  const quizForm = $('#quiz-form');
  if (quizForm) {let attempt, startKey=crypto.randomUUID(), submitKey=crypto.randomUUID();quizForm.addEventListener('submit',event => {event.preventDefault();busy($('button[type=submit]',quizForm),async () => {if(!quizForm.reportValidity())return;if(!attempt)attempt=await api('/learning/quizzes/'+quizForm.dataset.quizId+'/attempts',{method:'POST',key:startKey,body:{quiz_version:Number(quizForm.dataset.quizVersion)}});const form=new FormData(quizForm),answers=$$('[data-question-id]',quizForm).map(field=>({question_id:field.dataset.questionId,option_id:form.get('question-'+field.dataset.questionId)}));const result=await api('/learning/attempts/'+attempt.attempt_id+'/submit',{method:'POST',key:submitKey,version:attempt.version,body:{answers}});const output=$('#quiz-result');output.replaceChildren(make('h3',ui.quiz_result),make('p',`${ui.score}: ${result.score}`));for(const item of result.result || []){output.append(make('p',(item.correct?ui.correct:ui.incorrect)+' · '+item.explanation));}$$('input,button[type=submit]',quizForm).forEach(input=>input.disabled=true);output.focus();},'quiz-result');});}
})();
