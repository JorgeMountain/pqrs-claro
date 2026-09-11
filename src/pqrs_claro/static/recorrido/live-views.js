import {pendingCards,isLater,isOpen} from './live-pending-view.js?v=20260911-predraft';
import {esc,understanding,sourcesView} from './views.js';
export function identification(data,state){
  let html=understanding(data,state);
  html=html.replace('PETICIÓN DE DEMOSTRACIÓN','PETICIÓN · '+esc(data.subject));
  html=html.replace('Solicitante de demostración · 10 de septiembre de 2026',esc([data.requester,data.document_date].filter(Boolean).join(' · ')||data.filename));
  html=html.replace('3 solicitudes identificadas',`${data.requests.length} solicitudes identificadas`);
  const confirmed=data.status==='confirmed';
  const action=confirmed?'<button class="primary" data-action="live-responses">Ver respuestas →</button>':'<button class="primary" data-action="live-confirm">Confirmar solicitudes →</button>';
  html=html.replace('<p>Esta maqueta parte de la identificación ya confirmada.</p><button class="primary" data-action="prepare">Preparar las respuestas →</button>',`<p>${confirmed?'Identificación confirmada.':'Al confirmar, se buscarán las fuentes. Revisa los puntos necesarios; las solicitudes listas se redactan automáticamente.'}</p>${action}`);
  if(!confirmed)html+=`<div class="actionbar"><button data-action="live-correct">Corregir una solicitud</button><button data-action="live-collections">Fuentes de consulta</button></div>`;
  return html;
}
const names={support_found:'Respaldo encontrado',confirmation_pending:'Confirmación pendiente',document_missing:'Documento faltante',analysis_error:'Error de análisis'};
export function responses(current,job,mapping,drafts,review){
  const running=job.status==='running';
  let html=`<div class="heading responses-heading ${running?'is-preparing':''}"><div><p class="eyebrow">${current.request_count} SOLICITUDES</p><h1>Respuestas para revisar</h1><p class="muted">Consulta cada respuesta, sus fuentes y los puntos concretos por revisar.</p></div></div>`;
  if(running)html+=preparationProgress(job,mapping,current.request_count,drafts);
  if(job.status==='waiting_review')html+=`<section class="pre-draft-notice"><strong>Revisa los puntos antes de redactar</strong><p>Abre los puntos de cada solicitud, confirma su respaldo o explica por qué no aplican. Las solicitudes listas se redactan automáticamente; las demás conservan su avance.</p></section>`;
  if(job.error)html+=`<div class="alert" role="alert">${esc(job.error)}</div>`;
  if(!running&&(job.status!=='ready'||job.stale||mapping.stale))html+=`<div class="actionbar"><p>Se conserva el avance guardado.</p><button class="primary" data-action="live-resume">${job.status==='idle'?'Continuar con las respuestas':job.status==='waiting_review'?'Reintentar o actualizar fuentes':'Continuar o actualizar preparación'}</button><button data-action="live-collections">Fuentes de consulta</button></div>`;
  html+=current.identification.requests.map((r,i)=>{
    const finding=mapping.results?.find(x=>x.request_id===r.id),row=review.requests?.find(x=>x.request_id===r.id),draft=drafts.results?.find(x=>x.request_id===r.id);
    const states=(finding?.evidence_states||[]).filter(state=>{
      if(!row||row.stale)return true;
      if(state==='confirmation_pending'&&row.pending.some(p=>p.state==='confirmation_pending'))return row.pending.some(p=>!isLater(p)&&isOpen(p)&&p.state==='confirmation_pending');
      if(state==='document_missing'&&row.pending.some(p=>p.kind==='document'))return row.pending.some(p=>p.kind==='document'&&isOpen(p));
      return true;
    });
    const paragraphs=row?.paragraphs||draft?.draft?.paragraphs||[];
    const pending=row&&!row.stale?(row.pending||[]).filter(p=>!p.resolution||p.resolution.action==='open'):finding?.missing||[];
    const badges=(!mapping.stale?states.map(s=>`<span class="response-state ${s==='analysis_error'?'error':s==='support_found'?'supported':'attention'}">${names[s]||esc(s)}</span>`).join(''):'')
      +(row?.status==='approved'&&!row.stale?'<span class="response-state approved">Respuesta aprobada</span>':'')
      +(row?.edited_by&&!row.approval&&!row.assessment?'<span class="response-state attention">Actualizada · pendiente de revisión</span>':'')
      +(row?.stale?'<span class="response-state attention">Texto guardado · respaldo por actualizar</span>':'');
    const sourcesRunning=mapping.status==='running'||(running&&job.stage==='sources');
    const searchState=sourcesRunning?(mapping.request_states?.[r.id]||(finding?'completed':'queued')):null;
    const searchingSources=searchState==='searching';
    const draftStep=drafts.status==='running'?drafts.request_states?.[r.id]:null;
    const drafting=draftStep&&!['queued','completed','error'].includes(draftStep);
    const draftLabel={planificar:'Organizando la respuesta…',redactar:'Redactando con IA…',comprobar:'Comprobando la respuesta…',ajustar_citas:'Ajustando citas…',recomprobar:'Comprobando ajustes…'}[draftStep];
    const emptyMessage=drafting?draftLabel:draftStep==='queued'?'En espera de un turno para redactar.':row?.pre_draft&&pending.some(p=>!isLater(p))?'Revisa los puntos necesarios para preparar esta respuesta.':running?'La respuesta se está preparando.':states.includes('analysis_error')&&!mapping.stale?'La respuesta aún no está disponible. Consulta el detalle en las fuentes.':'La respuesta aún no está disponible.';
    return `<article class="response-card ${paragraphs.length?'has-answer':'awaiting-answer'}" id="request-${i}" aria-labelledby="response-title-${i}">
      <div class="response-header">
        <div class="response-identity"><span class="response-reference">Solicitud ${esc(String(r.label).replace(/\.$/,''))}</span><h2 id="response-title-${i}">${esc(r.title)}</h2></div>
        ${badges?`<div class="response-states" aria-label="Estado de esta respuesta">${badges}</div>`:''}
      </div>
      <div class="response-content">
        ${paragraphs.length?`<div class="response-copy">${paragraphs.map(p=>`<p>${esc(p.text)}</p>`).join('')}</div>`:`<p class="response-empty">${drafting?'<span class="source-spinner" aria-hidden="true"></span>':responseIcon('document')}<span>${emptyMessage}</span></p>`}
        ${draft?.error?`<p class="alert" role="alert">${esc(draft.error)}</p>`:''}
        ${row?pendingCards(row,i):pending.length?`<details class="pending-disclosure" data-pending-group="${esc(r.id)}"><summary>${pending.length} puntos detectados</summary><p class="library-note">Puedes consultarlos ahora. Las decisiones se habilitan al terminar la búsqueda.</p>${pending.map(p=>`<section class="live-pending-item"><p>${esc(p.description)}</p>${p.why_unresolved?`<p>${esc(p.why_unresolved)}</p>`:""}</section>`).join("")}</details>`:''}
      </div>
      <div class="response-toolbar">
        <div class="response-resources"><button data-action="live-sources" data-index="${i}">${searchingSources?'<span class="source-spinner" aria-hidden="true"></span>':responseIcon('sources')}${searchingSources?'Buscando fuentes…':'Ver fuentes'}</button>${searchState==='queued'?'<span class="response-search-status">En espera</span>':searchState==='completed'?'<span class="response-search-status">Búsqueda terminada</span>':''}<button data-action="live-evidence" data-index="${i}">${responseIcon('add')}Agregar evidencia</button></div>
        ${row?.paragraphs?.length?`<div class="response-editing"><button data-action="live-proposal" data-index="${i}">${responseIcon('refresh')}Actualizar con IA</button><button class="response-edit" data-action="live-edit" data-index="${i}">${responseIcon('edit')}Editar respuesta</button></div>`:''}
      </div>
      <details class="response-original"><summary>Qué solicitó la persona</summary><p>${esc(r.description)}</p></details>
    </article>`;
  }).join('');
  return html+'<div class="actionbar"><p class="muted">Las respuestas se guardan para revisión.</p><button class="primary" data-action="live-final">Revisar y preparar el oficio →</button></div>';
}
export function supports(items,caseId){
  return sourcesView(items.map(s=>({...s,url:`/api/sources/${s.source_id}/original?case_id=${caseId}`})));
}

