import {esc} from './views.js';

const fields = {topics:'Tema', issuer:'Dependencia emisora', period:'Período'};

export function labelFilterMarkup() {
  return Object.entries(fields).map(([key, title]) =>
    `<label class="field"><span id="filter-${key}">${title}</span><select data-library-label="${key}" aria-labelledby="filter-${key}" disabled><option>Todos</option></select></label>`
  ).join('');
}

export function bindLabelFilters(panel, sources, selected, changed) {
  for (const select of panel.querySelectorAll('[data-library-label]')) {
    const key = select.dataset.libraryLabel;
    const values = new Set();
    for (const source of sources) {
      if (!source.is_latest) continue;
      const value = source.sector?.[key];
      for (const label of Array.isArray(value) ? value : [value]) {
        if (label) values.add(label);
      }
    }
    select.replaceChildren(new Option('Todos', ''), new Option('Sin registrar', 'null'));
    for (const value of [...values].sort((a,b) => a.localeCompare(b, 'es'))) {
      select.add(new Option(value, JSON.stringify(value)));
    }
    select.value = selected[key] || '';
    selected[key] = select.value;
    select.disabled = false;
    select.onchange = () => { selected[key] = select.value; changed(); };
  }
}

export function matchesLabelFilters(sector, selected) {
  for (const [key, encoded] of Object.entries(selected)) {
    if (!encoded) continue;
    const wanted = JSON.parse(encoded);
    const value = sector?.[key];
    const labels = Array.isArray(value) ? value : value ? [value] : [];
    if (wanted === null ? labels.length > 0 : !labels.includes(wanted)) return false;
  }
  return true;
}

export function sectorSummary(sector) {
  const topics = sector?.topics?.join(', ') || 'Sin registrar';
  return `<dl class="library-label-values"><div><dt>Temas</dt><dd>${esc(topics)}</dd></div>
    <div><dt>Dependencia emisora</dt><dd>${esc(sector?.issuer || 'Sin registrar')}</dd></div>
    <div><dt>Período</dt><dd>${esc(sector?.period || 'Sin registrar')}</dd></div></dl>`;
}

export function labelEditor(sector) {
  return `<section class="source"><h3>Clasificación de esta versión</h3>${sectorSummary(sector)}
    ${sector.basis ? `<p class="library-meta">${esc(sector.basis)}</p>` : ''}
    <details><summary>Editar etiquetas</summary><form data-library-label-editor>
      <label class="field">Temas (uno por línea)<textarea name="topics" rows="3">${esc(sector.topics.join('\n'))}</textarea></label>
      <label class="field">Dependencia emisora<input name="issuer" maxlength="120" value="${esc(sector.issuer || '')}"></label>
      <label class="field">Período al que aplica<input name="period" maxlength="120" value="${esc(sector.period || '')}"></label>
      <button type="submit">Guardar etiquetas</button><p role="alert" data-label-error></p>
    </form></details></section>`;
}
