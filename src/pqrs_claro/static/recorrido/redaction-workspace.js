import {esc} from './views.js';
import {icon} from './inbox-icons.js';
import {expedienteHeading} from './expediente-workspace.js?v=stage-progress1';
import {pendingCards,isLater,isOpen} from './live-pending-view.js?v=pending-guide1';
import {analysisErrorDetail,retryFailedAction} from './source-analysis-feedback.js';
import {stageProgress} from './stage-progress.js?v=stage-progress1';
import {responseReading} from './response-reading.js?v=reading-confirmation1';

const draftingLabels={planificar:'Organizando la respuesta',redactar:'Redactando',comprobar:'Comprobando la respuesta',ajustar_citas:'Ajustando citas',recomprobar:'Comprobando ajustes'};

function retrievalCoverage(mapping){
  const progress=mapping.retrieval_progress||{};
  const partial=progress.complete===false&&Number.isInteger(progress.pending)&&progress.pending>0&&(progress.budget_exhausted||progress.cancelled);
  if(!mapping.retrieval_warning&&!partial)return '';
  if(partial){
    const pending=progress.pending.toLocaleString('es-CO');
    const total=Number.isInteger(progress.total)&&progress.total>=progress.pending?` de ${progress.total.toLocaleString('es-CO')}`:'';
    return `<div class="redaction-pending-summary" role="status">${icon('info')}<div><p><strong>Búsqueda por significado con cobertura parcial</strong></p><p>La búsqueda por texto e identificadores conserva el alcance de las fuentes autorizadas.</p><details data-redaction-disclosure="retrieval-coverage"><summary>Ver alcance de la búsqueda</summary><p>Quedan ${pending}${total} fragmentos por preparar.</p><p>Se conservan los pasajes encontrados. No encontrar una coincidencia todavía no confirma que falte un documento.</p>${mapping.retrieval_warning?`<p>${esc(mapping.retrieval_warning)}</p>`:''}</details></div></div>`;
  }
  return `<div class="redaction-pending-summary" role="status">${icon('info')}<div><p><strong>Limitación de la búsqueda</strong></p><p>${esc(mapping.retrieval_warning)}</p><p>Los pasajes encontrados se conservan. Esta limitación no confirma ausencia documental.</p></div></div>`;
}

// A missing per-request state can mean the shared index is still being prepared.
// Only completed findings can establish that no supporting passages were selected.
function sourceProgress(request,job,mapping,finding){
  const state=mapping.request_states?.[request.id];
  if(!mapping.stale&&finding?.status==='error')return {phase:'error',message:finding.summary||'No se pudo completar la búsqueda de fuentes.'};
  if(!mapping.stale&&finding)return {phase:'complete',message:mapping.retrieval_warning?'No se seleccionaron pasajes de respaldo para esta petición. Revisa la limitación de búsqueda indicada; esto no confirma que falte un documento.':'Búsqueda terminada. No se seleccionaron pasajes de respaldo para esta petición.'};
  if(!mapping.stale&&mapping.status==='error')return {phase:'error',message:mapping.error||'No se pudo completar la búsqueda de fuentes. Puedes reintentar la preparación.'};
  if(job.stage==='sources'&&['error','interrupted'].includes(job.status))return {phase:'error',message:job.error||'La búsqueda de fuentes se interrumpió. Puedes continuar la preparación.'};
  if(mapping.status==='running'||job.status==='running'&&job.stage==='sources'){
    if(mapping.retrieval_progress?.phase==='indexing'){
      const {prepared,total}=mapping.retrieval_progress;
      const progress=Number.isInteger(prepared)&&prepared>=0?` ${prepared.toLocaleString('es-CO')}${Number.isInteger(total)&&total>=prepared?` de ${total.toLocaleString('es-CO')}`:''} fragmentos preparados.`:'';
      return {phase:'indexing',label:'Preparando índice',message:`Preparando el índice de fuentes.${progress} La búsqueda de esta petición aún no ha comenzado.`};
    }
    if(state==='searching')return {phase:'searching',label:'Buscando fuentes',message:'Buscando y evaluando respaldo para esta petición.'};
    if(state==='queued')return {phase:'queued',label:'Fuentes en espera',message:'Esta petición está en espera de un turno para buscar fuentes.'};
    return {phase:'preparing',label:'Preparando búsqueda',message:'Preparando la búsqueda en las fuentes del expediente.'};
  }
  if(job.status==='starting')return {phase:'preparing',label:'Preparando búsqueda',message:'Recuperando el expediente y preparando la búsqueda de fuentes.'};
  if(mapping.stale)return {phase:'stale',message:'Los pasajes guardados necesitan actualizarse antes de continuar.'};
  if(!mapping.status)return {phase:'loading',message:'Recuperando el estado de las fuentes…'};
  return {phase:'idle',message:'La búsqueda aún no tiene un resultado guardado para esta petición.'};
}

