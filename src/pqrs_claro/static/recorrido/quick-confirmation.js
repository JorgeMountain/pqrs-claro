// Interaction for the isolated demonstration; it never writes a live case.
const PRIMARY_SOURCE = '3438152dd8c843e389d5b8051ead331e';
export const scopeStatement = 'El antecedente de la oferta espejo de 2019-2 aplica al semestre y a las asignaturas de esta solicitud. La respuesta no afirma que todas las versiones de los programas sean idénticas.';
export const demoActor = 'Revisor de demostración (simulado)';

export function selectedSupport(request) {
  return request.sources.find(source => source.document_id === PRIMARY_SOURCE && source.quote && source.version);
}
export function recordDecision(state, request, action, reason = '') {
  state.scopeHistory ||= [];
  const event = {
    id: crypto.randomUUID(), action, reason, actor: demoActor,
    recordedAt: new Date().toISOString(), simulation: true,
    requestId: request.request_id, requestText: request.original_text,
    statement: scopeStatement,
    response: request.paragraphs.map(p => p.text),
    supports: request.sources.map(source => ({documentId:source.document_id,
      title:source.title, version:source.version, page:source.page,
      locationKind:source.location_kind, quote:source.quote})),
    supersedes: state.scopeDecision?.id || null,
  };
  state.scopeHistory.push(event);
  state.scopeDecision = event;
  state.confirm = false;
  state.approved = false;
  return event;
}
export function confirmScope(state, request) {
  if (state.scenario !== 'pending' || state.edits[1] ||
      state.scopeDecision?.action === 'not_applicable' || !selectedSupport(request)) return false;
  recordDecision(state, request, 'confirmed');
  state.scenario = 'ready';
  return true;
}
export function reopenScope(state, request) {
  if (!['confirmed','not_applicable'].includes(state.scopeDecision?.action)) return false;
  recordDecision(state, request, 'reopened');
  state.scenario = 'pending';
  return true;
}
const when = value => new Intl.DateTimeFormat('es-CO', {dateStyle:'short',timeStyle:'short'}).format(new Date(value));
export function scopeHistory(state, esc) {
  if (!state.scopeHistory?.length) return '';
  const names = {confirmed:'Aplicación confirmada',not_applicable:'Antecedente no aplicable',reopened:'Decisión reabierta'};
  return `<details class="scope-history"><summary>Historial de prueba · ${state.scopeHistory.length} ${state.scopeHistory.length===1?'decisión':'decisiones'}</summary><p class="muted">Se conserva durante esta sesión de la maqueta. No es un registro institucional.</p>${[...state.scopeHistory].reverse().map(event=>`<section class="scope-event"><strong>${names[event.action]}</strong><small>${esc(event.actor)} · ${esc(when(event.recordedAt))}</small><p>${esc(event.reason || event.statement)}</p><details><summary>Ver solicitud y soportes registrados</summary><p>${esc(event.requestText)}</p>${event.supports.map(source=>`<p><strong>${esc(source.title)}</strong> · versión ${esc(source.version)} · ${source.locationKind==='section'?'sección':'página'} ${esc(source.page)}</p><blockquote>${esc(source.quote)}</blockquote>`).join('')}</details></section>`).join('')}</details>`;
}
export function confirmationPanel(request, state, esc) {
  const record = state.scopeDecision;
  const history = scopeHistory(state, esc);
  if (state.edits[1]) return history;
  if (state.scenario === 'ready' && record?.action === 'confirmed') {
    return `<div class="scope-confirmed"><strong>✓ Aplicación confirmada</strong><p>Se confirmó el alcance del antecedente para esta solicitud. La aprobación del oficio sigue siendo un paso separado.</p><small>${esc(record.actor)} · ${esc(when(record.recordedAt))}</small><div class="scope-actions"><button class="text-button" data-action="scope-support">Ver respaldo</button><button class="text-button" data-action="scope-reopen">Reabrir decisión</button></div></div>${history}`;
  }
  if (state.scenario !== 'pending') return history;
  if (record?.action === 'not_applicable') {
    return `<div class="alert"><strong>El antecedente fue marcado como no aplicable</strong><p>${esc(record.reason)}</p><p>La respuesta propuesta sigue visible para corregirla; este antecedente no cuenta como respaldo aplicable. Hace falta revisar el alcance o aportar otro soporte.</p><div class="scope-actions"><button data-action="scope-support">Ver respaldo</button><button data-action="edit" data-index="1">Revisar respuesta</button><button data-action="scope-reopen">Reabrir decisión</button></div></div>${history}`;
  }
  const support = selectedSupport(request);
  return `<div class="alert quick-confirmation"><strong>Por confirmar: aplicación del antecedente</strong><p>${esc(scopeStatement)}</p>${support?`<div class="scope-source"><strong>${esc(support.title)}</strong><span>Versión ${esc(support.version)} · ${support.location_kind==='section'?'sección':'página'} ${esc(support.page)}</span></div>`:'<p>No está disponible el pasaje seleccionado. No puede confirmarse su aplicación.</p>'}<div class="scope-actions"><button data-action="scope-support">Ver respaldo</button><button class="primary" data-action="scope-confirm" ${support?'':'disabled'}>Confirmar que aplica</button><button data-action="scope-reject">No aplica</button></div><small>Actor de prueba: ${esc(demoActor)}. La fecha, la solicitud y los pasajes se registran automáticamente en esta sesión.</small></div>${history}`;
}

export function rejectionForm(esc) {
  return `<p>Indica la diferencia concreta para orientar la revisión. Marcar «No aplica» no da por resuelta la solicitud.</p><form id="scope-rejection-form"><label class="field">Motivo<select id="scope-rejection-reason" required><option value="">Selecciona el motivo</option><option value="period">Corresponde a otro semestre</option><option value="group">Corresponde a otro grupo o asignatura</option><option value="scope">El alcance del antecedente no responde a lo solicitado</option><option value="contradiction">Hay una contradicción por aclarar</option><option value="other">Otra diferencia concreta</option></select></label><label class="field" id="scope-detail-field" hidden>Explica la diferencia<textarea id="scope-rejection-detail" rows="3" maxlength="2000"></textarea></label><div class="dialog-actions"><button type="submit" class="primary">Registrar que no aplica</button><button type="button" id="scope-rejection-cancel">Cancelar</button></div><p id="scope-rejection-error" role="alert"></p></form>`;
}
