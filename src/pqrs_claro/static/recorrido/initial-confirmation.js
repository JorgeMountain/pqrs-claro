// Aceptar la propuesta es una decisión explícita, no una comprobación inventada.
export const acceptedProposalNote='Confirmación conjunta: se acepta la propuesta de análisis mostrada.';

export function needsDecisionNote(row,decision={},special=false){
  return special||row.proposed_route!=='continue'||(decision.route||row.proposed_route)!=='continue'
    ||row.checks.some(c=>['attention','unverified'].includes(c.state))
    ||Boolean(row.petition_type&&decision.petition_type&&decision.petition_type!==row.petition_type);
}

export function decisionContinues(decision){
  return decision.document.route==='continue'&&decision.requests.every(r=>r.route==='continue');
}

export function confirmationPayload(decision,report){
  const {case_id,...body}=decision;
  if(!body.reviewed_by.trim())throw new Error('Indica quién revisó el trámite.');
  if(!body.document.reviewed||body.requests.some(r=>!r.reviewed))throw new Error('Confirma la revisión conjunta del resumen y las peticiones.');
  const fill=(item,row,special=false)=>{
    if(needsDecisionNote(row,item,special)&&!item.note.trim())throw new Error('Explica cómo atendiste las observaciones o el cambio de decisión.');
    if(item.route==='continue'&&item.petition_type==='undetermined')throw new Error('Define el tipo de cada petición antes de continuar.');
    return {...item,note:item.note.trim()||acceptedProposalNote};
  };
  return {...body,reviewed_by:body.reviewed_by.trim(),document:fill(body.document,report.document,report.special_treatment?.detected),requests:body.requests.map(item=>fill(item,report.requests.find(r=>r.request_id===item.request_id)))};
}

// Guardar primero permite reintentar la preparación sin duplicar la decisión.
export async function confirmAndPrepare({saved,decision,report,save,onSaved,prepare}){
  let value=saved;
  if(!value){value=await save(confirmationPayload(decision,report));onSaved(value);}
  if(!value.can_prepare)return {prepared:false};
  try{await prepare();return {prepared:true};}
  catch(error){return {prepared:false,error:'La revisión quedó guardada, pero no se pudo iniciar la preparación. Puedes reintentar. '+error.message};}
}
