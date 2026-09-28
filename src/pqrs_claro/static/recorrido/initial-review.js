import {esc} from './views.js';
import {isAutomaticDecisionNote,decisionContinues} from './initial-confirmation.js?v=drafts1';

const names={requirements:'Datos y requisitos del documento',respect:'Lenguaje y atribución al solicitante',repetition:'Antecedentes',classification:'Clasificación'};
export const initialStatuses={idle:'Pendiente de análisis',running:'Analizando',needs_review:'Pendiente de decisión',approved:'Decisión de continuar',routed:'Ruta alternativa registrada',error:'Error de análisis',interrupted:'Análisis interrumpido'};
const states={no_observation:'Sin observaciones preliminares',attention:'Requiere atención',unverified:'Por verificar',unavailable:'Consulta no disponible'};
export const typeNames={information:'Información',documents:'Documentos',individual:'Interés particular',general:'Interés general',consultation:'Consulta',complaint:'Queja',claim:'Reclamo',suggestion:'Sugerencia',denunciation:'Denuncia',congratulation:'Felicitación',undetermined:'Por determinar'};
export const routes={continue:'Continuar a preparar respuestas',complement:'Solicitar complemento',reject:'Revisar propuesta de rechazo',reiterate:'Revisar respuesta por reiteración',specialist:'Remitir a revisión especializada'};
const choices=(keys,value)=>keys.map(k=>`<option value="${k}" ${k===value?'selected':''}>${esc(routes[k]||typeNames[k])}</option>`).join('');
const list=items=>items?.length?`<ul>${items.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`:'';
const currentDraft=(current,value,draft)=>draft?.case_id===current.id&&draft.revision===value.revision?draft:null;
export const initialReady=value=>Boolean(value.report?.document&&!value.legacy_report&&!value.stale&&['needs_review','approved','routed'].includes(value.status));
function original(ref,id){return `<blockquote>${esc(ref.quote)}</blockquote><a href="/api/cases/${encodeURIComponent(id)}/original#page=${ref.page}" target="_blank" rel="noopener">Original · página ${ref.page}, líneas ${ref.line_start}–${ref.line_end}</a>`;}
function source(s,id){return `<div class="initial-source"><strong>${esc(s.title)}</strong><blockquote>${esc(s.quote)}</blockquote><a target="_blank" rel="noopener" href="/api/sources/${encodeURIComponent(s.source_id)}/original?case_id=${encodeURIComponent(id)}#page=${s.page}">${s.location_kind==='section'?'Sección':'Página'} ${s.page} · abrir original</a>${s.needs_review?'<p>Texto obtenido por OCR: cotejar con el original.</p>':''}<p class="muted">Vigencia registrada: ${esc(({unknown:'Por verificar',current:'Vigente según revisión registrada',superseded:'Sustituida',not_applicable:'No aplica'})[s.validity]||'Por verificar')}</p></div>`;}
function checksView(checks,id,key){return `<div class="initial-checks">${checks.map(c=>`<details data-initial-disclosure="${esc(key+'-'+c.key)}"><summary><span>${names[c.key]}</span><span class="initial-state ${c.state}">${states[c.state]}</span></summary><p><strong>${esc(c.summary)}</strong></p><p>${esc(c.reason)}</p>${list(c.pending)}${c.original_refs.map(r=>original(r,id)).join('')}${c.sources.map(s=>source(s,id)).join('')}</details>`).join('')}</div>`;}
function communication(row,decision,key){return row.draft?`<details data-initial-disclosure="draft-${key}"><summary>Borrador de comunicación · requiere revisión</summary><label class="field">Texto del borrador<textarea form="initial-decision-form" class="initial-draft" name="draft-${key}" maxlength="12000">${esc(decision?.communication??row.draft)}</textarea></label><p>No se ha enviado esta comunicación.</p></details>`:list(row.draft_missing);}
function decisionFields(row,decision,key,keys,label){
  const note=isAutomaticDecisionNote(decision?.note)?'':decision?.note||'';
  return `<div class="initial-decision" data-decision-key="${key}"><label class="field">${label}<select form="initial-decision-form" name="route-${key}">${choices(keys,decision?.route||row.proposed_route)}</select></label><details data-initial-disclosure="note-${key}" ${note?'open':''}><summary data-note-label>Añadir una observación (opcional)</summary><label class="field">${key==='document'?'Observación sobre el documento':'Observación sobre esta petición'}<textarea form="initial-decision-form" name="note-${key}" maxlength="5000" placeholder="Añade contexto si lo necesitas. Esta observación es opcional.">${esc(note)}</textarea></label></details></div>`;
}

