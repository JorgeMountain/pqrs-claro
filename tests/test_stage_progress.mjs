import test from 'node:test';
import assert from 'node:assert/strict';
import {preanalysisProgress,identificationProgress,draftProgress} from '../src/pqrs_claro/static/recorrido/stage-progress.js';
import {deriveDraftReview} from '../src/pqrs_claro/static/recorrido/draft-review.js';

const requests=[1,2,3].map(n=>({id:`P${n}`}));
const current={status:'needs_review',preanalysis_status:'ready',identification:{requests}};
const initial={status:'needs_review',can_prepare:false,report:{document:{},requests:requests.map(row=>({request_id:row.id,petition_type:'information'}))}};

test('preanálisis informa actividad sin inventar porcentajes mientras espera las tres verificaciones',()=>{
  const html=preanalysisProgress({status:'running'});
  assert.match(html,/Revisando el documento/);
  assert.match(html,/role="progressbar"/);
  assert.doesNotMatch(html,/aria-valuenow|3 de 3|Revisión previa confirmada/);
});

test('un hallazgo cuenta como verificación realizada, sin aprobarlo ni ocultar lo no verificado',()=>{
  const record={status:'ready',checks:{requester:{state:'attention'},respect:{state:'pass'},integrity:{state:'unverified'}}};
  const before=JSON.stringify(record),html=preanalysisProgress(record);
  assert.match(html,/2 de 3 verificaciones realizadas/);
  assert.match(html,/Revisa los hallazgos/);
  assert.doesNotMatch(html,/Revisión previa confirmada/);
  assert.equal(JSON.stringify(record),before);
});

test('las verificaciones completadas siguen pendientes de revisión humana hasta que exista aprobación guardada',()=>{
  const checks=Object.fromEntries(['requester','respect','integrity'].map(key=>[key,{state:'pass'}]));
  const html=preanalysisProgress({status:'ready',checks});
  assert.match(html,/3 de 3 verificaciones realizadas/);
  assert.match(html,/Pendiente de tu revisión/);
  assert.match(preanalysisProgress({status:'ready',checks,approval:{actor_id:'test'}}),/Revisión previa confirmada/);
  const saved=preanalysisProgress({status:'ready',checks,approval:{actor_id:'test'}},{completed:[true,true,true,true]});
  assert.match(saved,/workflow-segment stage-1 complete/);
  assert.match(saved,/workflow-segment stage-2 complete/);
  assert.match(saved,/workflow-segment stage-3 complete/);
});

test('un error o una consulta del preanálisis no muestran las comprobaciones anteriores como actuales',()=>{
  const saved={requester:{state:'pass'},respect:{state:'pass'},integrity:{state:'pass'}};
  const error=preanalysisProgress({status:'error',error:'Error de prueba',checks:saved});
  assert.match(error,/No se completaron las verificaciones/);
  assert.doesNotMatch(error,/source-spinner|3 de 3/);
  assert.doesNotMatch(preanalysisProgress({status:'loading',checks:saved}),/0 de 3|aria-valuenow/);
});

test('identificación no supone el total de peticiones antes de terminar la extracción',()=>{
  const html=identificationProgress({status:'identifying'},{});
  assert.match(html,/Identificando las peticiones/);
  assert.doesNotMatch(html,/0 de 0|aria-valuenow/);
});

test('la clasificación en curso cuenta solo resultados conservados de peticiones vigentes',()=>{
  const html=identificationProgress(current,{...initial,status:'running',analysis_work:{reused:['P2','P2','otra'],pending:['P1','P3']}});
  assert.match(html,/1 de 3 peticiones clasificadas/);
  assert.match(html,/Clasificando el tipo/);
  assert.match(html,/aria-valuenow="1"/);
});

test('clasificar todas no confirma la revisión conjunta ni cuenta un tipo indeterminado',()=>{
  const html=identificationProgress(current,initial);
  assert.match(html,/3 de 3 peticiones clasificadas/);
  assert.match(html,/Pendiente de tu revisión conjunta/);
  assert.doesNotMatch(html,/Revisión conjunta guardada/);
  const partial=structuredClone(initial);partial.report.requests[1].petition_type='undetermined';
  assert.match(identificationProgress(current,partial),/2 de 3 peticiones clasificadas/);
  assert.match(identificationProgress(current,partial),/tipos pendientes de determinar/);
  assert.match(identificationProgress(current,{...initial,can_prepare:true}),/Revisión conjunta guardada/);
});

