import {esc} from './views.js';

// El progreso conserva su DOM: reemplazar todas las barras antes de añadir la actual.
export function renderCaseNavigation(view,current,{step=1,showMail=false}={}){
  view.querySelectorAll(':scope > .gmail-origin').forEach(node=>node.remove());
  const queue=current.management?'<button data-action="live-queue">Volver a la bandeja</button>':'';
  const mail=step===1&&showMail?'<button data-action="live-mail-origin">Ver correos del expediente</button>':'';
  const origin=step===1&&current.origin?.kind==='gmail'?`<span>Recibida por Gmail${current.origin.reported_case_number?' · Caso '+esc(current.origin.reported_case_number):''}</span>`:'';
  if(queue||mail)view.insertAdjacentHTML('afterbegin',`<div class="gmail-origin">${origin}${queue}${mail}</div>`);
}
