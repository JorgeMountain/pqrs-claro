export function pilotReviewControls(current,value,{busy=false}={}){
  if(!current.identification||current.management?.state==='closed')return '';
  const active=value.pilot_bypass_active;
  const blocked=busy||current.analysis_running||value.status==='running';
  return `<section class="alert" aria-label="Opción del piloto"><strong>${active?'Piloto: revisión inicial sin bloqueo':'Continuar con la demostración'}</strong><p>${active?'Se conserva el análisis como referencia, sin aprobar sus observaciones. Las fuentes y las respuestas siguen comprobándose.':'Puedes continuar con las peticiones identificadas sin aprobar ni actualizar el análisis inicial. Se registrará esta elección para este expediente.'}</p><div class="dialog-actions"><button type="button" class="primary" data-action="live-pilot-continue" ${blocked?'disabled':''}>${active?'Preparar respuestas →':'Continuar sin revisión inicial — piloto →'}</button>${active?`<button type="button" data-action="live-pilot-require" ${blocked?'disabled':''}>Volver a exigir revisión inicial</button>`:''}</div>${blocked?'<p>Espera a que termine el proceso en curso.</p>':''}</section>`;
}
