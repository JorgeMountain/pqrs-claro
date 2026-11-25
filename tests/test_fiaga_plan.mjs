import test from 'node:test';
import assert from 'node:assert/strict';
import {applyPlanSuggestions, planForm} from '../src/pqrs_claro/static/recorrido/fiaga-plan.js';

function fakeRow(requestId, department = '') {
  const input = {value: department};
  const select = {value: requestId};
  const box = {hidden: true, innerHTML: ''};
  return {
    querySelector(selector) {
      if (selector === '[name="department"]') return input;
      if (selector === '[name="request_id"]') return select;
      if (selector === '[data-plan-suggestion]') return box;
      return null;
    },
    input,
    box,
  };
}

test('planForm muestra estado automático de IA sin botón manual y etiqueta abierta a responsable', () => {
  const html = planForm({requests: []});
  assert.match(html, /data-plan-ai-status/);
  assert.doesNotMatch(html, /data-plan-suggest/);
  assert.match(html, /dependencia o responsable/);
});

test('applyPlanSuggestions llena campos vacíos sin sobrescribir texto manual y escapa HTML', () => {
  const r1 = fakeRow('P1', '');
  const r2 = fakeRow('P2', 'Decanatura');
  const form = {
    dataset: {},
    querySelectorAll(selector) {
      return selector === '.task-editor' ? [r1, r2] : [];
    },
  };
  const summary = applyPlanSuggestions(form, [
    {
      index: 0,
      request_id: 'P1',
      kind: 'docente',
      responsible: 'Docente: Carlos Trujillo',
      reason: 'La petición pide respuesta <personal> del profesor.',
    },
    {
      index: 1,
      request_id: 'P2',
      kind: 'tercero',
      responsible: 'Tercero externo: Ministerio',
      reason: 'Corresponde a entidad externa.',
    },
  ]);
  assert.deepEqual(summary, {filled: 1, alternative: 1, total: 2});
  assert.equal(r1.input.value, 'Docente: Carlos Trujillo');
  assert.equal(form.dataset.edited, undefined);
  assert.equal(r1.box.hidden, false);
  assert.match(r1.box.innerHTML, /Sugerencia IA · Docente/);
  assert.match(r1.box.innerHTML, /&lt;personal&gt;/);
  assert.doesNotMatch(r1.box.innerHTML, /<personal>/);

  assert.equal(r2.input.value, 'Decanatura');
  assert.equal(r2.box.hidden, false);
  assert.match(r2.box.innerHTML, /Usar sugerencia/);
  assert.match(r2.box.innerHTML, /Sugerencia IA · Tercero/);
});
