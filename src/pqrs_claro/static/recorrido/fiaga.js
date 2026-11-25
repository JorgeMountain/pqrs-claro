import {mountFiagaHeader} from './fiaga-header.js';
import {adminReviewLink, bindReceipt, caseLink, homeView} from './fiaga-home.js';
import {applyPlanSuggestions, bindPlan, readPlan} from './fiaga-plan.js';
import {bindCaseView, caseView, updateCaseProgress} from './fiaga-case.js';
import {bindCaseRouteLayout} from './fiaga-route.js';
import {createGmail} from './gmail-inbox.js';
import {addProfileOption, bindManagerDialog, initialHomeProfile, savedProfile} from './fiaga-header-profile.js';

mountFiagaHeader(document.querySelector('header.top'));
const workspace = document.querySelector('#workspace');
const actorSelect = document.querySelector('#actor');
const feedback = document.querySelector('#feedback');
const announcement = document.querySelector('#announcement');
const managerButton = document.querySelector('#new-manager');
const header = document.querySelector('header.top');
let actor = 'admin';
let managers = [];
let detail = null;
let generation = 0;
let timer;
let busy = false;
let dirty = false;
let retainedPlan = null;
let releaseReceipt;
let historyPosition = history.state?.fiagaPosition ?? 0;
let restoringHistory = false;
history.replaceState({fiagaPosition:historyPosition}, '');
const currentId = () => new URLSearchParams(location.search).get('expediente');
const poolPath = id => '/api/cases/' + encodeURIComponent(id) + '/pool';

async function api(path, payload) {
  const options = {};
  if (payload !== undefined) {
    options.method = 'POST';
    if (payload instanceof FormData) options.body = payload;
    else {
      options.headers = {'Content-Type': 'application/json'};
      options.body = JSON.stringify(payload);
    }
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error('Se perdió la conexión con el servicio. Verifica la conexión y actualiza el expediente.');
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(typeof body.detail === 'string' ? body.detail : 'El servicio no pudo completar la operación. Revisa los datos e intenta nuevamente.');
    error.status = response.status;
    throw error;
  }
  return body;
}

function showFeedback(message, error = false) {
  feedback.hidden = !message;
  feedback.setAttribute('role', error ? 'alert' : 'status');
  feedback.classList.toggle('error', error);
  feedback.textContent = message;
  if (error) feedback.scrollIntoView({block: 'nearest'});
}

const planSuggestionCache = new Map();

async function autoSuggestPlanResponsibles(form) {
  if (busy || !detail || actor !== 'admin' || form.dataset.suggesting === 'true') return;
  const rows = [...form.querySelectorAll('.task-editor')];
  if (!rows.length) return;
  if (!rows.some(row => !row.querySelector('[name="department"]').value.trim())) return;
  const tasks = rows.map(row => ({
    request_id: row.querySelector('[name="request_id"]').value,
    instruction: row.querySelector('[name="instruction"]').value.trim(),
  }));
  const caseId = detail.case_id;
  const revision = detail.revision;
  const status = form.querySelector('[data-plan-ai-status]');
  const cacheKey = `${caseId}:${revision}:${JSON.stringify(tasks)}`;
  const cached = planSuggestionCache.get(cacheKey);
  if (cached) {
    applyPlanSuggestions(form, cached);
    if (status && cached.length) {
      status.textContent = 'Responsables sugeridos con IA. Revisa y ajusta antes de publicar.';
      status.hidden = false;
    }
    return;
  }
  form.dataset.suggesting = 'true';
  if (status) {
    status.textContent = 'Sugiriendo dependencias o responsables con IA…';
    status.hidden = false;
  }
  try {
    const result = await api(poolPath(caseId) + '/suggest-responsibles', {
      actor_id: actor, revision, tasks,
    });
    if (!form.isConnected || detail?.case_id !== caseId || detail.revision !== revision) return;
    const suggestions = result.suggestions || [];
    planSuggestionCache.set(cacheKey, suggestions);
    const {filled, alternative} = applyPlanSuggestions(form, suggestions);
    if (status) {
      if (filled || alternative) {
        status.textContent = 'Responsables sugeridos con IA. Revisa y ajusta antes de publicar.';
        status.hidden = false;
      } else {
        status.hidden = true;
      }
    }
  } catch {
    if (form.isConnected && status) {
      status.textContent = 'No se pudieron sugerir responsables automáticamente. Puedes escribirlos manualmente.';
      status.hidden = false;
    }
  } finally {
    delete form.dataset.suggesting;
  }
}

