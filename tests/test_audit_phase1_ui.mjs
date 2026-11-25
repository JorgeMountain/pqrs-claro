import test from 'node:test';
import assert from 'node:assert/strict';

import {safeUrl, sourcesView} from '../src/pqrs_claro/static/recorrido/views.js';
import {originalViewer} from '../src/pqrs_claro/static/recorrido/original-viewer.js';
import {esc} from '../src/pqrs_claro/static/recorrido/views.js';

test('safeUrl blocks javascript and data schemes while preserving safe paths', () => {
  assert.equal(safeUrl('javascript:alert(1)'), '');
  assert.equal(safeUrl('data:text/html,<script>alert(1)</script>'), '');
  assert.equal(safeUrl('//evil.example/x'), '');
  assert.equal(safeUrl('/api/sources/123/original'), '/api/sources/123/original');
  assert.equal(safeUrl('files/Peticion_academica_demo.pdf'), 'files/Peticion_academica_demo.pdf');
  assert.equal(safeUrl('https://udea.edu.co/doc.pdf'), 'https://udea.edu.co/doc.pdf');
});

test('sourcesView and originalViewer omit unsafe href links', () => {
  const srcHtml = sourcesView([{
    title: 'Norma',
    version: 1,
    location_kind: 'page',
    page: 2,
    quote: 'Texto',
    url: 'javascript:alert(1)',
  }]);
  assert.equal(srcHtml.includes('javascript:'), false);
  assert.equal(srcHtml.includes('<a '), false);

  const viewerHtml = originalViewer({
    original_url: 'javascript:alert(1)',
    original_pages: [],
    requests: [],
  }, {}, esc);
  assert.equal(viewerHtml.includes('javascript:'), false);
  assert.equal(viewerHtml.includes('Abrir PDF'), false);
});

test('live-views identification does not expand $& replacement patterns in metadata', async () => {
  const {readFileSync} = await import('node:fs');
  const source = readFileSync(
    new URL('../src/pqrs_claro/static/recorrido/live-views.js', import.meta.url),
    'utf8',
  );
  // Ensure every metadata/confirmation replace call uses a callback replacer () => ...
  assert.match(source, /\.replace\('PETICIÓN DE DEMOSTRACIÓN',\(\)=>/);
  assert.match(source, /\.replace\('Solicitante de demostración · 10 de septiembre de 2026',\(\)=>/);
  assert.match(source, /\.replace\('<div class="actionbar"><p>Esta maqueta/, 'confirmation replace');
  assert.match(source, /\(\)=>confirmation\)/);
});
