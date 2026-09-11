import {esc} from './views.js';
import {createOffice} from '/shared/office.js';

const labels={editing:'Por comprobar',checking:'Comprobando…',ready:'Lista para aprobar',approved:'Aprobada',needs_changes:'Revisar observaciones',needs_evidence:'Revisar respaldo',stale:'Actualizar fuentes',error:'Error de comprobación'};
export function createFinal({getCase,getReview,hasChanges,open,close,notice,refresh,render,isVisible,back}){
  let actor='';
  async function api(url,options){
    const response=await fetch(url,{...options,headers:{'Content-Type':'application/json',...options?.headers}});
    const value=await response.json();
    if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'Revisa los campos y vuelve a intentarlo.');
    return value;
  }
  const office=createOffice({api,notify:notice,getCase,hasReviewChanges:hasChanges,render:()=>{if(isVisible())render();},back});
  function view(){
    const rows=getReview().requests||[],current=getCase();
    const node=document.createElement('section');node.className='live-final';
    const approved=rows.filter(r=>r.status==='approved'&&!r.stale).length;
    node.innerHTML=`<p class="eyebrow">PASO 3 · OFICIO</p><h1>Revisar y preparar el oficio</h1><p class="muted">Comprueba las respuestas y aprueba su contenido. El documento conservará exactamente esa redacción.</p>
      <section class="final-review"><h2>${approved} de ${current.request_count} respuestas aprobadas</h2>
      ${hasChanges(current.id)?'<p class="alert">Tienes texto sin guardar. Vuelve a «Editar respuesta» para guardarlo o descartarlo antes de aprobar y generar.</p>':''}
      ${rows.map((r,i)=>`<article class="final-row"><div><strong>${esc(r.label)}. ${esc(r.title)}</strong><span class="status ${r.status==='approved'?'':'warn'}">${esc(labels[r.stale?'stale':r.status]||'Por revisar')}</span></div>
        <details><summary>Leer respuesta${r.assessment?.issues?.length?' y observaciones':''}</summary>${r.paragraphs.map(p=>`<p>${esc(p.text)}</p>`).join('')}${r.assessment?.issues?.length?`<ul>${r.assessment.issues.map(x=>`<li>${esc(x.description)}</li>`).join('')}</ul>`:''}${r.error?`<p role="alert">${esc(r.error)}</p>`:''}</details>
        <div class="card-footer"><button data-final="back">Volver a las respuestas</button>${!r.stale&&r.status!=='approved'&&r.status!=='checking'?`<button data-final="${r.status==='ready'?'approve':'assess'}" data-request="${esc(r.request_id)}" ${hasChanges(current.id)?'disabled':''}>${r.status==='ready'?'Revisar y aprobar':'Comprobar respuesta'}</button>`:''}</div></article>`).join('')||'<p>Las respuestas aparecerán al terminar la preparación.</p>'}</section>`;
    if(approved===current.request_count&&approved){
      const section=node.querySelector('.final-review'),details=document.createElement('details'),summary=document.createElement('summary');
      summary.textContent=`${approved} respuestas aprobadas · consultar`;details.className='final-review';
      section.querySelector('h2').remove();details.append(summary,...section.childNodes);section.replaceWith(details);
    }
    if(office.state?.data&&(office.state.data.eligible||(approved===current.request_count&&approved)))node.append(office.view());
    else if(approved===current.request_count&&approved)node.insertAdjacentHTML('beforeend',`<p role="status">${esc(office.state?.error||'Consultando el estado del oficio…')}</p><button data-final="load">Actualizar estado del oficio</button>`);
    else node.insertAdjacentHTML('beforeend','<p>Los datos del oficio y las descargas aparecerán aquí cuando las respuestas estén aprobadas.</p>');
    node.querySelectorAll('[data-final]').forEach(b=>b.onclick=async()=>{
      if(b.dataset.final==='back'){back();return;}
      b.disabled=true;
      try{
        if(b.dataset.final==='load'){await load();return;}
        if(hasChanges(current.id))throw new Error('Guarda o descarta tu edición local antes de continuar.');
        const latest=await api(`/api/cases/${current.id}/review`),row=latest.requests.find(r=>r.request_id===b.dataset.request);
        if(getCase()?.id!==current.id)return;
        if(b.dataset.final==='assess'){
          await api(`/api/cases/${current.id}/review/requests/${encodeURIComponent(row.request_id)}/assess`,{method:'POST',body:JSON.stringify({revision:row.revision})});
          await refresh();
        }else approve(current,row);
      }catch(e){notice(e.message);}finally{b.disabled=false;}
    });
    return node;
  }
  function approve(current,row){
    open('Aprobar respuesta',`<form id="final-approve"><h3>${esc(row.label)}. ${esc(row.title)}</h3>${row.paragraphs.map(p=>`<p>${esc(p.text)}</p>`).join('')}<label class="field">Tu nombre<input name="actor" required maxlength="240" value="${esc(actor)}"></label><label class="check"><input type="checkbox" name="confirmed" required>He revisado esta respuesta y apruebo su contenido para el oficio.</label><p id="final-approve-error" role="alert"></p><button class="primary" type="submit">Aprobar esta respuesta</button></form>`);
    const form=document.querySelector('#final-approve');
    form.onsubmit=async event=>{
      event.preventDefault();const button=form.querySelector('button');if(button.disabled)return;button.disabled=true;
      try{
        if(getCase()?.id!==current.id||hasChanges(current.id))throw new Error('El expediente o la edición cambiaron. Revisa la versión guardada.');
        const fields=new FormData(form);actor=String(fields.get('actor')).trim();
        await api(`/api/cases/${current.id}/review/requests/${encodeURIComponent(row.request_id)}/approve`,{method:'POST',body:JSON.stringify({revision:row.revision,assessment_hash:row.assessment?.input_hash,approved_by:actor,note:'',confirmed:fields.has('confirmed')})});
        if(form.isConnected)close();await refresh();await load();notice('Respuesta aprobada.');
      }catch(e){if(form.isConnected)form.querySelector('#final-approve-error').textContent=e.message;}finally{button.disabled=false;}
    };
  }
  async function load(){office.setCase(getCase());await office.load();}
  return {view,load,setCase:()=>office.setCase(getCase())};
}
