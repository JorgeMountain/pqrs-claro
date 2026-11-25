import {icon} from './inbox-icons.js';
import {esc} from './views.js';
import {adminReviewUrl} from './fiaga-admin-review.js';

export const stages = {
  admin_review: 'Análisis y borrador · En revisión',
  preparing: 'En preparación', initial_review: 'Revisión de faltantes', pool: 'En trámite',
  integration: 'Integrando aportes', final_review: 'Revisión final', approved: 'Aprobado',
};

export function caseLink(caseId) {
  return '/?expediente=' + encodeURIComponent(caseId);
}

export function adminReviewLink(caseId, hash = '') {
  const key = hash.replace(/^#/, '').split('/')[0];
  const steps = {preanalisis:0, documento:0, peticiones:1, redaccion:2, borrador:3};
  return adminReviewUrl(caseId, Object.hasOwn(steps, key) ? steps[key] : undefined);
}

export function stateChip(stage, compact = false) {
  const label = stages[stage] || stage;
  const text = compact && stage === 'admin_review' ? 'En revisión' : label;
  return `<span class="chip stage-${esc(stage)}"${text !== label ? ` title="${esc(label)}"` : ''}>${esc(text)}</span>`;
}

function caseList(items, actor, {recent = false} = {}) {
  return `<ul class="case-list">${items.map(item => {
    const file = item.filename || '';
    let name = item.subject?.trim() || file;
    if (recent && name === file) {
      name = file.replace(/\.pdf$/i, '').replace(/_/g, ' ').replace(/\s+/g, ' ').trim() || file;
    }
    const reference = [item.case_number, file !== name ? file : ''].filter(Boolean).join(' · ');
    const editor = actor === 'admin' && item.stage === 'admin_review';
    const url = editor ? adminReviewLink(item.case_id) : caseLink(item.case_id);
    return `<li><a ${editor ? 'data-open-editor' : 'data-home'} href="${url}">
      ${recent ? `<span class="recent-file-icon" aria-hidden="true">${icon('file')}</span>` : ''}
      <div class="case-main"><strong>${esc(name || 'Solicitud PQRS')}</strong>${reference ? `<span class="list-detail" title="${esc(reference)}">${esc(reference)}</span>` : ''}</div>
      <div class="case-status">${stateChip(item.stage, recent)}${item.error ? '<span>Requiere reintento</span>' : ''}</div>
      <span class="list-arrow">${icon('arrow-right')}</span></a></li>`;
  }).join('')}</ul>`;
}

function taskList(items, actor, managers) {
  return `<ul class="case-list task-list">${items.map(item => {
    const task = item.task;
    const assignee = managers.find(person => person.id === task.manager_id)?.name || task.manager_id;
    const context = [item.case_number, item.subject || item.filename, task.request_id].filter(Boolean).join(' · ');
    let status = 'Turno abierto';
    if (task.status === 'claimed') status = 'En gestión';
    else if (assignee) status = task.manager_id === actor ? 'Reservado para ti' : 'Reservado para ' + assignee;
    return `<li><a data-home href="${caseLink(item.case_id)}">
      <div class="case-main"><span class="case-ref">${esc(task.department)}</span><strong>${esc(task.instruction)}</strong>
      <span class="list-detail">${esc(context)}</span></div>
      <span class="chip">${esc(status)}</span><span class="list-arrow">${icon('arrow-right')}</span></a></li>`;
  }).join('')}</ul>`;
}

function pageHeading(title, description, action = '') {
  return `<div class="page-head reception-heading"><div><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
}

const poolLink = '<a class="button" data-home href="/#pool">Ver trámites disponibles</a>';
const refresh = `<button class="quiet" type="button" data-command="refresh">${icon('refresh')}Actualizar</button>`;

function queueView(items, page, actor, managers) {
  const isPool = page === 'pool';
  const visible = items.filter(({stage, task}) => {
    if (stage !== 'pool' || !task) return false;
    if (!isPool) return task.status === 'claimed' && task.owner_id === actor;
    return task.status === 'available' && (actor === 'admin' || !task.manager_id || task.manager_id === actor);
  });
  const title = isPool ? 'Pool de trámites' : 'Mi trabajo';
  const description = isPool ? 'Aquí aparecen los faltantes que ya tienen turno en su expediente.'
    : 'Abre un trámite que hayas tomado para entregar la respuesta o adjuntar su soporte.';
  const empty = isPool ? 'No hay trámites disponibles.' : 'Todavía no tienes trámites en gestión.';
  const hint = isPool ? 'Los turnos se habilitan en el orden definido por el administrador.' : 'Elige un turno disponible en el pool para empezar.';
  return `${pageHeading(title, description, !isPool ? poolLink : '')}
    <section class="panel"><div class="section-head"><h2>${isPool ? 'Turnos disponibles' : 'Trámites en gestión'} <span class="list-count">${visible.length}</span></h2>${refresh}</div>
      ${visible.length ? taskList(visible, actor, managers) : `<div class="list-empty"><h3>${empty}</h3><p>${hint}</p></div>`}
    </section>`;
}

function trackingView(items, actor) {
  const receive = actor === 'admin' ? '<a class="button" data-home href="/">Recibir solicitud</a>' : '';
  return `${pageHeading('Expedientes', 'Consulta la etapa de cada solicitud y abre su borrador, sus peticiones o su historial.', receive)}
    <section class="panel"><div class="section-head"><h2>Solicitudes recibidas <span class="list-count">${items.length}</span></h2>${refresh}</div>
      ${items.length ? caseList(items, actor) : '<div class="list-empty"><p>Aún no se han recibido solicitudes en este recorrido.</p></div>'}
    </section>`;
}

function pdfForm() {
  return `<form id="upload" class="pdf-channel" aria-labelledby="pdf-heading">
    <label class="pdf-picker">
      <span class="channel-icon" aria-hidden="true">${icon('upload')}</span>
      <strong class="drop-hint" id="pdf-drop-hint">Arrastra la solicitud en PDF</strong>
      <span class="drop-help">Puedes revisar el original antes de recibirlo.</span>
      <span class="pick-action" id="pdf-pick-action" data-file-label>Elegir archivo</span>
      <input type="file" name="file" accept=".pdf,application/pdf" aria-labelledby="pdf-pick-action" aria-describedby="pdf-drop-hint selected-file" required>
    </label>
    <div class="selected-pdf"><p id="selected-file" data-file-summary role="status"></p>
      <a data-file-preview target="_blank" rel="noopener noreferrer" hidden>Revisar PDF <span class="sr-only">(abre otra pestaña)</span>${icon('external-link')}</a></div>
    <div class="receipt-confirm" hidden><details class="receipt-fields"><summary>Datos de recepción (opcionales)</summary>
      <div class="receipt-fields-grid">
        <label class="field">Asunto<input name="subject" maxlength="240"></label>
        <label class="field">Radicado<input name="reference" maxlength="100"></label>
        <label class="field">Fecha de recepción<input type="date" name="received_date"></label>
        <label class="field">Fecha límite registrada<input type="date" name="due_date"></label>
      </div></details>
      <button class="primary channel-action" type="submit"><span>Recibir e iniciar preanálisis</span> ${icon('arrow-right')}</button></div>
  </form>`;
}

function receiptView(items) {
  return `<div class="reception-desk">${pageHeading('Recepción de solicitudes', 'Recibe una PQRS o retoma un expediente reciente.')}
    <div class="receipt-channels">
      <section class="panel receipt-intake" aria-labelledby="pdf-heading">
        <div class="reception-panel-head"><h2 id="pdf-heading">Nueva solicitud</h2></div>
        ${pdfForm()}
        <a class="email-channel" data-home href="/#correo"><span class="channel-icon" aria-hidden="true">${icon('mail')}</span>
          <span>Recibir desde Gmail</span><span class="list-arrow" aria-hidden="true">${icon('arrow-right')}</span></a>
      </section>
      <section class="panel recent-cases" aria-labelledby="recent-heading"><div class="recent-heading"><h2 id="recent-heading">Solicitudes recientes</h2>
        <a class="all-cases" href="/#expedientes" data-home>Ver expedientes ${icon('arrow-right')}</a></div>
        ${items?.length ? caseList(items.slice(0, 3), 'admin', {recent:true})
          : `<div class="list-empty"><p>${items ? 'Aquí aparecerán las solicitudes que recibas.' : 'La lista de solicitudes recientes no está disponible.'}</p></div>`}
      </section>
    </div></div>`;
}

export function homeView(items, {page, actor, managers}) {
  if (page === 'expedientes') return trackingView(items, actor);
  if (page === 'pool' || page === 'trabajo') return queueView(items, page, actor, managers);
  return actor === 'admin' ? receiptView(items) : queueView(items, 'trabajo', actor, managers);
}

export function bindReceipt(form) {
  const input = form.elements.file;
  const summary = form.querySelector('[data-file-summary]');
  const preview = form.querySelector('[data-file-preview]');
  const picker = form.querySelector('.pdf-picker');
  const fileLabel = form.querySelector('[data-file-label]');
  const confirm = form.querySelector('.receipt-confirm');
  let url;

  function clearPreview() {
    if (url) URL.revokeObjectURL(url);
    url = undefined;
    preview.hidden = true;
    preview.removeAttribute('href');
  }

  input.addEventListener('dragenter', () => picker.classList.add('dragging'));
  for (const eventName of ['dragleave', 'drop', 'dragend']) {
    input.addEventListener(eventName, () => picker.classList.remove('dragging'));
  }
  input.addEventListener('change', () => {
    clearPreview();
    const file = input.files[0];
    const invalid = file && (!file.size || !/\.pdf$/i.test(file.name));
    const error = invalid ? 'Elige un archivo PDF que contenga la solicitud.' : '';
    input.setCustomValidity(error);
    input.setAttribute('aria-invalid', String(Boolean(error)));
    confirm.hidden = !file || Boolean(error);
    fileLabel.textContent = confirm.hidden ? 'Elegir archivo' : 'Cambiar archivo';
    summary.classList.toggle('invalid-file', Boolean(error));
    if (!file || invalid) {
      summary.textContent = error;
      return;
    }
    const size = file.size < 1048576 ? Math.max(1, Math.round(file.size / 1024)) + ' KB'
      : new Intl.NumberFormat('es-CO', {maximumFractionDigits: 1}).format(file.size / 1048576) + ' MB';
    summary.textContent = file.name + ' · ' + size;
    url = URL.createObjectURL(new Blob([file], {type: 'application/pdf'}));
    preview.href = url;
    preview.hidden = false;
  });
  return clearPreview;
}
