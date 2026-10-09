import test from 'node:test';
import assert from 'node:assert/strict';
import {preparationSummary, watchPreparation} from '../src/pqrs_claro/static/recorrido/library-progress.js';

test('distingue preparación, texto ausente y errores sin bloquear consulta', () => {
  const text = preparationSummary({total:10,ready:6,queued:1,preparing:1,unreadable:1,error:1});
  assert.match(text,/6 de 10/);
  assert.match(text,/2 en preparación/);
  assert.match(text,/Puedes continuar/);
  assert.match(text,/1 sin texto/);
  assert.match(text,/1 con error/);
});

test('deja de consultar al cerrar el diálogo', async () => {
  const node = {isConnected:true,textContent:''};
  const callbacks = [];
  let calls = 0;
  const api = async () => { calls++; return {total:1,queued:1,preparing:0}; };
  await watchPreparation(node, api, callback => callbacks.push(callback));
  node.isConnected = false;
  await callbacks[0]();
  assert.equal(calls,1);
});

test('un error de estado no impide seleccionar fuentes ni genera promesas rechazadas', async () => {
  const node = {isConnected:true,textContent:''};
  await watchPreparation(node, async () => { throw Error('offline'); });
  assert.match(node.textContent,/Puedes continuar/);
});
