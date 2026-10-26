import {esc} from './views.js';
import {documentTarget} from './document-decision.js';

// Orienta la acción sin convertir un candidato en un respaldo confirmado.
export function pendingGuidance(p){
  if(p.state==='analysis_error')return {label:'Problema de lectura o análisis',help:'Reintenta el análisis para recuperar la información. No necesitas aportar una confirmación.',example:''};
  if(p.stage==='fulfillment'&&p.blocks_approval===false)return {label:'Actuación posterior',help:'Registra el respaldo cuando esta actuación se haya realizado. Puede hacerse después de revisar el contenido.',example:'Indica qué se realizó y dónde queda registrado.'};
  if(p.reason_code==='provenance')return {label:'Revisar un archivo',help:'Abre el original y comprueba su procedencia y contenido. Si ya está disponible, no necesitas volver a subirlo.',example:'Describe qué comprobaste sobre el origen y el contenido del archivo.'};
  if(p.reason_code==='validity')return {label:'Verificar vigencia',help:'Revisa una versión oficial o una actualización que permita confirmar si esta disposición sigue vigente y aplica al caso.',example:'Indica qué fuente confirma la vigencia y por qué aplica a esta petición.'};
  if(p.reason_code==='issued_version')return {label:'Identificar la versión',help:'Consulta el original para distinguir una versión expedida de un documento de trabajo.',example:''};
  if(p.kind==='document')return {label:'Aportar un documento',help:'Usa un documento disponible o sube el archivo que permita comprobar este punto.',example:'Explica qué parte del documento resuelve lo solicitado.'};
  return {label:'Completar información',help:'Busca la información en una fuente disponible. Si no está, sube un documento que la respalde.',example:'Indica qué información comprobaste en el fragmento y cómo responde a este punto.'};
}

export function pendingAction(row,p){
  const target=documentTarget(row,p);
  return target&&p.reason_code==='provenance'?'provenance_reviewed':target&&p.reason_code==='issued_version'?'document_choice':'resolved';
}

export function pendingContext(p){
  const guide=pendingGuidance(p);
  return `<div class="pending-task-context"><span class="pending-kind">${esc(guide.label)}</span><h3>${esc(p.description)}</h3>${p.why_unresolved?`<div class="pending-gap"><strong>Qué falta comprobar</strong><p>${esc(p.why_unresolved)}</p></div>`:''}<p class="pending-guidance">${esc(guide.help)}</p></div>`;
}
