import test from 'node:test';
import assert from 'node:assert/strict';
import {pilotReviewControls} from '../src/pqrs_claro/static/recorrido/pilot-review.js';
test('permite continuar con análisis desactualizado sin declarar aprobación',()=>{
  const html=pilotReviewControls({identification:{}},{stale:true,status:'needs_review'});
  assert.match(html,/live-pilot-continue/);
  assert.match(html,/sin aprobar ni actualizar/);
  assert.doesNotMatch(html,/disabled/);
});
test('muestra modo activo reversible y respeta cierre y procesos',()=>{
  assert.match(pilotReviewControls({identification:{}},{pilot_bypass_active:true}),/live-pilot-require/);
  assert.match(pilotReviewControls({identification:{}},{status:'running'}),/disabled/);
  assert.equal(pilotReviewControls({identification:{},management:{state:'closed'}},{}),'');
});
