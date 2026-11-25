import {icon} from './inbox-icons.js';

export function pageNavigation(selectorHtml, previousDisabled, nextDisabled) {
  return `<div class="document-page-nav" role="group" aria-label="Navegación entre páginas">
    <button type="button" data-page-step="-1" title="Página anterior" aria-label="Página anterior"${previousDisabled ? ' disabled' : ''}>${icon('arrow-left')}</button>
    ${selectorHtml}
    <button type="button" data-page-step="1" title="Página siguiente" aria-label="Página siguiente"${nextDisabled ? ' disabled' : ''}>${icon('arrow-right')}</button>
  </div>`;
}

export function scrollNavigation() {
  return `<div class="document-scroll-nav" role="group" aria-label="Desplazamiento dentro de la página">
    <button type="button" data-scroll-step="-1" title="Subir en la página" aria-label="Subir en la página" disabled>${icon('arrow-right')}</button>
    <button type="button" data-scroll-step="1" title="Bajar en la página" aria-label="Bajar en la página" disabled>${icon('arrow-right')}</button>
  </div>`;
}

export function bindDocumentScroll(root, viewport, sheet) {
  const up = root.querySelector('[data-scroll-step="-1"]');
  const down = root.querySelector('[data-scroll-step="1"]');
  const listeners = new AbortController();
  function updateButtons() {
    up.disabled = viewport.scrollTop <= 0;
    down.disabled = viewport.scrollHeight - viewport.clientHeight - viewport.scrollTop <= 1;
  }
  for (const button of [up, down]) {
    button.addEventListener('click', () => {
      const distance = Math.round(viewport.clientHeight * 0.8);
      viewport.scrollBy({top: Number(button.dataset.scrollStep) * distance});
    }, {signal: listeners.signal});
  }
  viewport.addEventListener('scroll', updateButtons, {passive: true, signal: listeners.signal});
  const observer = new ResizeObserver(updateButtons);
  observer.observe(viewport);
  observer.observe(sheet);
  updateButtons();
  return () => {
    listeners.abort();
    observer.disconnect();
  };
}
