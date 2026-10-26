// Aceptar la propuesta es una decisión explícita, no una comprobación inventada.
export const acceptedProposalNote='Confirmación conjunta: se acepta la propuesta de análisis mostrada.';
export const continuedDecisionNote='Confirmación conjunta: se revisó el análisis mostrado y se decidió continuar a preparar respuestas. Las observaciones del análisis se conservan.';

const alternativeNotes={
  complement:'solicitar complemento',
  reject:'revisar la propuesta de rechazo',
  reiterate:'revisar la respuesta por reiteración',
  specialist:'remitir a revisión especializada',
};
export function automaticDecisionNote(route){
  if(route==='continue')return continuedDecisionNote;
  if(!Object.hasOwn(alternativeNotes,route))throw new Error('Selecciona una ruta válida.');
  return `Confirmación conjunta: se eligió ${alternativeNotes[route]}, sin observación adicional.`;
}
export function isAutomaticDecisionNote(note){
  return [acceptedProposalNote,continuedDecisionNote,...Object.keys(alternativeNotes).map(automaticDecisionNote)].includes(note);
}

export function decisionContinues(decision){
  return decision.document.route==='continue'&&decision.requests.every(r=>r.route==='continue');
}

export function confirmationPayload(decision,report){
  const {case_id,...body}=decision;
  if(!body.reviewed_by.trim())throw new Error('Indica quién revisó el trámite.');
  if(!body.document.reviewed||body.requests.some(r=>!r.reviewed))throw new Error('Confirma la revisión conjunta del resumen y las peticiones.');
  const fill=item=>{
    if(item.route==='continue'&&item.petition_type==='undetermined')throw new Error('Define el tipo de cada petición antes de continuar.');
    return {...item,note:item.note.trim()||automaticDecisionNote(item.route)};
  };
  return {...body,reviewed_by:body.reviewed_by.trim(),document:fill(body.document),requests:body.requests.map(fill)};
}

// Guardar primero permite reintentar la preparación sin duplicar la decisión.
export async function confirmAndPrepare({saved,decision,report,save,onSaved,onPreparing=()=>{},prepare}){
  let value=saved;
  if(!value){value=await save(confirmationPayload(decision,report));onSaved(value);}
  if(!value.can_prepare||!decisionContinues(decision))return {prepared:false};
  onPreparing();
  try{const preparation=await prepare();return {prepared:true,preparation};}
  catch(error){return {prepared:false,error:'La revisión quedó guardada, pero no se pudo confirmar el inicio de la preparación. Actualiza el estado antes de reintentar. '+error.message};}
}
