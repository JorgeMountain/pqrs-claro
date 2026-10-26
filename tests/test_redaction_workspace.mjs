import test from 'node:test';
import assert from 'node:assert/strict';
import {redactionRows,redactionWorkspace,redactionProgress,captureRedactionView,restoreRedactionView} from '../src/pqrs_claro/static/recorrido/redaction-workspace.js';

const current={id:'demo',filename:'solicitud.pdf',management:{owner_name:'José'},identification:{requests:[1,2,3].map(n=>({id:`P${n}`,title:`Petición ${n}`,label:`Solicitud ${n}`,description:`Pregunta ${n}`}))}};
const job={status:'running',stage:'drafts'};
const mapping={status:'ready',results:[{request_id:'P1',supports:[{source_id:'source-1',title:'Guía',page:2,version:1,quote:'Texto de la fuente.'}]}]};
const drafts={status:'running',completed_count:2,request_states:{P1:'completed',P2:'redactar',P3:'queued'},results:[{request_id:'P1',draft:{paragraphs:[{text:'Respuesta de prueba.'}]}},{request_id:'error-outside-current',error:'Error de prueba'}]};
const review={requests:[{request_id:'P1',paragraphs:[{text:'Texto editado y guardado.'}],pending:[{id:'pending-1',state:'confirmation_pending',kind:'fact',description:'Confirmar el canal de atención.'}]}]};

test('recuperar respuestas anteriores no muestra un cero definitivo ni ofrece reiniciar',()=>{
  const html=redactionWorkspace({...current,saved_stage:2},{status:'idle'},{},{},{},{initialPending:true});
  assert.match(html,/Recuperando las respuestas guardadas/);
  assert.doesNotMatch(html,/0 de 3|La respuesta aún no está disponible|data-action="live-resume"/);
  assert.match(html,/Revisar identificación/);
});

test('las respuestas históricas se cuentan como guardadas aunque sus comprobaciones estén desactualizadas',()=>{
  const rows=redactionRows(current,{status:'idle'},mapping,{}, {status:'stale',requests:review.requests.map(r=>({...r,stale:true}))});
  const html=redactionProgress({status:'idle'},rows,{historical:true});
  assert.match(html,/1 de 3 respuestas guardadas/);
  assert.doesNotMatch(html,/respuestas preparadas|Identificación completados/);
  assert.equal(rows[0].paragraphs[0].text,'Texto editado y guardado.');
  assert.equal(rows[0].stale,true);
});

test('muestra avance guardado real, sin contar errores ni aprobar una respuesta redactada',()=>{
  const rows=redactionRows(current,job,mapping,drafts,review);
  assert.equal(rows[0].label,'Por revisar');
  assert.equal(rows[0].paragraphs[0].text,'Texto editado y guardado.');
  assert.equal(rows[1].label,'Redactando');assert.equal(rows[2].label,'Por preparar');
  assert.match(redactionProgress(job,rows),/1 de 3 respuestas preparadas/);
  assert.match(redactionProgress(job,rows),/Redactando la petición 2/);
});

