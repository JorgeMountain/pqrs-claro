import {bindActor} from './session-actor.js';
import {esc} from './views.js';

// Los cambios locales se conservan al cerrar el panel; solo Guardar escribe en el expediente.
export function createResponseEditor({open,close,notice,getCase,onSaved}) {
  const drafts=new Map();
  let lastActor='';
  async function edit(requestId) {
    const caseId=getCase()?.id;
    if(!caseId)return;
    const key=caseId+':'+requestId;
    open('Editar respuesta','<p role="status">Cargando la respuesta guardada…</p>');
    const drawer=document.querySelector('#drawer-body');
    try {
      const response=await fetch(`/api/cases/${caseId}/review`);
      if(!response.ok)throw new Error('No se pudo cargar la respuesta. Vuelve a intentarlo.');
      const review=await response.json();
      if(getCase()?.id!==caseId||!document.querySelector('#drawer').open)return;
      const row=review.requests.find(r=>r.request_id===requestId);
      if(!row)throw new Error('La respuesta todavía no está guardada para edición.');
      let draft=drafts.get(key);
      if(!draft){draft={revision:row.revision,paragraphs:structuredClone(row.paragraphs),original:JSON.stringify(row.paragraphs),actor:lastActor};drafts.set(key,draft);}
      const changedElsewhere=draft.revision!==row.revision;
      drawer.innerHTML=`<form id="live-response-edit"><p><strong>${esc(row.label)}. ${esc(row.title)}</strong></p>
        <p class="muted">Edita el texto. Los soportes asociados a cada párrafo se conservan; guardar un cambio deja la respuesta pendiente de revisión.</p>
        ${row.stale?'<p class="alert">Puedes guardar la redacción. Sus fuentes deberán actualizarse antes de aprobarla.</p>':''}
        <div id="response-paragraphs"></div><button type="button" id="response-add">Agregar párrafo</button>
        <label class="field">Tu nombre<input id="response-actor" required maxlength="240" autocomplete="name" value="${esc(draft.actor)}"></label>
        <p id="response-edit-error" role="alert">${changedElsewhere?'Existe una versión guardada más reciente. Tu texto local se conserva; carga esa versión antes de volver a editar.':''}</p>
        <button type="button" id="response-reload" ${changedElsewhere?'':'hidden'}>Descartar cambios locales y cargar versión guardada</button>
        <div class="actionbar"><button class="primary" type="submit" ${changedElsewhere?'disabled':''}>Guardar cambios</button><button type="button" id="response-cancel">Cancelar</button></div>
        <p class="library-note">Cerrar el panel conserva el texto local mientras esta página siga abierta. Cancelar descarta los cambios sin guardar.</p></form>`;
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
          if(getCase()?.id!==caseId)throw new Error('El expediente cambió. Vuelve a abrir la respuesta.');
          const result=await fetch(`/api/cases/${caseId}/review/requests/${encodeURIComponent(requestId)}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:draft.revision,edited_by:draft.actor.trim(),paragraphs:draft.paragraphs,pending_resolutions:[]})});
          const value=await result.json();
          if(!result.ok){if(result.status===409){reload.hidden=false;throw new Error('La respuesta cambió en otra sesión. Tu texto se conserva aquí; carga la versión guardada antes de volver a editar.');}throw new Error(typeof value.detail==='string'?value.detail:'No se pudo guardar. Tu texto se conserva aquí.');}
          drafts.delete(key);lastActor=draft.actor.trim();
          if(form.isConnected&&getCase()?.id===caseId)close();notice(value.revision===row.revision?'No había cambios en la respuesta.':'Cambios guardados. La respuesta queda pendiente de revisión.');
          await onSaved(value);
        } catch(failure) {
          if(form.isConnected){error.textContent=failure.message;form.querySelectorAll('button,input,textarea').forEach(el=>el.disabled=false);saveButton.disabled=!reload.hidden;saveButton.textContent='Guardar cambios';form.querySelector('#response-add').disabled=draft.paragraphs.length>=30;}
        } finally {saving=false;}
      };
      form.querySelector('textarea,input')?.focus();
    } catch(error) {drawer.innerHTML=`<p role="alert">${esc(error.message)}</p>`;}
  }
  return {edit,hasChanges(caseId){return [...drafts].some(([key,draft])=>key.startsWith(caseId+':')&&JSON.stringify(draft.paragraphs)!==draft.original);}};
}