test('recuperar identificación no muestra cero definitivo y los resultados desactualizados se distinguen',()=>{
  assert.doesNotMatch(identificationProgress(current,{}),/0 de 3|aria-valuenow/);
  const missing=identificationProgress(current,{loadError:'La consulta no respondió'});
  assert.match(missing,/No se pudo recuperar la identificación/);
  assert.doesNotMatch(missing,/0 de 3|aria-valuenow|source-spinner/);
  const stale=identificationProgress(current,{...initial,stale:true,can_prepare:true});
  assert.match(stale,/Resultados anteriores/);
  assert.doesNotMatch(stale,/Revisión conjunta guardada|aria-valuenow/);
  const error=identificationProgress(current,{...initial,status:'error',error:'Interrumpido'});
  assert.match(error,/requiere atención/);assert.doesNotMatch(error,/source-spinner/);
});

test('borrador cuenta respuestas comprobadas, sin confundir cantidad de ajustes con cantidad de respuestas',()=>{
  const work={requests:[
    {request_id:'P1',status:'ready',paragraphs:[{text:'Lista'}]},
    {request_id:'P2',status:'needs_changes',paragraphs:[{text:'Por corregir'}],assessment:{issues:[{description:'Primer ajuste'},{description:'Segundo ajuste'}]}},
    {request_id:'P3',status:'checking',paragraphs:[{text:'En comprobación'}]}
  ]};
  const html=draftProgress(work,deriveDraftReview(work),{total:3});
  assert.match(html,/1 de 3 respuestas comprobadas/);
  assert.match(html,/Comprobando 1 respuesta/);
  assert.doesNotMatch(html,/Versión final generada/);
  work.requests[2].status='ready';
  const checked=draftProgress(work,deriveDraftReview(work),{total:3});
  assert.match(checked,/2 de 3 respuestas comprobadas/);
  assert.match(checked,/2 ajustes pendientes/);
});

test('el borrador no está generado por estar comprobado, confirmado o tener cambios locales',()=>{
  const work={requests:[{status:'ready',paragraphs:[{text:'Ejemplo'}]}]},model=deriveDraftReview(work);
  assert.match(draftProgress(work,model),/Pendiente de tu revisión final/);
  assert.match(draftProgress(work,model,{confirmed:true}),/falta generar el oficio/);
  assert.match(draftProgress(work,model,{generated:true}),/Versión final generada/);
  const dirty=draftProgress(work,model,{generated:true,dirty:true});
  assert.match(dirty,/Cambios pendientes de comprobar/);
  assert.doesNotMatch(dirty,/Versión final generada|aria-valuenow/);
});

test('una respuesta ausente no desaparece del total y el borrador vacío no anuncia finalización',()=>{
  const work={requests:[{status:'ready',paragraphs:[{text:'Ejemplo'}]}]};
  assert.match(draftProgress(work,deriveDraftReview(work),{total:3}),/1 de 3 respuestas comprobadas/);
  assert.match(draftProgress(work,deriveDraftReview(work),{total:3}),/Falta preparar las respuestas/);
  assert.match(draftProgress(null,null),/Recuperando el borrador guardado/);
  assert.doesNotMatch(draftProgress(null,null,{error:'Error'}),/source-spinner|Versión final generada/);
});

test('aprobar muestra solo confirmaciones guardadas aunque todas las respuestas estén comprobadas',()=>{
  const work={requests:Array.from({length:10},()=>({status:'ready',paragraphs:[{text:'Ejemplo'}]}))},model=deriveDraftReview(work);
  const html=draftProgress(work,model,{busy:true,approval:{count:3,total:10,phase:'approving'},message:'Aprobando la respuesta 4 de 10…'});
  assert.match(html,/3 de 10 respuestas aprobadas/);
  assert.match(html,/aria-valuenow="3"/);
  assert.doesNotMatch(html,/10 de 10 respuestas comprobadas|Versión final generada/);
  const rendering=draftProgress(work,model,{busy:true,approval:{count:10,total:10,phase:'generating'},message:'Creando Word y PDF…'});
  assert.match(rendering,/10 de 10 respuestas aprobadas/);
  assert.match(rendering,/Creando Word y PDF/);
  assert.doesNotMatch(rendering,/stage-3 current complete|Versión final generada/);
});

test('el error conserva el número de aprobaciones y terminar la generación reemplaza el contador',()=>{
  const work={requests:[{status:'approved',paragraphs:[{text:'Ejemplo'}]}]},model=deriveDraftReview(work),approval={count:1,total:1,phase:'generating'};
  const error=draftProgress(work,model,{approval,error:'Interrupción'});
  assert.match(error,/1 de 1 respuesta aprobada/);
  assert.match(error,/El avance guardado se conserva/);
  assert.doesNotMatch(error,/source-spinner|Versión final generada/);
  const ready=draftProgress(work,model,{approval,generated:true});
  assert.match(ready,/Versión final generada/);
  assert.match(ready,/stage-3 current complete/);
});
