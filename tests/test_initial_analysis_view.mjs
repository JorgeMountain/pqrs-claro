import test from 'node:test';
import assert from 'node:assert/strict';
import {initialReviewSummary,initialRequestContent,initialConfirmation,documentDetails} from '../src/pqrs_claro/static/recorrido/initial-review.js';
import {identification} from '../src/pqrs_claro/static/recorrido/live-views.js';

const current={id:'test',status:'needs_review',identification:{requests:[{id:'P1',title:'Requisitos'}]}};
const check=key=>({key,state:'no_observation',summary:'Sin observaciones',reason:'Prueba',original_refs:[],sources:[],pending:[]});
const ready={revision:2,status:'needs_review',can_prepare:false,classification_provider:'jev',report:{document:{checks:[check('requirements'),check('respect')],proposed_route:'continue'},requests:[{request_id:'P1',petition_type:'information',classification_model:'typesafe-ai/jev',classification_confidence:0.9,checks:[{...check('repetition'),state:'unavailable'},check('classification')],proposed_route:'continue'}],special_treatment:{detected:false},warnings:[]}};

test('identificación solo clasifica y reserva las fuentes para Redacción',()=>{
  const value={...ready,analysis_scope:'petition_types_v1'};
  const html=documentDetails(current,value);
  assert.match(html,/fuentes se consultarán al continuar a Redacción/);
  assert.match(html,/live-preanalysis/);
  assert.doesNotMatch(html,/0 fuentes|Fuentes de consulta|consulta no disponible/);
  assert.match(initialRequestContent(current,value,null,{workspace:true}).P1.details,/Ver clasificación/);
  assert.doesNotMatch(initialRequestContent(current,value,null,{workspace:true}).P1.details,/antecedentes/);
  assert.match(initialReviewSummary(current,{...value,status:'running'}),/Clasificando las peticiones a partir del documento original/);
  assert.match(initialConfirmation(current,value,null,{workspace:true}),/He revisado todas las peticiones/);
});

test('muestra el resumen y JEV antes de confirmar la identificación',()=>{
  const summary=initialReviewSummary(current,ready);
  assert.match(summary,/1 petición analizada/);
  assert.doesNotMatch(summary,/Confirma las peticiones identificadas/);
  assert.match(initialRequestContent(current,ready).P1.header,/Tipo sugerido · JEV/);
  assert.match(initialConfirmation(current,ready),/Buscar fuentes y redactar/);
});

const withClassifier=(model,confidence=0.9,configured='jev')=>({...ready,classification_provider:configured,report:{...ready.report,requests:ready.report.requests.map(row=>({...row,classification_model:model,classification_confidence:confidence}))}});

test('los detalles atribuyen cada resultado a su modelo guardado en ambas vistas',()=>{
  for(const workspace of [false,true]){
    const direct=initialRequestContent(current,withClassifier('jev-1.14.0',0.9,'openai'),null,{workspace}).P1;
    assert.match(direct.details,/Clasificado por JEV 1\.14\.0 · TypeSafe · confianza 90 %/);
    assert.doesNotMatch(direct.details,/Vercel/);
    if(!workspace)assert.match(direct.header,/Tipo sugerido · JEV/);
    const legacy=initialRequestContent(current,withClassifier('typesafe-ai/jev'),null,{workspace}).P1;
    assert.match(legacy.details,/Clasificado por JEV · Vercel/);
    assert.doesNotMatch(legacy.details,/JEV 1\.14/);
    const luna=initialRequestContent(current,withClassifier('gpt-6-luna',null),null,{workspace}).P1;
    assert.match(luna.details,/Clasificado por Luna · gpt-6-luna/);
    assert.doesNotMatch(luna.header+luna.details,/JEV|Vercel|TypeSafe|confianza/);
  }
});

test('la confianza ausente o inválida no se convierte en cero ni porcentaje inventado',()=>{
  for(const workspace of [false,true]){
    for(const confidence of [null,undefined,NaN,Infinity,-0.1,1.1,'0.9',false]){
      const value=withClassifier('jev-1.14.0');
      value.report.requests[0].classification_confidence=confidence;
      assert.doesNotMatch(initialRequestContent(current,value,null,{workspace}).P1.details,/confianza|garantía/);
    }
    for(const confidence of [0,1])assert.match(initialRequestContent(current,withClassifier('jev-1.14.0',confidence),null,{workspace}).P1.details,new RegExp(`confianza ${confidence*100} %`));
  }
});

test('sin modelo guardado no atribuye una clasificación al proveedor configurado',()=>{
  for(const workspace of [false,true]){
    const row=initialRequestContent(current,withClassifier(null),null,{workspace}).P1;
    assert.doesNotMatch(row.header+row.details,/JEV|Clasificado por|confianza/);
  }
});

test('la nota del próximo análisis distingue configuración actual de resultados anteriores',()=>{
  const value={...withClassifier('gpt-6-luna',null),classification_model:'jev-1.14.0',stale:true};
  assert.match(initialReviewSummary(current,value),/Próxima clasificación: JEV 1\.14\.0.*se envía a TypeSafe/);
  assert.doesNotMatch(initialRequestContent(current,value).P1.details,/JEV/);
  assert.match(initialReviewSummary(current,{...ready,classification_model:'typesafe-ai/jev'}),/Próxima clasificación: JEV.*se envía a Vercel/);
  assert.doesNotMatch(initialReviewSummary(current,ready),/se envía a Vercel|se envía a TypeSafe/);
});

test('el nombre de un modelo guardado se escapa como texto',()=>{
  const html=initialRequestContent(current,withClassifier('<img src=x onerror=alert(1)>',null)).P1.details;
  assert.doesNotMatch(html,/<img/);
  assert.match(html,/&lt;img/);
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

test('distingue peticiones conservadas, reintento y análisis completo',()=>{
  const record={...current,identification:{requests:[{id:'P1',title:'Una'},{id:'P2',title:'Otra'}]}};
  const analysis_work={pending:['P1'],reused:['P2']};
  const running={status:'running',analysis_work};
  assert.match(initialReviewSummary(record,running),/1 petición por clasificar y 1 resultado conservado/);
  assert.match(initialRequestContent(record,running).P1.header,/Clasificando/);
  assert.match(initialRequestContent(record,running).P2.header,/Resultado conservado/);
  assert.match(initialReviewSummary(current,{...ready,status:'error',error:'Fallo simulado',next_analysis:analysis_work}),/Reintentar pendientes/);
  assert.match(initialReviewSummary(current,ready),/live-initial-full/);
  assert.match(initialReviewSummary(current,ready),/Reanalizar todo con IA/);
});


test('una ruta alternativa guardada exige cambiar expresamente las rutas',()=>{
  const routed={...ready,status:'routed',document_decision:{route:'specialist',reviewed:true},decisions:[{request_id:'P1',route:'specialist',reviewed:true}],reviewed_by:'Gestor ficticio'};
  const html=initialConfirmation(current,routed);
  assert.match(html,/<button[^>]*data-action="live-initial-confirm"[^>]*>Buscar fuentes y redactar/);
  assert.match(html,/<button[^>]*data-action="live-initial-confirm"[^>]*disabled/);
  assert.doesNotMatch(html,/Volver a la bandeja|Decisión guardada<\/button>/);
  assert.match(html,/cambia expresamente esas rutas/);
  assert.doesNotMatch(html,/<button[^>]*data-action="live-initial-route"[^>]*hidden/);
  assert.match(html,/name="reviewed-all" required checked/);
});
