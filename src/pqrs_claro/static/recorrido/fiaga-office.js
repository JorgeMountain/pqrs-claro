import {paginate} from './document-pages.js';
import {esc} from './views.js';

export function officePreview(detail, version, title) {
  const layout = detail.office_layouts?.[version];
  const paragraphs = detail[version].split('\n\n').map((text, index) => {
    const kind = layout?.kinds?.[index] || 'body';
    const tag = kind === 'heading' ? 'h3' : 'div';
    return `<${tag} class="oficio-block kind-${esc(kind)}">${esc(text)}</${tag}>`;
  }).join('');
  return `<fiaga-office class="document-stage" data-template="${esc(layout?.letterhead?.sha256 || '')}">
    <template>${paragraphs}</template>
    <div class="office-preview-tools" role="group" aria-label="Vista de ${esc(title)}">
      <button type="button" data-prev aria-label="Página anterior del oficio" disabled>←</button>
      <span data-count role="status"></span>
      <button type="button" data-next aria-label="Página siguiente del oficio" disabled>→</button>
      <label><span class="sr-only">Zoom del oficio</span><select data-fit>
        <option value="page">Página completa</option><option value="width">Ajustar al ancho</option>
        <option value="actual">100 %</option></select></label>
    </div>
    <div class="document-canvas" role="region" tabindex="0" aria-label="${esc(title)}">
      <div class="oficio-pages"></div>
    </div>
  </fiaga-office>`;
}

if (typeof customElements !== 'undefined' && !customElements.get('fiaga-office')) customElements.define('fiaga-office', class extends HTMLElement {
  connectedCallback() {
    // innerHTML may connect the element before its children have finished parsing.
    queueMicrotask(() => {
      if (!this.isConnected || this.observer) return;
      const canvas = this.querySelector('.document-canvas');
      const pages = this.querySelector('.oficio-pages');
      const previous = this.querySelector('[data-prev]');
      const next = this.querySelector('[data-next]');
      const count = this.querySelector('[data-count]');
      const fit = this.querySelector('[data-fit]');
      const template = this.dataset.template ? {sha256:this.dataset.template} : null;
      let page = 0;
      const display = () => {
        if (!canvas.clientHeight || !canvas.clientWidth) return;
        if (!pages.childElementCount || pages.dataset.needsPagination) {
          const blocks = [...this.querySelector('template').content.children];
          paginate(this, blocks, block => block.outerHTML, template);
          if (pages.dataset.needsPagination) return;
        }
        const frames = [...pages.children];
        if (!frames.length) return;
        page = Math.max(0, Math.min(page, frames.length - 1));
        frames.forEach((frame, i) => { frame.hidden = i !== page; });
        const paper = frames[page].querySelector('.oficio-sheet');
        if (!paper) return;
        const style = getComputedStyle(canvas);
        const width = canvas.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        const height = canvas.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
        const scale = width / paper.offsetWidth;
        const pageHeight = paper.offsetHeight + parseFloat(getComputedStyle(paper).marginBottom);
        pages.style.zoom = fit.value === 'actual' ? 1 : fit.value === 'width' ? scale : Math.min(scale, height / pageHeight, 1);
        count.textContent = `Página ${page + 1} de ${frames.length}`;
        previous.disabled = page === 0;
        next.disabled = page === frames.length - 1;
      };
      const changePage = offset => {
        page += offset;
        display();
        canvas.scrollTo(0, 0);
      };
      previous.onclick = () => changePage(-1);
      next.onclick = () => changePage(1);
      fit.onchange = () => { display(); canvas.scrollTo(0, 0); };
      this.observer = new ResizeObserver(display);
      this.observer.observe(canvas);
      display();
    });
  }

  disconnectedCallback() {
    this.observer?.disconnect();
    this.observer = null;
  }
});
