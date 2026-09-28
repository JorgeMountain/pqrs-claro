import test from 'node:test';
import assert from 'node:assert/strict';
import {continuedDecisionNote,automaticDecisionNote,isAutomaticDecisionNote,confirmationPayload,confirmAndPrepare} from '../src/pqrs_claro/static/recorrido/initial-confirmation.js';

const report=()=>({document:{proposed_route:'continue',checks:[{state:'no_observation'}]},requests:[{request_id:'P1',petition_type:'documents',proposed_route:'continue',checks:[{state:'no_observation'},{state:'unavailable'}]}],special_treatment:{detected:false}});
const decision=()=>({case_id:'test',revision:10,reviewed_by:'QA ficticia',document:{route:'continue',reviewed:true,note:'',communication:''},requests:[{request_id:'P1',petition_type:'documents',route:'continue',reviewed:true,note:'',communication:''}]});

test('la confirmación conjunta acepta una propuesta limpia sin inventar verificaciones',()=>{
  const result=confirmationPayload(decision(),report());
  assert.equal(result.document.note,continuedDecisionNote);
  assert.equal(result.requests[0].note,continuedDecisionNote);
  assert.equal(result.document.reviewed,true);
  assert.ok(!('case_id' in result));
});
test('no confunde la ausencia de histórico con una observación pendiente',()=>{
  assert.equal(confirmationPayload(decision(),report()).requests[0].note,continuedDecisionNote);
});
for(const state of ['attention','unverified'])test(`permite continuar sin nota ante ${state}`,()=>{
  const r=report();r.document.checks[0].state=state;
  assert.equal(confirmationPayload(decision(),r).document.note,continuedDecisionNote);
});
test('permite corregir el tipo sin nota y conserva una observación voluntaria',()=>{
  const d=decision();d.requests[0].petition_type='consultation';
  assert.equal(confirmationPayload(d,report()).requests[0].note,continuedDecisionNote);
  d.requests[0].note='La petición solicita una interpretación.';
  assert.equal(confirmationPayload(d,report()).requests[0].note,d.requests[0].note);
});
test('permite elegir continuar frente a una propuesta alternativa',()=>{
  const r=report();r.document.proposed_route='complement';
  assert.equal(confirmationPayload(decision(),r).document.note,continuedDecisionNote);
});
test('tratamiento especial conserva el aviso sin exigir una nota al continuar',()=>{
  const r=report();r.special_treatment.detected=true;
  assert.equal(confirmationPayload(decision(),r).document.note,continuedDecisionNote);
});
test('no confirma sin responsable o sin aceptación explícita',()=>{
  const d=decision();d.reviewed_by='  ';
  assert.throws(()=>confirmationPayload(d,report()),/quién/);
  d.reviewed_by='QA';d.document.reviewed=false;
  assert.throws(()=>confirmationPayload(d,report()),/Confirma/);
  d.document.reviewed=true;d.requests[0].reviewed=false;
  assert.throws(()=>confirmationPayload(d,report()),/Confirma/);
});
test('no continúa con un tipo sin determinar',()=>{
  const d=decision();d.requests[0].petition_type='undetermined';d.requests[0].note='Pendiente';
  assert.throws(()=>confirmationPayload(d,report()),/Define el tipo/);
});
test('guarda antes de preparar y conserva la decisión confirmada',async()=>{
  const calls=[];
  const result=await confirmAndPrepare({decision:decision(),report:report(),save:async()=>{calls.push('save');return {can_prepare:true};},onSaved:()=>calls.push('saved'),prepare:async()=>calls.push('prepare')});
  assert.deepEqual(calls,['save','saved','prepare']);assert.equal(result.prepared,true);
});
test('un error de guardado no inicia la preparación',async()=>{
  const calls=[];
  await assert.rejects(()=>confirmAndPrepare({decision:decision(),report:report(),save:async()=>{throw new Error('Conflicto de revisión');},onSaved:()=>calls.push('saved'),prepare:async()=>calls.push('prepare')}),/Conflicto/);
  assert.deepEqual(calls,[]);
});
test('la ruta alternativa se guarda y respeta el bloqueo devuelto por el servidor',async()=>{
  const d=decision();d.document.route='complement';d.document.note='';
  let prepared=false,saved=false;
  const result=await confirmAndPrepare({decision:d,report:report(),save:async()=>({can_prepare:false}),onSaved:()=>saved=true,prepare:async()=>prepared=true});
  assert.equal(saved,true);assert.equal(prepared,false);assert.equal(result.prepared,false);
});
test('si falla preparar, conserva la decisión y reintenta sin volver a guardarla',async()=>{
  let saves=0,saved;
  const options={decision:decision(),report:report(),save:async()=>{saves++;return {can_prepare:true};},onSaved:value=>saved=value,prepare:async()=>{throw new Error('Servicio temporalmente no disponible');}};
  const result=await confirmAndPrepare(options);
  assert.equal(result.prepared,false);assert.match(result.error,/revisión quedó guardada/);
  assert.equal((await confirmAndPrepare({...options,saved,prepare:async()=>{}})).prepared,true);
  assert.equal(saves,1);
});

for(const route of ['complement','reject','reiterate','specialist'])test(`la ruta ${route} permite nota vacía y conserva la observación voluntaria`,()=>{
  const d=decision();d.document.route=route;
  d.requests[0].route=route;
  const payload=confirmationPayload(d,report());
  assert.equal(payload.document.route,route);
  assert.equal(payload.requests[0].route,route);
  assert.equal(payload.document.note,automaticDecisionNote(route));
  assert.equal(payload.requests[0].note,automaticDecisionNote(route));
  assert.match(payload.document.note,/sin observación adicional/);
  assert.ok(isAutomaticDecisionNote(payload.document.note));
  assert.notEqual(payload.document.note,continuedDecisionNote);
  d.document.note='Motivo escrito por el gestor.';
  assert.equal(confirmationPayload(d,report()).document.note,d.document.note);
});

test('continuar con observaciones no las borra ni las declara resueltas',()=>{
  const r=report();r.document.checks[0].state='attention';
  const original=JSON.stringify(r);const payload=confirmationPayload(decision(),r);
  assert.equal(JSON.stringify(r),original);
  assert.match(payload.document.note,/observaciones del análisis se conservan/);
});

test('el registro automático de especialista no atribuye una decisión de continuar',()=>{
  assert.equal(automaticDecisionNote('specialist'),'Confirmación conjunta: se eligió remitir a revisión especializada, sin observación adicional.');
  assert.equal(isAutomaticDecisionNote('Nota del gestor'),false);
  assert.throws(()=>automaticDecisionNote('invalid'),/ruta válida/);
});