function renderCase({keepReader = false} = {}) {
  const reader = keepReader && workspace.querySelector('.document-reader');
  const paper = reader ? reader.querySelector('.reader-paper') : null;
  const scroll = paper ? [paper.scrollLeft, paper.scrollTop] : null;
  const focused = reader && reader.contains(document.activeElement) ? document.activeElement : null;
  workspace.innerHTML = caseView(detail, actor, managers, location.hash);
  bindCaseRouteLayout(workspace.querySelector('.fiaga-route-layout'));
  const nextReader = workspace.querySelector('.document-reader');
  if (reader && nextReader) {
    nextReader.replaceWith(reader);
    if (scroll) paper.scrollTo(...scroll);
    focused?.focus({preventScroll:true});
  } else bindCaseView(workspace, detail);
  const plan = workspace.querySelector('#plan');
  if (plan) {
    bindPlan(plan, detail, managers,
      retainedPlan?.id === detail.case_id ? retainedPlan.rows : null);
    const disclosure = plan.closest('details.return-panel');
    if (disclosure && !disclosure.open) {
      disclosure.addEventListener('toggle', () => {
        if (disclosure.open) void autoSuggestPlanResponsibles(plan);
      });
    } else {
      void autoSuggestPlanResponsibles(plan);
    }
  }
  document.title = (detail.subject || detail.filename || 'Expediente') + ' · Gestión de PQRS';
}

function pageName() {
  if (currentId()) return 'expedientes';
  const hash = location.hash.slice(1);
  if (['expedientes', 'pool'].includes(hash)) return hash;
  if (actor !== 'admin') return 'trabajo';
  return hash === 'correo' ? 'correo' : 'recepcion';
}

const titles = {
  recepcion:'Recepción', correo:'Recibir desde correo electrónico',
  expedientes:'Expedientes', pool:'Pool de trámites', trabajo:'Mi trabajo',
};

async function renderMail(ticket, id) {
  const back = id ? caseLink(id) + '#recepcion' : '/';
  workspace.innerHTML = '<section class="mail-reception"><a data-home class="back-link"></a><div class="page-heading"><h1></h1></div><div class="panel" id="mail-host"></div></section>';
  const link = workspace.querySelector('.back-link');
  link.href = back;
  link.textContent = id ? '← Volver al documento' : '← Volver a recepción';
  const title = workspace.querySelector('h1');
  const host = workspace.querySelector('#mail-host');
  async function openReceived(caseId, received = false) {
    const current = await api('/api/cases/' + encodeURIComponent(caseId));
    if (ticket !== generation) return;
    if (current.receipt?.workflow === 'fiaga') await route(caseLink(caseId) + (received ? '#preanalisis' : ''));
    else location.assign('/?case=' + encodeURIComponent(caseId));
  }
  const gmail = createGmail({
    open(heading, html) {
      if (ticket !== generation) return;
      title.textContent = heading;
      document.title = heading + ' · FIAGA';
      host.innerHTML = html;
    },
    close() {}, notice(message) { if (ticket === generation) showFeedback(message); },
    fiaga:true, getManager:() => actor, getPanel:() => host.querySelector('#gmail-panel'),
    onOpenCase:openReceived, onReceive:id => openReceived(id, true),
  });
  if (id) await gmail.showCase(id);
  else await gmail.show();
}

function redirectsToEditor(data) {
  return data.stage === 'admin_review' && actor === 'admin' && !['#recepcion', '#borrador-anterior'].includes(location.hash);
}