// These projections describe saved work; neither a source nor a finished draft is an approval.
export function redactionRows(current,job={},mapping={},drafts={},review={}){
  return (current.identification?.requests||[]).map((request,index)=>{
    const finding=mapping.results?.find(r=>r.request_id===request.id);
    const row=review.requests?.find(r=>r.request_id===request.id);
    const draft=drafts.results?.find(r=>r.request_id===request.id);
    const preview=Boolean(row?.pre_draft&&!row.paragraphs?.length&&draft?.draft?.paragraphs?.length);
    const paragraphs=preview?draft.draft.paragraphs:row?.paragraphs||draft?.draft?.paragraphs||[];
    const stale=Boolean(row?.stale||mapping.stale||drafts.stale||job.stale);
    const pending=preview?draft.draft.pending||[]:row&&!stale?(row.pending||[]).filter(isOpen):finding?.missing||[];
    const draftStep=drafts.status==='running'?drafts.request_states?.[request.id]:null;
    const draftActive=Boolean(draftStep&&!['queued','completed','error'].includes(draftStep));
    const source=sourceProgress(request,job,mapping,finding);
    const sourceActive=['preparing','indexing','searching'].includes(source.phase);
    const error=draft?.error||(source.phase==='error'?source.message:'');
    let tone='waiting',label='Por preparar',message='La respuesta está pendiente de preparación.';
    if(stale){tone='review';label='Por actualizar';message='El avance guardado se conserva. Actualiza las fuentes antes de continuar.';}
    else if(error){tone='error';label='Requiere atención';message=error;}
    else if(draftActive){tone='processing';label=draftingLabels[draftStep]||'Redactando';message='Estamos preparando la respuesta con el apoyo de las fuentes del expediente.';}
    else if(paragraphs.length){tone=row?.status==='approved'||review.reading_confirmation?.confirmed?'complete':'review';label=tone==='complete'?'Revisión guardada':'Por revisar';message='';}
    else if(pending.some(p=>!isLater(p))){tone='review';label='Revisar pendientes';message='Revisa los puntos necesarios para preparar esta respuesta.';}
    else if(sourceActive){tone='processing';label=source.label;message=source.message;}
    else if(source.phase==='queued'){label=source.label;message=source.message;}
    else if(draftStep==='queued'){message='La respuesta está en espera de un turno para redactarse.';}
    else if(job.status==='starting'){message='Recuperando el expediente y comprobando sus fuentes.';}
    else if(!['running','starting'].includes(job.status)){message='La respuesta aún no está disponible. Puedes continuar la preparación.';}
    return {request,index,finding,row,draft,paragraphs,pending,stale,tone,label,message,draftActive,sourceActive,source,preview};
  });
}

export function redactionProgress(job,rows,{historical=false,loadingSaved=false,navigation}={}){
  const total=rows.length,prepared=rows.filter(r=>r.paragraphs.length&&!r.stale&&!r.draft?.error).length;
  const active=rows.filter(r=>r.draftActive),sources=rows.filter(r=>r.sourceActive);
  const running=['running','starting'].includes(job.status);
  const shownCount=historical?rows.filter(r=>r.paragraphs.length).length:prepared;
  const sourceMessage=sources.some(r=>r.source.phase==='indexing')?'Preparando el índice de fuentes':sources.some(r=>r.source.phase==='preparing')?'Preparando la búsqueda de fuentes':'Buscando y evaluando respaldo en las fuentes';
  const message=job.status==='starting'?'Revisión guardada · Iniciando la preparación':active.length===1?`${active[0].label} la petición ${active[0].index+1}`:active.length>1?`Preparando ${active.length} peticiones`:sources.length||job.stage==='sources'&&running?sourceMessage:job.status==='waiting_review'?'Revisa los pendientes para continuar':job.status==='ready'?'Respuestas disponibles para tu revisión':running?'Preparando las respuestas':'Avance guardado';
  return stageProgress({stage:2,
    title:loadingSaved?'Recuperando las respuestas guardadas…':`${shownCount} de ${total} ${historical?(total===1?'respuesta guardada':'respuestas guardadas'):(total===1?'respuesta preparada':'respuestas preparadas')}`,
    message:historical?'Avance anterior conservado':message,count:loadingSaved?null:shownCount,total,
    running:running||loadingSaved,completed:navigation?.completed||(historical?[]:[true,true]),stageComplete:!historical&&!loadingSaved&&total>0&&prepared===total,
    warning:Boolean(job.error),historical});
}

