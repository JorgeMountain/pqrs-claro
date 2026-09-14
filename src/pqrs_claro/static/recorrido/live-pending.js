import {bindActor} from './session-actor.js';
import {esc} from './views.js';
import {decisionForm,factForm,when} from './live-pending-view.js?v=20260911-document-decisions';
import {documentDecisionForm} from './document-decision.js';

export function createPendingActions({open,close,notice,getCase,onSaved,upload}) {
  let actor='';
  async function api(url,body,method='POST') {
    const response=await fetch(url,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const value=await response.json();
    if(!response.ok)throw new Error(response.status===409?'El expediente cambió. Tu información sigue en el panel; vuelve a consultar el punto antes de guardar.':typeof value.detail==='string'?value.detail:'Revisa los campos. No se pudo guardar.');
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
    bindActor(form);
    let saving=false;
    form.querySelector('#pending-cancel').onclick=close;
    form.onsubmit=async event=>{
      event.preventDefault();if(saving)return;saving=true;
      const error=form.querySelector('#pending-error');error.textContent='';
      const values=new FormData(form);
      form.querySelectorAll('button').forEach(b=>b.disabled=true);
      try {await work(values);}catch(e){if(form.isConnected){error.textContent=e.message;form.querySelectorAll('button').forEach(b=>b.disabled=false);}}finally{saving=false;}
    };
  }
  async function decide(requestId,pendingId,action) {
    const quick=['issued','draft','provenance_reviewed'].includes(action);
    if(!quick&&!['resolved','not_applicable','open','detail'].includes(action))return;
    const id=getCase()?.id;if(!id)return;
    open('Decisión sobre este punto','<p id="pending-loading" role="status">Cargando el punto y sus soportes…</p>');
    const marker=document.querySelector('#pending-loading'),body=document.querySelector('#drawer-body');
    try {
      const row=await rowFor(id,requestId);if(!marker.isConnected||getCase()?.id!==id)return;
      const p=row.pending.find(p=>p.id===pendingId);if(!p)throw new Error('El pendiente cambió. Actualiza la respuesta.');
      if(action==='detail'){
        const r=p.resolution;
        if(!r)throw new Error('La decisión fue reabierta. Actualiza la respuesta.');
        body.innerHTML=`<p><strong>${esc(p.description)}</strong></p><p>${esc(r.note)}</p><p>${esc(r.by)} · ${esc(when(r.at))}</p>${(r.cited_chunk_ids||[]).map(chunk=>{const s=row.available_supports.find(s=>s.chunk_id===chunk);return s?`<section class="source"><strong>${esc(s.title)} · versión ${esc(s.version)}</strong><blockquote>${esc(s.quote)}</blockquote><a target="_blank" rel="noopener" href="/api/sources/${encodeURIComponent(s.source_id)}/original?case_id=${id}">Abrir documento original ↗</a></section>`:'<p>El pasaje anterior ya no está disponible en las fuentes vigentes. Consulta el historial.</p>';}).join('')}${(r.cited_fact_ids||[]).map(fid=>{const f=row.facts.find(f=>f.id===fid);return f?`<blockquote>${esc(f.text)}</blockquote><p>Aporte de ${esc(f.author)} · ${esc(f.observed_at)}</p>`:'<p>El aporte anterior se conserva en el historial.</p>';}).join('')}`;
        return;
      }
      if(row.stale&&action!=='open')throw new Error('Actualiza las fuentes de esta respuesta antes de registrar una decisión.');
      if(quick){
        const view=documentDecisionForm(row,p,action,actor);body.innerHTML=view.html;
        const form=document.querySelector('#pending-decision-form');
        bind(form,async()=>{
          if(getCase()?.id!==id)throw new Error('Cambió el expediente abierto.');
          const name=form.querySelector('#pending-actor').value.trim();
          if(!name)throw new Error('Indica tu nombre para registrar la decisión.');
          const saved=await api(prefix(id)+`/requests/${encodeURIComponent(requestId)}`,{
            revision:row.revision,edited_by:name,paragraphs:row.paragraphs,
            pending_resolutions:[{pending_id:pendingId,action:'resolved',document_decision:action,document_source_id:view.source.source_id}]
          },'PUT');
          actor=name;if(form.isConnected)close();await onSaved(saved);notice('Decisión documental guardada. Se conserva el alcance de esta versión.');
        });
        form.querySelector(actor?'button[type="submit"]':'input')?.focus();return;
      }
      const view=decisionForm(row,p,action,actor);body.innerHTML=view.html;
      const form=document.querySelector('#pending-decision-form');
      const select=form.querySelector('#pending-support');
      if(select)select.onchange=()=>{const quote=form.querySelector('#pending-quote');quote.textContent=view.options.find(o=>o.value===select.value)?.text||'';quote.hidden=!quote.textContent;};
      form.querySelector('#pending-upload')?.addEventListener('click',()=>upload(requestId));
      form.querySelector('#pending-fact')?.addEventListener('click',()=>contribute(row,pendingId));
      bind(form,async()=>{
        if(getCase()?.id!==id)throw new Error('Cambió el expediente abierto.');
        const name=form.querySelector('#pending-actor').value.trim(),note=form.querySelector('#pending-note')?.value.trim()||'';
        if(!name||(action!=='open'&&!note))throw new Error('Completa tu nombre y la explicación de la decisión.');
        const choice=select?.value||'';
        if(action==='resolved'&&!view.options.some(o=>o.value===choice))throw new Error('Selecciona el respaldo que revisaste.');
        const resolution={pending_id:pendingId,action,note,cited_chunk_ids:choice.startsWith('source:')?[choice.slice(7)]:[],cited_fact_ids:choice.startsWith('fact:')?[choice.slice(5)]:[]};
        const saved=await api(prefix(id)+`/requests/${encodeURIComponent(requestId)}`,{revision:row.revision,edited_by:name,paragraphs:row.paragraphs,pending_resolutions:[resolution]},'PUT');
        actor=name;if(form.isConnected)close();await onSaved(saved);
        notice(action==='open'?'Punto reabierto.':'Decisión guardada. Revisa su aplicación a la respuesta.');
      });
      form.querySelector('select,textarea,input')?.focus();
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
