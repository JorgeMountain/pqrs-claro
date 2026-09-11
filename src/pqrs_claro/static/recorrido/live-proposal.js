import {esc} from './views.js';

export function createProposalPanel({open,close,notice,getCase,onSaved}) {
  let actor='';
  async function api(url,body) {
    const response=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const value=await response.json();
    if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'No se pudo completar la operación. Tu respuesta se conserva.');
    return value;
  }
  async function show(requestId) {
    const caseId=getCase()?.id;if(!caseId)return;
    const reviewUrl=`/api/cases/${caseId}/review`;
    const url=reviewUrl+`/requests/${encodeURIComponent(requestId)}/proposals`;
    open('Actualizar respuesta con IA','<div id="proposal-panel"><p role="status">Consultando la propuesta guardada…</p></div>');
    const panel=document.querySelector('#proposal-panel');let job,working=false;
    const active=()=>panel.isConnected&&document.querySelector('#drawer').open&&getCase()?.id===caseId;
    const paragraphs=rows=>(rows||[]).map(p=>`<p>${esc(p.text)}</p>`).join('');
    function render(){
      if(!active())return;
      if(job.status==='running')panel.innerHTML=`<p role="status">${job.stage==='checking'?'Comprobando la propuesta y sus soportes…':'Preparando un ajuste con las decisiones y el texto actuales…'}</p><progress aria-label="Actualización de respuesta"></progress><p>Tu respuesta guardada permanece intacta. Puedes cerrar este panel y volver después.</p>`;
      else if(job.status==='ready'){
        const issues=job.checks?.issues||[];
        panel.innerHTML=`<p>${esc(job.proposal.summary)}</p>${job.stale?'<p class="alert" role="alert">La respuesta o sus fuentes cambiaron. Esta propuesta corresponde a una versión anterior y no puede aplicarse.</p>':''}
          <div class="proposal-comparison"><section><h3>Texto actual al solicitar el ajuste</h3>${paragraphs(job.original)}</section><section><h3>Propuesta de la IA</h3>${paragraphs(job.proposal.paragraphs)}</section></div>
          ${issues.length?`<details open><summary>${issues.length} observaciones de la comprobación</summary><ul>${issues.map(i=>`<li>${esc(i.description)}</li>`).join('')}</ul></details>`:job.checks?.status==='passed'?'<p>La comprobación de la propuesta no registró observaciones.</p>':'<p>La comprobación requiere revisión. Aplicar esta propuesta no aprueba la respuesta.</p>'}
          <p>Revisa los cambios. Aplicarlos guarda una nueva versión para revisión; las decisiones registradas se conservan.</p>
          ${job.stale?'<button id="proposal-retry" class="primary">Solicitar una propuesta actualizada</button>':`<form id="proposal-apply"><label class="field">Tu nombre<input id="proposal-actor" required maxlength="240" value="${esc(actor)}"></label><button type="submit" class="primary">Aplicar propuesta</button></form>`}
          <button id="proposal-dismiss">Mantener mi texto y descartar propuesta</button><p id="proposal-error" role="alert"></p>`;
      }else panel.innerHTML=`<p>${esc(job.error||({idle:'Solicita una propuesta basada en la respuesta, los soportes y las decisiones guardadas.',dismissed:'Conservaste tu texto. La propuesta anterior quedó descartada.',applied:'La propuesta ya se aplicó a la respuesta.',interrupted:'La generación se interrumpió. Puedes solicitarla otra vez.'}[job.status]||'La propuesta no está disponible.'))}</p><button class="primary" id="proposal-retry">${job.status==='idle'?'Generar propuesta con IA':'Solicitar otra propuesta'}</button><p id="proposal-error" role="alert"></p>`;
      panel.querySelector('#proposal-retry')?.addEventListener('click',()=>act(generate));
      panel.querySelector('#proposal-dismiss')?.addEventListener('click',()=>act(async()=>{job=await api(url+`/${job.id}/dismiss`,{});notice('Se conserva tu respuesta.');}));
      panel.querySelector('#proposal-apply')?.addEventListener('submit',event=>{
        event.preventDefault();const name=panel.querySelector('#proposal-actor').value.trim();
        if(!name){panel.querySelector('#proposal-error').textContent='Escribe tu nombre para registrar quién aplica el cambio.';return;}
        act(async()=>{const saved=await api(url+`/${job.id}/apply`,{revision:job.base_revision,edited_by:name});actor=name;if(active())close();await onSaved(saved);notice('Propuesta aplicada. Revisa la nueva versión antes de aprobarla.');});
      });
    }
    async function generate(){
      const result=await api(reviewUrl),row=result.requests.find(r=>r.request_id===requestId);
      if(!active())return;
      if(!row||row.stale)throw new Error('Actualiza las fuentes de la respuesta antes de solicitar una propuesta.');
      job=await api(url,{revision:row.revision});
    }
    async function act(work){
      if(working||!active())return;working=true;
      panel.querySelectorAll('button').forEach(b=>b.disabled=true);
      try{await work();render();if(job.status==='running')schedule();}
      catch(e){if(active()){const error=panel.querySelector('#proposal-error');if(error)error.textContent=e.message;else notice(e.message);panel.querySelectorAll('button').forEach(b=>b.disabled=false);}}
      finally{working=false;}
    }
    function schedule(){setTimeout(async()=>{if(!active())return;try{job=await api(url);render();if(job.status==='running')schedule();}catch(e){if(active()){panel.innerHTML=`<p role="alert">${esc(e.message)}</p><p>Cierra y vuelve a abrir este panel para consultar el avance guardado.</p>`;}}},2000);}
    try{job=await api(url);render();if(job.status==='running')schedule();}
    catch(e){if(active())panel.innerHTML=`<p role="alert">${esc(e.message)}</p>`;}
  }
  return {show};
}
