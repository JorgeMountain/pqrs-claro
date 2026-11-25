import {esc} from './views.js';

const statusText = {pending: 'Pendiente', running: 'En curso', done: 'Completado', error: 'Interrumpido'};
const readingSteps = {reading: 'Lectura del documento', checks: 'Verificación del documento',
  identification: 'Identificación de peticiones', library: 'Preparación de fuentes'};

function status(value) {
  const state = Object.hasOwn(statusText, value) ? value : 'pending';
  return `<span class="progress-state progress-${state}">${statusText[state]}</span>`;
}

function progressRows(progress, initial) {
  if (!progress) return '';
  const rows = progress.requests || [];
  const steps = initial ? Object.entries(readingSteps).map(([key, label]) => `
    <li>${label} ${key === 'checks' && progress.steps?.checks === 'error'
      ? '<span class="progress-state progress-error">Requiere revisión</span>' : status(progress.steps?.[key])}</li>`).join('') : '';
  return `${steps ? `<ul class="progress-steps">${steps}</ul>` : ''}
    ${rows.length ? `<div class="progress-requests"><table>
      <thead><tr><th scope="col">Petición</th>${initial ? '<th scope="col">Búsqueda de fuentes</th><th scope="col">Redacción</th>' : '<th scope="col">Integración del aporte</th>'}</tr></thead>
      <tbody>${rows.map((r, i) => `<tr><th scope="row">${esc(r.label || 'Petición ' + (i + 1))}</th>
        ${initial ? `<td>${status(r.sources)}</td><td>${status(r.drafting)}</td>` : `<td>${status(r.integration)}</td>`}</tr>`).join('')}</tbody>
      </table></div>` : ''}`;
}

function progressView(detail, actor) {
  const initial = detail.stage === 'preparing';
  const progress = detail.progress;
  const current = detail.error ? 'error' : progress?.status === 'running' ? 'running' : 'pending';
  return `<section class="panel processing-panel"><div class="section-head"><h2>${initial ? 'Preparación de la respuesta' : 'Integración de los aportes'}</h2>
    <span class="progress-state progress-${current}">${current === 'pending' ? 'En espera' : statusText[current]}</span></div>
    ${detail.error ? `<div class="processing-error" role="alert"><p>${esc(detail.error)}</p>
      ${actor === 'admin' ? '<button type="button" data-command="retry">Reintentar procesamiento</button>' : ''}</div>` : ''}
    ${progress ? progressRows(progress, initial) : detail.error ? '' : `<p class="exp-note">${initial ? 'Solicitud en espera de preanálisis.' : 'Aportes recibidos en espera de integración.'}</p>`}</section>`;
}

export function caseProgress(detail, actor, selected) {
  if (['preparing', 'integration'].includes(detail.stage)) {
    return `<div data-exp-progress>${progressView(detail, actor)}</div>`;
  }
  const progress = detail.progress;
  const initial = progress?.stage === 'preanalysis';
  if (progress?.status !== 'done' || selected !== (initial ? 'preanalisis' : 'borrador')) return '';
  return `<details class="panel progress-history"><summary>${initial ? 'Consultar avance de la preparación' : 'Consultar la última integración de aportes'}</summary>
    ${progressRows(progress, initial)}</details>`;
}

export function updateCaseProgress(workspace, detail, actor) {
  const container = workspace.querySelector('[data-exp-progress]');
  if (!container) return;
  const table = container.querySelector('.progress-requests');
  const scroll = table?.scrollTop || 0;
  container.innerHTML = progressView(detail, actor);
  if (scroll) container.querySelector('.progress-requests')?.scrollTo(0, scroll);
}
