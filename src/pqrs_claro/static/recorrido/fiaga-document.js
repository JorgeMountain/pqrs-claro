import {esc} from './views.js';
import {icon} from './inbox-icons.js';
import {caseLink} from './fiaga-home.js';

const checks = {
  requester: {title: 'Datos del solicitante', pass: 'Identificados', description: 'Nombre y medio de contacto consignados en la solicitud.'},
  respect: {title: 'Lenguaje de la solicitud', pass: 'Sin alertas', description: 'Revisión de insultos, groserías o amenazas en su contexto.'},
  integrity: {title: 'Legibilidad e integridad', pass: 'Sin indicios de problemas', description: 'Revisión de páginas ilegibles, vacías o con texto incompleto.'},
};

export function originLabel(detail) {
  if (detail.origin?.kind !== 'gmail') return 'Archivo PDF';
  return detail.origin.primary === 'body' ? 'Cuerpo del correo' : 'PDF adjunto al correo';
}

export function originalReferences(refs, detail) {
  const rows = (refs || []).filter(ref => Number.isInteger(ref.page) && ref.page >= 1);
  if (!rows.length) return '';
  return `<details class="doc-references"><summary>Consultar fragmentos del original (${rows.length})</summary>
    <ul>${rows.map(ref => `<li>${ref.quote ? `<blockquote>${esc(ref.quote)}</blockquote>` : ''}
      <a data-home href="${caseLink(detail.case_id)}#documento/${ref.page}">Ver página ${ref.page}</a>
      ${ref.line_start ? `<span> · Línea${ref.line_end > ref.line_start ? 's' : ''} ${esc(ref.line_start)}${ref.line_end > ref.line_start ? '–' + esc(ref.line_end) : ''}</span>` : ''}</li>`).join('')}</ul></details>`;
}

function readingResult(detail) {
  const pages = detail.reading?.pages || [];
  if (!pages.length) return '';
  const uncertain = pages.filter(page => (page.needs_review || page.method === 'ocr') && Number.isInteger(page.number) && page.number > 0);
  const count = pages.length === 1 ? '1 página leída' : pages.length + ' páginas leídas';
  const links = uncertain.map(page => `<a data-home href="${caseLink(detail.case_id)}#documento/${page.number}">pág. ${page.number}${page.method === 'ocr' ? ' (OCR)' : ''}</a>`);
  return `<p class="exp-muted">${count}.${links.length ? ' Revisión visual de ' + links.join(', ') + '.' : ''}</p>`;
}

function checkRow(detail, key, check) {
  const value = detail.checks?.[key];
  const step = detail.progress?.steps?.checks;
  const active = detail.stage === 'preparing' && !detail.error && !['done', 'error'].includes(step);
  const state = value?.state;
  const labels = {pass: check.pass, attention: 'Requiere atención', unverified: 'Por verificar'};
  const reported = Object.hasOwn(labels, state);
  const label = reported ? labels[state] : active ? (step === 'running' ? 'Verificando' : 'En espera') : 'Sin resultado';
  const missingData = state === 'unverified' ? 'Por verificar' : 'Sin identificar';
  const description = value?.summary || (active ? check.description : 'Este expediente no tiene un resultado guardado para esta verificación.');
  return `<li data-check="${key}"><div class="exp-row-head"><h3>${check.title}</h3>
      <span class="chip ${reported ? 'check-' + state : ''}">${label}</span></div>
    ${key === 'requester' && value ? `<dl class="doc-meta"><dt>Nombre</dt><dd>${esc(value.name || missingData)}</dd>
      <dt>Contacto</dt><dd>${esc(value.contact || missingData)}</dd></dl>` : ''}
    <p>${esc(description)}</p>${key === 'integrity' ? readingResult(detail) : ''}
    ${originalReferences(value?.refs, detail)}</li>`;
}

function checksPanel(detail) {
  return `<section class="panel exp-checks"><div class="section-head"><h2>Verificaciones del documento</h2></div>
    <ul>${Object.entries(checks).map(([key, check]) => checkRow(detail, key, check)).join('')}</ul></section>`;
}

export function updateDocumentChecks(workspace, detail) {
  const rows = workspace.querySelectorAll('.exp-checks > ul > [data-check]');
  for (const row of rows) {
    const key = row.dataset.check;
    const template = document.createElement('template');
    template.innerHTML = checkRow(detail, key, checks[key]);
    const next = template.content.firstElementChild;
    if (row.querySelector('.doc-references')?.open && next.querySelector('.doc-references')) {
      next.querySelector('.doc-references').open = true;
    }
    if (!row.isEqualNode(next)) row.replaceWith(next);
  }
}

