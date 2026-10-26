import {esc} from './views.js';
import {icon} from './inbox-icons.js';
import {initialReady,identificationDetails} from './initial-review.js?v=reading-space1';
import {identificationProgress} from './stage-progress.js?v=stage-progress1';

export const expedienteStages=['Preanálisis','Identificación','Redacción','Borrador'];

export function expedienteSteps(stage,{reviewing=false,canContinue=false,redactionComplete=false,draftComplete=false,activeLabel='',navigation}={}){
  return `<ol class="expediente-steps" aria-label="Etapas del expediente">${expedienteStages.map((name,i)=>{
    const active=i===stage,generated=i===3&&draftComplete&&(active||navigation);
    const done=(navigation?Boolean(navigation.completed?.[i]):i<stage&&(i!==2||redactionComplete))||generated;
    const label=generated?'Versión generada':active?activeLabel||(stage===3?'En revisión':reviewing?'Tu revisión':'En curso'):i===2&&stage===3?(redactionComplete?'Preparada':'Por completar'):done?'Completado':navigation?.labels?.[i]||'Pendiente';
    const action=['live-preanalysis','live-identification','live-responses','live-final'][i];
    const available=navigation?Boolean(navigation.available?.[i]):i===0?stage>0:i===1||canContinue;
    return `<li class="${done?'complete':active?'current':''} stage-${i}" ${active?'aria-current="step"':''}><${available?'button':'div'} ${available?`type="button" data-action="${action}"`:''} class="expediente-stage"><span class="expediente-step-number">${done?icon('check'):i+1}</span><span><strong>${name}</strong><small>${esc(label)}</small></span></${available?'button':'div'}></li>`;
  }).join('')}</ol>`;
}

export function expedienteHeading(current,stage,{title='',subtitle='',status='',tone='review',reviewing=false,canContinue=false,showMail=false,redactionComplete=false,draftComplete=false,activeLabel='',navigation}={}){
  const owner=current.management?.owner_name||'Sin asignar';
  const reference=current.management?.reference||current.case_number||current.internal_number||`PQRS-${current.id.slice(0,12).toUpperCase()}`;
  return `<div class="expediente-heading"><button type="button" class="text-button expediente-back" data-action="live-queue">${icon('arrow-left')}Volver a la bandeja</button>${title?`<h1>${esc(title)}</h1><p class="expediente-subtitle">${esc(subtitle)}</p>`:''}<div class="expediente-meta"><span class="expediente-file">${icon('file')}<span>${esc(reference)} <span class="muted">· ${esc(current.filename)}</span></span></span><span class="expediente-owner"><span class="inbox-avatar">${esc(owner.slice(0,1).toUpperCase())}</span>${esc(owner)}</span>${status?`<span class="expediente-status ${tone}">${esc(status)}</span>`:''}${showMail?`<button type="button" class="text-button expediente-mail" data-action="live-mail-origin">${icon('mail')}Correos</button>`:''}</div>${expedienteSteps(stage,{reviewing,canContinue,redactionComplete,draftComplete,activeLabel,navigation})}</div>`;
}

export function identificationState(current,initial){
  if(current.error)return {tone:'error',label:'Requiere atención',text:current.error,action:'live-analyze',actionLabel:'Reintentar identificación'};
  if(current.analysis_running||['reading','identifying'].includes(current.status))return {tone:'processing',label:'Identificando',text:current.status==='reading'?'Leyendo el documento para identificar sus peticiones.':'Identificando las peticiones y sus fragmentos de origen.'};
  if(!current.identification)return {tone:'processing',label:'Identificando',text:current.status==='reading'?'Leyendo el documento para identificar sus peticiones.':'Identificando las peticiones y sus fragmentos de origen.'};
  if(initial.status==='running')return {tone:'processing',label:'Identificando',text:initial.analysis_scope==='petition_types_v1'?'Clasificando las peticiones a partir del documento original. Las fuentes se consultarán en Redacción.':'Analizando el contenido y el tipo de cada petición.'};
  if(initial.error||initial.status==='interrupted')return {tone:'error',label:'Identificación incompleta',text:initial.error||'La identificación se interrumpió. Se conserva el avance.',action:'live-initial-analyze',actionLabel:'Reintentar pendientes'};
  if(initial.stale||initial.legacy_report)return {tone:'review',label:'Por actualizar',text:'El expediente cambió. Actualiza la identificación antes de confirmar.',action:'live-initial-analyze',actionLabel:'Actualizar identificación'};
  if(initial.status==='idle')return {tone:'review',label:'Identificación guardada',text:'Las peticiones identificadas se conservan. La revisión de contenido y tipo del flujo actual aún no está registrada; completarla no vuelve a extraer las peticiones.',action:'live-initial-analyze',actionLabel:'Revisar contenido y tipos'};
  if(initialReady(initial))return {tone:initial.can_prepare?'complete':'review',label:initial.can_prepare?'Revisión guardada':'Por revisar',text:''};
  if(initial.loadError)return {tone:'error',label:'No se pudo cargar la revisión',text:initial.loadError,action:'live-refresh',actionLabel:'Volver a cargar'};
  return {tone:'loading',label:'Cargando revisión guardada',text:'Recuperando los resultados guardados. No se está iniciando una nueva identificación.'};
}

