import {esc} from './views.js';
import {documentTarget} from './document-decision.js';
export const isLater=p=>p.stage==='fulfillment'&&p.blocks_approval===false;
export const isOpen=p=>!p.resolution||p.resolution.action==='open';
export const when=value=>value?new Intl.DateTimeFormat('es-CO',{dateStyle:'short',timeStyle:'short'}).format(new Date(value)):'';

export function pendingCards(row,index) {
  if(!row?.pending?.length)return '';
  const button=(action,p,label)=>`<button data-action="live-pending" data-index="${index}" data-pending="${esc(p.id)}" data-decision="${action}">${label}</button>`;
  const actions=p=>{
    if(p.state==='analysis_error')return '<p class="library-note">Este problema debe corregirse en el análisis. No necesitas confirmarlo ni inventar un respaldo.</p><button data-action="live-resume" data-retry-analysis="true">Reintentar análisis</button>';
    if(row.stale)return '';
    const target=documentTarget(row,p);
    if(target&&p.reason_code==='issued_version')return `${target.document_status!=='draft'&&!/\bXXX+/i.test(target.title)?button('issued',p,'Es la versión expedida'):''}${button('draft',p,'Es un documento de trabajo')}<small>No lo sé: puedes dejarlo pendiente y consultar el original.</small>`;
    if(target&&p.reason_code==='provenance')return button('provenance_reviewed',p,'Ya revisé este archivo');
    return button('resolved',p,isLater(p)?'Registrar realización':'Confirmar con respaldo')+button('not_applicable',p,'No aplica este pendiente');
  };
  const render=p=>`<section class="live-pending-item"><strong>${isOpen(p)?isLater(p)?'Actuación posterior':'Por resolver':p.resolution.action==='not_applicable'?'Pendiente marcado como no aplicable':'Decisión confirmada'}</strong><p>${esc(p.description)}</p>${p.why_unresolved?`<p class="library-note"><strong>Por qué:</strong> ${esc(p.why_unresolved)}</p>`:""}
    ${isLater(p)?'<p class="library-note">Puede realizarse después de revisar el contenido. Confirmarla registra su ejecución, no solo la intención de realizarla.</p>':''}
    ${row.stale?'<p class="library-note">Las fuentes cambiaron. Actualiza la preparación para decidir sobre el respaldo vigente.</p>':''}
    ${isOpen(p)?`<div class="scope-actions">${actions(p)}${p.state!=='analysis_error'?`<button data-action="live-evidence" data-index="${index}">Agregar evidencia</button>`:''}</div>`:`<p>${esc(p.resolution.note)}</p><small>${esc(p.resolution.by)} · ${esc(when(p.resolution.at))}</small><div class="scope-actions">${button('detail',p,'Ver decisión y respaldo')}${button('open',p,'Reabrir')}</div>`}
  </section>`;
  const pending=row.pending.filter(isOpen),done=row.pending.filter(p=>!isOpen(p));
  return `<details class="pending-disclosure" data-pending-group="${esc(row.request_id)}"><summary>${pending.length?`${pending.length} ${pending.length===1?"punto por revisar":"puntos por revisar"}`:"Decisiones registradas"}${row.pre_draft?" · antes de redactar":""}</summary><section class="live-pending-list" aria-label="Decisiones de esta respuesta">${pending.map(render).join('')}${done.length?`<details><summary>${done.length} ${done.length===1?'decisión registrada':'decisiones registradas'}</summary>${done.map(render).join('')}</details>`:''}<button class="text-button" data-action="live-pending-history" data-index="${index}">Historial de decisiones</button></section></details>`;
}

export function decisionForm(row,p,action,actor) {
  const resolved=action==='resolved',isDocument=p.kind==='document';
  const options=[...(row.available_supports||[]).map(s=>({value:'source:'+s.chunk_id,label:`${s.title} · versión ${s.version} · ${s.location_kind==='section'?'sección':'página'} ${s.page}`,text:s.quote})),...(!isDocument&&!row.pre_draft?(row.facts||[]).map(f=>({value:'fact:'+f.id,label:`Aporte de ${f.author} · ${f.observed_at}`,text:f.text})):[])];
  return {options,html:`<form id="pending-decision-form"><p><strong>${esc(p.description)}</strong></p>
    <p>${action==='not_applicable'?'Explica por qué este pendiente no corresponde a esta respuesta. La decisión no descarta el documento citado ni reescribe la respuesta.':action==='open'?'El punto volverá a aparecer por resolver. Se conserva la decisión anterior en el historial.':'Selecciona el pasaje o aporte que has revisado y explica cómo resuelve este punto.'}</p>
    ${resolved?`<label class="field">Respaldo<select id="pending-support" required><option value="">Selecciona el respaldo revisado</option>${options.map(o=>`<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('')}</select></label><blockquote id="pending-quote" hidden></blockquote>${!options.length?'<p>No hay soportes disponibles para confirmar este punto.</p>':''}<div class="scope-actions"><button type="button" id="pending-upload">Agregar evidencia</button>${!isDocument&&!row.pre_draft?'<button type="button" id="pending-fact">Aportar información comprobada</button>':''}</div>`:''}
    ${action!=='open'?'<label class="field">'+(action==='not_applicable'?'Por qué no aplica':'Qué comprobaste y cómo resuelve este punto')+'<textarea id="pending-note" required maxlength="8000" rows="3"></textarea></label>':''}
    <label class="field">Tu nombre<input id="pending-actor" required maxlength="240" autocomplete="name" value="${esc(actor)}"></label>
    <p id="pending-error" role="alert"></p><div class="scope-actions"><button class="primary" type="submit" ${resolved&&!options.length?'disabled':''}>${resolved?'Confirmar y guardar':action==='open'?'Reabrir pendiente':'Guardar que no aplica'}</button><button type="button" id="pending-cancel">Cancelar</button></div>
    <p class="library-note">${row.pre_draft?"Al resolver los puntos necesarios, se redactará esta solicitud con las decisiones registradas. Confirmar un punto no aprueba el oficio.":"Se guarda esta decisión. La respuesta mantiene su texto y queda pendiente de revisión."}</p></form>`};
}

export function factForm(actor) {
  return `<form id="pending-fact-form"><p>Registra un hecho que conoces o comprobaste. Se conserva como aporte atribuido; después podrás seleccionarlo como respaldo de la decisión.</p><label class="field">Información comprobada<textarea name="text" required maxlength="6000" rows="3"></textarea></label><label class="field">Cómo la comprobaste<textarea name="basis" required maxlength="3000" rows="2"></textarea></label><label class="field">Fecha de la comprobación<input name="observed_at" type="date" required></label><label class="field">Tu nombre<input name="author" required maxlength="240" value="${esc(actor)}"></label><p id="pending-error" role="alert"></p><div class="scope-actions"><button type="submit" class="primary">Guardar aporte</button><button type="button" id="pending-cancel">Cancelar</button></div></form>`;
}