export function documentPanel(detail, page) {
  const base = '/api/cases/' + encodeURIComponent(detail.case_id);
  const email = detail.origin?.kind === 'gmail';
  return `<div class="exp-split"><section class="panel document-reader" data-page="${page}" aria-label="Lector del documento">
    <div class="section-head"><h2>Documento recibido</h2>
      <a class="reader-original" href="${base}/original" target="_blank" rel="noopener">Abrir PDF ${icon('external-link')}</a></div>
    <div class="reader-tools"><span class="reader-name">${icon(email ? 'mail' : 'file')}${esc(detail.filename || originLabel(detail))}</span>
      <button type="button" class="reader-zoom" data-reader-zoom aria-pressed="false">Ampliar página</button>
      <nav aria-label="Páginas del documento"><button type="button" data-reader-prev aria-label="Página anterior" disabled>${icon('arrow-left')}</button>
      <span data-reader-position aria-live="polite">Página ${page}</span>
      <button type="button" data-reader-next aria-label="Página siguiente" disabled>${icon('arrow-right')}</button></nav></div>
    <p data-reader-error hidden class="exp-note" role="status"></p>
    <div class="reader-paper" tabindex="0" aria-label="Página del documento, desplázate para leerla">
      <img data-reader-image alt="Página ${page} del documento recibido"></div>
    <details data-reader-text hidden><summary>Leer el texto de esta página</summary><p></p></details></section>
    <div class="column">${checksPanel(detail)}${email ? `<section class="panel panel-body"><h2>Correo recibido</h2>
      <dl class="doc-meta"><dt>Documento principal</dt><dd>${esc(originLabel(detail))}</dd>
      ${detail.origin.sender ? `<dt>Remitente</dt><dd>${esc(detail.origin.sender)}</dd>` : ''}
      ${detail.origin.subject ? `<dt>Asunto</dt><dd>${esc(detail.origin.subject)}</dd>` : ''}</dl>
      <a data-home href="${caseLink(detail.case_id)}#correo-original">Consultar correo original</a></section>` : ''}</div></div>`;
}

export function bindDocumentReader(workspace, detail) {
  const reader = workspace.querySelector('.document-reader');
  if (!reader) return;
  const image = reader.querySelector('[data-reader-image]');
  const prev = reader.querySelector('[data-reader-prev]');
  const next = reader.querySelector('[data-reader-next]');
  const position = reader.querySelector('[data-reader-position]');
  const plain = reader.querySelector('[data-reader-text]');
  const error = reader.querySelector('[data-reader-error]');
  const paper = reader.querySelector('.reader-paper');
  const zoom = reader.querySelector('[data-reader-zoom]');
  zoom.onclick = () => {
    const enlarged = paper.classList.toggle('reader-enlarged');
    zoom.setAttribute('aria-pressed', String(enlarged));
  };
  const base = '/api/cases/' + encodeURIComponent(detail.case_id) + '/pages/';
  let current = Number(reader.dataset.page);
  let count = 0;
  let version = 0;

  function inform(message) {
    error.textContent = message;
    error.hidden = !message;
  }
  async function show(number, writeHash = false) {
    const ticket = ++version;
    current = number;
    if (writeHash) history.replaceState(history.state, '', caseLink(detail.case_id) + '#documento/' + number);
    const png = base + number + '.png';
    image.onerror = () => {
      if (ticket === version && reader.isConnected) {
        image.hidden = true;
        inform('No se pudo mostrar esta página. Puedes abrir el PDF completo.');
      }
    };
    image.hidden = false;
    image.alt = 'Página ' + number + ' del documento recibido';
    image.src = png;
    paper.scrollTop = 0;
    plain.hidden = true;
    plain.open = false;
    inform('');
    function controls() {
      prev.disabled = number <= 1;
      next.disabled = !count || number >= count;
      position.textContent = 'Página ' + number + (count ? ' de ' + count : '');
    }
    controls();
    try {
      const response = await fetch(base + number + '/view');
      if (ticket !== version || !reader.isConnected) return;
      if (response.status === 404 && number !== 1) return show(1, true);
      if (!response.ok) throw new Error();
      const meta = await response.json();
      if (ticket !== version || !reader.isConnected) return;
      count = meta.page_count;
      controls();
      plain.querySelector('p').textContent = meta.text || '';
      plain.hidden = !meta.text?.trim();
    } catch {
      if (ticket === version && reader.isConnected) inform('No se pudo consultar el detalle de la página. Puedes abrir el PDF completo.');
    }
  }
  prev.onclick = () => void show(current - 1, true);
  next.onclick = () => void show(current + 1, true);
  void show(current);
}
