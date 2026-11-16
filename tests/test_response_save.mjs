import assert from 'node:assert/strict';
import test from 'node:test';
import {createResponseEditor} from '../src/pqrs_claro/static/recorrido/live-edit.js';

const copy = value => structuredClone(value);
const response = (value, status = 200) => ({ok: status < 400, status, json: async () => copy(value)});
const paragraph = text => ({text, cited_chunk_ids: ['chunk-1'], cited_fact_ids: ['fact-1'], office_section: 'response'});

// The DOM adapter exercises the real editor handlers and API payloads. Durable
// storage and reopening/reloading the complete page are covered by browser QA.
function setup(onSavedHook = () => {}) {
  const rows = new Map(['P1', 'P2'].map(requestId => [requestId, {
    request_id: requestId, label: requestId, title: 'Petición ficticia',
    revision: 1, paragraphs: [paragraph('Respuesta inicial ' + requestId)], edited_by: 'Origen',
  }]));
  const calls = [], saved = [], history = [], notices = [];
  let form, markup = '', putHook;
  const dialog = {open: false};
  function field() { return {value: '', hidden: false, disabled: false, textContent: '', innerHTML: '', focus() {}}; }
  function newForm() {
    const fields = new Map();
    return {
      isConnected: true,
      querySelector(selector) {
        // Session-actor UI itself has separate coverage.
        if (selector.includes('[name="author"]')) return null;
        if (!fields.has(selector)) fields.set(selector, field());
        return fields.get(selector);
      },
      querySelectorAll() { return [...fields.values()]; },
    };
  }
  const drawer = {
    querySelector: () => form,
    set innerHTML(value) {
      markup = value;
      if (!value.includes('<form')) return;
      form.querySelector('#response-actor').value = value.match(/id="response-actor"[^>]*value="([^"]*)"/)?.[1] || '';
      form.querySelector('#response-reload').hidden = /id="response-reload" hidden/.test(value);
    },
    get innerHTML() { return markup; },
  };
  globalThis.document = {querySelector: selector => selector === '#drawer-body' ? drawer : dialog};
  const accept = (requestId, body) => {
    const current = rows.get(requestId);
    if (body.revision !== current.revision) return response({detail: 'Revision conflict'}, 409);
    const updated = {...current, revision: current.revision + 1, edited_by: body.edited_by, paragraphs: copy(body.paragraphs)};
    // The actual API can omit this optional field when its value is 'response'.
    for (const p of updated.paragraphs) if (p.office_section === 'response') delete p.office_section;
    rows.set(requestId, updated);
    history.push(copy(body));
    return response(updated);
  };
  globalThis.fetch = async (url, options = {}) => {
    const method = options.method || 'GET';
    const body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({url, method, body});
    if (method === 'GET') return response({requests: [...rows.values()]});
    assert.equal(method, 'PUT');
    const requestId = decodeURIComponent(url.split('/').at(-1));
    return putHook ? putHook(requestId, body, accept) : accept(requestId, body);
  };
  const editor = createResponseEditor({
    open() { if (form) form.isConnected = false; form = newForm(); dialog.open = true; },
    close() { dialog.open = false; form.isConnected = false; },
    notice(message) { notices.push(message); }, getCase: () => ({id: 'C01'}),
    onSaved(row) { saved.push(copy(row)); return onSavedHook(row); },
  });
  return {
    editor, rows, calls, saved, history, drawer, dialog, notices,
    get form() { return form; },
    get writes() { return calls.filter(call => call.method === 'PUT'); },
    set putHook(value) { putHook = value; },
    text(value, index = 0) {
      form.oninput({target: {value, dataset: {paragraph: String(index)}, matches: selector => selector === '[data-paragraph]'}});
    },
    actor(value = 'Gestora QA') {
      form.querySelector('#response-actor').value = value;
      form.oninput({target: {id: 'response-actor', value, matches: () => false}});
    },
    submit() { return form.onsubmit({preventDefault() {}}); },
    closePanel() { dialog.open = false; form.isConnected = false; },
  };
}

