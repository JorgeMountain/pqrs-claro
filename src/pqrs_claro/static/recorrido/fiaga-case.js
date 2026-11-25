import {esc} from './views.js';
import {adminReviewLink, caseLink, stages, stateChip} from './fiaga-home.js';
import {planForm} from './fiaga-plan.js';
import {officePreview} from './fiaga-office.js';
import {icon} from './inbox-icons.js';
import {documentPanel, originLabel, updateDocumentChecks} from './fiaga-document.js';
import {identificationPanel, writingPanel} from './fiaga-analysis.js';
import {caseProgress, updateCaseProgress as updateProgressPanel} from './fiaga-progress.js';
import {analysisSteps, caseHeadingMarkup, caseRouteMarkup, caseSidebarMarkup, updateAnalysisStep} from './fiaga-route.js';
import {fiagaStages as sections} from './fiaga-stages.js';
export {bindDocumentReader as bindCaseView} from './fiaga-document.js';

const taskStates = {waiting: 'En espera', available: 'Disponible', claimed: 'En gestión', completed: 'Completado'};
const management = [['recepcion', 'Recepción'], ['faltantes', 'Revisión de faltantes'], ['tramites', 'Trámites'], ['decision', 'Revisión final']];
const reviewSection = {initial_review: 'faltantes', pool: 'tramites', integration: 'tramites',
  final_review: 'decision', approved: 'decision'};
const eventLabels = {
  enrolled: 'Recepción de la solicitud', published: 'Publicación de la secuencia', claimed: 'Toma del trámite',
  completed: 'Entrega del aporte', returned: 'Devolución a la pool', approved: 'Aprobación de la respuesta',
  initial_review: 'Borrador inicial disponible', final_review: 'Borrador integrado para revisión',
  retry: 'Reintento de procesamiento', error: 'Procesamiento interrumpido', request_reviewed: 'Corrección de una petición',
  review_opened: 'Apertura de la revisión administrativa', review_imported: 'Borrador revisado por el administrador',
};

function needsInput(request) { return Boolean(request.gap || !request.answer?.trim()); }

function draftPanel(detail) {
  const final = ['final_review','approved'].includes(detail.stage);
  const title = detail.stage === 'approved' ? 'Respuesta aprobada' : final ? 'Borrador para revisión final'
    : detail.stage === 'integration' ? 'Borrador anterior a esta integración' : 'Borrador de respuesta';
  if (!detail.draft && !detail.initial_draft) return emptyPanel(title, 'El primer borrador estará disponible cuando terminen la búsqueda de fuentes y la redacción.');
  return `<section class="panel draft-panel"><div class="section-head"><h2>${title}</h2></div>
    ${officePreview(detail, detail.draft ? 'draft' : 'initial_draft', title)}
    ${detail.draft && detail.initial_draft && detail.initial_draft !== detail.draft ? `<details class="previous"><summary>Consultar borrador inicial</summary>${officePreview(detail, 'initial_draft', 'Borrador inicial')}</details>` : ''}
    ${detail.previous_draft && detail.previous_draft !== detail.initial_draft && detail.previous_draft !== detail.draft
      ? `<details class="previous"><summary>Consultar borrador anterior a la revisión administrativa</summary>${officePreview(detail, 'previous_draft', 'Borrador anterior a la revisión administrativa')}</details>` : ''}
    </section>`;
}

function contributions(task, people) {
  return (task.contributions || []).map(item => `<div class="contribution">
    <strong>Aporte de ${esc(people(item.actor_id))}</strong>
    ${item.note ? `<p>${esc(item.note)}</p>` : ''}
    ${item.files?.length ? `<ul>${item.files.map(f => {
      const url = String(f.url || '');
      return `<li>${url.startsWith('/api/') ? `<a href="${esc(url)}" download>${esc(f.filename)}</a>` : esc(f.filename)}
        ${f.extraction_error ? '<span class="help"> · Revisar el original. La lectura automática quedó incompleta.</span>' : ''}</li>`;
    }).join('')}</ul>` : ''}</div>`).join('');
}