function poll(ticket, failures = 0) {
  clearTimeout(timer);
  if (ticket !== generation || !['preparing', 'integration'].includes(detail?.stage) || detail.error) return;
  const delay = failures ? Math.min(15000, 2200 * (2 ** Math.min(failures, 3))) : 2200;
  timer = setTimeout(async () => {
    if (ticket !== generation) return;
    if (globalThis.document?.hidden) {
      poll(ticket, failures);
      return;
    }
    let nextFailures = 0;
    try {
      const fresh = await api(poolPath(detail.case_id));
      if (ticket !== generation) return;
      if (redirectsToEditor(fresh)) {
        location.replace(adminReviewLink(fresh.case_id, location.hash));
        return;
      }
      const changed = fresh.revision !== detail.revision || fresh.stage !== detail.stage || fresh.error !== detail.error;
      const progressChanged = fresh.progress?.updated_at !== detail.progress?.updated_at
        || fresh.scope_revoked !== detail.scope_revoked;
      const previous = detail;
      detail = fresh;
      if (changed) {
        showFeedback('');
        renderCase({keepReader:true});
        announcement.textContent = fresh.error || 'El expediente se actualizó.';
      } else if (progressChanged) {
        updateCaseProgress(workspace, fresh, actor, previous);
      }
    } catch (error) {
      nextFailures = failures + 1;
      if (ticket === generation) showFeedback(error.message, true);
    }
    if (ticket === generation && nextFailures < 8) poll(ticket, nextFailures);
  }, delay);
}

async function load({focus = false} = {}) {
  const ticket = ++generation;
  clearTimeout(timer);
  const id = currentId();
  releaseReceipt?.();
  releaseReceipt = null;
  const page = pageName();
  document.querySelectorAll('[data-admin-only]').forEach(el => { el.hidden = actor !== 'admin'; });
  document.querySelectorAll('[data-operator-only]').forEach(el => { el.hidden = actor === 'admin'; });
  const resources = document.querySelector('.resources');
  if (resources) resources.open = false;
  document.querySelectorAll('.tabs [data-page]').forEach(link => {
    if (link.dataset.page === (page === 'correo' ? 'recepcion' : page)) link.setAttribute('aria-current','page');
    else link.removeAttribute('aria-current');
  });
  showFeedback('');
  workspace.setAttribute('aria-busy','true');
  try {
    if (page === 'correo' || (id && location.hash === '#correo-original')) {
      detail = null;
      await renderMail(ticket, id);
    } else if (id) {
      if (detail?.case_id !== id) {
        detail = null;
        document.title = 'Abriendo expediente · FIAGA';
        workspace.innerHTML = '<p class="case-opening panel" role="status">Abriendo el expediente…</p>';
      }
      const data = await api(poolPath(id));
      if (ticket !== generation) return;
      if (data.stage === 'legacy') {
        location.replace('/?case=' + encodeURIComponent(id));
        return;
      }
      if (redirectsToEditor(data)) {
        location.replace(adminReviewLink(id, location.hash));
        return;
      }
      detail = data;
      renderCase();
      poll(ticket);
    } else {
      let items = [];
      try {
        ({items} = await api('/api/pool'));
      } catch (error) {
        if (page !== 'recepcion') throw error;
        items = null;
        if (ticket === generation) showFeedback('No se pudieron consultar los ingresos recientes. Puedes recibir una solicitud o volver a consultar los expedientes.', true);
      }
      if (ticket !== generation) return;
      detail = null;
      workspace.innerHTML = homeView(items, {page, actor, managers});
      const receipt = workspace.querySelector('#upload');
      if (receipt) releaseReceipt = bindReceipt(receipt);
      document.title = titles[page] + ' · FIAGA';
    }
    if (ticket !== generation) return;
    dirty = Boolean(workspace.querySelector('#plan[data-edited="true"]'));
    retainedPlan = null;
    if (focus) document.querySelector('#contenido').focus();
  } catch (error) {
    if (ticket !== generation) return;
    detail = null;
    workspace.innerHTML = '<div class="actions"><button type="button" data-command="refresh">Reintentar</button><a data-home href="/">Volver al inicio</a></div>';
    showFeedback(error.message, true);
  } finally {
    if (ticket === generation) workspace.removeAttribute('aria-busy');
  }
}

function canLeave() {
  return !busy && (!dirty || window.confirm('Hay cambios sin guardar. ¿Salir de esta edición?'));
}

