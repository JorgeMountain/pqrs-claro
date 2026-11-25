import {esc} from './views.js';
import {icon} from './inbox-icons.js';
import {fiagaStages} from './fiaga-stages.js';

const phases = [
  ['receipt', 'Recepción', 'inbox'],
  ['analysis', 'Análisis y borrador', 'file'],
  ['gaps', 'Revisión de faltantes', 'search'],
  ['tasks', 'Trámites e integración', 'layers'],
  ['final', 'Revisión final', 'flag'],
];
const stagePhases = {
  preparing: 'analysis', admin_review: 'analysis', initial_review: 'gaps',
  pool: 'tasks', integration: 'tasks', final_review: 'final', approved: 'final',
};
export const routePhase = stage => stagePhases[stage] ?? null;

export function caseHeadingMarkup({title, stage, reference}) {
  const phase = phases.find(([id]) => id === routePhase(stage));
  return `<header class="fiaga-case-heading">
    <div class="fiaga-case-identity"><p class="fiaga-case-kicker">${icon('file')} Expediente${reference ? ' · ' + esc(reference) : ''}</p>
    <h1>${esc(title)}</h1></div><div class="fiaga-heading-actions">
      ${phase ? `<span class="fiaga-phase-badge">Fase actual: ${phase[1]}</span>` : ''}
    </div></header>`;
}

function phaseItems({stage, view, targets = {}, substeps}, sidebar = false) {
  const currentIndex = phases.findIndex(([id]) => id === routePhase(stage));
  return phases.map(([id, label, symbol], index) => {
    const current = index === currentIndex;
    const viewed = id === view;
    // A case can go directly from reviewing gaps to the final review.
    const completed = (index < currentIndex && (id !== 'tasks' || Boolean(targets.tasks)))
      || (current && stage === 'approved');
    const state = current ? (stage === 'approved' ? 'Aprobada' : 'Fase actual')
      : completed ? 'Completada' : !targets[id] && index < currentIndex ? 'Sin trámites' : '';
    const href = targets[id];
    const attrs = `class="${sidebar ? 'fiaga-side-entry' : 'fiaga-phase-entry'}" ${viewed ? 'aria-current="page"' : ''} aria-label="${label}${state ? ' · ' + state : ''}"`;
    const content = sidebar
      ? `<span class="fiaga-side-dot" aria-hidden="true">${completed ? icon('check') : ''}</span><span class="fiaga-side-name">${label}</span>`
      : `<span class="fiaga-phase-icon" aria-hidden="true">${icon(completed || current ? 'check' : symbol)}</span><span class="fiaga-phase-name">${label}</span>`;
    const expandable = sidebar && id === 'analysis' && viewed && substeps?.length !== 0;
    const submenu = expandable ? `<details class="fiaga-side-stages"${preferredOpen('stages') ? ' open' : ''}>
        <summary class="fiaga-side-stages-toggle" aria-label="Etapas del análisis" title="Etapas del análisis">${icon('chevron-down')}</summary>
        ${analysisSteps(substeps, true)}</details>` : '';
    return `<li data-phase="${id}" class="${current ? 'is-current ' : ''}${viewed ? 'is-viewed ' : ''}${completed ? 'is-past' : ''}">${href
      ? `<a ${attrs} href="${esc(href)}">${content}</a>` : `<span ${attrs}>${content}</span>`}${submenu}</li>`;
  }).join('');
}

export function caseRouteMarkup(route) {
  return `<nav class="fiaga-phase-route" aria-label="Ruta del expediente"><ol class="fiaga-phase-list">${phaseItems(route)}</ol></nav>`;
}

export function caseSidebarMarkup(route) {
  return `<aside class="fiaga-side-route"><details class="fiaga-side-fold"${preferredOpen('menu') ? ' open' : ''}>
    <summary class="fiaga-side-toggle" aria-label="Ruta del expediente" title="Mostrar u ocultar la ruta del expediente">
      <span class="fiaga-side-title">Ruta del expediente</span><span class="fiaga-side-toggle-icon" aria-hidden="true">${icon('panel')}</span>
    </summary><nav class="fiaga-side-nav" aria-label="Menú lateral del expediente">
      <ol class="fiaga-side-list">${phaseItems(route, true)}</ol>
    </nav></details></aside>`;
}

const stateLabels = {pending:'Pendiente', working:'En curso', completed:'Completado', review:'Por revisar'};

export function updateAnalysisStep(control, index, {state, current, caption = stateLabels[state]}) {
  const label = control.querySelector('.fiaga-tab-label').textContent;
  control.dataset.state = state;
  control.setAttribute('aria-label', `${label} · ${caption}`);
  control.title = `${fiagaStages[index][1]} · ${caption}`;
  if (current) control.setAttribute('aria-current', 'step');
  else control.removeAttribute('aria-current');
  const circle = control.querySelector('.fiaga-step-circle');
  const mark = state === 'completed' ? '✓' : String(index + 1);
  if (circle.textContent !== mark) circle.textContent = mark;
}

export function analysisSteps(steps, sidebar = false) {
  if (steps && !steps.length) return '';
  const items = fiagaStages.map(([key, name], index) => {
    const step = steps?.[index];
    const label = key === 'redaccion' ? 'Redacción' : name;
    const state = step?.state || 'pending';
    const caption = stateLabels[state];
    const attrs = `class="${sidebar ? 'fiaga-side-step' : 'fiaga-analysis-tab'}" data-route-substep="${index}" data-state="${state}"
      aria-label="${label} · ${caption}" title="${name} · ${caption}" ${step?.current ? 'aria-current="step"' : ''}`;
    const content = `<span class="fiaga-step-circle" aria-hidden="true">${state === 'completed' ? '✓' : index + 1}</span><span class="fiaga-tab-label">${label}</span>`;
    return `<li>${step?.href ? `<a ${attrs} href="${esc(step.href)}">${content}</a>`
      : `<button type="button" ${attrs} disabled>${content}</button>`}</li>`;
  }).join('');
  return sidebar ? `<ol class="fiaga-side-analysis">${items}</ol>`
    : `<nav class="fiaga-analysis-tabs" aria-label="Etapas del análisis"><ol>${items}</ol></nav>`;
}

const desktop = globalThis.matchMedia?.('(min-width: 1100px)');
function preferenceKey(group) {
  return 'fiaga-sidebar-' + group + (desktop?.matches ? '-desktop' : '-compact');
}

function preferredOpen(group) {
  try {
    const value = globalThis.sessionStorage?.getItem(preferenceKey(group));
    if (value != null) return value === 'open';
  } catch { /* Use the default when storage is unavailable. */ }
  return group === 'menu' && desktop?.matches;
}

export function bindCaseRouteLayout(layout) {
  for (const fold of layout?.querySelectorAll('.fiaga-side-route details') || []) {
    const group = fold.classList.contains('fiaga-side-fold') ? 'menu' : 'stages';
    fold.addEventListener('toggle', () => {
      try { sessionStorage.setItem(preferenceKey(group), fold.open ? 'open' : 'closed'); } catch {}
    });
  }
}

desktop?.addEventListener('change', () => {
  for (const fold of document.querySelectorAll('.fiaga-side-route details')) {
    const next = preferredOpen(fold.classList.contains('fiaga-side-fold') ? 'menu' : 'stages');
    if (!next && fold.contains(document.activeElement)) fold.querySelector('summary').focus({preventScroll:true});
    fold.open = next;
  }
});
