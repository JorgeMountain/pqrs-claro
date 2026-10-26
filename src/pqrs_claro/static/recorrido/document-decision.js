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
  const explanation=choice==='draft'?'Se registrará como documento de trabajo. La IA no debe presentarlo como una respuesta oficial expedida.':choice==='issued'?'Confirmas que este archivo es la versión expedida. Esto no certifica todos sus hechos ni la entrega de anexos.':'Confirmas que revisaste la procedencia y el contenido de este archivo. Esta revisión no confirma por sí sola su vigencia ni todos los hechos que menciona.';
  return {source:s,html:`<form id="pending-decision-form" class="pending-guided-form"><div class="pending-task-context"><span class="pending-kind">Revisar un archivo</span><h3>Comprueba el documento original</h3><p>${esc(p.description)}</p></div><section class="pending-guide-step"><h3><span>1</span> Revisa este archivo</h3><div class="pending-document-preview"><h4>${esc(s.title)}</h4><p class="pending-help">Versión ${esc(s.version)} · ${s.location_kind==='section'?'Sección':'Página'} ${esc(s.page)}</p><a target="_blank" rel="noopener" href="/api/sources/${encodeURIComponent(s.source_id)}/original?case_id=${encodeURIComponent(row.case_id)}${s.location_kind!=='section'?'#page='+Number(s.page||1):''}">Abrir documento original ↗</a><details><summary>Consultar el fragmento relacionado</summary><blockquote tabindex="0">${esc(s.quote)}</blockquote></details></div></section><section class="pending-guide-step"><h3><span>2</span> Guarda tu revisión</h3><p>${explanation}</p><label class="field">Tu nombre<input id="pending-actor" required maxlength="240" autocomplete="name" value="${esc(actor)}"></label></section><div class="pending-form-footer"><p id="pending-error" role="alert"></p><div class="scope-actions"><button class="primary" type="submit">${labels[choice]}</button><button type="button" id="pending-cancel">Volver sin confirmar</button></div><p class="pending-help">Se guarda tu revisión con el archivo, su versión y la fecha. No necesitas subirlo de nuevo.</p></div></form>`};
}