test('saveAll persists edits from closed panels for every edited request', async () => {
  const h = setup();
  for (const id of ['P1', 'P2']) {
    await h.editor.edit(id);
    h.text('Cambio conservado ' + id); h.actor(); h.closePanel();
  }
  assert.equal(h.editor.hasChanges('C01'), true);
  await h.editor.saveAll('C01');
  assert.equal(h.writes.length, 2);
  assert.deepEqual(h.writes.map(call => call.body.paragraphs[0].text), ['Cambio conservado P1', 'Cambio conservado P2']);
  assert.deepEqual(h.writes[0].body.paragraphs[0].cited_chunk_ids, ['chunk-1']);
  assert.deepEqual(h.writes[0].body.pending_resolutions, []);
  assert.equal(h.editor.hasChanges('C01'), false);
  await h.editor.saveAll('C01');
  assert.equal(h.writes.length, 2, 'saving an already persisted draft creates no extra revision');
});

test('manual save and saveAll share the pending write', async () => {
  const h = setup();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  h.putHook = async (id, body, accept) => { await gate; return accept(id, body); };
  await h.editor.edit('P1'); h.text('Edición simultánea'); h.actor();
  const manual = h.submit();
  const bulk = h.editor.saveAll('C01');
  assert.equal(h.writes.length, 1);
  release();
  await Promise.all([manual, bulk]);
  assert.equal(h.history.length, 1);
  assert.equal(h.saved.length, 1);
  assert.equal(h.editor.hasChanges('C01'), false);
});

test('a failed UI refresh after confirmed persistence closes the editor and reports the saved result', async () => {
  const h = setup(async () => { throw new Error('View refresh unavailable'); });
  await h.editor.edit('P1'); h.text('Texto confirmado antes del fallo de vista'); h.actor();
  await h.submit();
  assert.equal(h.rows.get('P1').paragraphs[0].text, 'Texto confirmado antes del fallo de vista');
  assert.equal(h.rows.get('P1').revision, 2);
  assert.equal(h.editor.hasChanges('C01'), false);
  assert.equal(h.dialog.open, false, 'the saved editor cannot remain open with a deleted draft');
  assert.equal(h.form.isConnected, false);
  assert.equal(h.form.querySelector('#response-edit-error').textContent, '', 'a refresh failure is not a failed write');
  assert.match(h.notices.at(-1), /guardad/i);
  assert.match(h.notices.at(-1), /vista/i, 'the normal success notice must not hide the refresh warning');
  await h.editor.saveAll('C01');
  assert.equal(h.writes.length, 1);
  assert.equal(h.history.length, 1);
});

test('saveAll recovers a lost successful PUT by GET without duplicating history', async () => {
  const h = setup();
  h.putHook = (id, body, accept) => {
    accept(id, body);
    throw new TypeError('Connection lost after commit');
  };
  await h.editor.edit('P1'); h.text('Guardado con respuesta de red perdida'); h.actor();
  await h.submit();
  assert.match(h.form.querySelector('#response-edit-error').textContent, /No se pudo confirmar/);
  assert.equal(h.editor.hasChanges('C01'), true);
  assert.equal(h.rows.get('P1').paragraphs[0].office_section, undefined);
  h.closePanel();
  await h.editor.saveAll('C01');
  assert.equal(h.calls.filter(call => call.method === 'GET').length, 2, 'recovery checks the persisted revision');
  assert.equal(h.writes.length, 1);
  assert.equal(h.history.length, 1);
  assert.equal(h.saved[0].revision, 2);
  assert.equal(h.editor.hasChanges('C01'), false);
});

