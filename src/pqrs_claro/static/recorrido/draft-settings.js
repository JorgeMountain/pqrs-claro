import {esc} from './views.js';
import {icon} from './inbox-icons.js';

const fields={recipient:'Destinatario',subject:'Asunto',city:'Ciudad',issue_date:'Fecha del oficio',received_date:'Fecha de recepción (opcional)',office_number:'Número de oficio (opcional)',petition_number:'Radicado (opcional)',recipient_contact:'Contacto del destinatario (opcional)'};
function input(work,key,label){
  return `<label>${label}<input data-meta="${key}" type="${key.endsWith('date')?'date':'text'}" value="${esc(work.metadata[key]||'')}" maxlength="${key==='subject'?600:300}"></label>`;
}
export function draftSettings(work,actor){
  return `<form class="document-settings">
    <details data-office-details><summary>${icon('file')}Datos del oficio${icon('chevron-down')}</summary><div class="document-fields">${Object.entries(fields).map(([key,label])=>input(work,key,label)).join('')}</div></details>
    <details data-responsible-details><summary>${icon('user')}Responsable y firma${icon('chevron-down')}</summary><div class="document-fields">${input(work,'signer_name','Nombre de quien suscribe')}${input(work,'signer_role','Cargo de quien suscribe')}</div><label class="field">Responsable de esta sesión<input id="office-actor" required maxlength="240" value="${esc(actor)}" autocomplete="name"></label><p class="small muted">Los datos del firmante se incluyen en el oficio. No se añade una firma digital.</p></details>
    ${work.attachment_options?.length||work.attachment_source_ids?.length?`<details data-attachment-details><summary>${icon('file')}Anexos${icon('chevron-down')}</summary><fieldset class="document-attachments"><legend>Documentos citados para anexar</legend>${(work.attachment_options||[]).map(a=>`<label><input type="checkbox" data-attachment="${esc(a.source_id)}" ${(work.attachment_source_ids||[]).includes(a.source_id)?'checked':''}>${esc(a.title)}</label>`).join('')||'<p>No hay documentos citados disponibles para anexar.</p>'}</fieldset></details>`:''}
  </form>`;
}