test('mantiene todas las peticiones en una lista y vincula fuentes y acciones a la seleccionada',()=>{
  const html=redactionWorkspace(current,job,mapping,drafts,review,{selectedRequest:'P1',canContinue:true});
  assert.equal((html.match(/data-response-id=/g)||[]).length,3);
  assert.doesNotMatch(html,/role="tab"|Solicitud Solicitud|Respuesta aprobada/);
  assert.match(html,/Confirmar el canal de atención/);
  assert.match(html,/source-1\/original\?case_id=demo#page=2/);
  assert.match(html,/data-action="live-edit" data-index="0"/);
  assert.match(html,/data-action="live-collections"/);
  const second=redactionWorkspace(current,job,mapping,drafts,review,{selectedRequest:'P2'});
  assert.match(second,/Petición 2 · Petición 2/);
  assert.doesNotMatch(second,/Confirmar el canal de atención/);
});

test('una proyección previa vacía no oculta una respuesta que terminó mientras otras se redactan',()=>{
  const rows=redactionRows(current,job,mapping,drafts,{requests:[{request_id:'P1',pre_draft:true,paragraphs:[],pending:[]}]});
  assert.equal(rows[0].preview,true);assert.equal(rows[0].paragraphs[0].text,'Respuesta de prueba.');
  assert.match(redactionProgress(job,rows),/1 de 3 respuestas preparadas/);
  const html=redactionWorkspace(current,job,mapping,drafts,{requests:[{request_id:'P1',pre_draft:true,paragraphs:[],pending:[]}]});
  assert.match(html,/disabled title="Disponible cuando termine de guardarse/);
});

test('conserva texto anterior, marca resultados desactualizados y no los cuenta como preparados',()=>{
  const rows=redactionRows(current,job,{...mapping,stale:true},drafts,review);
  assert.equal(rows[0].label,'Por actualizar');assert.equal(rows[0].paragraphs.length,1);
  assert.match(redactionProgress(job,rows),/0 de 3 respuestas preparadas/);
});

test('expone errores recuperables sin convertirlos en documentos faltantes',()=>{
  const failed={status:'ready',results:[{request_id:'P1',status:'error',summary:'Falló la extracción.',evidence_states:['analysis_error']}]};
  const html=redactionWorkspace(current,{status:'error',error:'No se completó la preparación'},failed,{},{});
  assert.match(html,/Falló la extracción/);assert.match(html,/live-retry-failed/);
  assert.doesNotMatch(html,/Documento faltante/);
});

test('preparar el índice es trabajo real previo a buscar, aunque no existan estados por petición',()=>{
  const indexing={status:'running',results:[],retrieval_progress:{phase:'indexing',prepared:52731,cached:21323,encoded:31408,queries:0}};
  const preparing={status:'running',stage:'sources'};
  const rows=redactionRows(current,preparing,indexing);
  assert.equal(rows[0].sourceActive,true);
  assert.equal(rows[0].label,'Preparando índice');
  assert.match(rows[0].message,/52\.731 fragmentos preparados/);
  assert.match(rows[0].message,/aún no ha comenzado/);
  const html=redactionWorkspace(current,preparing,indexing);
  assert.match(html,/Preparando el índice de fuentes/);
  assert.match(html,/<h3>Fuentes de respaldo<\/h3>/);
  assert.doesNotMatch(html,/Fuentes consultadas|Fuentes de respaldo \(0\)|Ver fuentes \(0\)|después de completar las anteriores|52\.731 de/);
});

test('muestra el total de fragmentos solo cuando el servidor lo informa',()=>{
  const rows=redactionRows(current,{status:'running',stage:'sources'},{status:'running',retrieval_progress:{phase:'indexing',prepared:12,total:90}});
  assert.match(rows[0].message,/12 de 90 fragmentos preparados/);
});

test('no presenta un cero definitivo al recuperar el estado o iniciar la búsqueda',()=>{
  for(const state of [{status:'running',stage:'sources'},{status:'starting'},{}]){
    const html=redactionWorkspace(current,state,{});
    assert.doesNotMatch(html,/Fuentes de respaldo \(0\)|Ver fuentes \(0\)|después de completar las anteriores/);
    assert.match(html,/Preparando la búsqueda|preparando la búsqueda|Recuperando el estado/);
  }
});

test('distingue peticiones buscando de las que esperan un turno, incluso la primera',()=>{
  const sourceRun={status:'running',request_states:{P1:'queued',P2:'searching',P3:'queued'}};
  const rows=redactionRows(current,{status:'running',stage:'sources'},sourceRun);
  assert.equal(rows[0].label,'Fuentes en espera');
  assert.equal(rows[0].sourceActive,false);
  assert.match(rows[0].message,/espera de un turno para buscar fuentes/);
  assert.equal(rows[1].label,'Buscando fuentes');
  assert.equal(rows[1].sourceActive,true);
});

test('solo una búsqueda terminada puede mostrar cero pasajes de respaldo seleccionados',()=>{
  const empty={status:'ready',results:[{request_id:'P1',status:'no_matches',supports:[]}]};
  const html=redactionWorkspace(current,{status:'waiting_review'},empty);
  assert.match(html,/Fuentes de respaldo \(0\)/);
  assert.match(html,/Búsqueda terminada. No se seleccionaron pasajes/);
  assert.doesNotMatch(html,/No existen fuentes|Documento faltante/);
});

test('un fallo de búsqueda sin resultados explica el error, sin afirmar que se consultaron cero fuentes',()=>{
  const html=redactionWorkspace(current,{status:'error',stage:'sources'},{status:'error',error:'No se pudo abrir el índice <temporal>.',results:[]});
  assert.match(html,/Requiere atención/);
  assert.match(html,/No se pudo abrir el índice &lt;temporal&gt;/);
  assert.doesNotMatch(html,/Fuentes de respaldo \(0\)|Búsqueda terminada|No existen fuentes|Documento faltante/);
});

test('conserva todos los pasajes guardados y cuenta las fuentes únicas al reanudar otras peticiones',()=>{
  const support=mapping.results[0].supports[0];
  const partial={status:'running',request_states:{P1:'completed',P2:'searching'},results:[{request_id:'P1',status:'references_found',supports:[support,{...support,page:3,quote:'Segundo pasaje conservado.'}]}]};
  const html=redactionWorkspace(current,{status:'running',stage:'sources'},partial);
  assert.match(html,/Fuentes de respaldo \(1\)/);
  assert.match(html,/Texto de la fuente\./);
  assert.match(html,/Segundo pasaje conservado\./);
  assert.equal((html.match(/class="redaction-source"/g)||[]).length,2);
});

test('advierte cobertura semántica parcial sin ocultar los pasajes encontrados',()=>{
  const partial={...mapping,retrieval_warning:'La búsqueda por significado tiene cobertura parcial.',retrieval_progress:{phase:'completed',prepared:52731,total:60000,pending:7269,complete:false,budget_exhausted:true}};
  const html=redactionWorkspace(current,{status:'ready'},partial,drafts,review);
  assert.match(html,/Búsqueda por significado con cobertura parcial/);
  assert.match(html,/7\.269 de 60\.000 fragmentos por preparar/);
  assert.match(html,/búsqueda por texto e identificadores conserva el alcance de las fuentes autorizadas/);
  assert.match(html,/no confirma que falte un documento/);
  assert.match(html,/Texto de la fuente\./);
  assert.match(html,/Texto editado y guardado\./);
  assert.match(html,/Fuentes de respaldo \(1\)/);
});

test('un resultado vacío con cobertura parcial no se presenta como búsqueda completa',()=>{
  const limited={status:'ready',results:[{request_id:'P1',status:'no_matches',supports:[]}],retrieval_warning:'La búsqueda por significado tiene cobertura parcial.',retrieval_progress:{phase:'completed',prepared:12,total:20,pending:8,complete:false,budget_exhausted:true}};
  const html=redactionWorkspace(current,{status:'waiting_review'},limited);
  assert.match(html,/Revisa la limitación de búsqueda indicada/);
  assert.match(html,/8 de 20 fragmentos por preparar/);
  assert.doesNotMatch(html,/Búsqueda terminada\.|No existen fuentes|Documento faltante/);
});

test('la cobertura parcial interrumpida también se comunica sin prometer trabajo en segundo plano',()=>{
  const limited={...mapping,retrieval_warning:'La preparación se interrumpió.',retrieval_progress:{pending:3,total:5,complete:false,cancelled:true}};
  const html=redactionWorkspace(current,{status:'interrupted'},limited);
  assert.match(html,/Búsqueda por significado con cobertura parcial/);
  assert.match(html,/3 de 5 fragmentos por preparar/);
  assert.doesNotMatch(html,/completando en segundo plano|terminará automáticamente/);
});

test('una limitación del recuperador se muestra escapada sin inventar cantidades ni cobertura',()=>{
  const limited={...mapping,retrieval_warning:'Motor <temporal> no disponible.'};
  const html=redactionWorkspace(current,{status:'ready'},limited);
  assert.match(html,/Limitación de la búsqueda/);
  assert.match(html,/Motor &lt;temporal&gt; no disponible/);
  assert.match(html,/Esta limitación no confirma ausencia documental/);
  assert.doesNotMatch(html,/fragmentos por preparar|Búsqueda por significado con cobertura parcial|<temporal>/);
});

test('un índice completo y sin advertencias no muestra una limitación residual',()=>{
  const complete={...mapping,retrieval_progress:{phase:'completed',total:20,prepared:20,pending:0,complete:true,budget_exhausted:false}};
  const html=redactionWorkspace(current,{status:'ready'},complete,drafts,review);
  assert.doesNotMatch(html,/Limitación de la búsqueda|Búsqueda por significado con cobertura parcial|fragmentos por preparar/);
});

test('un pendiente resuelto no se vuelve a presentar como abierto, y escapa contenido de documentos',()=>{
  const clean={requests:[{...review.requests[0],pending:[{...review.requests[0].pending[0],description:'<script>bad</script>',resolution:{action:'resolved',note:'Comprobado'}}]}]};
  const html=redactionWorkspace(current,job,mapping,drafts,clean);
  assert.doesNotMatch(html,/<script>|<strong>Pendiente:<\/strong>/);
  assert.match(html,/&lt;script&gt;bad/);
});

test('polling restaura lectura, selección expandida y foco sin saltar a otra petición',()=>{
  const summary={tagName:'SUMMARY',dataset:{},parentElement:{dataset:{responseId:'P2'}},focus:options=>assert.equal(options.preventScroll,true)};
  const details=[{dataset:{responseId:'P1'},open:true},{dataset:{responseId:'P2'},open:false,querySelector:()=>summary}];
  const scroll=[{dataset:{redactionScroll:'responses'},scrollTop:238},{dataset:{redactionScroll:'context'},scrollTop:126}];
  const frame={contains:()=>true,querySelectorAll:q=>q==='[data-response-id]'?details:scroll};
  const view={querySelector:()=>frame,querySelectorAll:frame.querySelectorAll};
  globalThis.document={activeElement:summary};
  const saved=captureRedactionView(view);details[1].open=true;scroll[0].scrollTop=0;
  restoreRedactionView(view,saved);assert.equal(details[1].open,false);assert.equal(scroll[0].scrollTop,238);assert.equal(scroll[1].scrollTop,126);
  delete globalThis.document;
});
