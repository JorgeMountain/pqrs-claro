import test from 'node:test';
import assert from 'node:assert/strict';

import {apiJson, safeJson} from '../src/pqrs_claro/static/recorrido/http.js';
import {createResponseEditor} from '../src/pqrs_claro/static/recorrido/live-edit.js';

test('safeJson returns null instead of throwing SyntaxError on HTML/text responses', async () => {
  const htmlResponse = {
    async json() {
      throw new SyntaxError('Unexpected token < in JSON');
    },
  };
  assert.equal(await safeJson(htmlResponse), null);
  assert.deepEqual(await safeJson({async json() { return {ok: true}; }}), {ok: true});
});

test('apiJson handles non-JSON 502, JSON 409 detail, network uncertain, and caller abort', async () => {
  const realFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({
      ok: false,
      status: 502,
      async json() { throw new SyntaxError('Bad Gateway HTML'); },
    });
    await assert.rejects(
      () => apiJson('/api/test', {fallbackError: 'Error amigable.'}),
      err => err.message === 'Error amigable.' && err.status === 502,
    );

    globalThis.fetch = async () => ({
      ok: false,
      status: 409,
      async json() { return {detail: 'Conflicto de versión.'}; },
    });
    await assert.rejects(
      () => apiJson('/api/test'),
      err => err.message === 'Conflicto de versión.' && err.status === 409,
    );

    globalThis.fetch = async () => { throw new TypeError('network down'); };
    await assert.rejects(
      () => apiJson('/api/test', {body: {a: 1}, method: 'PUT'}),
      err => err.uncertain === true,
    );

    const controller = new AbortController();
    globalThis.fetch = async (_url, init) => {
      controller.abort();
      assert.equal(init.signal.aborted, true);
      const err = new Error('aborted');
      err.name = 'AbortError';
      throw err;
    };
    await assert.rejects(
      () => apiJson('/api/test', {signal: controller.signal, timeoutMs: 0}),
      err => err.name === 'AbortError' && err.aborted === true && !err.timeout,
    );
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('live-edit edit() cancels stale request so late P1 response never overwrites P2', async () => {
  const realFetch = globalThis.fetch;
  const realDocument = globalThis.document;
  const realLocalStorage = globalThis.localStorage;
  try {
    const store = new Map();
    globalThis.localStorage = {
      getItem: k => store.get(k) ?? null,
      setItem: (k, v) => store.set(k, String(v)),
    };
    const drawerEl = {open: true};
    let currentMarker = null;
    const bodyEl = {
      _html: '',
      get innerHTML() { return this._html; },
      set innerHTML(val) {
        if (currentMarker) currentMarker.isConnected = false;
        this._html = val;
        currentMarker = val.includes('live-response-loading') ? {isConnected: true} : null;
      },
      querySelector(sel) {
        if (sel === '#live-response-loading') return currentMarker;
        if (sel === 'form') return formEl;
        return null;
      },
    };
    const noopEl = {
      value: 'Ana',
      disabled: false,
      hidden: false,
      textContent: '',
      isConnected: true,
      focus() {},
      addEventListener() {},
      querySelectorAll() { return []; },
    };
    const formEl = {
      isConnected: true,
      querySelector() { return noopEl; },
      querySelectorAll() { return []; },
    };
    globalThis.document = {
      querySelector(sel) {
        if (sel === '#drawer') return drawerEl;
        if (sel === '#drawer-body') return bodyEl;
        return null;
      },
    };

    const resolvers = [];
    const signals = [];
    globalThis.fetch = (_url, init) => {
      signals.push(init?.signal);
      return new Promise(resolve => resolvers.push(resolve));
    };

    const editor = createResponseEditor({
      open(_title, html) { bodyEl.innerHTML = html; },
      close() { drawerEl.open = false; },
      notice() {},
      getCase() { return {id: 'c1'}; },
      async onSaved() {},
    });

    const p1 = editor.edit('P1');
    const p2 = editor.edit('P2');
    assert.equal(signals[0].aborted, true);
    assert.equal(signals[1].aborted, false);

    // Resolve P2 first, then resolve stale P1 late.
    resolvers[1]({
      ok: true,
      status: 200,
      async json() {
        return {
          requests: [
            {request_id: 'P1', label: '1', title: 'Petición Uno', revision: 1, paragraphs: [{text: 'Texto 1'}]},
            {request_id: 'P2', label: '2', title: 'Petición Dos', revision: 1, paragraphs: [{text: 'Texto 2'}]},
          ],
        };
      },
    });
    await p2;
    assert.match(bodyEl.innerHTML, /Petición Dos/);

    resolvers[0]({
      ok: true,
      status: 200,
      async json() {
        return {
          requests: [
            {request_id: 'P1', label: '1', title: 'Petición Uno', revision: 1, paragraphs: [{text: 'Texto 1'}]},
          ],
        };
      },
    });
    await p1;
    assert.match(bodyEl.innerHTML, /Petición Dos/);
    assert.doesNotMatch(bodyEl.innerHTML, /Petición Uno/);
  } finally {
    globalThis.fetch = realFetch;
    globalThis.document = realDocument;
    globalThis.localStorage = realLocalStorage;
  }
});
