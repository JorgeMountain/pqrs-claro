import {mountFiagaHeader} from './fiaga-header.js';
import {analysisSteps, bindCaseRouteLayout, caseHeadingMarkup, caseRouteMarkup, caseSidebarMarkup, updateAnalysisStep} from './fiaga-route.js';
import {bindEditorProfile, savedProfile as fiagaProfile} from './fiaga-header-profile.js';

export {fiagaProfile};

// The historical editor uses independent clients for the reader, evidence and drafts.
// Bind their case mutations to the selected FIAGA profile for this document only.
export function enableAdminReview(caseId) {
  const fetchOriginal = window.fetch.bind(window);
  const prefix = '/api/cases/' + encodeURIComponent(caseId) + '/';
  window.fetch = function(input, init) {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    const method = init?.method || (input instanceof Request ? input.method : 'GET');
    if (url.origin !== location.origin || /^(GET|HEAD)$/i.test(method)) {
      return fetchOriginal(input, init);
    }
    let scoped = url.pathname.startsWith(prefix);
    if (!scoped && /^\/api\/(?:sources|evidence)$/.test(url.pathname)) {
      scoped = init?.body instanceof FormData && init.body.get('case_id') === caseId;
    }
    if (!scoped && /^\/api\/sources\/[^/]+\/review$/.test(url.pathname)) {
      let bodyCase;
      if(typeof init?.body === 'string'){
        try { bodyCase = JSON.parse(init.body).case_id; } catch {}
      }
      scoped = (url.searchParams.get('case_id') || bodyCase) === caseId;
    }
    if (!scoped) return fetchOriginal(input, init);
    const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
    headers.set('X-Fiaga-Actor', fiagaProfile());
    return fetchOriginal(input, {...init, headers});
  };
}

export function adminReviewUrl(caseId, step) {
  const params = new URLSearchParams({case:caseId, view:'revision-fiaga'});
  if (step != null) params.set('step', step);
  return '/?' + params;
}

// The editor already owns progress, access checks and unsaved edits. Its four
// controls remain the source of truth even when a saved stage is being viewed.
function bindAnalysisSubsteps(layout, view) {
  const buttons = [...layout.querySelectorAll('[data-route-substep]')];
  let steps;
  function sync() {
    for (const button of buttons) {
      const index = Number(button.dataset.routeSubstep);
      const step = steps?.children[index];
      const current = step?.getAttribute('aria-current') === 'step';
      const target = step?.querySelector('button[data-action]');
      const state = step?.querySelector('[data-stage-running]') ? 'working'
        : step?.classList.contains('complete') ? 'completed' : current ? 'review' : 'pending';
      const caption = step?.querySelector('small:not([hidden])')?.textContent.trim() || (current ? 'En revisión' : 'Pendiente');
      updateAnalysisStep(button, index, {state, current, caption});
      button.disabled = !target || target.disabled;
    }
  }
  const states = new MutationObserver(sync);
  function connect() {
    steps = view.querySelector('.expediente-steps, .pre-steps');
    states.disconnect();
    if (steps) {
      steps.hidden = true;
      states.observe(steps, {
        subtree:true, childList:true, characterData:true, attributes:true,
        attributeFilter:['data-stage-running', 'aria-current', 'class', 'disabled', 'hidden'],
      });
    }
    sync();
  }
  connect();
  // Some screens replace the whole stepper, others only change its markers.
  new MutationObserver(() => {
    if (!steps?.isConnected) connect();
  }).observe(view, {childList:true, subtree:true});
  layout.addEventListener('click', event => {
    const button = event.target.closest('[data-route-substep]');
    if (!button || button.disabled) return;
    const step = view.querySelector('.expediente-steps, .pre-steps')?.children[Number(button.dataset.routeSubstep)];
    const target = step?.querySelector('button[data-action]');
    if (target && !target.disabled && step.getAttribute('aria-current') !== 'step') target.click();
  });
}

export function mountReviewHeader() {
  const masthead = document.querySelector('.institutional-header');
  masthead.hidden = true;
  const header = document.createElement('header');
  masthead.after(header);
  mountFiagaHeader(header);
  header.querySelector('[data-page="expedientes"]').setAttribute('aria-current', 'page');
  header.querySelector('#actor').disabled = true;
  header.querySelector('#new-manager').disabled = true;
}

export function mountAnalysisFrame(record, detail, notice) {
  const url = '/?expediente=' + encodeURIComponent(record.id);
  const title = detail.subject || record.identification?.subject || record.receipt?.subject || record.filename;
  document.querySelector('#actor').disabled = false;
  document.querySelector('#new-manager').disabled = false;
  document.querySelector('.workspace-rail').hidden = true;
  const main = document.querySelector('#main');
  const layout = main.parentElement;
  layout.classList.add('fiaga-route-layout');
  main.classList.add('fiaga-route-main');
  const previous = detail.draft || detail.initial_draft;
  const route = {stage:detail.stage, view:'analysis', targets:{receipt:url + '#recepcion'}};
  main.insertAdjacentHTML('beforebegin', caseSidebarMarkup(route));
  main.insertAdjacentHTML('afterbegin',
    caseHeadingMarkup({title, stage:detail.stage}) +
    caseRouteMarkup(route) +
    analysisSteps() +
    (previous ? `<a class="fiaga-analysis-previous" href="${url}#borrador-anterior" target="_blank" rel="noopener">Consultar borrador anterior</a>` : '')
  );
  bindCaseRouteLayout(layout);
  bindAnalysisSubsteps(layout, document.querySelector('#view'));
  document.body.classList.add('fiaga-analysis-page');
  void bindEditorProfile(url, notice);
}