function documentViewer(data,state){
  const pages=data.original_pages||[],page=pages.find(p=>p.number===(state.originalPage||1))||pages[0];
  const selected=data.requests[state.originalSelection],marks=selected?.original_marks?.filter(m=>m.page===page?.number)||[];
  const number=page?.number||1,zoom=state.originalZoom||100;
  return `<section id="original-pane" class="original-viewer expediente-document" aria-labelledby="original-title"><div class="original-head"><h2 id="original-title" tabindex="-1">Documento original</h2><a href="${esc(data.original_url)}" target="_blank" rel="noopener">Abrir PDF ${icon('external-link')}</a></div><div class="original-tools"><label>Página <select id="original-page" aria-label="Página del documento original">${(pages.length?pages:[{number:1}]).map(p=>`<option value="${p.number}" ${p.number===number?'selected':''}>${p.number}</option>`).join('')}</select> de ${pages.length||'…'}</label><div class="expediente-zoom"><button type="button" data-original-zoom="-25" aria-label="Reducir documento" ${zoom<=75?'disabled':''}>${icon('minus')}</button><output>${zoom}%</output><button type="button" data-original-zoom="25" aria-label="Ampliar documento" ${zoom>=200?'disabled':''}>${icon('plus')}</button></div></div><p id="original-selection" class="sr-only" role="status">${selected?esc(selected.title):'Selecciona Ver origen en una petición para resaltar su fragmento.'}</p><div class="original-scroll" tabindex="0" aria-label="Documento original; desplázate para leerlo"><div class="original-sheet" style="--document-zoom:${zoom/100}"><img id="original-image" src="${esc(page?.image||`/api/cases/${encodeURIComponent(data.id)}/pages/1.png`)}" alt="Página ${number} del documento original">${marks.flatMap(m=>m.rectangles.map(r=>`<span class="expediente-source-mark quote-mark" style="left:${r[0]/page.width*100}%;top:${r[1]/page.height*100}%;width:${(r[2]-r[0])/page.width*100}%;height:${(r[3]-r[1])/page.height*100}%" aria-hidden="true"></span>`)).join('')}</div></div>${selected?`<div class="expediente-source-caption"><span>Origen · petición ${esc(selected.label)}</span><button class="text-button" type="button" data-action="clear-original">Quitar resaltado</button></div><details class="original-quote"><summary>Leer fragmento de origen</summary><p>${esc(marks.map(m=>m.quote).join('\n'))}</p></details>`:''}</section>`;
}