test('restoring original text after a lost successful PUT persists the reversal', async () => {
  const h = setup();
  const originalText = h.rows.get('P1').paragraphs[0].text;
  let loseResponse = true;
  h.putHook = (id, body, accept) => {
    const result = accept(id, body);
    if (loseResponse) { loseResponse = false; throw new TypeError('Connection lost after commit'); }
    return result;
  };
  await h.editor.edit('P1'); h.text('Cambio guardado cuya confirmación se pierde'); h.actor();
  await h.submit();
  assert.equal(h.rows.get('P1').revision, 2);
  h.closePanel();
  await h.editor.edit('P1');
  h.text(originalText);
  assert.equal(h.editor.hasChanges('C01'), true, 'an unconfirmed write remains pending even when local text matches the original');
  h.closePanel();
  await h.editor.saveAll('C01');
  assert.equal(h.calls.filter(call => call.method === 'GET').length, 3, 'recovery rereads the saved attempt after reopening');
  assert.equal(h.writes.length, 2);
  assert.equal(h.writes[1].body.revision, 2, 'the reversal is based on the recovered revision');
  assert.equal(h.writes[1].body.paragraphs[0].text, originalText);
  assert.equal(h.history.length, 2);
  assert.equal(h.rows.get('P1').revision, 3);
  assert.equal(h.rows.get('P1').paragraphs[0].text, originalText);
  assert.equal(h.editor.hasChanges('C01'), false);
});

test('scope invalidation blocks bulk save and preserves edited text without withdrawn citations', async () => {
  const h = setup();
  await h.editor.edit('P1'); h.text('Texto humano que se debe conservar'); h.actor();
  h.editor.discardScope('C01');
  h.rows.set('P1', {...h.rows.get('P1'), revision: 2, paragraphs: [], stale: true, can_replace_withdrawn_paragraphs: true});
  assert.equal(h.editor.hasChanges('C01'), true);
  await assert.rejects(h.editor.saveAll('C01'), /fuentes cambiaron.*revisa el texto conservado/);
  assert.equal(h.writes.length, 0);
  await h.editor.edit('P1');
  assert.match(h.form.querySelector('#response-paragraphs').innerHTML, /Texto humano que se debe conservar/);
  h.actor();
  await h.editor.saveAll('C01');
  assert.equal(h.writes.length, 1);
  assert.equal(h.writes[0].body.replace_withdrawn_paragraphs, true);
  assert.deepEqual(h.writes[0].body.paragraphs, [{
    text: 'Texto humano que se debe conservar', cited_chunk_ids: [], cited_fact_ids: [], office_section: 'response',
  }]);
  assert.equal(h.editor.hasChanges('C01'), false);
});

for (const scenario of ['different content', 'different author']) {
  test(`a lost response followed by ${scenario} remains a conflict and cannot overwrite that revision`, async () => {
    const h = setup();
    let loseResponse = true;
    h.putHook = (id, body, accept) => {
      const result = accept(id, body);
      if (loseResponse) { loseResponse = false; throw new TypeError('Connection lost'); }
      return result;
    };
    await h.editor.edit('P1'); h.text('Texto local que no debe perderse'); h.actor();
    await h.submit();
    const remote = {...h.rows.get('P1'), revision: 3};
    if (scenario === 'different content') remote.paragraphs = [paragraph('Cambio de otra sesión')];
    else remote.edited_by = 'Otra gestora';
    h.rows.set('P1', remote);
    await assert.rejects(h.editor.saveAll('C01'), /cambió en otra sesión/);
    assert.equal(h.writes.length, 2);
    assert.equal(h.writes[1].body.revision, 1, 'the failed recovery must not adopt an unrelated revision');
    assert.equal(h.history.length, 1, 'only the original successful PUT changed storage');
    assert.deepEqual(h.rows.get('P1'), remote);
    assert.equal(h.editor.hasChanges('C01'), true);
    await h.editor.edit('P1');
    assert.match(h.drawer.innerHTML, /versión guardada más reciente/);
    assert.match(h.form.querySelector('#response-paragraphs').innerHTML, /Texto local que no debe perderse/);
  });
}

for (const scenario of ['missing actor', 'empty paragraph']) {
  test(`saveAll rejects ${scenario} without writing or losing the local draft`, async () => {
    const h = setup();
    await h.editor.edit('P1');
    h.text(scenario === 'empty paragraph' ? '   ' : 'Una edición pendiente');
    if (scenario !== 'missing actor') h.actor();
    await assert.rejects(h.editor.saveAll('C01'), /completa el responsable y los párrafos/);
    assert.equal(h.writes.length, 0);
    assert.equal(h.editor.hasChanges('C01'), true);
  });
}