export function initialReviewSummary(current,value,draft,{automatic=true}={}){
  const legacy=Boolean(value.report&&!value.report.document)||value.legacy_report;
  const report=legacy?null:value.report,identified=Boolean(current.identification)&&(automatic||current.status==='confirmed'),running=value.status==='running',form=currentDraft(current,value,draft);
  let status='Identificando peticiones',description='El análisis del trámite comenzará al identificar las peticiones.';
  if(!automatic&&!identified){status='Pendiente';description='Esta instancia usa el flujo anterior. Confirma las peticiones para analizar su trámite.';}
  if(identified){
    status=initialStatuses[value.status]||'Cargando';description='Analiza los datos y el lenguaje del documento, y el tipo de cada petición.';
    if(!value.status)description='Recuperando el análisis guardado…';
    else if(running)description='Analizando el documento y clasificando sus peticiones…';
    else if(legacy){status='Por actualizar';description='El análisis anterior se conserva en el historial. Actualízalo para revisar los datos y el lenguaje una sola vez.';}
    else if(value.stale){status='Por actualizar';description='Cambiaron las solicitudes, las fuentes o el modelo. Vuelve a analizar antes de continuar.';}
    else if(value.error)description=value.error;
    else if(report){
      description=`${report.requests.length} ${report.requests.length===1?'petición analizada':'peticiones analizadas'}. Revisa el tipo en cada tarjeta.`;
      if(value.can_prepare&&!form){status='Puedes continuar';description+=' Decisión de continuar guardada.';}
      else if(form){status='Borrador sin confirmar';description='Tus cambios están pendientes de confirmación. Consulta el estado de guardado al final de la pantalla.';}
      else if(value.status==='routed')description+=' Hay una ruta alternativa registrada.';
      if(report.special_treatment?.detected)description+=' Hay un tratamiento especial por revisar.';
    }
  }
  const classifierNote=value.classification_provider==='jev'?'<p class="muted">Clasificación por petición: JEV a través de Vercel. Al analizar, se envían el título, la descripción y sus fragmentos originales a Vercel / TypeSafe.</p>':'';
  const analyze=identified&&value.status&&!running&&(!report||value.stale||value.error)?`<button class="primary" data-action="live-initial-analyze">${value.report?'Actualizar análisis':'Analizar trámite'}</button>`:'';
  const general=report&&!value.stale&&!running&&!value.error?`<div class="intake-global-summary">${report.document.checks.map(c=>`<p class="${c.state==='attention'?'has-observation':''}"><strong>${c.key==='requirements'?'Datos del documento':'Lenguaje'} <span class="initial-state ${c.state}">${states[c.state]}</span></strong><span>${esc(c.summary)}</span></p>`).join('')}</div>${!report.history_available?'<p class="intake-history-note">Antecedentes: consulta no disponible con las fuentes actuales.</p>':''}`:'';
  return `<section class="intake-summary" aria-labelledby="intake-summary-title"><div class="intake-summary-heading"><h2 id="intake-summary-title" tabindex="-1">Resumen del trámite</h2><span class="initial-state ${value.stale||value.error?'attention':''}">${esc(status)}</span></div><div class="intake-summary-content"><p role="${value.error||value.stale?'alert':'status'}">${esc(description)}</p>${analyze}${classifierNote}</div>${general}${running?'<progress aria-label="Analizando trámite"></progress>':''}<p class="initial-unsaved" role="status" ${form?'':'hidden'}>Hay cambios sin confirmar. Puedes guardar el borrador y continuar después.</p>${identified?`<details class="intake-details" id="initial-review-details" data-initial-disclosure="review"><summary>Ver detalle${report?' y decisión general':''}</summary>${report?documentDetails(current,value,form):'<p>Los resultados requieren revisión humana. El historial conserva los análisis anteriores.</p><button data-action="live-collections">Fuentes de consulta</button> <button data-action="live-initial-history">Ver historial</button>'}</details>`:''}</section>`;
}
function documentDetails(current,value,form){
  const report=value.report,row=report.document,decision=form?.document||value.document_decision;
  let html=`<div class="intake-tools"><button data-action="live-initial-history">Ver historial</button><button data-action="live-collections">Fuentes de consulta</button>${initialReady(value)?'<button data-action="live-initial-analyze">Volver a analizar</button>':''}</div><details class="initial-scope" data-initial-disclosure="scope"><summary>Alcance de la consulta · ${value.scope?.readable_sources||0} fuentes disponibles</summary>${list(report.warnings)}</details>`;
  const special=report.special_treatment;
  if(special.detected)html+=`<section class="alert"><h3>Tratamiento especial por revisar</h3><p>${esc(special.reason)}</p><dl>${[['Remitente',special.sender],['Asunto',special.subject],['Información solicitada',special.requested_information],['Término escrito',special.stated_term]].map(([k,v])=>`<dt>${k}</dt><dd>${esc(v||'No identificado')}</dd>`).join('')}</dl>${special.original_refs.map(r=>original(r,current.id)).join('')}</section>`;
  if(value.decided_at)html+=`<p class="initial-saved">Decisión guardada por ${esc(value.reviewed_by)} · ${esc(new Date(value.decided_at).toLocaleString('es-CO'))}.</p>`;
  return html+checksView(row.checks,current.id,'document')+`<fieldset class="intake-request-fields" ${initialReady(value)?'':'disabled'}><legend class="sr-only">Decisión sobre el documento completo</legend>${communication(row,decision,'document')}${decisionFields(row,decision,'document',['continue','complement','reject','specialist'],'Ruta del documento completo')}</fieldset>`;
}
export function initialRequestContent(current,value,draft){
  const report=value.report,content={};
  if(value.status==='running'){
    for(const r of current.identification.requests)content[r.id]={header:'<span class="intake-type" role="status">Clasificando petición…</span>',details:''};
    return content;
  }
  if(!report?.document||value.legacy_report)return content;
  const form=currentDraft(current,value,draft),valid=initialReady(value);
  for(const [i,row] of report.requests.entries()){
    const request=current.identification.requests.find(r=>r.id===row.request_id),decision=(form?.requests||value.decisions||[]).find(r=>r.request_id===row.request_id),repetition=row.checks.find(c=>c.key==='repetition');
    const canReiterate=!['unavailable','unverified'].includes(repetition.state)&&repetition.sources.some(s=>s.category==='historical_response');
    content[row.request_id]={
      header:`<label class="intake-type">${value.decisions?'Tipo de petición':row.classification_model?'Tipo sugerido · JEV':'Tipo sugerido'}<select form="initial-decision-form" data-initial-type="${i}" name="type-${i}" aria-label="Tipo de petición: ${esc(request?.title||row.request_id)}" ${valid?'':'disabled'}>${choices(Object.keys(typeNames),decision?.petition_type||row.petition_type)}</select></label>${value.stale?'<p class="muted">Clasificación anterior · actualiza el análisis.</p>':''}`,
      details:`<details class="intake-petition-details" data-initial-disclosure="request-${esc(row.request_id)}"><summary>Ver clasificación${repetition.state==='unavailable'?'':' y antecedentes'} y decisión</summary>${row.classification_model?`<p class="muted">Clasificado por JEV · Vercel · confianza ${Math.round(row.classification_confidence*100)} %. Es una estimación del modelo, no una garantía.</p>`:''}${checksView(row.checks.filter(c=>c.key!=='repetition'||c.state!=='unavailable'),current.id,row.request_id)}<fieldset class="intake-request-fields" ${valid?'':'disabled'}><legend class="sr-only">Decisión de la petición ${esc(request?.label||row.request_id)}</legend>${communication(row,decision,i)}${decisionFields(row,decision,i,canReiterate?['continue','reiterate','specialist']:['continue','specialist'],'Ruta de esta petición')}</fieldset></details>`,
    };
  }
  return content;
}
export function initialConfirmation(current,value,draft,{busy=false,error='',draftMessage='',draftProblem=false,hasPrevious=false}={}){
  if(!initialReady(value))return '';
  const form=currentDraft(current,value,draft),saved=value.can_prepare&&!form,recorded=Boolean(value.document_decision)&&!form;
  const decision=form||{document:value.document_decision,requests:value.decisions};
  const continuing=form||value.document_decision?decisionContinues(decision):value.report.document.proposed_route==='continue'&&value.report.requests.every(r=>r.proposed_route==='continue');
  const checked=form?form.document.reviewed&&form.requests.every(r=>r.reviewed):Boolean(value.document_decision?.reviewed&&value.decisions?.every(r=>r.reviewed));
  return `<section class="intake-confirmation" aria-labelledby="intake-confirmation-title"><h2 id="intake-confirmation-title">Confirmar revisión</h2><form id="initial-decision-form" novalidate data-revision="${value.revision}" data-case="${esc(current.id)}"><label class="field">Responsable de la revisión<input name="reviewed_by" required maxlength="200" value="${esc(form?.reviewed_by??value.reviewed_by??'')}" autocomplete="name"></label><label class="check"><input type="checkbox" name="reviewed-all" required ${checked?'checked':''}>Revisé las peticiones identificadas, el resumen del trámite y los tipos sugeridos.</label><p class="muted">La observación es opcional para cualquier ruta. Se registra tu confirmación y se conservan las observaciones del análisis; no se marcan como resueltas automáticamente.</p><p class="muted" role="${draftProblem?'alert':'status'}" data-draft-status>${esc(draftMessage)}</p><div class="dialog-actions"><button type="button" data-action="live-initial-save" ${busy?'disabled':''}>Guardar borrador</button>${hasPrevious?'<button type="button" data-action="live-initial-draft-preview">Ver borrador conservado</button>':''}<button type="button" data-action="live-initial-draft-download">Descargar borrador</button></div><p class="alert" role="alert" data-initial-error ${error?'':'hidden'}>${esc(error)}</p><div class="actionbar"><p data-confirmation-message>${continuing?'La confirmación se guarda y comienza la preparación. No se envía ninguna comunicación.':'Hay una ruta alternativa. Se guardará la decisión y el expediente seguirá en este paso.'}</p><button type="button" class="primary" data-action="live-initial-confirm" ${busy?'disabled':''}>${busy?'Procesando…':saved?'Preparar respuestas →':recorded?'Decisión guardada':continuing?'Confirmar y preparar respuestas →':'Guardar decisión'}</button></div></form></section>`;
}
export function updateInitialConfirmation(view,value,decision,{saved=false,recorded=false}={}){
  if(!decision)return;
  const continuing=decisionContinues(decision),button=view.querySelector('[data-action="live-initial-confirm"]');
  if(button)button.textContent=saved?'Preparar respuestas →':recorded?'Decisión guardada':continuing?'Confirmar y preparar respuestas →':'Guardar decisión';
  if(button)button.disabled=recorded&&!saved;
  const message=view.querySelector('[data-confirmation-message]');
  if(message)message.textContent=continuing?'La confirmación se guarda y comienza la preparación. No se envía ninguna comunicación.':'Hay una ruta alternativa. Se guardará la decisión y el expediente seguirá en este paso.';
  for(const field of view.querySelectorAll('[data-decision-key] textarea[name^="note-"]')){
    field.required=false;
    field.setCustomValidity('');
    field.closest('[data-decision-key]').querySelector('[data-note-label]').textContent='Añadir una observación (opcional)';
  }
  for(const [i,item] of decision.requests.entries())view.querySelector(`[name="type-${i}"]`)?.setCustomValidity(item.route==='continue'&&item.petition_type==='undetermined'?'Define el tipo de esta petición antes de continuar.':'');
  const reviewer=view.querySelector('[name="reviewed_by"]');
  reviewer?.setCustomValidity(reviewer.value.trim()?'':'Indica quién revisó el trámite.');
}
export function readInitialDecision(view,current,value){
  const form=view.querySelector('#initial-decision-form');if(!form)return null;
  const data=new FormData(form),decision=k=>({route:data.get(`route-${k}`),note:String(data.get(`note-${k}`)||''),reviewed:data.has('reviewed-all'),communication:String(data.get(`draft-${k}`)||'')});
  return {case_id:current.id,revision:value.revision,reviewed_by:String(data.get('reviewed_by')||''),document:decision('document'),requests:value.report.requests.map((r,i)=>({request_id:r.request_id,petition_type:data.get(`type-${i}`),...decision(i)}))};
}
export function initialHistory(events){return events.map(e=>`<section class="source"><h3>Versión ${e.revision} · ${esc(initialStatuses[e.status]||e.status)}</h3><p>${esc(new Date(e.updated_at).toLocaleString('es-CO'))}${e.reviewed_by?' · '+esc(e.reviewed_by):''}</p>${e.document_decision?`<p><strong>Documento completo · ${esc(routes[e.document_decision.route])}</strong><br>${esc(e.document_decision.note)}</p>`:''}${e.decisions?.map(r=>`<p><strong>${esc(r.request_id)} · ${esc(typeNames[r.petition_type]||r.petition_type)} · ${esc(routes[r.route]||r.route)}</strong><br>${esc(r.note)}</p>`).join('')||'<p>Análisis y recomendaciones conservados.</p>'}</section>`).join('')||'<p>Todavía no hay eventos.</p>';}