function taskAction(task, actor, people) {
  if (task.status === 'claimed' && task.owner_id === actor) return `
    <form id="contribute" data-task="${esc(task.id)}"><label class="field">Respuesta o constancia de gestión<textarea name="note" rows="3" maxlength="16000"></textarea></label>
      <label class="field">Archivos de soporte<input name="files" type="file" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg" multiple></label>
      <p class="help">Registra una respuesta o adjunta soportes en PDF, Word (.docx), TXT, PNG o JPG. Hasta 20 MB en total.</p>
      <button type="submit" class="primary">Completar trámite</button></form>`;
  if (task.status === 'claimed') return `<p class="help">Lo está tramitando ${esc(people(task.owner_id))}.</p>`;
  if (task.status !== 'available') return '';
  if (actor === 'admin') return '<p class="help">Selecciona un perfil de tramitador para tomar este turno.</p>';
  if (task.manager_id && task.manager_id !== actor) return `<p class="help">Turno reservado para ${esc(people(task.manager_id))}.</p>`;
  return `<button type="button" class="primary" data-command="claim" data-task="${esc(task.id)}">Tomar trámite</button>`;
}

function taskPanel(detail, actor, people) {
  if (!detail.tasks?.length) {
    const message = ['preparing', 'admin_review', 'initial_review'].includes(detail.stage)
      ? 'El administrador publica los trámites después de revisar los faltantes del borrador.'
      : 'Esta solicitud pasó a revisión final sin requerir aportes de las dependencias.';
    return emptyPanel('Secuencia de trámites', message);
  }
  const rounds = new Map();
  for (const task of detail.tasks) {
    const round = task.round || 1;
    if (!rounds.has(round)) rounds.set(round, []);
    rounds.get(round).push(task);
  }
  const currentRound = Math.max(...rounds.keys());
  const turns = tasks => `<ol class="turns">${tasks.map(task => {
      const requestIndex = detail.requests.findIndex(r => r.id === task.request_id);
      return `<li class="turn turn-${esc(task.status)}">
        <div class="turn-top"><span>${requestIndex >= 0 ? 'Petición ' + (requestIndex + 1) : 'Trámite de la solicitud'}</span>
          <span class="chip">${esc(taskStates[task.status] || task.status)}</span></div>
        <h3>${esc(task.department)}</h3><p>${esc(task.instruction)}</p>
        ${requestIndex >= 0 ? `<details><summary>Consultar petición ${requestIndex + 1}</summary><p>${esc(detail.requests[requestIndex].text)}</p></details>` : ''}
        ${contributions(task, people)}${taskAction(task, actor, people)}</li>`;
    }).join('')}</ol>`;
  return `<section class="panel exp-turn-panel"><div class="section-head"><h2>Secuencia de trámites</h2>
    <span class="exp-count">Ronda ${currentRound}</span></div>
    <div class="panel-body">${turns(rounds.get(currentRound))}</div>
    ${[...rounds.entries()].reverse().filter(([round]) => round !== currentRound).map(([round, tasks]) =>
      `<details class="exp-old-round"><summary>Consultar ronda ${round} · ${tasks.length} ${tasks.length === 1 ? 'trámite' : 'trámites'}</summary>${turns(tasks)}</details>`).join('')}
    </section>`;
}

function historyPanel(detail, people) {
  if (!detail.events?.length) return '';
  return `<details class="panel panel-body"><summary>Historial del expediente</summary><ol class="history">
    ${detail.events.map(event => {
      const date = new Date(event.created_at);
      const when = Number.isNaN(date.getTime()) ? '' : date.toLocaleString('es-CO', {timeZone:'America/Bogota'});
      return `<li><strong>${esc(eventLabels[event.action] || event.action)}</strong>
        <span>${esc([event.actor_id && people(event.actor_id), when].filter(Boolean).join(' · '))}</span>
        ${event.reason ? `<p>${esc(event.reason)}</p>` : ''}</li>`;
    }).join('')}</ol></details>`;
}

function reviewAction(detail) {
  const missing = detail.requests.some(needsInput);
  return `<section class="panel panel-body"><h2>Decisión del administrador</h2>
    <p>Revisa la respuesta y los soportes antes de aprobar el documento.</p>
    ${missing ? '<p class="gap">Quedan peticiones por completar. Solicita un nuevo aporte o registra una corrección en la petición correspondiente.</p>' : ''}
    <a data-home href="${caseLink(detail.case_id)}#redaccion">Revisar peticiones y fuentes</a>
    <button type="button" class="primary" data-command="approve" ${missing ? 'disabled' : ''}>Aprobar respuesta final</button>
    <details class="return-panel"><summary>Solicitar un nuevo aporte</summary>${planForm(detail, true)}</details></section>`;
}

function emptyPanel(title, message) {
  return `<section class="panel panel-body"><h2>${esc(title)}</h2><p class="help">${esc(message)}</p></section>`;
}