export function identificationWorkspace(data,state,{initial={},draft=null,requestContent={},confirmation='',banner='',showMail=false,canContinue=false,navigation}={}){
  const progress=identificationState(data,initial),ready=initialReady(initial)&&!['processing','error'].includes(progress.tone),closed=data.management?.state==='closed';
  const count=data.requests.length,validDraft=draft?.case_id===data.id&&draft.revision===initial.revision?draft:null;
  const status=progress.text?`<div class="expediente-progress ${progress.tone}" role="${progress.tone==='error'?'alert':'status'}">${progress.tone==='processing'?'<span class="source-spinner" aria-hidden="true"></span>':icon('info')}<div><strong>${progress.tone==='processing'?'Identificación en curso':esc(progress.label)}</strong><p>${esc(progress.text)}</p>${progress.action&&!closed?`<button type="button" data-action="${progress.action}">${progress.actionLabel}</button>`:''}</div></div>`:'';
  const summary=initial.report?.document&&!initial.legacy_report?`<details id="initial-review-details" class="expediente-summary" data-initial-disclosure="review"><summary id="intake-summary-title">${icon(ready?'check':'info')}<strong>Resumen de identificación</strong><span class="expediente-summary-state">${ready?'Completa':'Por actualizar'}</span>${icon('chevron-down')}</summary><div class="expediente-summary-content">${identificationDetails(data,initial,validDraft)}</div></details>`:'';
  const cards=data.requests.map((r,i)=>{
    const content=requestContent[r.id]||{};
    const editable=!closed&&data.status==='needs_review'&&initial.status!=='running';
    return `<article class="expediente-petition ${state.originalSelection===i?'selected':''}" id="identified-${i}" aria-labelledby="petition-title-${i}"><div class="expediente-petition-heading"><span class="expediente-number">${i+1}</span><h3 id="petition-title-${i}">${esc(r.title)}</h3><span class="expediente-petition-state ${progress.tone}">${ready?initial.can_prepare&&!validDraft?'Revisión guardada':'Por revisar':progress.tone==='processing'?'En curso':progress.tone==='loading'?'Cargando revisión':'Por verificar'}</span></div>${content.header||(progress.tone==='loading'?'<p class="muted">Cargando el tipo de petición guardado…</p>':'<p class="muted">Tipo de petición pendiente de identificar.</p>')}${content.route||''}<p class="expediente-description">${esc(r.description)}</p><button type="button" class="text-button expediente-source" data-action="original" data-index="${i}" aria-pressed="${state.originalSelection===i}" aria-controls="original-selection">${icon('file')}Ver origen · página ${r.source_refs?.[0]?.page||1}</button>${content.notes||''}${content.details||''}${editable?`<details class="expediente-corrections"><summary>Corregir petición</summary><button type="button" data-action="live-correct" data-index="${i}">Editar petición</button><button type="button" data-action="live-discard" data-index="${i}">No es una petición</button></details>`:''}</article>`;
  }).join('');
  const footer=ready&&confirmation||`<div class="expediente-waiting"><p>${closed?'Expediente finalizado. Consulta disponible.':'El avance se guarda. La revisión conjunta estará disponible al terminar la identificación.'}</p><button type="button" class="text-button" data-action="live-queue">Volver a la bandeja</button></div>`;
  return `<section class="expediente-workspace">${expedienteHeading(data,1,{title:'Identificación de peticiones',subtitle:'Revisa las peticiones, su tipo y el contenido identificado.',status:progress.label,tone:progress.tone,reviewing:ready,canContinue,showMail,navigation})}${identificationProgress(data,initial,navigation)}<div class="expediente-columns"><section class="expediente-petitions" aria-labelledby="petitions-title"><div class="expediente-list-heading"><h2 id="petitions-title">Peticiones identificadas</h2><p>${count?`${count} ${count===1?'petición':'peticiones'}`:'La identificación está en curso'}</p></div><div id="requests-pane" class="expediente-list" tabindex="0" role="region" aria-label="Peticiones identificadas; desplazamiento vertical">${summary}${status}${banner}${cards||'<p class="expediente-empty">Las peticiones aparecerán aquí cuando se identifiquen. Puedes consultar el documento mientras tanto.</p>'}</div></section>${documentViewer(data,state)}</div>${footer}</section>`;
}

const positions=new Map();
export function bindIdentificationWorkspace(view,current,state){
  const root=view.querySelector('.expediente-workspace');if(!root)return ()=>{};
  const list=root.querySelector('#requests-pane'),pdf=root.querySelector('.original-scroll'),previous=positions.get(current.id);
  if(previous){list.scrollTop=previous.list;pdf.scrollTop=previous.pdf;pdf.scrollLeft=previous.pdfLeft;}
  for(const control of root.querySelectorAll('[data-original-zoom]'))control.addEventListener('click',()=>{
    state.originalZoom=Math.min(200,Math.max(75,(state.originalZoom||100)+Number(control.dataset.originalZoom)));
    root.querySelector('.original-sheet').style.setProperty('--document-zoom',state.originalZoom/100);
    root.querySelector('.expediente-zoom output').textContent=state.originalZoom+'%';
    root.querySelector('[data-original-zoom="-25"]').disabled=state.originalZoom<=75;
    root.querySelector('[data-original-zoom="25"]').disabled=state.originalZoom>=200;
  });
  return ()=>positions.set(current.id,{list:list.scrollTop,pdf:pdf.scrollTop,pdfLeft:pdf.scrollLeft});
}
