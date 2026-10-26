import {esc} from './views.js';
import {icon} from './inbox-icons.js';

export function responseReading(review={}, {reviewer='',busy=false,error=''}={}){
  const state=review.reading_confirmation||{};
  const message=state.confirmed
    ?`Revisión de todas las respuestas guardada · ${state.reviewed_by}`
    :state.changed_since_confirmation?'El contenido cambió. Revisa la versión actual y confirma de nuevo.'
    :state.eligible?'Confirma que leíste y revisaste todas las respuestas propuestas por la IA.'
    :'Podrás confirmar cuando estén guardadas todas las respuestas actuales.';
  return `<section class="response-reading${state.confirmed?' is-confirmed':''}" aria-label="Revisión conjunta de respuestas">
    <div><p data-reading-status role="status" tabindex="-1">${state.confirmed?icon('check'):icon('file')}<span>${esc(message)}</span></p>
    ${!reviewer&&!state.confirmed&&state.eligible?'<label class="response-reading-actor">Tu nombre<input id="response-reading-actor" autocomplete="name" maxlength="240" required></label>':''}
    ${error?`<p class="response-reading-error" role="alert">${esc(error)}</p>`:''}</div>
    ${state.confirmed?'':`<button type="button" class="response-reading-button" data-action="live-confirm-responses"${!state.eligible||busy?' disabled':''}>${busy?'<span class="source-spinner" aria-hidden="true"></span> Guardando revisión…':`${icon('check')} Ya revisé todas las respuestas`}</button>`}
  </section>`;
}
