import {esc} from './views.js';
import {caseLink} from './fiaga-home.js';
import {originalReferences} from './fiaga-document.js';
import {secondaryChecksNote} from './source-analysis-feedback.js';

function requestList(detail, number, title, empty, content, notes = '') {
  const requests = detail.requests || [];
  const selected = Math.max(1, Math.min(number, requests.length));
  return `<section class="panel exp-requests"><div class="section-head"><h2>${title}</h2>
    ${requests.length ? `<span class="exp-count">${requests.length} ${requests.length === 1 ? 'petición' : 'peticiones'}</span>` : ''}</div>
    ${requests.length ? `<ol class="petition-list">${requests.map((request, i) => `<li>
      <details class="petition-record" data-request="${esc(request.id)}" ${i + 1 === selected ? 'open' : ''}>
      ${content(request, i + 1)}</details></li>`).join('')}</ol>` : `<p class="exp-note">${empty}</p>`}${notes}</section>`;
}

function petitionTitle(request, index) {
  return `<span>Petición ${index}${request.title ? ' · ' + esc(request.title) : ''}</span>`;
}

export function identificationPanel(detail, number = 1) {
  let empty = 'Este expediente no contiene peticiones identificadas.';
  if (detail.stage === 'preparing') {
    const state = detail.progress?.steps?.identification;
    if (state === 'error' || (state !== 'done' && detail.error)) empty = 'La identificación quedó pendiente de revisión.';
    else if (state === 'running') empty = 'Se están identificando las peticiones en el documento.';
    else if (state !== 'done') empty = 'La identificación comenzará después de verificar el documento.';
  }
  const warnings = detail.identification_warnings || [];
  const notes = warnings.length ? `<div class="panel-body"><h3>Observaciones de la identificación</h3>
    <ul>${warnings.map(text => `<li>${esc(text)}</li>`).join('')}</ul></div>` : '';
  const positions = new Map((detail.requests || []).map((item, index) => [item.id, index + 1]));
  return requestList(detail, number, 'Peticiones identificadas', empty, (request, index) => {
    const parent = positions.get(request.parent_id);
    return `<summary>${petitionTitle(request, index)}</summary>
      ${request.label || parent ? `<p class="exp-muted">${[
        request.label && 'Apartado ' + esc(request.label),
        parent && 'Subpetición de la petición ' + parent,
      ].filter(Boolean).join(' · ')}</p>` : ''}
      <p>${esc(request.text)}</p>
      ${originalReferences(request.source_refs, detail) || '<p class="exp-muted">Sin fragmento del original registrado.</p>'}
      <a data-home href="${caseLink(detail.case_id)}#redaccion/${index}">Consultar fuentes y redacción de esta petición</a>`;
  }, notes);
}

function sourceList(request, caseId, state) {
  const sources = [...(request.sources || []), ...(request.contribution_sources || [])];
  if (!sources.length) {
    const message = {pending: 'Búsqueda de fuentes pendiente.', running: 'Buscando respaldo para esta petición.',
      error: 'La búsqueda de fuentes se interrumpió.'}[state] || 'Sin fuentes de respaldo registradas para esta petición.';
    return `<p class="exp-muted">${message}</p>`;
  }
  return `<details class="sources"><summary>Consultar fuentes y aportes (${sources.length})</summary><ul>
    ${sources.map(source => {
      const title = source.title || source.filename || 'Documento fuente';
      const url = source.source_id ? `/api/sources/${encodeURIComponent(source.source_id)}/original?case_id=${encodeURIComponent(caseId)}`
        : String(source.url || '').startsWith('/api/') ? source.url : '';
      return `<li>${url ? `<a target="_blank" rel="noopener" href="${esc(url)}">${esc(title)} ↗</a>` : esc(title)}
        ${source.department ? ' · ' + esc(source.department) : ''}${source.page ? ' · pág. ' + esc(source.page) : ''}
        ${source.line_start ? ' · línea ' + esc(source.line_start) + (source.line_end > source.line_start ? '–' + esc(source.line_end) : '') : ''}
        ${source.quote ? `<blockquote>${esc(source.quote)}</blockquote>` : ''}</li>`;
    }).join('')}</ul></details>`;
}