function receiptPanel(detail) {
  const email = detail.origin?.kind === 'gmail';
  return `<section class="panel"><div class="section-head"><h2>Solicitud recibida</h2></div>
    <div class="panel-body"><dl class="doc-meta"><dt>Documento</dt><dd>${esc(detail.filename)}</dd>
    <dt>Origen</dt><dd>${esc(originLabel(detail))}</dd>
    ${detail.origin?.sender ? `<dt>Remitente del correo</dt><dd>${esc(detail.origin.sender)}</dd>` : ''}
    ${detail.case_number ? `<dt>Referencia</dt><dd>${esc(detail.case_number)}</dd>` : ''}</dl>
    <a href="/api/cases/${encodeURIComponent(detail.case_id)}/original" target="_blank" rel="noopener">Abrir documento recibido ${icon('external-link')}</a>
    ${email ? `<a data-home href="${caseLink(detail.case_id)}#correo-original">Consultar correo original</a>` : ''}</div></section>`;
}

function analysisSubsteps(detail, selected) {
  // During the four-stage administrative review the live editor owns its progress.
  // Pool snapshots from earlier runs cannot establish the editor's accessible steps.
  if (detail.stage === 'admin_review') return [];
  const progress = detail.progress?.stage === 'preanalysis' ? detail.progress : null;
  const requests = detail.requests || [];

  function state(flags, hasSavedResult = false) {
    if (detail.review_imported) return 'completed';
    if (flags.includes('running')) {
      return detail.stage === 'preparing' && progress?.status === 'running' && !detail.error ? 'working' : 'review';
    }
    if (flags.includes('error')) return 'review';
    if (flags.length && flags.every(flag => flag === 'done')) return 'completed';
    return hasSavedResult ? 'review' : 'pending';
  }
  const steps = progress?.steps || {};
  const writing = (progress?.requests || []).flatMap(request => [request.sources, request.drafting]);
  // Preparing the library alone does not finish the responses to the requests.
  if (!writing.length) writing.push('pending');
  const states = [
    state([steps.reading, steps.checks], Object.keys(detail.checks || {}).length > 0),
    state([steps.identification], requests.length > 0),
    state([steps.library, ...writing],
      requests.some(request => request.answer || request.gap || request.source_status)),
    state([], Boolean(detail.initial_draft || detail.draft)),
  ];
  return sections.map(([key], index) => ({
    href: caseLink(detail.case_id) + '#' + key, state: states[index], current: selected === key,
  }));
}

function caseRouteOptions(detail, actor, selected) {
  const url = caseLink(detail.case_id);
  const stage = detail.stage;
  const targets = {receipt: url + '#recepcion', analysis: url + '#preanalisis'};
  if (stage === 'admin_review' && actor === 'admin') targets.analysis = adminReviewLink(detail.case_id, '#preanalisis');
  if (detail.review_imported || stage === 'initial_review') targets.gaps = url + '#faltantes';
  if (detail.tasks?.length || stage === 'pool' || stage === 'integration') targets.tasks = url + '#tramites';
  if (stage === 'final_review' || stage === 'approved') targets.final = url + '#decision';
  const view = {recepcion:'receipt', faltantes:'gaps', tramites:'tasks', decision:'final'}[selected] || 'analysis';
  return {stage, view, targets, substeps:view === 'analysis' ? analysisSubsteps(detail, selected) : []};
}

function caseLayout(detail, actor, selected, content, back) {
  const title = detail.subject || detail.filename || 'Solicitud PQRS';
  const heading = caseHeadingMarkup({title, stage: detail.stage, reference: detail.case_number});
  const route = caseRouteOptions(detail, actor, selected);
  return `<div class="fiaga-route-layout">${caseSidebarMarkup(route)}<div class="fiaga-route-main">${back}
    ${heading}${caseRouteMarkup(route)}${analysisSteps(route.substeps)}${content}</div></div>`;
}

function gapsPanel(detail) {
  const requests = detail.requests || [];
  return `<section class="panel exp-gap-panel"><div class="section-head"><h2>Faltantes del borrador</h2></div>
    <div class="panel-body">${requests.some(needsInput)
      ? requests.map((r, i) => needsInput(r) ? `<p class="gap"><strong><a data-home href="${caseLink(detail.case_id)}#redaccion/${i + 1}">Petición ${i + 1}</a></strong>${esc(r.gap || 'Hace falta una respuesta sustentada.')}</p>` : '').join('')
      : '<p>Todas las peticiones tienen una respuesta para revisar.</p>'}
    <a data-home href="${caseLink(detail.case_id)}#redaccion">Consultar respuestas y fuentes</a></div></section>`;
}

