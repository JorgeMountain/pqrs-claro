import {createWorkClock, workId} from './work-clock.js';

async function post(caseId, path, body, keepalive = false) {
  const response = await fetch('/api/cases/' + encodeURIComponent(caseId) + '/' + path, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    keepalive, signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const message = typeof data.detail === 'string' ? data.detail : 'Revisa los datos del registro.';
    throw Object.assign(new Error(message), {status: response.status});
  }
  return response.json();
}

const labels = {
  active: 'Tiempo en pantalla · Registro activo',
  connecting: 'Conectando el registro de tiempo…',
  away: 'El registro se reanuda al volver al expediente.',
  ended: 'El registro se reanudará con tu próxima interacción.',
  unconfirmed: 'Lectura sin confirmar',
  offline: 'Sin conexión al registro. Se reintentará automáticamente.',
  unavailable: 'El expediente ya no admite registrar tiempo con este gestor.',
};

export function bindWorkActivity({view, actor, notice}) {
  const bar = document.createElement('section');
  bar.className = 'work-activity';
  bar.setAttribute('aria-label', 'Tiempo de gestión del expediente');
  bar.hidden = true;
  bar.innerHTML = `<span role="status"></span><button type="button" class="text-button" data-confirm-reading hidden>Confirmar que sigo trabajando</button>
    <button type="button" class="text-button" data-external-work>Registrar trabajo externo</button>`;
  view.before(bar);
  const dialog = document.createElement('dialog');
  dialog.className = 'work-activity-dialog';
  dialog.setAttribute('aria-labelledby', 'work-activity-title');
  document.body.append(dialog);
  const confirmButton = bar.querySelector('[data-confirm-reading]');
  const externalButton = bar.querySelector('[data-external-work]');
  bar.querySelector('[role="status"]').textContent = labels.away;
  let record = null, target = null, generalDrawer = false, focused = document.hasFocus();
  let mode = '', status = '', openFormId = '';
  const clock = createWorkClock({
    post: (id, body) => post(id, 'work-session', body, body.event === 'stop'),
    status: paint,
  });

  function paint(value) {
    status = value;
    bar.querySelector('[role="status"]').textContent = labels[value];
    confirmButton.hidden = value !== 'unconfirmed';
    externalButton.disabled = value === 'unavailable';
    if (value !== 'unconfirmed' && mode === 'reading' && dialog.open) dialog.close();
    if (value === 'unconfirmed' && !dialog.open && focused && !document.hidden) askReading();
  }

  function askReading() {
    mode = 'reading';
    dialog.innerHTML = `<h2 id="work-activity-title">¿Sigues trabajando en el expediente?</h2>
      <p>Han pasado dos minutos sin señales de actividad. El tiempo queda sin confirmar hasta que retomes el registro.</p>
      <div class="dialog-actions"><button type="button" class="primary" data-resume>Sí, continúo</button><button type="button" data-dismiss>Cerrar aviso</button></div>`;
    dialog.querySelector('[data-resume]').onclick = () => { void clock.confirm(); };
    dialog.querySelector('[data-dismiss]').onclick = () => dialog.close();
    if (!dialog.open) dialog.showModal();
  }

  function declareWork() {
    if (!target) return;
    const {caseId, actorId} = target;
    mode = 'external';
    const entryId = openFormId = workId();
    dialog.innerHTML = `<h2 id="work-activity-title">Registrar trabajo externo</h2>
      <p>Registra una actividad realizada fuera del expediente, como una llamada. Se mostrará por separado del tiempo estimado en pantalla.</p>
      <form><label class="field">Duración en minutos<input required name="minutes" type="number" min="1" max="1440" step="1"></label>
      <label class="field">Actividad realizada<textarea required name="reason" minlength="3" maxlength="500" rows="2"></textarea></label>
      <p role="alert"></p><div class="dialog-actions"><button class="primary" type="submit">Guardar actividad</button>
      <button type="button" data-dismiss>Cancelar</button></div></form>`;
    const form = dialog.querySelector('form');
    let payload;
    form.querySelector('[data-dismiss]').onclick = () => dialog.close();
    form.onsubmit = async event => {
      event.preventDefault();
      if (!target || caseId !== target.caseId || actorId !== target.actorId) return;
      const save = form.querySelector('[type="submit"]');
      if (save.disabled) return;
      if (!payload) payload = {actor_id: actorId, entry_id: entryId, minutes: Number(form.elements.minutes.value), reason: form.elements.reason.value.trim()};
      save.disabled = true;
      form.elements.minutes.readOnly = form.elements.reason.readOnly = true;
      form.querySelector('[role="alert"]').textContent = '';
      try {
        await post(caseId, 'external-work', payload);
        if (openFormId === entryId && dialog.open) {
          dialog.close();
          notice('Trabajo externo registrado.');
        }
      } catch (error) {
        if (error.status && error.status < 500) {
          payload = null;
          form.elements.minutes.readOnly = form.elements.reason.readOnly = false;
          form.querySelector('[role="alert"]').textContent = error.message;
        } else {
          form.querySelector('[role="alert"]').textContent = 'No se pudo confirmar el registro. Reintenta guardar esta misma actividad.';
        }
      } finally {
        save.disabled = false;
      }
    };
    dialog.showModal();
  }

  function sync() {
    const actorId = actor();
    const eligible = record?.management?.owner_id && record.management.owner_id === actorId &&
      record.management.state !== 'closed' && !record.deleted_at;
    const next = eligible ? {caseId: record.id, actorId} : null;
    if (target?.caseId !== next?.caseId || target?.actorId !== next?.actorId) {
      openFormId = '';
      if (dialog.open) dialog.close();
    }
    target = next;
    bar.hidden = !target || generalDrawer;
    void clock.setTarget(!bar.hidden && focused && !document.hidden ? target : null);
  }

  dialog.addEventListener('close', () => {
    if (dialog.open) return;
    const wasExternal = mode === 'external';
    openFormId = '';
    mode = '';
    if (wasExternal && status === 'unconfirmed' && target && focused && !document.hidden) askReading();
  });
  externalButton.onclick = declareWork;
  confirmButton.onclick = () => { void clock.confirm(); };
  window.addEventListener('blur', () => { focused = false; sync(); });
  window.addEventListener('focus', () => { focused = true; sync(); });
  window.addEventListener('pagehide', () => { focused = false; sync(); });
  window.addEventListener('pageshow', () => { focused = document.hasFocus(); sync(); });
  document.addEventListener('visibilitychange', () => { focused = document.hasFocus(); sync(); });
  window.addEventListener('pqrs-manager-change', sync);
  window.addEventListener('storage', event => { if (!event.key || event.key === 'pqrs-pilot-manager') sync(); });
  for (const name of ['pointerdown', 'keydown', 'wheel', 'touchmove', 'input']) {
    document.addEventListener(name, event => { if (event.isTrusted) void clock.interact(); }, {capture: true, passive: true});
  }
  window.setInterval(() => { void clock.tick(); }, 15000);
  return {
    setCase(value) { record = value; sync(); },
    setGeneralDrawer(open) { generalDrawer = open; sync(); },
    flush: clock.flush,
  };
}