async function route(url) {
  if (new URL(url, location.href).href !== location.href) {
    history.pushState({fiagaPosition:++historyPosition}, '', url);
  }
  window.scrollTo(0, 0);
  await load({focus:true});
}

async function perform(label, operation, {openPage = false} = {}) {
  if (busy) return;
  busy = true;
  clearTimeout(timer);
  ++generation;
  showFeedback(label);
  actorSelect.disabled = true;
  managerButton.disabled = true;
  workspace.inert = true;
  header.inert = true;
  workspace.setAttribute('aria-busy','true');
  let nextPage;
  try {
    const startLocation = location.href;
    const destination = await operation();
    if (location.href !== startLocation) return;
    dirty = false;
    if (openPage) nextPage = destination;
    else if (destination) await route(destination);
    else await load({focus:true});
    if (!openPage) announcement.textContent = 'Cambios guardados en el expediente.';
  } catch (error) {
    showFeedback(error.message + (error.status === 409 ? ' Actualiza el expediente para ver su estado actual.' : ''), true);
    poll(generation);
  } finally {
    actorSelect.disabled = false;
    managerButton.disabled = false;
    workspace.inert = false;
    header.inert = false;
    workspace.removeAttribute('aria-busy');
    busy = false;
  }
  if (nextPage) location.assign(nextPage);
}

document.addEventListener('click', event => {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
  const editorLink = event.target.closest('a[data-open-editor]');
  if (editorLink) {
    // Keep the link's native navigation and the browser's unsaved-changes guard.
    if (!busy && !dirty) {
      workspace.querySelector('[data-opening]')?.removeAttribute('data-opening');
      editorLink.setAttribute('data-opening', '');
      announcement.textContent = 'Abriendo el expediente…';
    }
    return;
  }
  const link = event.target.closest('a[data-home], .fiaga-route-layout nav a[href^="/?expediente="]');
  if (link) {
    event.preventDefault();
    if (canLeave()) void route(link.href);
    return;
  }
  const button = event.target.closest('[data-command]');
  if (!button || busy) return;
  const command = button.dataset.command;
  if (command === 'refresh') {
    if (canLeave()) void load();
    return;
  }
  if (!detail) return;
  const path = poolPath(detail.case_id);
  const body = {revision:detail.revision, actor_id:actor};
  if (command === 'open-review') void perform('Abriendo el preanálisis…', async () => {
    await api(path + '/open-review', body);
    return caseLink(detail.case_id) + '#preanalisis';
  });
  if (command === 'retry') void perform('Reiniciando el procesamiento…', async () => { await api(path + '/start', {actor_id:actor}); });
  if (command === 'claim') void perform('Tomando el trámite…', async () => { await api(path + '/tasks/' + encodeURIComponent(button.dataset.task) + '/claim', body); });
  if (command === 'approve') void perform('Registrando la aprobación…', async () => {
    await api(path + '/approve', body);
    return caseLink(detail.case_id);
  });
});

