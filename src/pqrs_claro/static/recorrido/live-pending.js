import {bindSupportPicker} from './pending-supports.js?v=pending-guide1';
import {bindActor,rememberActor} from './session-actor.js';
import {esc} from './views.js';
import {decisionForm,factForm,when,isOpen} from './live-pending-view.js?v=pending-guide1';
import {documentDecisionForm,documentTarget} from './document-decision.js?v=pending-guide1';
import {pendingAction} from './pending-guidance.js';

export function createPendingActions({open,close,notice,getCase,onSaved,upload,getActor=()=>''}) {
  let actor='';
  const drafts=new Map();
  const draftKey=(id,requestId,pendingId,action)=>[id,requestId,pendingId,action].join(':');
  async function api(url,body,method='POST') {
    let response,value;
    try{response=await fetch(url,{...(body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),signal:AbortSignal.timeout(60000)});value=await response.json();}
    catch(error){error.uncertain=body!==undefined&&method==='PUT';throw error;}
    if(!response.ok){const error=new Error(response.status===409?'El expediente cambió. Tu información sigue en el panel; vuelve a consultar el punto antes de guardar.':typeof value.detail==='string'?value.detail:'Revisa los campos. No se pudo guardar.');error.uncertain=response.status===409;throw error;}
    return value;
  }
  const prefix=id=>`/api/cases/${id}/review`;
  async function rowFor(id,requestId) {
    const result=await api(prefix(id));
    const row=result.requests.find(r=>r.request_id===requestId);
    if(!row)throw new Error('No está disponible esta respuesta.');
    return row;
  }
  function bind(form,work) {
    if(getActor()){actor=getActor();rememberActor(actor);}
    bindActor(form);
    const activeActor=getActor();
    let saving=false;
    form.querySelector('#pending-cancel').onclick=close;
    form.onsubmit=async event=>{
      event.preventDefault();if(saving)return;saving=true;
      const error=form.querySelector('#pending-error');error.textContent='';
      if(getActor()!==activeActor){error.textContent='Cambió el gestor activo. Vuelve a consultar el punto para registrar la decisión con el gestor actual.';form.querySelector('#pending-reload')?.removeAttribute('hidden');saving=false;return;}
      const values=new FormData(form);
      const controls=[...form.querySelectorAll('button,input,textarea,select')].map(control=>[control,control.disabled]);
      controls.forEach(([control])=>control.disabled=true);
      form.setAttribute('aria-busy','true');
      let uncertain=false;
      try {await work(values);}catch(e){if(form.isConnected){uncertain=Boolean(e.uncertain);error.textContent=uncertain?'No se pudo confirmar el estado del guardado. Tu explicación se conserva. Consulta el punto antes de volver a enviar.':e.message;form.querySelector('#pending-reload')?.removeAttribute('hidden');error.tabIndex=-1;error.focus();}}finally{saving=false;if(form.isConnected){controls.forEach(([control,disabled])=>control.disabled=disabled);if(uncertain)form.querySelector('[type="submit"]').disabled=true;form.removeAttribute('aria-busy');}}
    };
  }
  async function savedDecision(saved,action){
    let refreshError='';
    try{await onSaved(saved);}catch(error){refreshError='La decisión se guardó, pero no se pudo actualizar la vista. '+error.message;}
    if(getCase()?.id!==saved.case_id)return;
    const remaining=(saved.pending||[]).filter(p=>isOpen(p)&&p.blocks_approval!==false);
    const next=remaining.find(p=>p.state!=='analysis_error');
    open('Decisión guardada',`<section class="pending-success"><span class="pending-success-icon" aria-hidden="true">✓</span><h3>${action==='open'?'Punto reabierto':'Tu decisión quedó guardada'}</h3><p>${action==='open'?'Puedes volver a revisarlo cuando tengas el respaldo.':remaining.length?`Quedan ${remaining.length} ${remaining.length===1?'punto por resolver':'puntos por resolver'} para esta petición.`:saved.pre_draft?'Las confirmaciones necesarias están listas. La preparación continuará automáticamente.':'Puedes continuar revisando la respuesta.'}</p>${refreshError?`<p role="alert">${esc(refreshError)}</p>`:''}<div class="scope-actions">${next&&action!=='open'?'<button type="button" class="primary" id="pending-next">Resolver siguiente punto</button>':''}<button type="button" id="pending-back">Volver a respuestas</button></div><p class="pending-help">La aprobación del borrador se realiza después.</p></section>`);
    document.querySelector('#pending-next')?.addEventListener('click',()=>decide(saved.request_id,next.id,pendingAction(saved,next)));
    document.querySelector('#pending-back').onclick=close;
    document.querySelector('#pending-next,#pending-back')?.focus();
  }
  async function decide(requestId,pendingId,action) {
    const quick=['issued','draft','provenance_reviewed'].includes(action);
    if(!quick&&!['resolved','not_applicable','open','detail','document_choice'].includes(action))return;
    const id=getCase()?.id;if(!id)return;
    open('Resolver pendiente','<p id="pending-loading" role="status">Cargando el punto y sus respaldos…</p>');
    const marker=document.querySelector('#pending-loading'),body=document.querySelector('#drawer-body');
    try {
      const row=await rowFor(id,requestId);if(!marker.isConnected||getCase()?.id!==id)return;
      const p=row.pending.find(p=>p.id===pendingId);
      if(!p){body.innerHTML='<section class="pending-task-context"><h3>Los pendientes se actualizaron</h3><p>Este punto ya no aparece en la revisión actual. Consulta los resultados nuevos para continuar. No se ha aplicado tu decisión a otro punto.</p><button id="pending-back">Ver pendientes actuales</button></section>';body.querySelector('#pending-back').onclick=async()=>{close();await onSaved(row);};return;}
      if(action==='detail'){
        const r=p.resolution;
        if(!r)throw new Error('La decisión fue reabierta. Actualiza la respuesta.');
        body.innerHTML=`<p><strong>${esc(p.description)}</strong></p><p>${esc(r.note)}</p><p>${esc(r.by)} · ${esc(when(r.at))}</p>${(r.cited_chunk_ids||[]).map(chunk=>{const s=row.available_supports.find(s=>s.chunk_id===chunk);return s?`<section class="source"><strong>${esc(s.title)} · versión ${esc(s.version)}</strong><blockquote>${esc(s.quote)}</blockquote><a target="_blank" rel="noopener" href="/api/sources/${encodeURIComponent(s.source_id)}/original?case_id=${id}">Abrir documento original ↗</a></section>`:'<p>El pasaje anterior ya no está disponible en las fuentes vigentes. Consulta el historial.</p>';}).join('')}${(r.cited_fact_ids||[]).map(fid=>{const f=row.facts.find(f=>f.id===fid);return f?`<blockquote>${esc(f.text)}</blockquote><p>Aporte de ${esc(f.author)} · ${esc(f.observed_at)}</p>`:'<p>El aporte anterior se conserva en el historial.</p>';}).join('')}`;
        return;
      }
      if(row.stale&&action!=='open'){
        body.innerHTML='<section class="pending-task-context"><h3>Actualizando los respaldos</h3><p>Las fuentes cambiaron. Espera a que termine la preparación y vuelve a consultar este punto. Tu explicación se conserva en este panel.</p><button type="button" id="pending-reload">Consultar de nuevo</button><button type="button" id="pending-back">Volver a respuestas</button></section>';
        body.querySelector('#pending-reload').onclick=()=>decide(requestId,pendingId,action);body.querySelector('#pending-back').onclick=close;return;
      }
      if(!isOpen(p)&&!['detail','open'].includes(action)){await savedDecision(row,p.resolution.action);return;}
      if(action==='document_choice'){
        const source=documentTarget(row,p);if(!source)throw new Error('Consulta las fuentes para identificar la versión correcta.');
        body.innerHTML=`<section class="pending-task-context"><h3>${esc(p.description)}</h3><p>Abre el archivo y elige la opción que pudiste comprobar.</p><a target="_blank" rel="noopener" href="/api/sources/${encodeURIComponent(source.source_id)}/original?case_id=${id}">Abrir ${esc(source.title)} ↗</a><div class="scope-actions">${source.document_status!=='draft'&&!/\bXXX+/i.test(source.title)?'<button id="pending-issued">Es la versión expedida</button>':''}<button id="pending-draft">Es un documento de trabajo</button><button id="pending-back">Volver sin decidir</button></div></section>`;
        body.querySelector('#pending-issued')?.addEventListener('click',()=>decide(requestId,pendingId,'issued'));body.querySelector('#pending-draft').onclick=()=>decide(requestId,pendingId,'draft');body.querySelector('#pending-back').onclick=close;return;
      }
      if(quick){
        const view=documentDecisionForm(row,p,action,actor);body.innerHTML=view.html;
        const form=document.querySelector('#pending-decision-form');
        form.querySelector('#pending-error').insertAdjacentHTML('afterend','<button type="button" class="text-button" id="pending-reload" hidden>Consultar el punto actualizado</button>');
        form.querySelector('#pending-reload').onclick=()=>decide(requestId,pendingId,action);
        bind(form,async()=>{
          if(getCase()?.id!==id)throw new Error('Cambió el expediente abierto.');
          const name=form.querySelector('#pending-actor').value.trim();
          if(!name)throw new Error('Indica tu nombre para registrar la decisión.');
          const saved=await api(prefix(id)+`/requests/${encodeURIComponent(requestId)}`,{
            revision:row.revision,edited_by:name,paragraphs:row.paragraphs,
            pending_resolutions:[{pending_id:pendingId,action:'resolved',document_decision:action,document_source_id:view.source.source_id}]
          },'PUT');
          actor=name;await savedDecision(saved,action);
        });
        form.querySelector('a')?.focus({preventScroll:true});return;
      }
      const view=decisionForm(row,p,action,actor);body.innerHTML=view.html;
      const form=document.querySelector('#pending-decision-form');
      form.querySelector('#pending-error').insertAdjacentHTML('afterend','<button type="button" class="text-button" id="pending-reload" hidden>Consultar el punto actualizado</button>');
      form.querySelector('#pending-reload').onclick=()=>decide(requestId,pendingId,action);
      bindSupportPicker(form);
      const key=draftKey(id,requestId,pendingId,action),draft=drafts.get(key);
      if(draft){const note=form.querySelector('#pending-note');if(note)note.value=draft.note;const choice=[...form.querySelectorAll('[name="pending-support"]')].find(input=>input.value===draft.choice);if(choice){choice.checked=true;choice.dispatchEvent(new Event('change',{bubbles:true}));}}
      const remember=()=>drafts.set(key,{note:form.querySelector('#pending-note')?.value||'',choice:form.querySelector('input[name="pending-support"]:checked')?.value||''});
      form.addEventListener('input',remember);form.addEventListener('change',remember);
      const returnToPoint=()=>getCase()?.id===id?decide(requestId,pendingId,action):undefined;
      form.querySelector('#pending-upload')?.addEventListener('click',()=>{remember();upload(requestId,{description:p.description,onCancel:returnToPoint,onUploaded:returnToPoint});});
      form.querySelector('#pending-not-applicable')?.addEventListener('click',()=>{remember();decide(requestId,pendingId,'not_applicable');});
      form.querySelector('#pending-fact')?.addEventListener('click',()=>contribute(row,pendingId));
      bind(form,async()=>{
        if(getCase()?.id!==id)throw new Error('Cambió el expediente abierto.');
        const name=form.querySelector('#pending-actor').value.trim(),note=form.querySelector('#pending-note')?.value.trim()||'';
        if(!name||(action!=='open'&&!note))throw new Error('Completa tu nombre y la explicación de la decisión.');
        const choice=form.querySelector('input[name="pending-support"]:checked')?.value||'';
        if(action==='resolved'&&!view.options.some(o=>o.value===choice))throw new Error('Selecciona el respaldo que revisaste.');
        const resolution={pending_id:pendingId,action,note,cited_chunk_ids:choice.startsWith('source:')?[choice.slice(7)]:[],cited_fact_ids:choice.startsWith('fact:')?[choice.slice(5)]:[]};
        const saved=await api(prefix(id)+`/requests/${encodeURIComponent(requestId)}`,{revision:row.revision,edited_by:name,paragraphs:row.paragraphs,pending_resolutions:[resolution]},'PUT');
        actor=name;drafts.delete(key);await savedDecision(saved,action);
      });
      body.scrollTop=0;form.querySelector('#pending-upload,textarea,input')?.focus({preventScroll:true});
    }catch(e){if(marker.isConnected)body.innerHTML=`<p role="alert">${esc(e.message)}</p>`;else notice(e.message);}
  }
  function contribute(row,pendingId) {
    open('Aportar información comprobada',factForm(actor));
    const form=document.querySelector('#pending-fact-form');
    bind(form,async values=>{
      if(getCase()?.id!==row.case_id)throw new Error('Cambió el expediente abierto.');
      const input=Object.fromEntries(values);input.revision=row.revision;
      const saved=await api(prefix(row.case_id)+`/requests/${encodeURIComponent(row.request_id)}/facts`,input);
      actor=input.author;await onSaved(saved);notice('Aporte guardado. Selecciónalo como respaldo para confirmar el punto.');
      if(form.isConnected)await decide(row.request_id,pendingId,'resolved');
    });
  }
  async function history(requestId) {
    const id=getCase()?.id;if(!id)return;
    open('Historial de decisiones','<p id="pending-history-loading">Cargando historial…</p>');
    const marker=document.querySelector('#pending-history-loading');
    try {
      const data=await api(prefix(id)+`/requests/${encodeURIComponent(requestId)}/history`);
      if(!marker.isConnected)return;
      const entries=(data.revisions||[]).filter(e=>['edited','synchronized'].includes(e.event));
      marker.outerHTML=entries.length?entries.map(e=>`<section class="source"><strong>Revisión ${e.revision}</strong><p>${esc(e.actor||'Actualización de fuentes')} · ${esc(when(e.created_at))}</p>${(e.body?.pending||[]).map(p=>`<p>${esc(p.description)}<br><strong>${p.resolution?p.resolution.action==='not_applicable'?'No aplica':'Confirmado':'Abierto'}</strong> ${esc(p.resolution?.note||'')}</p>`).join('')}</section>`).join(''):'<p>No hay decisiones anteriores registradas.</p>';
    }catch(e){if(marker.isConnected)marker.textContent=e.message;}
  }
  return {decide,history};
}