function preparationProgress(job,mapping,total,drafts){
  const stages=[['sources','Buscar fuentes'],['points','Revisar puntos'],['drafts','Redactar con IA'],['review','Revisar respuestas']];
  const active=stages.findIndex(([key])=>key===job.stage);
  const messages={points:'Organizando los puntos y las solicitudes listas para redactar.',sources:'Buscando respaldo en las fuentes del expediente.',drafts:'Redactando las respuestas con las fuentes encontradas.',review:'Guardando las respuestas para que puedas revisarlas.'};
  return `<section class="preparation-progress" aria-labelledby="preparation-title">
    <span class="analysis-badge">Preparación en curso</span>
    <h2 id="preparation-title">Estamos preparando tus respuestas</h2>
    <p class="preparation-description" role="status">${messages[job.stage]||'Iniciando la preparación de respuestas.'}</p>
    <ol class="preparation-track" aria-label="Avance de la preparación">${stages.map(([key,label],i)=>{
      const done=active>=0&&i<active,current=i===active;
      return `<li class="preparation-stage ${done?'complete':current?'current':''}"${current?' aria-current="step"':''}><span class="preparation-mark" aria-hidden="true">${done?'✓':i+1}</span><span>${label}<span class="analysis-sr">${done?', completado':current?', en curso':', pendiente'}</span></span></li>`;
    }).join('')}</ol>
    ${job.stage==='drafts'?`<p class="preparation-hint">${drafts.completed_count||0} de ${total} respuestas preparadas · Hasta ${drafts.concurrency||3} en paralelo</p>`:""}
    ${job.stage==='sources'&&Number.isInteger(mapping.completed_count)?`<p class="preparation-hint">${mapping.completed_count} de ${total} solicitudes analizadas${mapping.concurrency?` · Hasta ${mapping.concurrency} en paralelo`:""}</p>`:""}<p class="preparation-hint">El avance se guarda. Puedes volver a este expediente después.</p>
  </section>`;
}

function responseIcon(name){
  const shapes={document:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',sources:'<path d="M12 6c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V5c-4-1-7-1-10 1zM12 6v15"/>',add:'<path d="M12 5v14M5 12h14"/>',edit:'<path d="m16 3 5 5-12 12H4v-5zM13 6l5 5"/>',refresh:'<path d="M20 7a9 9 0 0 0-15-2L2 8m0-6v6h6M4 17a9 9 0 0 0 15 2l3-3m0 6v-6h-6"/>'};
  return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${shapes[name]}</svg>`;
}
