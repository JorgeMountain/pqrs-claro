import test from 'node:test';
import assert from 'node:assert/strict';
import {createWorkClock} from '../src/pqrs_claro/static/recorrido/work-clock.js';

const first = {caseId:'expediente-uno', actorId:'gestor-a'};
const second = {caseId:'expediente-dos', actorId:'gestor-a'};
function harness(reply = () => ({status:'active'})) {
  const calls = [], states = [];
  let serial = 0;
  const clock = createWorkClock({
    newId: () => 'session-' + ++serial,
    async post(id, body) { calls.push({id, ...body}); return reply(body); },
    status: state => states.push(state),
  });
  return {calls, states, clock};
}

test('volver a pintar no reinicia el tiempo y cada interacción se informa una sola vez', async () => {
  const {calls, clock} = harness();
  await clock.setTarget(first);
  await clock.setTarget({...first});
  await clock.interact();
  await clock.tick();
  await clock.tick();
  await clock.setTarget(null);
  await clock.tick();
  assert.deepEqual(calls.map(x => [x.event, x.sequence, x.activity]), [
    ['start', 0, false], ['heartbeat', 1, true], ['heartbeat', 2, false], ['stop', 3, false],
  ]);
});

test('detener durante una petición en vuelo no reactiva la sesión anterior al cambiar de expediente', async () => {
  let resolveFirst;
  const {calls, states, clock} = harness(body => body.event === 'start' && body.session_id === 'session-1'
    ? new Promise(resolve => { resolveFirst = resolve; }) : {status:'active'});
  const inFlight = clock.setTarget(first);
  await clock.setTarget(second);
  resolveFirst({status:'unconfirmed'});
  await inFlight;
  assert.deepEqual(calls.map(x => [x.id, x.session_id, x.event, x.sequence]), [
    [first.caseId,'session-1','start',0], [first.caseId,'session-1','stop',1], [second.caseId,'session-2','start',0],
  ]);
  assert.equal(states.at(-1), 'active');
});

test('un corte de conexión en el inicio reintenta el mismo ID y una sesión desplazada necesita otra interacción', async () => {
  let attempts = 0;
  const {calls, states, clock} = harness(body => {
    if (!attempts++) throw Error('Desconectado');
    return {status: body.event === 'heartbeat' ? 'ended' : 'active'};
  });
  await clock.setTarget(first);
  assert.equal(states.at(-1), 'offline');
  await clock.tick();
  assert.deepEqual(calls[0], calls[1]);
  await clock.tick();
  assert.equal(states.at(-1), 'ended');
  await clock.tick();
  assert.equal(calls.length, 3);
  await clock.interact();
  assert.equal(calls.at(-1).session_id, 'session-2');
});

test('la interacción ordinaria no confirma la lectura y una confirmación durante el latido sí se conserva', async () => {
  let resolveHeartbeat, beats = 0;
  const {calls, states, clock} = harness(body => {
    if (body.event !== 'heartbeat') return {status:'active'};
    if (!beats++) return {status:'unconfirmed'};
    return new Promise(resolve => { resolveHeartbeat = resolve; });
  });
  await clock.setTarget(first);
  await clock.tick();
  await clock.interact();
  assert.equal(states.at(-1), 'unconfirmed');
  const inFlight = clock.tick();
  await clock.confirm();
  assert.equal(calls.at(-1).event, 'heartbeat');
  resolveHeartbeat({status:'unconfirmed'});
  await inFlight;
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.at(-1).event, 'confirm');
  assert.equal(states.at(-1), 'active');
});

test('un rechazo por cierre o cambio de gestor no genera reintentos automáticos', async () => {
  const {calls, states, clock} = harness(() => { throw Object.assign(Error('No disponible'),{status:409}); });
  await clock.setTarget(first);
  await clock.tick();
  await clock.interact();
  assert.equal(states.at(-1), 'unavailable');
  assert.equal(calls.length, 1);
});

test('el informe espera el cierre en vuelo y sigue disponible si ese cierre no llega', async () => {
  let rejectStop;
  const {clock} = harness(body => body.event === 'stop'
    ? new Promise((_resolve, reject) => { rejectStop = reject; }) : {status:'active'});
  await clock.setTarget(first);
  await clock.setTarget(null);
  let ready = false;
  const read = clock.flush().then(() => { ready = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ready, false);
  rejectStop(Error('Respuesta perdida'));
  await read;
  assert.equal(ready, true);
});