function responseRow(item,selected){
  const {request:r,index:i,paragraphs,row,finding,tone,label,message,stale}=item;
  const count=new Set((finding?.supports||[]).map(s=>s.source_id)).size;
  const sourceLabel=`Ver fuentes${count||item.source.phase==='complete'?` (${count})`:''}`;
  const sourceButton=`<button type="button" class="redaction-sources-button" data-action="live-sources" data-index="${i}" aria-controls="redaction-context" aria-pressed="${selected}" aria-label="Ver fuentes de la petición ${i+1}" title="${sourceLabel}">${icon('book')}${paragraphs.length?sourceLabel:item.pending.some(p=>p.blocks_approval!==false)?'Resolver pendientes':''}</button>`;
  return `<details class="redaction-response ${selected?'selected':''}" data-response-id="${esc(r.id)}" id="request-${i}" open><summary><span class="redaction-number ${tone}">${i+1}</span><h3>${esc(r.title)}</h3><span class="redaction-state ${tone}">${tone==='processing'?'<span class="source-spinner" aria-hidden="true"></span>':''}${esc(label)}</span>${icon('chevron-down')}</summary><div class="redaction-response-body"><div class="redaction-question"><strong>Qué solicitó la persona</strong><p>${esc(r.description)}</p></div>${paragraphs.length?`<strong class="redaction-answer-label">Respuesta sugerida</strong><div class="redaction-answer">${paragraphs.map(p=>`<p>${esc(p.text)}</p>`).join('')}</div>${stale?`<p class="redaction-inline-note">${esc(message)}</p>`:''}`:`<p class="redaction-empty ${tone}" ${tone==='error'?'role="alert"':''}>${tone==='processing'?'<span class="source-spinner" aria-hidden="true"></span>':icon('info')}<span>${esc(message)}</span>${sourceButton}</p>`}${item.draft?.error&&paragraphs.length?`<p class="alert" role="alert">${esc(item.draft.error)}</p>`:''}${paragraphs.length?`<div class="redaction-row-actions">${row?.paragraphs?.length?`<button type="button" class="redaction-edit" data-action="live-edit" data-index="${i}">Editar respuesta</button>`:item.preview?'<button type="button" class="redaction-edit" disabled title="Disponible cuando termine de guardarse la preparación">Editar respuesta</button>':'<span></span>'}${sourceButton}</div>`:''}</div></details>`;
}