function workingSection(detail) {
  if (reviewSection[detail.stage]) return reviewSection[detail.stage];
  const steps = detail.progress?.steps || {};
  if (!['done','error'].includes(steps.checks)) return 'preanalisis';
  if (steps.identification !== 'done') return 'peticiones';
  return 'redaccion';
}

function sectionRoute(hash, detail) {
  const [key, n] = String(hash).replace(/^#/, '').split('/');
  const section = key === 'documento' ? 'preanalisis' : key;
  const selected = [...sections, ...management].some(([id]) => id === section)
    ? section : reviewSection[detail.stage] || 'preanalisis';
  return {selected, page: /^[1-9]\d{0,6}$/.test(n || '') ? Number(n) : 1};
}

function currentLink(detail, selected) {
  const active = workingSection(detail);
  if (selected === active) return '';
  const [, label] = [...sections, ...management].find(([key]) => key === active);
  return `<a data-home href="${caseLink(detail.case_id)}#${active}">Ir a ${label}</a>`;
}

function sectionContents(key, detail, actor, people, page) {
  const isAdmin = actor === 'admin';
  const stage = detail.stage;
  if (key === 'recepcion') return receiptPanel(detail);
  if (key === 'preanalisis') return documentPanel(detail, page);
  if (key === 'peticiones') return identificationPanel(detail, page);
  if (key === 'redaccion') return writingPanel(detail, isAdmin, page);
  if (key === 'tramites') return taskPanel(detail, actor, people) + (stage === 'integration' ? draftPanel(detail) : '');
  if (key === 'decision') {
    if (stage === 'approved') return `<section class="approved-banner"><div><h2>Documento final aprobado</h2><p>La versión aprobada está disponible en Word.</p></div>
      <a class="button primary" href="/api/cases/${encodeURIComponent(detail.case_id)}/pool/document.docx" download>Descargar Word</a></section>${draftPanel(detail)}`;
    if (stage !== 'final_review') return emptyPanel('Revisión final', 'La decisión se habilita cuando el administrador cierra la revisión inicial y se han integrado los aportes requeridos.');
    return `<div class="exp-split">${draftPanel(detail)}<div class="column">${isAdmin ? reviewAction(detail)
      : emptyPanel('Decisión pendiente', 'El administrador revisa la respuesta antes de aprobarla o solicitar otro aporte.')}</div></div>`;
  }
  if (!detail.requests?.length || (!detail.initial_draft && !detail.draft)) return draftPanel(detail);
  return `<div class="exp-split">${draftPanel(detail)}<div class="column">${gapsPanel(detail)}
    ${stage === 'initial_review' && detail.review_imported ? (isAdmin ? planForm(detail) : emptyPanel('Revisión inicial', 'El administrador revisa la respuesta y organiza los aportes pendientes antes de abrir los turnos.')) : ''}</div></div>`;
}

export function caseView(detail, actor, managers, hash = '') {
  if (detail.stage === 'legacy') return `<div class="panel panel-body"><h1>Expediente anterior</h1>
    <p>Esta solicitud está en el recorrido en el que se recibió.</p>
    <a class="button primary" href="/?case=${encodeURIComponent(detail.case_id)}">Abrir expediente anterior</a></div>`;
  const people = id => id === 'admin' ? 'Administrador' : managers.find(m => m.id === id)?.name || (id === 'system' ? 'Sistema' : id);
  const back = `<a class="breadcrumb" data-home href="/#expedientes">${icon('arrow-left')} Volver a los expedientes</a>`;
  if (detail.stage === 'admin_review') {
    if (hash === '#recepcion') return caseLayout(detail, actor, 'recepcion', receiptPanel(detail), back);
    if (hash === '#borrador-anterior' && actor === 'admin') {
      const backToReview = `<a class="breadcrumb" href="${adminReviewLink(detail.case_id)}">${icon('arrow-left')} Volver a la revisión</a>`;
      return caseLayout(detail, actor, 'borrador', `<section class="panel draft-panel"><div class="section-head"><h2>Borrador anterior a la revisión administrativa</h2></div>
        ${detail.draft || detail.initial_draft ? officePreview(detail, detail.draft ? 'draft' : 'initial_draft', 'Borrador anterior a la revisión administrativa') : '<p class="panel-body">Este expediente aún no tenía un borrador guardado.</p>'}</section>`, backToReview);
    }
    return caseLayout(detail, actor, 'preanalisis', `<section class="panel panel-body"><h2>${esc(stages[detail.stage])}</h2>
      <p>El administrador revisa el documento, las peticiones y sus respuestas. Los trámites se habilitan cuando publica los faltantes.</p>
      <a href="/api/cases/${encodeURIComponent(detail.case_id)}/original" target="_blank" rel="noopener">Consultar el documento recibido</a></section>`, back);
  }
  const {selected, page} = sectionRoute(hash, detail);
  return caseLayout(detail, actor, selected, `
    <div class="page-head fiaga-case-metadata"><div class="subheading"><span class="exp-origin">${icon(detail.origin?.kind === 'gmail' ? 'mail' : 'file')}${originLabel(detail)}</span>
    <span class="exp-stage">Estado actual ${stateChip(detail.stage)}</span>${detail.round && detail.tasks?.length ? `<span>Ronda ${esc(detail.round)}</span>` : ''}
    <span data-active-link>${currentLink(detail, selected)}</span></div>
    <button data-command="refresh" class="quiet" type="button">Actualizar</button></div>
    ${['preparing', 'initial_review'].includes(detail.stage) && !detail.review_imported && actor === 'admin'
      ? `<section class="panel panel-body fiaga-resume-review"><div><h2>Revisión del administrador</h2>
        <p>${detail.draft || detail.initial_draft
          ? 'Este expediente ya tiene un borrador. Puedes consultarlo y retomar la revisión desde el documento original.'
          : 'Retoma la revisión desde el preanálisis del documento recibido.'}</p></div>
        <button type="button" class="primary" data-command="open-review">Revisar las cuatro etapas</button></section>` : ''}
    ${detail.stage === 'preparing' || selected === 'recepcion' ? '' : caseProgress(detail, actor, selected)}
    <div class="exp-content">${sectionContents(selected, detail, actor, people, page)}</div>
    ${historyPanel(detail, people)}`, back);
}

export function updateCaseProgress(workspace, detail, actor, previous) {
  updateProgressPanel(workspace, detail, actor);
  const {selected, page} = sectionRoute(location.hash, detail);
  if (detail.stage === 'preparing' && workspace.querySelector('.fiaga-analysis-tabs')) {
    const steps = analysisSubsteps(detail, selected);
    const old = analysisSubsteps(previous, selected);
    for (const control of workspace.querySelectorAll('[data-route-substep]')) {
      const index = Number(control.dataset.routeSubstep);
      if (steps[index].state !== old[index].state) updateAnalysisStep(control, index, steps[index]);
    }
  }
  const shortcut = workspace.querySelector('[data-active-link]');
  if (shortcut && currentLink(previous, selected) !== currentLink(detail, selected)) {
    shortcut.innerHTML = currentLink(detail, selected);
  }
  if (selected === 'preanalisis') {
    updateDocumentChecks(workspace, detail);
    return;
  }
  const panel = selected === 'peticiones' ? identificationPanel
    : selected === 'redaccion' ? (item, n) => writingPanel(item, actor === 'admin', n) : null;
  if (!panel) return;
  const html = panel(detail, page);
  if (html === panel(previous, page)) return;
  const container = workspace.querySelector('.exp-content');
  const template = document.createElement('template');
  template.innerHTML = html;
  // Preserve the reader's place when new sources or answers arrive.
  for (const row of template.content.querySelectorAll('.petition-record')) {
    const old = container.querySelector(`.petition-record[data-request="${CSS.escape(row.dataset.request)}"]`);
    if (!old) continue;
    row.open = old.open;
    for (const nested of row.querySelectorAll('details')) {
      const prior = old.querySelector(`details.${CSS.escape(nested.classList[0])}`);
      if (prior) nested.open = prior.open;
    }
  }
  const focused = document.activeElement;
  const record = focused?.closest('.petition-record');
  const focusIndex = record ? [...record.querySelectorAll('summary, a, button')].indexOf(focused) : -1;
  container.replaceChildren(template.content);
  if (focusIndex >= 0) {
    const replacement = container.querySelector(`.petition-record[data-request="${CSS.escape(record.dataset.request)}"]`);
    replacement?.querySelectorAll('summary, a, button')[focusIndex]?.focus({preventScroll:true});
  }
}
