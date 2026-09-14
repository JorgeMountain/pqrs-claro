import {esc} from './views.js';

export function documentTarget(row,p) {
  const supports=row.available_supports||[],ids=p.linked_chunk_ids||[];
  let targets=supports.filter(s=>ids.includes(s.chunk_id));
  if(!targets.length)targets=supports.filter(s=>(p.linked_source_ids||[]).includes(s.source_id));
  return new Set(targets.map(s=>s.source_id)).size===1?targets[0]:null;
}

export function documentDecisionForm(row,p,choice,actor) {
  const s=documentTarget(row,p);
  if(!s)throw new Error('No se identificó una única versión. Consulta los archivos antes de confirmar.');
  const labels={issued:'Confirmar versión expedida',draft:'Confirmar documento de trabajo',provenance_reviewed:'Confirmar revisión del archivo'};
  const explanation=choice==='draft'?'Se registrará como documento de trabajo. La IA no debe presentarlo como una respuesta oficial expedida.':choice==='issued'?'Confirmas que este archivo es la versión expedida. Esto no certifica todos sus hechos ni la entrega de anexos.':'Confirmas que revisaste la procedencia y el contenido de este archivo para utilizarlo como antecedente.';
  return {source:s,html:`<form id="pending-decision-form"><p><strong>${esc(s.title)}</strong></p><p>Versión ${esc(s.version)}</p><a target="_blank" rel="noopener" href="/api/sources/${encodeURIComponent(s.source_id)}/original?case_id=${encodeURIComponent(row.case_id)}">Abrir este archivo ↗</a><p>${explanation}</p><label class="field">Tu nombre<input id="pending-actor" required maxlength="240" autocomplete="name" value="${esc(actor)}"></label><p class="library-note">Se guardarán tu elección, el archivo, su versión y la fecha. No necesitas adjuntar otro soporte ni escribir una explicación.</p><p id="pending-error" role="alert"></p><div class="scope-actions"><button class="primary" type="submit">${labels[choice]}</button><button type="button" id="pending-cancel">No lo sé / Volver</button></div></form>`};
}
