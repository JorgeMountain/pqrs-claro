import test from 'node:test';
import assert from 'node:assert/strict';
import {initialReviewSummary,initialRequestContent,initialConfirmation} from '../src/pqrs_claro/static/recorrido/initial-review.js';
import {identification} from '../src/pqrs_claro/static/recorrido/live-views.js';

const current={id:'test',status:'needs_review',identification:{requests:[{id:'P1',title:'Requisitos'}]}};
const check=key=>({key,state:'no_observation',summary:'Sin observaciones',reason:'Prueba',original_refs:[],sources:[],pending:[]});
const ready={revision:2,status:'needs_review',can_prepare:false,classification_provider:'jev',report:{document:{checks:[check('requirements'),check('respect')],proposed_route:'continue'},requests:[{request_id:'P1',petition_type:'information',classification_model:'typesafe-ai/jev',classification_confidence:0.9,checks:[{...check('repetition'),state:'unavailable'},check('classification')],proposed_route:'continue'}],special_treatment:{detected:false},warnings:[]}};

test('muestra el resumen y JEV antes de confirmar la identificación',()=>{
  const summary=initialReviewSummary(current,ready);
  assert.match(summary,/1 petición analizada/);
  assert.doesNotMatch(summary,/Confirma las peticiones identificadas/);
  assert.match(initialRequestContent(current,ready).P1.header,/Tipo sugerido · JEV/);
  assert.match(initialConfirmation(current,ready),/Confirmar y preparar respuestas/);
});

test('durante el análisis muestra progreso sin clasificación inventada',()=>{
  const running={status:'running',revision:1};
  assert.match(initialReviewSummary(current,running),/Analizando el documento y clasificando/);
  assert.match(initialRequestContent(current,running).P1.header,/Clasificando petición/);
  assert.equal(initialConfirmation(current,running),'');
});

test('un error mantiene disponible el reintento sin confirmación previa',()=>{
  const failed={status:'error',error:'Servicio no disponible'};
  const summary=initialReviewSummary(current,failed);
  assert.match(summary,/Servicio no disponible/);
  assert.match(summary,/live-initial-analyze/);
  assert.equal(initialConfirmation(current,failed),'');
});

test('FIAGA no añade el paso de confirmar solicitudes',()=>{
  const data={...current,initial_review_enabled:true,subject:'Prueba',requests:[],original_pages:[]};
  const html=identification(data,{originalPage:1},{initial:{status:'running'}});
  assert.doesNotMatch(html,/data-action="live-confirm"/);
  assert.doesNotMatch(html,/data-action="live-correct"/);
});

test('un servidor anterior conserva su botón de confirmación hasta reiniciarse',()=>{
  const data={...current,initial_review_enabled:true,automatic_initial_review:false,subject:'Prueba',requests:[],original_pages:[]};
  assert.match(identification(data,{originalPage:1},{initial:{status:'idle'}}),/data-action="live-confirm"/);
  assert.match(initialReviewSummary(current,{status:'idle'},null,{automatic:false}),/flujo anterior/);
});
