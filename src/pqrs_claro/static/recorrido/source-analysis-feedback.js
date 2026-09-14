import {esc} from './views.js';

const reasons={
  invalid_passage_range:'La ubicación elegida queda fuera del fragmento o tiene las líneas invertidas.',
  unknown_candidate:'La IA seleccionó un fragmento que no estaba entre las fuentes disponibles.',
  candidate_not_selected_in_supports:'El pasaje no quedó vinculado a los soportes de la afirmación.',
  empty_passage:'La ubicación seleccionada no contiene texto.',
  passage_too_long:'El pasaje seleccionado es demasiado extenso.',
  incompatible_coverage_use:'El tipo de fuente no permite respaldar esa afirmación de la forma propuesta.',
  quote_not_literal_in_candidate:'La cita propuesta no coincide con el texto de la fuente.',
  invalid_evidence_contract:'La evaluación no cumplió las comprobaciones de respaldo.',
};
const codes={
  provider_authentication:'El proveedor rechazó la configuración de acceso.',
  provider_rate_limit:'El proveedor alcanzó un límite de uso.',
  provider_timeout:'El proveedor tardó demasiado en responder.',
  provider_connection:'No se pudo completar la conexión con el proveedor.',
  provider_error:'El proveedor no pudo completar la evaluación.',
  invalid_response_schema:'La IA devolvió una evaluación con un formato no válido.',
  incomplete_response:'La evaluación de la IA quedó incompleta.',
};

export function failedRequests(mapping){
  return (mapping.results||[]).filter(r=>r.status==='error');
}

export function retryFailedAction(mapping,running){
  const count=failedRequests(mapping).length;
  if(!count||running||mapping.status==='running'||mapping.stale)return '';
  const label=count===1?'Reintentar la solicitud con error':`Reintentar las ${count} solicitudes con error`;
  return `<section class="pre-draft-notice source-retry" role="status"><div class="source-retry-copy"><strong>${count===1?'1 solicitud no pudo analizarse':`${count} solicitudes no pudieron analizarse`}</strong><p>Se conservan los análisis terminados. Estos errores se corrigen en el análisis; no requieren una confirmación tuya.</p></div><button class="primary" data-action="live-retry-failed">${label}</button><button data-action="live-collections">Fuentes de consulta</button></section>`;
}

export function analysisErrorDetail(finding){
  if(finding?.status!=='error')return '';
  const d=finding.analysis_diagnostic;
  const errors=d?.errors||[];
  return `<details class="pending-disclosure"><summary>Por qué falló este análisis</summary><p>${esc(finding.summary||'No se pudo completar la evaluación.')}</p>${d?.code&&codes[d.code]?`<p>${esc(codes[d.code])}</p>`:''}${d?.attempts?`<p>Intentos de evaluación: ${esc(d.attempts)}.</p>`:''}${errors.length?`<ul>${errors.map(e=>`<li>${esc(reasons[e.reason]||'La evaluación requiere corregir sus referencias.')}${Number.isInteger(e.line_start)&&Number.isInteger(e.line_end)?` Líneas del fragmento: ${esc(e.line_start)}–${esc(e.line_end)}${Number.isInteger(e.line_count)?` (contiene ${esc(e.line_count)} líneas)`:''}.`:''}</li>`).join('')}</ul>`:''}<p class="library-note">${d?'El diagnóstico quedó guardado para revisar este intento.':'Este intento anterior solo conserva el mensaje del error. El próximo guardará un diagnóstico detallado.'}</p></details>`;
}
