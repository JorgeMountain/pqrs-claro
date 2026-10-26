import {esc} from './views.js';

export function progress(c){
  const initial=c.initial_review_status;
  if(c.management?.state==='closed')return {tone:'closed',label:'Finalizada',detail:'Gestión finalizada',stage:4};
  if(c.status==='uploaded')return {tone:c.management?.owner_id?'preanalysis':'uploaded',label:c.management?.owner_id?(c.preanalysis_status==='running'?'En preanálisis':'Preanálisis'):'Disponible',detail:c.management?.owner_id?'Revisión previa · identificación sin iniciar':'Pendiente de asignar',stage:0};
  if(c.status==='error'||['error','interrupted'].includes(initial))return {tone:'error',label:'Requiere atención',detail:'La identificación necesita revisión',stage:c.request_count?1:0};
  if(['reading','identifying'].includes(c.status)||initial==='running')return {tone:'processing',label:'Identificando',detail:initial==='running'?'Analizando contenido y tipo de petición':c.status==='reading'?'Leyendo documento':'Identificando peticiones',stage:1};
  if(initial==='idle'){
    const savedStage=Math.max(c.saved_stage||0,c.preparation?.status&&c.preparation.status!=='idle'?2:0);
    if(c.status==='confirmed'&&savedStage>=2)return {tone:'confirmed',label:savedStage>=3?'Borrador guardado':'Redacción guardada',compactLabel:savedStage>=3?'Borrador':'Redacción',detail:'Avance anterior conservado · revisión de tipos sin registro',compactDetail:'Consultar avance guardado',stage:Math.min(savedStage,3),historical:true};
    if(c.request_count>0)return {tone:'review',label:'Identificada',detail:'Peticiones guardadas · falta la revisión de contenido y tipo',compactDetail:'Peticiones guardadas · revisar tipos',stage:1,identifiedOnly:true};
    return {tone:'review',label:'Identificación pendiente',compactLabel:'Por identificar',detail:'Falta completar el contenido y tipo de petición',compactDetail:'Contenido y tipo pendientes',stage:1,identifiedOnly:true};
  }
  if(['needs_review','stale'].includes(initial))return {tone:'review',label:initial==='stale'?'Por actualizar':'Por revisar',detail:'Revisión conjunta de las peticiones pendiente',stage:1};
  if(initial==='routed')return {tone:'confirmed',label:'Ruta registrada',detail:'Ruta alternativa guardada · redacción pendiente',stage:1};
  if(initial==='approved'){
    const office=c.office_progress?.status;
    if(office==='ready')return {tone:'confirmed',label:'Oficio generado',detail:'Word y PDF guardados · disponibles para consultar',stage:3,complete:true};
    if(office==='generating')return {tone:'processing',label:'Generando oficio',detail:'Creando Word y PDF con las respuestas aprobadas',stage:3};
    if(office==='stale')return {tone:'review',label:'Borrador por actualizar',compactLabel:'Por actualizar',detail:'Hay una versión anterior · revisa los cambios guardados',stage:3};
    if(office==='failed')return {tone:'error',label:'Borrador',detail:'La generación del oficio requiere atención',stage:3};
    if(c.saved_stage>=3)return {tone:'confirmed',label:'Borrador guardado',compactLabel:'Borrador',detail:'Continuar con la revisión final del oficio',stage:3};
    if(c.management?.state==='ready_review')return {tone:'confirmed',label:'Borrador',detail:'Gestión marcada para revisión del borrador',stage:3};
    return {tone:c.processing?'processing':'confirmed',label:'Redacción',detail:c.processing?'Preparando respuestas':'Continuar con las respuestas del expediente',stage:2};
  }
  if(c.processing||c.analysis_running||c.status==='confirming')return {tone:'processing',label:'En curso',detail:'Procesando expediente',stage:1};
  return {tone:'review',label:'Por revisar',detail:'Revisar peticiones y completar su identificación',stage:1,identifiedOnly:true};
}
function stagesFor(p,c={}){
  const stages=[
    ['preanalysis','Preanálisis','Datos del solicitante, lenguaje y legibilidad del documento.'],
    ['identify','Identificación','Peticiones, tipo y contenido; revisión conjunta del gestor.'],
    ['draft','Redacción','Preparar y revisar las respuestas a las peticiones.'],
    ['review','Borrador','Revisar el oficio antes de finalizar la gestión.'],
  ];
  return stages.map(([key,name,description],i)=>{
    const missingPreanalysis=p.historical&&i===0&&c.preanalysis_status!=='ready';
    const done=(i<p.stage||p.complete)&&!missingPreanalysis,current=!done&&i===p.stage&&p.tone!=='uploaded';
    return {key,name,description,state:done?'complete':current?'current':'pending',label:missingPreanalysis?'Sin registro':p.historical&&(done||current)?'Guardado':done?'Completado':current?p.tone==='review'?'Por revisar':p.tone==='error'?'Requiere atención':'En curso':'Pendiente'};
  });
}
export function progressBar(c,{compact=false}={}){
  const p=progress(c);
  if(p.stage===0||p.tone==='closed')return '';
  const stages=stagesFor(p,c),description=stages.map(s=>`${s.name}: ${s.label}`).join('. ');
  return `<div class="inbox-progress ${p.tone}" role="img" aria-label="${esc(description)}">${stages.map(s=>`<span class="stage-${s.key} ${s.state}" title="${esc(s.name+': '+s.label)}" aria-hidden="true"></span>`).join('')}</div><small class="inbox-progress-label">${esc(compact&&p.compactDetail||p.detail)}</small>`;
}
export function actionFor(c,manager){
  if(!c.management?.owner_id)return {kind:'claim',label:'Tomar expediente'};
  if(c.management.owner_id!==manager)return {kind:'detail',label:'Ver detalle'};
  const p=progress(c);
  if(p.tone==='preanalysis'||c.status==='error'&&!c.request_count)return {kind:'preanalysis',label:'Revisar documento'};
  if(p.tone==='processing')return {kind:'detail',label:'Ver progreso'};
  if(!c.management.started_at)return {kind:'start',label:'Iniciar análisis'};
  return {kind:'continue',label:p.complete?'Ver oficio':p.stage===3?'Revisar borrador':p.tone==='review'?'Revisar resultado':p.tone==='error'?'Revisar problema':p.tone==='uploaded'?'Iniciar análisis':p.tone==='closed'?'Consultar':'Continuar gestión'};
}
export function progressDetail(c,manager){
  const p=progress(c),own=c.management?.owner_id===manager;
  return `<h2 id="inbox-panel-title">Seguimiento del expediente</h2><h3>${esc(c.subject||c.filename)}</h3><p class="muted">${esc(c.case_number||c.internal_number||c.id)}</p><span class="inbox-state ${p.tone}">${p.label}</span>${progressBar(c)}<ol class="inbox-stages">${stagesFor(p,c).map(({key,name,description,state,label},i)=>{
    return `<li class="stage-${key} ${state}" ${state==='current'?'aria-current="step"':''}><span class="stage-number">${i+1}</span><div><strong>${name}</strong><p>${description}</p><small>${label}</small></div></li>`;
  }).join('')}</ol><dl class="inbox-detail-meta"><div><dt>Responsable</dt><dd>${esc(c.management?.owner_name||'Sin asignar')}${own?' (tú)':''}</dd></div><div><dt>Recepción</dt><dd>${esc(c.management?.received_date||'Sin registrar')}</dd></div></dl><a class="inbox-original" href="/api/cases/${encodeURIComponent(c.id)}/original" target="_blank" rel="noopener">Ver documento recibido ↗</a><p class="inbox-panel-hint">${p.tone==='processing'?'Puedes seguir trabajando en la bandeja mientras termina.':'El análisis y la revisión humana se conservan por expediente.'}</p>${own&&p.tone==='preanalysis'?`<button class="primary" data-management-action="preanalysis" data-id="${esc(c.id)}">Revisar documento</button>`:''}${own&&c.management?.started_at&&!['processing','preanalysis'].includes(p.tone)?`<button class="primary" data-management-action="continue" data-id="${esc(c.id)}">${p.tone==='uploaded'?'Iniciar análisis':p.tone==='review'?'Revisar resultado':'Abrir expediente'}</button>`:''}<button class="text-button inbox-management" data-management-edit="${esc(c.id)}">Detalles e historial de gestión</button>${!c.processing?`<button class="text-button inbox-trash-link" data-case-delete="${esc(c.id)}">Mover a la papelera</button>`:''}`;
}
