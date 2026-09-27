import test from 'node:test';
import assert from 'node:assert/strict';
import {acceptedProposalNote,needsDecisionNote,confirmationPayload,confirmAndPrepare} from '../src/pqrs_claro/static/recorrido/initial-confirmation.js';

const report=()=>({document:{proposed_route:'continue',checks:[{state:'no_observation'}]},requests:[{request_id:'P1',petition_type:'documents',proposed_route:'continue',checks:[{state:'no_observation'},{state:'unavailable'}]}],special_treatment:{detected:false}});
const decision=()=>({case_id:'test',revision:10,reviewed_by:'QA ficticia',document:{route:'continue',reviewed:true,note:'',communication:''},requests:[{request_id:'P1',petition_type:'documents',route:'continue',reviewed:true,note:'',communication:''}]});

test('la confirmación conjunta acepta una propuesta limpia sin inventar verificaciones',()=>{
  const result=confirmationPayload(decision(),report());
  assert.equal(result.document.note,acceptedProposalNote);
  assert.equal(result.requests[0].note,acceptedProposalNote);
  assert.equal(result.document.reviewed,true);
  assert.ok(!('case_id' in result));
});
test('no confunde la ausencia de histórico con una observación pendiente',()=>{
  assert.equal(needsDecisionNote(report().requests[0],decision().requests[0]),false);
});
for(const state of ['attention','unverified'])test(`exige explicación ante ${state}`,()=>{
  const r=report();r.document.checks[0].state=state;
  assert.throws(()=>confirmationPayload(decision(),r),/Explica/);
});
test('exige explicación para cambiar el tipo',()=>{
  const d=decision();d.requests[0].petition_type='consultation';
  assert.throws(()=>confirmationPayload(d,report()),/Explica/);
  d.requests[0].note='La petición solicita una interpretación.';
  assert.equal(confirmationPayload(d,report()).requests[0].note,d.requests[0].note);
});
test('una propuesta alternativa también requiere explicación al elegir continuar',()=>{
  const r=report();r.document.proposed_route='complement';
  assert.throws(()=>confirmationPayload(decision(),r),/Explica/);
});
test('tratamiento especial exige explicación general',()=>{
  const r=report();r.special_treatment.detected=true;
  assert.throws(()=>confirmationPayload(decision(),r),/Explica/);
});
test('no confirma sin responsable o sin aceptación explícita',()=>{
  const d=decision();d.reviewed_by='  ';
  assert.throws(()=>confirmationPayload(d,report()),/quién/);
  d.reviewed_by='QA';d.document.reviewed=false;
  assert.throws(()=>confirmationPayload(d,report()),/Confirma/);
  d.document.reviewed=true;d.requests[0].reviewed=false;
  assert.throws(()=>confirmationPayload(d,report()),/Confirma/);
});
test('no continúa con un tipo sin determinar ni una nota en blanco ante observaciones',()=>{
  const d=decision();d.requests[0].petition_type='undetermined';d.requests[0].note='Pendiente';
  assert.throws(()=>confirmationPayload(d,report()),/Define el tipo/);
  d.document.route='complement';d.document.note='  ';
  assert.throws(()=>confirmationPayload(d,report()),/Explica/);
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
  const d=decision();d.document.route='complement';d.document.note='Se requiere completar el dato indicado.';
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
