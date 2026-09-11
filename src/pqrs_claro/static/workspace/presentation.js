import {el,button} from '../ui.js';
const labels={support_found:'Respaldo encontrado',confirmation_pending:'Confirmación pendiente',document_missing:'Documento faltante',analysis_error:'Error de análisis'};
const cachedPages=new Map();
export function documentPanel(state,api,onPage){
  const current=state.current,number=state.page||1;
  const request=current.identification?.requests.find(r=>r.id===state.selectedId);
  const panel=el('section',{id:'original-pane',className:'original-viewer','aria-label':'Documento original'},
    el('div',{className:'original-head'},el('h2',{id:'original-title',tabindex:'-1'},'Documento original'),el('a',{href:`/api/cases/${current.id}/original`,target:'_blank',rel:'noopener'},'Abrir PDF ↗')));
  const selector=el('select',{'aria-label':'Página del documento original',onChange:e=>onPage(Number(e.target.value))},
    (current.pages||[]).map(p=>el('option',{value:p.number},String(p.number))));selector.value=number;
  panel.append(el('label',{className:'original-tools'},'Página ',selector,` de ${current.pages?.length||'—'}`));
  const content=el('div',{},el('p',{role:'status'},'Cargando página…'));panel.append(content);
  const key=`${current.id}:${current.version}:${number}:${state.highlight?request?.id||'':''}`;
  if(!cachedPages.has(key))cachedPages.set(key,api(`/api/cases/${current.id}/pages/${number}/view${state.highlight&&request?'?request_id='+encodeURIComponent(request.id):''}`).catch(e=>{cachedPages.delete(key);throw e;}));
  cachedPages.get(key).then(page=>{
    if(!panel.isConnected)return;
    const sheet=el('div',{className:'original-sheet'},el('img',{src:`/api/cases/${current.id}/pages/${number}.png`,alt:`Página ${number} del documento original`,width:page.width,height:page.height}));
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('class','original-marks');svg.setAttribute('viewBox',`0 0 ${page.width} ${page.height}`);svg.setAttribute('aria-hidden','true');
    for(const mark of page.marks)for(const rect of mark.rectangles){const node=document.createElementNS(svg.namespaceURI,'rect');node.setAttribute('class','quote-mark');for(const [name,value] of Object.entries({x:rect[0],y:rect[1],width:rect[2]-rect[0],height:rect[3]-rect[1]}))node.setAttribute(name,value);svg.append(node);}sheet.append(svg);
    const image=sheet.querySelector('img');image.onerror=()=>{sheet.replaceChildren(el('p',{role:'alert'},'No se pudo mostrar la imagen. Abre el PDF original.'));};
    const viewport=el('div',{className:'original-scroll',tabindex:'0','aria-label':'Visor del documento original'},sheet);
    const focusMark=()=>{const first=svg.querySelector('rect');if(first){const rect=first.getBoundingClientRect(),bounds=viewport.getBoundingClientRect();viewport.scrollTop+=rect.top-bounds.top-viewport.clientHeight*.3;}};
    image.onload=focusMark;
    content.replaceChildren(el('p',{className:'original-selection'},state.highlight&&request?`Solicitud ${request.label} · ${request.title}`:'Selecciona «Ver de dónde salió» para resaltar su origen.'),viewport,
      page.marks.length?el('div',{className:'original-quote'},el('strong',{},'Texto de origen'),el('p',{},page.marks.map(m=>m.quote).join('\n')),!page.has_visual_match?el('p',{className:'warning-box'},'El pasaje está en el texto extraído; no se pudo localizar un resaltado exacto sobre la imagen.'):null):null,
      el('details',{className:'original-transcript'},el('summary',{},'Leer texto de esta página'),el('p',{},page.text)));
    if(image.complete)focusMark();
  }).catch(error=>{if(panel.isConnected)content.replaceChildren(el('p',{role:'alert'},error.message));});
  return panel;
}
export function identificationCards(state,actions){
  return el('div',{id:'requests-pane',className:'identified-requests'},state.current.identification.requests.map(r=>el('article',{
    id:`request-${r.id}`,className:`identified-card ${state.selectedId===r.id&&state.highlight?'selected':''}`},
    el('div',{className:'card-title'},el('span',{className:'card-number'},r.label+'.'),el('h2',{},r.title)),
    el('p',{},r.description),r.source_refs.map((ref,i)=>button(`Ver de dónde salió · página ${ref.page}`,()=>{actions.selectSource(r.id,ref);},'quiet',{'aria-label':`Origen de solicitud ${r.label}, fragmento ${i+1}, página ${ref.page}`})),
    state.current.status==='needs_review'?button('Corregir solicitud',()=>actions.edit(r.id),'quiet'):null)));
}
export function divider(){
  const handle=el('div',{id:'request-divider',className:'pane-divider',role:'separator',tabindex:'0','aria-label':'Ajustar ancho de solicitudes y documento','aria-orientation':'vertical','aria-controls':'requests-pane original-pane','aria-valuemin':'30','aria-valuemax':'70','aria-valuenow':'60'});
  handle.append(el('span',{className:'split-grip','aria-hidden':'true'},'⋮'));return handle;
}
export function responseCards(state,sources,drafts,reviews,actions){
  const current=state.current,mapping=sources.state.mapping,rows=reviews.state?.data?.requests||[],run=drafts.state.run;
  const approved=rows.filter(r=>r.approval&&!r.stale&&!reviews.state.locals.get(r.request_id)?.dirty).length;
  const wrapper=el('section',{'aria-label':'Respuestas de la petición'});
  wrapper.append(el('div',{className:'actionbar'},el('p',{},`${approved} de ${current.request_count} respuestas aprobadas`),button(rows.length?'Actualizar respaldo':'Preparar las respuestas',actions.prepare,'primary',{disabled:state.busy||!state.config?.ready})));
  for(const error of [sources.state.error,drafts.state.error,reviews.state?.error])if(error)wrapper.append(el('p',{className:'warning-box',role:'alert'},error));
  for(const r of current.identification.requests){
    const finding=mapping?.results?.find(f=>f.request_id===r.id),row=rows.find(v=>v.request_id===r.id),draft=run?.results?.find(v=>v.request_id===r.id),local=reviews.state?.locals.get(r.id);
    const paragraphs=local?.dirty?local.paragraphs:row?.paragraphs||draft?.draft?.paragraphs||[];
    const stale=mapping?.stale||row?.stale||(!row&&run?.stale);
    const pending=row&&!row.stale?(row.pending||[]).filter(p=>!p.resolution||p.resolution.action==='open'):(finding?.missing||[]);
    const card=el('article',{className:'answer-card',id:`response-${r.id}`},el('div',{className:'card-title'},el('span',{className:'card-number'},r.label+'.'),el('h2',{},r.title)));
    const badges=el('div',{});
    if(finding&&!mapping.stale){for(const status of finding.evidence_states||[])badges.append(el('span',{className:`badge ${status==='analysis_error'?'error':''}`},labels[status]||status));}
    else badges.append(el('span',{className:'badge'},'Búsqueda por realizar'));
    if(stale)badges.append(el('span',{className:'badge'},'Texto guardado · revisión pendiente'));
    if(local?.dirty)badges.append(el('span',{className:'badge'},'Edición sin guardar'));
    else if(row?.approval&&!row.stale)badges.append(el('span',{className:'badge'},'Respuesta aprobada'));
    card.append(badges,paragraphs.length?el('div',{className:'answer-text'},paragraphs.map(p=>el('p',{},p.text))):el('p',{className:'muted'},'La respuesta se preparará con los documentos disponibles.'));
    if(stale)card.append(el('p',{className:'warning-box'},'El texto guardado se conserva. Actualiza su respaldo antes de volver a comprobar y aprobar.'));
    if(finding?.status==='error'||draft?.error)card.append(el('p',{className:'warning-box',role:'alert'},finding?.status==='error'?finding.summary:draft.error));
    if(pending.length)card.append(el('div',{className:'answer-pending'},el('strong',{},`${pending.length} puntos por revisar`),el('ul',{},pending.slice(0,3).map(p=>el('li',{},p.description))),pending.length>3?el('p',{},'Consulta los demás en «Revisar respuesta».'):null));
    const supports=finding?.supports||row?.available_supports||draft?.supports||[];
    const count=new Set(supports.map(s=>s.source_id)).size;
    card.append(el('div',{className:'card-footer'},button(`Ver respaldo · ${count} ${count===1?'documento':'documentos'}`,()=>actions.supports(r,supports),'quiet'),
      button('Agregar evidencia',()=>actions.upload(r.id),'secondary',{disabled:state.busy}),button('Revisar respuesta',()=>actions.review(r.id),'secondary',{disabled:state.busy})),el('details',{},el('summary',{},'Qué solicitó la persona'),el('p',{},r.description)));
    wrapper.append(card);
  }
  wrapper.append(el('div',{className:'actionbar'},el('p',{},'El oficio utiliza únicamente las versiones aprobadas.'),button('Revisar el oficio →',actions.office,'primary',{disabled:state.busy})));
  return wrapper;
}