workspace.addEventListener('submit', event => {
  event.preventDefault();
  const form = event.target;
  if (busy || form.closest('#mail-host') || !form.reportValidity()) return;
  if (form.id === 'upload') {
    const body = new FormData(form);
    for (const field of ['received_date', 'due_date']) {
      if (!body.get(field)) body.delete(field);
    }
    body.set('workflow','fiaga');
    const button = form.querySelector('button[type="submit"]');
    if (!button) return;
    const caption = button.querySelector('span');
    const idleCaption = caption.textContent;
    void perform('Recibiendo el PDF…', async () => {
      caption.textContent = 'Recibiendo el PDF…';
      button.disabled = true;
      try {
        const saved = await api('/api/cases', body);
        const review = document.createElement('a');
        review.href = adminReviewLink(saved.id, '#preanalisis');
        review.className = 'button primary channel-action';
        review.textContent = 'Abrir preanálisis';
        form.elements.file.disabled = true;
        form.querySelector('.receipt-confirm').replaceChildren(review);
        showFeedback('PDF recibido. Abriendo el preanálisis…');
        return review.href;
      } finally {
        button.disabled = false;
        caption.textContent = idleCaption;
      }
    }, {openPage:true});
    return;
  }
  if (!detail) return;
  const path = poolPath(detail.case_id);
  if (form.hasAttribute('data-review')) {
    void perform('Guardando la corrección de la petición…', async () => {
      const values = new FormData(form);
      const answer = String(values.get('answer')).trim();
      const reason = String(values.get('reason')).trim();
      const gaps = String(values.get('gaps')).split('\n').map(line => line.trim()).filter(Boolean);
      if (!reason || (!gaps.length && !answer)) throw new Error('Indica el motivo y registra una respuesta o un faltante.');
      const draftPlan = workspace.querySelector('#plan[data-edited="true"]');
      await api(path + '/requests/' + encodeURIComponent(form.dataset.review) + '/review',
        {actor_id:actor, revision:detail.revision, answer, gaps, reason});
      if (draftPlan) retainedPlan = {id:detail.case_id, rows:readPlan(draftPlan, false)};
    });
  } else if (form.id === 'plan') {
    void perform('Publicando la decisión del administrador…', async () => {
      const tasks = readPlan(form);
      await api(path + (form.dataset.returning === 'true' ? '/return' : '/publish'), {actor_id:actor, revision:detail.revision, tasks});
      return caseLink(detail.case_id);
    });
  } else if (form.id === 'contribute') {
    void perform('Guardando el aporte…', async () => {
      const body = new FormData(form);
      const files = [...form.elements.files.files];
      body.delete('files');
      files.forEach(file => body.append('files', file));
      if (!String(body.get('note') || '').trim() && !files.length) throw new Error('Escribe una respuesta o adjunta un archivo para completar el trámite.');
      body.set('actor_id', actor);
      body.set('revision', String(detail.revision));
      await api(path + '/tasks/' + encodeURIComponent(form.dataset.task) + '/complete', body);
      return caseLink(detail.case_id);
    });
  }
});

workspace.addEventListener('input', event => {
  if (event.target.closest('#upload, #plan, #contribute, [data-review]')) dirty = true;
});
workspace.addEventListener('click', event => {
  if (event.target.closest('[data-plan]')) dirty = true;
});
actorSelect.addEventListener('change', () => {
  if (!canLeave()) { actorSelect.value = actor; return; }
  actor = actorSelect.value;
  try { sessionStorage.setItem('fiaga-profile', actor); } catch {}
  if (!currentId() && (['#cargar', '#correo'].includes(location.hash) || location.hash === '#trabajo')) void route('/');
  else void load();
});
window.addEventListener('popstate', event => {
  if (restoringHistory) { restoringHistory = false; return; }
  if (location.hash === '#contenido') return;
  const target = event.state?.fiagaPosition;
  if (Number.isInteger(target) && target !== historyPosition && !canLeave()) {
    restoringHistory = true;
    history.go(historyPosition - target);
    return;
  }
  historyPosition = target ?? historyPosition;
  void load({focus:true});
});
window.addEventListener('beforeunload', event => {
  if (dirty || busy) { event.preventDefault(); event.returnValue = true; }
});
window.addEventListener('pageshow', event => {
  if (!event.persisted) return;
  workspace.querySelector('[data-opening]')?.removeAttribute('data-opening');
  announcement.textContent = '';
  if (actor !== savedProfile()) {
    location.reload();
    return;
  }
  if (workspace.querySelector('#upload input[type="file"]:disabled')) void load();
});

bindManagerDialog({
  api, isAdmin:() => actor === 'admin', notify:showFeedback,
  onAdded(manager) {
    if (!managers.some(m => m.id === manager.id)) managers.push(manager);
    workspace.querySelectorAll('select[name="manager_id"]').forEach(select => addProfileOption(select, manager));
  },
});

async function init() {
  try {
    managers = await api('/api/managers');
    managers.forEach(manager => addProfileOption(actorSelect, manager));
    actor = initialHomeProfile(managers);
    actorSelect.value = actor;
    await load();
  } catch (error) {
    workspace.innerHTML = '<button type="button" id="reload">Reintentar conexión</button>';
    workspace.querySelector('#reload').onclick = () => location.reload();
    showFeedback(error.message, true);
  }
}

void init();
