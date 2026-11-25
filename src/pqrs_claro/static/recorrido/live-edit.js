import {safeJson} from './http.js';
import {bindActor} from './session-actor.js';
import {esc} from './views.js';

// Both save controls persist through the same revision-checked API.
export function createResponseEditor({open,close,notice,getCase,onSaved}) {
  const drafts=new Map();
  const changedText=new Map(), scopes=new Map();
  let lastActor='', editSeq=0, editController=null;
  const dirty=draft=>JSON.stringify(draft.paragraphs)!==draft.original;
  const pending=draft=>dirty(draft)||Boolean(draft.uncertain);
  const canonical=paragraphs=>JSON.stringify(paragraphs.map(p=>({
    text:p.text,cited_chunk_ids:p.cited_chunk_ids||[],cited_fact_ids:p.cited_fact_ids||[],
    office_section:p.office_section||'response',
  })));
  function checkScope(caseId,scope){
    if(getCase()?.id!==caseId)throw new Error('El expediente cambió. Vuelve a abrir la respuesta.');
    if(scope!==scopes.get(caseId))throw new Error('Las fuentes cambiaron. Revisa la edición con los respaldos actuales antes de guardar.');
  }
  async function refreshSaved(row,draft){
    draft.refreshFailed=false;
    try{await onSaved(row);}catch{draft.refreshFailed=true;}
  }
  async function persist(caseId,requestId,draft){
    const key=caseId+':'+requestId,scope=scopes.get(caseId);
    checkScope(caseId,scope);
    if(changedText.has(key)||drafts.get(key)!==draft)throw new Error('Las fuentes cambiaron. Abre Editar respuesta para revisar el texto conservado antes de guardar.');
    if(!draft.actor.trim()||draft.paragraphs.some(p=>!p.text.trim()))throw new Error('Abre Editar respuesta y completa el responsable y los párrafos, o quita los que estén vacíos.');
    // A lost PUT response can leave the server ahead of this local revision.
    // Only adopt that revision when the previously submitted content and author match.
    if(draft.uncertain){
      const response=await fetch(`/api/cases/${encodeURIComponent(caseId)}/review`,{signal:AbortSignal.timeout(60000)});
      const review=await safeJson(response);
      if(!response.ok||!review)throw new Error('No se pudo comprobar el guardado anterior. El texto local se conserva; vuelve a intentar.');
      const attempt=draft.uncertain;
      checkScope(caseId,scope);
      const saved=review.requests.find(row=>row.request_id===requestId);
      if(saved&&!saved.scope_reduced&&saved.revision>attempt.revision&&saved.edited_by===attempt.edited_by&&canonical(saved.paragraphs)===canonical(attempt.paragraphs)){
        draft.revision=saved.revision;draft.original=JSON.stringify(attempt.paragraphs);draft.uncertain=null;
        if(!dirty(draft)){drafts.delete(key);await refreshSaved(saved,draft);return saved;}
      }
    }
    const body={revision:draft.revision,edited_by:draft.actor.trim(),paragraphs:structuredClone(draft.paragraphs),pending_resolutions:[],
      ...(draft.replaceWithdrawn?{replace_withdrawn_paragraphs:true}:{})};
    let result;
    try{
      result=await fetch(`/api/cases/${encodeURIComponent(caseId)}/review/requests/${encodeURIComponent(requestId)}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(60000)});
    }catch{
      draft.uncertain=body;
      throw new Error('No se pudo confirmar el guardado. El texto local se conserva; vuelve a intentar.');
    }
    const value=await safeJson(result);
    checkScope(caseId,scope);
    if(!result.ok||!value){
      draft.uncertain=result.status>=500||!value?body:null;
      const error=new Error(result.status===409?'La respuesta cambió en otra sesión. Tu texto local se conserva; abre Editar respuesta para revisar la versión guardada.':typeof value?.detail==='string'?value.detail:'No se pudo guardar. El texto local se conserva.');
      error.conflict=result.status===409;throw error;
    }
    draft.revision=value.revision;draft.original=JSON.stringify(body.paragraphs);draft.uncertain=null;
    if(!dirty(draft))drafts.delete(key);
    lastActor=body.edited_by;
    await refreshSaved(value,draft);
    return value;
  }
  async function save(caseId,requestId,draft){
    if(draft.saving)return draft.saving;
    draft.saving=persist(caseId,requestId,draft);
    try{return await draft.saving;}finally{draft.saving=null;}
  }
  async function saveAll(caseId){
    const prefix=caseId+':',scope=scopes.get(caseId);
    for(const key of changedText.keys()){
      if(key.startsWith(prefix))throw new Error(`Petición ${key.slice(prefix.length)}: las fuentes cambiaron. Abre Editar respuesta y revisa el texto conservado antes de guardar.`);
    }
    for(const [key,draft] of drafts){
      if(!key.startsWith(prefix)||(!pending(draft)&&!draft.saving))continue;
      const requestId=key.slice(prefix.length);
      try{await save(caseId,requestId,draft);}
      catch(error){throw new Error(`Petición ${draft.label||requestId}: ${error.message}`);}
    }
    checkScope(caseId,scope);
    if([...drafts].some(([key,draft])=>key.startsWith(prefix)&&pending(draft)))throw new Error('Quedan cambios locales. Vuelve a guardar antes de salir.');
  }
  async function edit(requestId) {
    const caseId=getCase()?.id;
    if(!caseId)return;
    const seq=++editSeq;
    editController?.abort();
    const controller=new AbortController();
    editController=controller;
    const key=caseId+':'+requestId;
    const scope=scopes.get(caseId);
    open('Editar respuesta','<p id="live-response-loading" role="status">Cargando la respuesta guardada…</p>');
    const drawer=document.querySelector('#drawer-body');
    const marker=drawer.querySelector('#live-response-loading');
    const stillActive=()=>seq===editSeq&&marker?.isConnected&&getCase()?.id===caseId&&scope===scopes.get(caseId)&&document.querySelector('#drawer')?.open;
    try {
      if(drafts.get(key)?.saving)await drafts.get(key).saving;
      if(!stillActive())return;
      const response=await fetch(`/api/cases/${encodeURIComponent(caseId)}/review`,{signal:controller.signal});
      const review=await safeJson(response);
      if(!stillActive())return;
      if(!response.ok||!review)throw new Error(typeof review?.detail==='string'?review.detail:'No se pudo cargar la respuesta. Vuelve a intentarlo.');
      const row=review.requests.find(r=>r.request_id===requestId);
      if(!row)throw new Error('La respuesta todavía no está guardada para edición.');
      let draft=drafts.get(key);
      if(!draft){draft={revision:row.revision,paragraphs:structuredClone(row.paragraphs),original:JSON.stringify(row.paragraphs),actor:lastActor,label:row.label,replaceWithdrawn:Boolean(row.can_replace_withdrawn_paragraphs)};drafts.set(key,draft);}
      if(changedText.has(key)){
        for(const text of changedText.get(key))draft.paragraphs.push({text,cited_chunk_ids:[],cited_fact_ids:[],office_section:'response'});
        changedText.delete(key);
      }
      const changedElsewhere=draft.revision!==row.revision;
      drawer.innerHTML=`<form id="live-response-edit"><p><strong>${esc(row.label)}. ${esc(row.title)}</strong></p>
        <p class="muted">Edita el texto. Los soportes asociados a cada párrafo se conservan; guardar un cambio deja la respuesta pendiente de revisión.</p>
        ${row.can_replace_withdrawn_paragraphs?'<p class="alert">Al guardar se utilizará la redacción visible. Los párrafos con respaldo retirado se conservan en la revisión anterior.</p>':row.stale?'<p class="alert">Actualiza las fuentes antes de aprobar la redacción.</p>':''}
        <div id="response-paragraphs"></div><button type="button" id="response-add">Agregar párrafo</button>
        <label class="field">Tu nombre<input id="response-actor" required maxlength="240" autocomplete="name" value="${esc(draft.actor)}"></label>
        <p id="response-edit-error" role="alert">${changedElsewhere?'Existe una versión guardada más reciente. Tu texto local se conserva; carga esa versión antes de volver a editar.':''}</p>
        <button type="button" id="response-reload" ${changedElsewhere?'':'hidden'}>Descartar cambios locales y cargar versión guardada</button>
        <div class="actionbar dialog-actions"><button type="button" id="response-cancel">Cancelar</button><button class="primary" type="submit" ${changedElsewhere?'disabled':''}>Guardar cambios</button></div>
        <p class="library-note">Puedes guardar aquí o cerrar el panel y usar «Guardar y volver a la bandeja». Cancelar descarta los cambios sin guardar.</p></form>`;
      const form=drawer.querySelector('form');bindActor(form);draft.actor=form.querySelector('#response-actor').value;
      const error=form.querySelector('#response-edit-error');
      const saveButton=form.querySelector('[type="submit"]');
      const reload=form.querySelector('#response-reload');
      function paragraphs() {
        form.querySelector('#response-paragraphs').innerHTML=draft.paragraphs.map((p,i)=>`<div class="response-paragraph"><label class="field">Párrafo ${i+1}<textarea data-paragraph="${i}" required maxlength="6000" rows="6">${esc(p.text)}</textarea></label><button type="button" class="text-button" data-remove="${i}" aria-label="Quitar párrafo ${i+1}">Quitar párrafo</button></div>`).join('');
        form.querySelector('#response-add').disabled=draft.paragraphs.length>=30;
      }
      paragraphs();
      form.oninput=event=>{
        if(event.target.matches('[data-paragraph]'))draft.paragraphs[Number(event.target.dataset.paragraph)].text=event.target.value;
        if(event.target.id==='response-actor')draft.actor=event.target.value;
      };
      form.onclick=event=>{
        const remove=event.target.closest('[data-remove]');
        if(remove){const index=Number(remove.dataset.remove);draft.paragraphs.splice(index,1);paragraphs();(form.querySelector(`[data-paragraph="${Math.min(index,draft.paragraphs.length-1)}"]`)||form.querySelector('#response-add')).focus();}
      };
      form.querySelector('#response-add').onclick=()=>{draft.paragraphs.push({text:'',cited_chunk_ids:[],cited_fact_ids:[],office_section:'response'});paragraphs();form.querySelector(`[data-paragraph="${draft.paragraphs.length-1}"]`).focus();};
      form.querySelector('#response-cancel').onclick=()=>{drafts.delete(key);close();void onSaved(row);};
      reload.onclick=()=>{drafts.delete(key);void edit(requestId);};
      let saving=false;
      form.onsubmit=async event=>{
        event.preventDefault();if(saving)return;error.textContent='';draft.actor=form.querySelector('#response-actor').value;
        if(!draft.actor.trim()||draft.paragraphs.some(p=>!p.text.trim())){error.textContent='Escribe tu nombre y completa los párrafos, o quita los que estén vacíos.';return;}
        saving=true;form.querySelectorAll('button,input,textarea').forEach(el=>el.disabled=true);
        saveButton.textContent='Guardando…';
        try {
          const value=await save(caseId,requestId,draft);
          if(form.isConnected&&getCase()?.id===caseId)close();notice(draft.refreshFailed?'Los cambios quedaron guardados, pero no se pudo actualizar la vista. Vuelve a abrir la respuesta.':value.revision===row.revision?'No había cambios en la respuesta.':'Cambios guardados. La respuesta queda pendiente de revisión.');
        } catch(failure) {
          if(failure.conflict)reload.hidden=false;
          if(form.isConnected){error.textContent=failure.message;form.querySelectorAll('button,input,textarea').forEach(el=>el.disabled=false);saveButton.disabled=!reload.hidden;saveButton.textContent='Guardar cambios';form.querySelector('#response-add').disabled=draft.paragraphs.length>=30;}
        } finally {saving=false;}
      };
      form.querySelector('textarea,input')?.focus();
    } catch(error) {if(error?.name!=='AbortError'&&stillActive())drawer.innerHTML=`<p role="alert">${esc(error.message)}</p>`;}
  }
  function discardScope(caseId){
    scopes.set(caseId,(scopes.get(caseId)||0)+1);
    for(const [key,draft] of drafts){
      if(!key.startsWith(caseId+':'))continue;
      const original=new Set(JSON.parse(draft.original).map(p=>p.text));
      const edits=draft.paragraphs.filter(p=>p.text&&!original.has(p.text)).map(p=>p.text);
      if(edits.length)changedText.set(key,edits);
      drafts.delete(key);
    }
  }
  return {edit,saveAll,discardScope,hasChanges(caseId){return [...changedText.keys()].some(k=>k.startsWith(caseId+':'))||[...drafts].some(([key,draft])=>key.startsWith(caseId+':')&&pending(draft));}};
}