function contextPanel(current,item,mapping){
  if(!item)return '<section class="redaction-context redaction-panel"><h2>Fuentes y pendientes</h2><p>No hay peticiones identificadas en este expediente.</p></section>';
  const {request:r,index:i,finding,row,stale,pending}=item,supports=finding?.supports||[];
  const count=new Set(supports.map(s=>s.source_id)).size;
  const sourceTitle=`Fuentes de respaldo${count||item.source.phase==='complete'?` (${count})`:''}`;
  const sourceNotice=['preparing','indexing','searching','queued','loading'].includes(item.source.phase)?`${item.source.message} Los pasajes seleccionados aparecerán aquí al terminar.`:item.source.message;
  const original=`/api/cases/${encodeURIComponent(current.id)}/original`;
  return `<aside id="redaction-context" class="redaction-context redaction-panel" aria-labelledby="redaction-context-title" data-redaction-scroll="context"><div class="redaction-panel-heading"><h2 id="redaction-context-title" tabindex="-1">Fuentes y pendientes</h2><p>Información de apoyo para la petición seleccionada.</p></div><div class="redaction-context-body"><div class="redaction-context-request" role="status"><strong>Petición ${i+1} · ${esc(r.title)}</strong><p>Consulta las fuentes y revisa los pendientes antes de continuar.</p></div>${stale?'<p class="redaction-pending-summary">Las fuentes cambiaron. Estos resultados son anteriores y necesitan actualizarse.</p>':''}${pending.length&&!row?`<div class="redaction-pending-summary">${icon('info')}<div>${pending.map(p=>`<p><strong>${isLater(p)?'Actuación posterior':'Pendiente'}:</strong> ${esc(p.description)}</p>`).join('')}</div></div>`:item.sourceActive?`<p class="redaction-inline-note" role="status">${esc(item.source.message)}</p>`:!pending.length&&finding&&!stale&&finding.status!=='error'?'<p class="redaction-no-pending">Sin pendientes de evidencia registrados. Revisa el texto propuesto.</p>':''}${row?pendingCards({...row,stale},i):pending.length?'<p class="redaction-inline-note">Las decisiones se habilitan al terminar la búsqueda.</p>':''}${analysisErrorDetail(finding)}${finding?.analysis_notices?.length?`<details class="pending-disclosure"><summary>Detalle del análisis de citas</summary>${finding.analysis_notices.map(n=>`<p>${esc(n.message)}</p>`).join('')}</details>`:''}<div class="redaction-evidence"><h3>Agregar evidencia</h3><button type="button" class="redaction-upload" data-action="live-evidence" data-index="${i}" data-redaction-drop="${i}">${icon('file-up')}<span>Arrastra un archivo aquí o <u>selecciona un archivo</u></span></button></div><section class="redaction-sources" aria-label="Fuentes de la petición ${i+1}"><div class="redaction-sources-heading"><h3>${esc(sourceTitle)}</h3><button type="button" class="text-button" data-action="live-collections">Seleccionar fuentes</button></div>${retrievalCoverage(mapping)}${supports.map((s,sourceIndex)=>`<article class="redaction-source">${icon('file')}<div><h4>${esc(s.title)}</h4><p class="redaction-source-location">${s.location_kind==='section'?'Sección':'Página'} ${esc(s.page)} · Versión ${esc(s.version)}</p><blockquote>${esc(s.quote)}</blockquote><a href="/api/sources/${encodeURIComponent(s.source_id)}/original?case_id=${encodeURIComponent(current.id)}${s.location_kind!=='section'&&Number.isInteger(Number(s.page))?'#page='+Number(s.page):''}" target="_blank" rel="noopener">Ver documento fuente ${icon('external-link')}</a>${s.reason?`<details data-redaction-disclosure="${esc(r.id)}-source-${sourceIndex}"><summary>Por qué se consultó</summary><p>${esc(s.reason)}</p></details>`:''}</div></article>`).join('')||`<p class="redaction-inline-note" role="${item.source.phase==='error'?'alert':'status'}">${esc(sourceNotice)}</p>`}</section>${row?.paragraphs?.length?`<button type="button" class="text-button redaction-update" data-action="live-proposal" data-index="${i}">${icon('refresh')}Actualizar respuesta con IA</button>`:''}<div class="redaction-original"><h3>Documento original</h3><a href="${original}" target="_blank" rel="noopener">${icon('file')}<span>Ver documento · ${esc(current.filename)}</span>${icon('external-link')}</a></div><p class="redaction-human-note">${icon('info')}<span>Las respuestas son un apoyo para la gestión. La revisión y edición final la realiza el equipo antes del borrador.</span></p></div></aside>`;
}

