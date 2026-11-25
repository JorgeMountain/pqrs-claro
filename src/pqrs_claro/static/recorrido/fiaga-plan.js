import {esc} from './views.js';

export const kindLabels = {
  dependencia: 'Dependencia',
  docente: 'Docente',
  directivo: 'Directivo',
  comite: 'Comité',
  tercero: 'Tercero',
  por_definir: 'Por definir',
};

function taskEditor(task, requests, managers) {
  const options = requests.map((request, index) => `<option value="${esc(request.id)}"
    ${request.id === task.request_id ? 'selected' : ''}>Petición ${index + 1} · ${esc(request.text)}</option>`).join('');
  return `<fieldset class="task-editor"><legend>Trámite <span data-order></span></legend>
    <label class="field">Petición<select name="request_id" required>${options}</select></label>
    <label class="field">Aporte que se necesita<textarea name="instruction" required rows="2" maxlength="8000">${esc(task.instruction)}</textarea></label>
    <label class="field">Dependencia o responsable<input name="department" required maxlength="200" placeholder="Ej.: Decanatura, departamento, profesor o tercero" value="${esc(task.department)}"></label>
    <div class="plan-suggestion" data-plan-suggestion hidden></div>
    <label class="field">Quién puede tomarlo<select name="manager_id">
      <option value="">Cualquier tramitador</option>
      ${managers.map(m => `<option value="${esc(m.id)}" ${task.manager_id === m.id ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}
    </select></label>
    <div class="row-actions"><button type="button" data-plan="up">Subir</button>
      <button type="button" data-plan="down">Bajar</button><button type="button" class="quiet remove" data-plan="remove">Quitar</button></div>
  </fieldset>`;
}

export function planForm(detail, returning = false) {
  const title = returning ? 'Devolver a la pool' : 'Organizar los trámites';
  return `<form id="plan" class="panel panel-body" data-returning="${returning}">
    <h2>${title}</h2><p class="help">${returning
      ? 'Indica qué falta y a qué dependencia o responsable le corresponde. Los aportes de las rondas anteriores se conservan.'
      : 'Revisa los faltantes y ordénalos según la dependencia o responsable que deba intervenir primero.'}</p>
    <p class="plan-ai-status" data-plan-ai-status role="status" aria-live="polite" hidden></p>
    <div id="plan-rows"></div>
    <p class="empty-plan" data-empty-plan></p>
    <div class="actions"><button type="button" data-plan="add">Añadir trámite</button>
      <button class="primary" type="submit" data-plan-submit></button></div></form>`;
}

export function applyPlanSuggestions(form, suggestions = [], {markEdited = false} = {}) {
  const editors = [...form.querySelectorAll('.task-editor')];
  let filled = 0;
  let alternative = 0;
  for (const item of suggestions) {
    const row = editors[item.index];
    if (!row || !item.responsible) continue;
    if (item.request_id && row.querySelector('[name="request_id"]')?.value !== item.request_id) continue;
    const input = row.querySelector('[name="department"]');
    const box = row.querySelector('[data-plan-suggestion]');
    const label = kindLabels[item.kind] || 'Sugerencia';
    const current = input.value.trim();
    if (!current) {
      input.value = item.responsible;
      if (markEdited) form.dataset.edited = 'true';
      filled++;
      box.innerHTML = `<span class="plan-suggestion-kind">Sugerencia IA · ${esc(label)}</span> <span>${esc(item.reason)}</span>`;
      box.hidden = false;
    } else if (current === item.responsible) {
      box.innerHTML = `<span class="plan-suggestion-kind">Sugerencia IA · ${esc(label)}</span> <span>${esc(item.reason)}</span>`;
      box.hidden = false;
    } else {
      alternative++;
      box.innerHTML = `<span class="plan-suggestion-kind">Sugerencia IA · ${esc(label)}</span> <span>${esc(item.responsible)} — ${esc(item.reason)}</span> <button type="button" class="quiet plan-apply-suggestion" data-plan="apply-suggestion" data-value="${esc(item.responsible)}" data-kind="${esc(label)}" data-reason="${esc(item.reason)}">Usar sugerencia</button>`;
      box.hidden = false;
    }
  }
  return {filled, alternative, total: suggestions.length};
}

export function bindPlan(form, detail, managers, savedRows) {
  const requests = detail.requests;
  const returning = form.dataset.returning === 'true';
  const rows = form.querySelector('#plan-rows');
  const submit = form.querySelector('[data-plan-submit]');
  function append(task) {
    rows.insertAdjacentHTML('beforeend', taskEditor(task, requests, managers));
  }
  function update() {
    const editors = [...rows.children];
    editors.forEach((row, i) => {
      row.querySelector('[data-order]').textContent = String(i + 1);
      for (const [command, disabled] of [['up', i === 0], ['down', i === editors.length - 1]]) {
        row.querySelector(`[data-plan="${command}"]`).disabled = disabled;
      }
    });
    const empty = form.querySelector('[data-empty-plan]');
    empty.hidden = Boolean(editors.length);
    empty.textContent = returning ? 'Añade al menos un trámite para devolver el borrador.' : 'Sin trámites en la secuencia.';
    submit.disabled = returning && !editors.length;
    submit.textContent = returning ? 'Publicar devolución' : editors.length ? 'Publicar secuencia en la pool' : 'Pasar a revisión final';
  }
  if (savedRows) {
    savedRows.forEach(append);
    form.dataset.edited = 'true';
  } else {
    const incomplete = requests.filter(request => request.gap);
    incomplete.forEach(request => append({request_id: request.id, instruction: request.gap}));
    if (returning && !incomplete.length) append({});
  }
  update();
  form.addEventListener('input', () => { form.dataset.edited = 'true'; });
  form.addEventListener('click', event => {
    const button = event.target.closest('[data-plan]');
    if (!button) return;
    form.dataset.edited = 'true';
    const command = button.dataset.plan;
    const row = button.closest('fieldset');
    if (command === 'apply-suggestion' && row) {
      const input = row.querySelector('[name="department"]');
      input.value = button.dataset.value || '';
      const box = row.querySelector('[data-plan-suggestion]');
      box.innerHTML = `<span class="plan-suggestion-kind">Sugerencia IA · ${esc(button.dataset.kind || 'Sugerencia')}</span> <span>${esc(button.dataset.reason || '')}</span>`;
      input.focus();
      return;
    }
    if (command === 'add') {
      append({});
      rows.lastElementChild.querySelector('select').focus();
    } else if (command === 'remove') {
      const next = row.nextElementSibling || row.previousElementSibling;
      row.remove();
      (next?.querySelector('select') || form.querySelector('[data-plan="add"]')).focus();
    } else if (command === 'up' && row.previousElementSibling) {
      rows.insertBefore(row, row.previousElementSibling);
    } else if (command === 'down' && row.nextElementSibling) {
      rows.insertBefore(row.nextElementSibling, row);
    }
    update();
    if (command === 'up' || command === 'down') row.querySelector('select').focus();
  });
}

export function readPlan(form, validate = true) {
  return [...form.querySelectorAll('.task-editor')].map(row => {
    const value = name => row.querySelector(`[name="${name}"]`).value.trim();
    const task = {request_id: value('request_id'), department: value('department'), instruction: value('instruction')};
    if (validate && (!task.department || !task.instruction)) throw new Error('Escribe el responsable y el aporte de cada trámite.');
    if (value('manager_id')) task.manager_id = value('manager_id');
    return task;
  });
}
