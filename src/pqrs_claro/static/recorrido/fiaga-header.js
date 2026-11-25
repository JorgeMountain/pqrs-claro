export function mountFiagaHeader(header) {
  header.classList.add('top', 'fiaga-header');
  // Keep the institutional strip visible while the navigation scrolls with the page.
  header.insertAdjacentHTML('beforebegin', `<div class="fiaga-brandbar">
    <div class="fiaga-brandbar-inner">
      <div class="fiaga-brandbar-name"><strong>FIAGA</strong><span>Gestión de PQRS</span></div>
      <time></time>
    </div>
  </div>`);
  const now = new Date();
  const time = header.previousElementSibling.querySelector('time');
  time.dateTime = now.toISOString();
  time.textContent = new Intl.DateTimeFormat('es-CO', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'America/Bogota',
  }).format(now);
  header.innerHTML = `
    <div class="top-inner">
      <a href="/" data-home class="fiaga-header-brand" aria-label="FIAGA · Gestión de PQRS, inicio">
        <img src="/logo.png" alt="Universidad de Antioquia">
      </a>
      <nav class="tabs" aria-label="Navegación principal">
        <div class="tabs-inner">
          <a href="/" data-home data-page="recepcion" data-admin-only>Recepción</a>
          <a href="/#trabajo" data-home data-page="trabajo" data-operator-only hidden>Mi trabajo</a>
          <a href="/#expedientes" data-home data-page="expedientes">Expedientes</a>
          <a href="/#pool" data-home data-page="pool">Pool de trámites</a>
          <details class="resources">
            <summary>Recursos</summary>
            <div class="resources-links">
              <a href="/?view=library">Biblioteca de fuentes</a>
              <a href="/?view=legacy">Expedientes anteriores</a>
              <button type="button" id="new-manager" data-admin-only>Añadir tramitador</button>
            </div>
          </details>
        </div>
      </nav>
      <div class="profile-tools"><label class="profile">Perfil del prototipo
        <select id="actor"><option value="admin">Administrador</option></select>
      </label></div>
    </div>`;
  header.insertAdjacentHTML('afterend', `
  <dialog id="manager-dialog" aria-labelledby="manager-title">
    <form id="manager-form"><h2 id="manager-title">Añadir tramitador</h2>
      <label class="field">Nombre del tramitador<input name="name" required maxlength="100" autofocus autocomplete="off"></label>
      <p id="manager-error" role="alert"></p>
      <div class="actions"><button class="primary" type="submit">Guardar tramitador</button><button type="button" id="manager-cancel">Cancelar</button></div>
    </form>
  </dialog>`);

  const resources = header.querySelector('.resources');
  const managerDialog = document.getElementById('manager-dialog');
  document.addEventListener('pointerdown', event => {
    if (resources.open && !managerDialog.open && !resources.contains(event.target)) resources.open = false;
  });
  resources.addEventListener('keydown', event => {
    if (resources.open && event.key === 'Escape') {
      resources.open = false;
      resources.querySelector('summary').focus();
      event.preventDefault();
    }
  });
}
