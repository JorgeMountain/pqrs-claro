import {request} from './management-ui.js?v=phase2';

const profileKey = 'fiaga-profile';
const switchKey = 'fiaga-profile-destination';

export function savedProfile() {
  try { return sessionStorage.getItem(profileKey) || 'admin'; } catch { return 'admin'; }
}

export function addProfileOption(select, manager) {
  if (![...select.options].some(option => option.value === manager.id)) {
    select.add(new Option(manager.name, manager.id));
  }
}

// Commit an editor selection in the destination document, after the browser's
// unsaved-changes prompt has allowed navigation. A copied URL cannot switch roles.
export function initialHomeProfile(managers) {
  const url = new URL(location.href);
  const requested = url.searchParams.get('perfil');
  try {
    if (requested && sessionStorage.getItem(switchKey) === url.search &&
        managers.some(manager => manager.id === requested)) {
      sessionStorage.setItem(profileKey, requested);
    }
    sessionStorage.removeItem(switchKey);
  } catch { /* A browser with storage disabled starts with the default profile. */ }
  if (requested !== null) {
    url.searchParams.delete('perfil');
    history.replaceState(history.state, '', url);
  }
  const saved = savedProfile();
  return managers.some(manager => manager.id === saved) ? saved : 'admin';
}

export function bindManagerDialog({api, isAdmin, onAdded, notify}) {
  const dialog = document.querySelector('#manager-dialog');
  const form = dialog.querySelector('#manager-form');
  const error = form.querySelector('[role="alert"]');
  const submit = form.querySelector('[type="submit"]');
  document.querySelector('#new-manager').addEventListener('click', () => {
    if (!isAdmin()) return;
    form.reset();
    error.textContent = '';
    dialog.showModal();
  });
  form.querySelector('#manager-cancel').addEventListener('click', () => dialog.close());
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!isAdmin() || submit.disabled || !form.reportValidity()) return;
    submit.disabled = true;
    try {
      const manager = await api('/api/managers', {name:form.elements.name.value.trim()});
      addProfileOption(document.querySelector('#actor'), manager);
      onAdded?.(manager);
      dialog.close();
      notify('Tramitador disponible en el selector de perfil: ' + manager.name);
    } catch (cause) {
      error.textContent = cause.message;
    } finally {
      submit.disabled = false;
    }
  });
}

export async function bindEditorProfile(caseUrl, notify) {
  const select = document.querySelector('#actor');
  bindManagerDialog({api:request, isAdmin:() => savedProfile() === 'admin', notify});
  select.addEventListener('change', () => {
    const next = select.value;
    select.value = 'admin';
    if (next === 'admin') return;
    const url = new URL(caseUrl, location.origin);
    url.searchParams.set('perfil', next);
    try {
      sessionStorage.setItem(switchKey, url.search);
      location.assign(url.href);
    } catch {
      notify('El navegador no pudo guardar el perfil seleccionado.');
    }
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted && savedProfile() !== 'admin') {
      location.replace(caseUrl);
    }
  });
  try {
    for (const manager of await request('/api/managers')) addProfileOption(select, manager);
  } catch {
    notify('No se pudieron cargar los perfiles de tramitadores.');
  }
}