function petitionCorrection(request, gaps) {
  return `<details class="petition-correction"><summary>Corregir petición</summary>
    <form data-review="${esc(request.id)}">
      <label class="field">Respuesta revisada<textarea name="answer" rows="4" maxlength="64000">${esc(request.answer)}</textarea></label>
      <label class="field">Faltantes, uno por línea<textarea name="gaps" rows="2">${esc(gaps.join('\n'))}</textarea></label>
      <label class="field">Motivo de la corrección<textarea name="reason" required rows="2" maxlength="2000"></textarea></label>
      <button type="submit">Guardar corrección</button>
    </form></details>`;
}

export function writingPanel(detail, isAdmin, number = 1) {
  const preparing = detail.stage === 'preparing';
  const progress = new Map((preparing ? detail.progress?.requests || [] : []).map(item => [item.id, item]));
  const empty = preparing ? 'La búsqueda de fuentes comienza cuando se identifican las peticiones.' : 'Sin peticiones para consultar.';
  return requestList(detail, number, 'Fuentes y redacción', empty, (request, index) => {
    if (detail.scope_revoked) {
      return `<summary>${petitionTitle(request, index)}</summary><p>${esc(request.text)}</p>
        <p class="exp-muted">Cambió el acceso a la biblioteca. Vuelve a preparar la respuesta con las fuentes disponibles.</p>`;
    }
    const step = progress.get(request.id);
    const gaps = request.gaps?.length ? request.gaps : (request.gap || '').split('\n').filter(Boolean);
    const waiting = preparing && !request.answer && !gaps.length && step?.drafting !== 'done';
    const interrupted = detail.error || step?.sources === 'error' || step?.drafting === 'error';
    const needsInput = !request.answer?.trim() || gaps.length > 0;
    const status = waiting ? (interrupted ? 'Interrumpida' : step?.drafting === 'running' ? 'En redacción' : 'En preparación')
      : needsInput ? 'Por completar' : 'Respuesta disponible';
    const answerEmpty = waiting ? (interrupted ? 'La preparación de la respuesta quedó interrumpida.'
      : step?.drafting === 'running' ? 'Preparando la respuesta con las fuentes disponibles.' : 'Redacción pendiente.')
      : 'Sin respuesta redactada.';
    const sourceStatus = {references_found: 'Respaldo encontrado', no_matches: 'Sin coincidencias de respaldo',
      needs_evidence: 'Hace falta evidencia', error: 'Búsqueda interrumpida'}[request.source_status];
    return `<summary>${petitionTitle(request, index)} <span class="chip ${waiting ? '' : needsInput ? 'check-attention' : 'check-pass'}">${status}</span></summary>
      <p>${esc(request.text)}</p>
      <h4>Fuentes de respaldo</h4>
      ${sourceStatus || request.source_summary ? `<p>${sourceStatus ? `<strong>${esc(sourceStatus)}</strong> ` : ''}${esc(request.source_summary)}</p>` : ''}
      ${sourceList(request, detail.case_id, request.source_status ? 'done' : step?.sources || (preparing ? 'pending' : 'done'))}
      ${secondaryChecksNote(request.secondary_source_checks)}
      <h4>Respuesta del borrador</h4><p class="petition-answer">${esc(request.answer || answerEmpty)}</p>
      ${gaps.length ? `<div class="gap"><strong>Falta por resolver</strong><ul>${gaps.map(gap => `<li>${esc(gap)}</li>`).join('')}</ul></div>` : ''}
      ${request.human_review ? `<p class="help">Corrección del administrador · ${esc(request.human_review.reason)}</p>` : ''}
      ${isAdmin && ['initial_review', 'final_review'].includes(detail.stage) ? petitionCorrection(request, gaps) : ''}`;
  });
}