export function redactionWorkspace(current,job={},mapping={},drafts={},review={},options={}){
  const rows=redactionRows(current,job,mapping,drafts,review);
  const selected=rows.find(r=>r.request.id===options.selectedRequest)||rows[0];
  const running=['running','starting'].includes(job.status),retry=retryFailedAction(mapping,running);
  const loadingSaved=current.saved_stage>=2&&!drafts.status&&!review.status&&!running;
  if(loadingSaved)for(const row of rows)if(!row.paragraphs.length&&row.tone==='waiting'){row.label='Cargando';row.message='Recuperando la respuesta guardada…';}
  const waiting=!job.stale&&!mapping.stale&&job.status==='waiting_review';
  const canResume=!running&&!retry&&!waiting&&(job.status!=='ready'||job.stale||mapping.stale);
  return `<section class="expediente-later redaction-workspace ${selected?.row?.pre_draft&&selected.pending.length?'pending-focus':''}">${expedienteHeading(current,2,{title:'Redacción de respuestas',subtitle:'Revisa las respuestas junto a sus fuentes.',canContinue:options.canContinue,navigation:options.navigation,showMail:options.showMail,reviewing:!running,activeLabel:loadingSaved?'Cargando avance':running?'En preparación':job.error?'Requiere atención':rows.some(r=>r.paragraphs.length)?'Tu revisión':'Por preparar'})}${redactionProgress(job,rows,{historical:options.initialPending,loadingSaved,navigation:options.navigation})}${options.initialPending?'<div class="redaction-resume"><span><strong>Avance anterior conservado.</strong> Puedes consultar las respuestas guardadas. La revisión de contenido y tipos del flujo actual aún no está registrada.</span><button type="button" data-action="live-identification">Revisar identificación</button></div>':''}${options.refreshError?`<div class="alert" role="alert">${esc(options.refreshError)} <button data-action="live-refresh">Actualizar estado</button></div>`:''}${job.error?`<div class="alert" role="alert">${esc(job.error)}</div>`:''}${retry}${canResume&&!loadingSaved&&!options.initialPending?`<div class="redaction-resume"><span>${job.status==='waiting_review'?'Resuelve los pendientes de cada petición para continuar.':'El avance guardado se conserva.'}</span><button type="button" data-action="live-resume">${job.status==='idle'?'Continuar preparación':'Actualizar preparación'}</button></div>`:''}<div class="redaction-columns"><section class="redaction-responses redaction-panel" aria-labelledby="redaction-list-title"><div class="redaction-panel-heading"><h2 id="redaction-list-title">Respuestas del expediente</h2><p>Revisa y edita cada respuesta con el apoyo de sus fuentes.</p></div><div class="redaction-list" data-redaction-scroll="responses" tabindex="0" aria-label="Respuestas del expediente; desplázate para leerlas">${rows.map(r=>responseRow(r,r===selected)).join('')||'<p class="redaction-inline-note">No hay peticiones identificadas.</p>'}</div></section>${contextPanel(current,selected,mapping)}</div>${responseReading(review,{reviewer:options.reviewer,busy:options.confirmingReading,error:options.readingError})}<div class="redaction-footer"><button type="button" class="text-button" data-action="live-queue">Guardar y volver a la bandeja</button><div><button type="button" class="primary" data-action="live-continue-draft"${review.reading_confirmation?.confirmed?'':' disabled'}>Continuar al borrador ${icon('arrow-right')}</button><p>${review.reading_confirmation?.confirmed?'La revisión del oficio continúa en el borrador.':'Confirma la revisión conjunta para continuar.'}</p></div></div></section>`;
}

// Polling must not collapse petitions, move the reading position, or steal keyboard focus.
export function captureRedactionView(view){
  const frame=view.querySelector('.redaction-workspace');
  if(!frame)return null;
  const active=document.activeElement;
  return {disclosures:[...frame.querySelectorAll('[data-redaction-disclosure]')].map(e=>[e.dataset.redactionDisclosure,e.open]),details:[...frame.querySelectorAll('[data-response-id]')].map(e=>[e.dataset.responseId,e.open]),scroll:[...frame.querySelectorAll('[data-redaction-scroll]')].map(e=>[e.dataset.redactionScroll,e.scrollTop]),focus:frame.contains(active)?{action:active.dataset.action,index:active.dataset.index,response:active.tagName==='SUMMARY'?active.parentElement.dataset.responseId:null}:null};
}
export function restoreRedactionView(view,saved){
  if(!saved)return;
  const details=new Map(saved.details),scroll=new Map(saved.scroll),disclosures=new Map(saved.disclosures||[]);
  view.querySelectorAll('[data-redaction-disclosure]').forEach(e=>{if(disclosures.has(e.dataset.redactionDisclosure))e.open=disclosures.get(e.dataset.redactionDisclosure);});
  view.querySelectorAll('[data-response-id]').forEach(e=>{if(details.has(e.dataset.responseId))e.open=details.get(e.dataset.responseId);});
  view.querySelectorAll('[data-redaction-scroll]').forEach(e=>e.scrollTop=scroll.get(e.dataset.redactionScroll)||0);
  if(saved.focus){const f=saved.focus;const target=f.response?[...view.querySelectorAll('[data-response-id]')].find(e=>e.dataset.responseId===f.response)?.querySelector('summary'):f.action?[...view.querySelectorAll('[data-action]')].find(e=>e.dataset.action===f.action&&e.dataset.index===f.index):null;target?.focus({preventScroll:true});}
}
