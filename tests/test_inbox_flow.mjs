import test from 'node:test';
import assert from 'node:assert/strict';
import {receiveDocument} from '../src/pqrs_claro/static/recorrido/receipt-flow.js';
import {progress,progressBar,actionFor,progressDetail} from '../src/pqrs_claro/static/recorrido/inbox-progress.js';
import {inboxTable} from '../src/pqrs_claro/static/recorrido/inbox-views.js';

test('guardar en el pool conserva el original sin asignar ni analizar',async()=>{
  const item={file:{name:'test.pdf'}};let uploads=0;
  await receiveDocument(item,{mode:'save',upload:async()=>{uploads++;return {id:'c1'};},request:()=>assert.fail('Guardar no debe ejecutar gestión o análisis')});
  assert.equal(item.caseId,'c1');assert.equal(uploads,1);
});
test('recepción directa requiere gestor antes de subir un documento',async()=>{
  await assert.rejects(receiveDocument({file:{}},{mode:'analyze',manager:'',upload:()=>assert.fail('No debe crear sin gestor')}),/Selecciona/);
});
test('recepción directa solo toma; reintentar la asignación no duplica ni inicia',async()=>{
  const item={file:{name:'test.pdf'}};let uploads=0,fail=true;
  const events=[];let record={owner_id:null,revision:0,started_at:null};
  const opts={mode:'analyze',manager:'ana',upload:async()=>{uploads++;return {id:'c1'};},request:async(url,body)=>{
    if(!body)return {...record};events.push(body.action);
    if(fail){fail=false;throw new Error('Servicio temporalmente no disponible');}
    assert.equal(body.action,'claim');record={...record,owner_id:'ana',revision:1};return {...record};
  }};
  await assert.rejects(receiveDocument(item,opts),/temporalmente/);
  assert.equal(item.caseId,'c1');await receiveDocument(item,opts);
  assert.equal(uploads,1);assert.deepEqual(events,['claim','claim']);assert.equal(record.started_at,null);
});
test('si otro gestor tomó el documento, no inicia ni reasigna',async()=>{
  await assert.rejects(receiveDocument({caseId:'c1'},{mode:'analyze',manager:'ana',request:async(url,body)=>{assert.equal(body,undefined);return {owner_id:'carlos'};}}),/Otro gestor/);
});
test('un inicio ya aceptado no se repite al recuperar la recepción',async()=>{
  const seen=[];
  await receiveDocument({caseId:'c1'},{mode:'analyze',manager:'ana',request:async(url,body)=>{assert.equal(body,undefined);seen.push(url);return url.endsWith('/management')?{owner_id:'ana',started_at:'today'}:{status:'identifying',analysis_running:true};}});
  assert.equal(seen.length,1);
});
test('tomar un expediente nunca lo muestra como identificado',()=>{
  const c={id:'c1',status:'uploaded',initial_review_status:'idle',processing:true,preanalysis_status:'running',management:{owner_id:'ana',owner_name:'Ana',started_at:null}};
  assert.equal(progress(c).stage,0);
  assert.equal(progress(c).label,'En preanálisis');
  assert.equal(progressBar(c),'');
  assert.deepEqual(actionFor(c,'ana'),{kind:'preanalysis',label:'Revisar documento'});
  assert.doesNotMatch(inboxTable([c],'ana'),/Identificación lista|Completado|Revisar resultado|\[object Object\]/);
});
test('los compañeros pueden consultarse sin ofrecer tomar su expediente',()=>{
  const c={id:'c1',subject:'<script>prueba</script>',status:'uploaded',management:{owner_id:'carlos',owner_name:'Carlos',started_at:null}};
  assert.deepEqual(actionFor(c,'ana'),{kind:'detail',label:'Ver detalle'});
  const html=inboxTable([c],'ana');assert.match(html,/Carlos/);assert.match(html,/Ver detalle/);assert.doesNotMatch(html,/Tomar expediente|<script>/);
});
test('el progreso usa estados guardados y mantiene la revisión humana pendiente',()=>{
  const c={id:'c1',status:'needs_review',initial_review_status:'running',processing:true,management:{owner_id:'ana',started_at:'today'}};
  assert.equal(progress(c).detail,'Analizando contenido y tipo de petición');assert.equal(progress(c).stage,1);
  assert.equal(progress({...c,processing:false,initial_review_status:'needs_review'}).tone,'review');
  assert.equal(progress({...c,status:'confirmed',processing:false,initial_review_status:'needs_review'}).tone,'review');
  assert.equal(progress({...c,status:'confirmed',processing:false,initial_review_status:'idle'}).identifiedOnly,true);
  assert.equal(progress({...c,status:'needs_review',processing:false,initial_review_status:null}).identifiedOnly,true);
  assert.doesNotMatch(progressDetail(c,'ana'),/\d+%/);
  assert.equal(progress({...c,processing:false,initial_review_status:'error'}).tone,'error');
});
test('el avance sigue visible al terminar el análisis, sin completar la revisión humana',()=>{
  const c={id:'c1',status:'confirmed',initial_review_status:'needs_review',management:{owner_id:'ana',started_at:'today'}};
  const label='Preanálisis: Completado. Identificación: Por revisar. Redacción: Pendiente. Borrador: Pendiente';
  assert.ok(inboxTable([c],'ana').includes(label));
  assert.ok(progressDetail(c,'ana').includes(label));
  assert.doesNotMatch(progressBar(c),/Identificación: Completado/);
  const identified=progressBar({...c,initial_review_status:'idle'});
  assert.match(identified,/Redacción: Pendiente/);
  assert.match(identified,/Borrador: Pendiente/);
  assert.equal(progressBar({...c,status:'uploaded',initial_review_status:undefined}), '');
});


test('una ruta alternativa no aparece como redacción y el borrador sigue el estado registrado',()=>{
  const c={status:'confirmed',initial_review_status:'routed',management:{owner_id:'ana',started_at:'today'}};
  assert.equal(progress(c).stage,1);
  assert.match(progressBar(c),/Redacción: Pendiente/);
  assert.equal(progress({...c,initial_review_status:'approved'}).stage,2);
  assert.equal(progress({...c,initial_review_status:'approved',management:{...c.management,state:'ready_review'}}).stage,3);
});

test('expedientes anteriores recuperan la redacción guardada aunque no tengan revisión del flujo nuevo',()=>{
  const c={id:'old',status:'confirmed',request_count:2,initial_review_status:'idle',saved_stage:2,management:{owner_id:'ana',started_at:'before'}};
  assert.equal(progress(c).stage,2);
  assert.equal(progress(c).label,'Redacción guardada');
  assert.equal(actionFor(c,'ana').label,'Continuar gestión');
  assert.doesNotMatch(inboxTable([c],'ana'),/Por identificar|Identificación pendiente/);
  assert.match(progressDetail(c,'ana'),/revisión de tipos sin registro/);
  assert.match(progressBar(c),/Preanálisis: Sin registro/);
  assert.match(progressBar(c),/Identificación: Guardado/);
  assert.equal(progress({...c,saved_stage:3}).label,'Borrador guardado');
  assert.equal(progress({...c,saved_stage:0,preparation:{status:'waiting_review'}}).stage,2);
  assert.equal(progress({...c,saved_stage:0}).label,'Identificada');
  assert.equal(progress({...c,initial_review_status:'needs_review'}).stage,1);
  assert.equal(progress({...c,initial_review_status:'running'}).tone,'processing');
  assert.equal(progress({...c,status:'uploaded'}).stage,0);
});

test('la bandeja reabre el borrador guardado y reconoce un oficio generado sin cerrar la gestión',()=>{
  const c={id:'ordinary',status:'confirmed',request_count:2,initial_review_status:'approved',saved_stage:3,
    preparation:{status:'ready'},management:{owner_id:'ana',started_at:'today',state:'in_progress'}};
  assert.equal(progress(c).stage,3);
  assert.equal(progress(c).label,'Borrador guardado');
  assert.equal(actionFor(c,'ana').label,'Revisar borrador');
  assert.match(progressBar(c),/Redacción: Completado\. Borrador: En curso/);
  assert.doesNotMatch(progressBar(c),/Borrador: Completado/);
  const generated={...c,office_progress:{id:'export',status:'ready'}};
  assert.equal(progress(generated).label,'Oficio generado');
  assert.equal(progress(generated).stage,3);
  assert.equal(actionFor(generated,'ana').label,'Ver oficio');
  assert.match(progressBar(generated),/Borrador: Completado/);
  assert.equal((progressBar(generated).match(/class="stage-\w+ complete"/g)||[]).length,4);
  assert.doesNotMatch(inboxTable([generated],'ana'),/Finalizada|Continuar con las respuestas/);
  assert.equal(c.management.state,'in_progress');
});

test('un oficio modificado o una generación fallida conserva su etapa sin fingir finalización',()=>{
  const c={status:'confirmed',initial_review_status:'approved',saved_stage:3};
  for(const status of ['stale','failed','generating']){
    const value={...c,office_progress:{id:'export',status}};
    assert.equal(progress(value).stage,3);
    assert.doesNotMatch(progressBar(value),/Borrador: Completado/);
  }
  assert.equal(progress({...c,office_progress:{status:'stale'}}).label,'Borrador por actualizar');
  assert.equal(progress({...c,office_progress:{status:'generating'}}).label,'Generando oficio');
  assert.equal(progress({...c,initial_review_status:'routed'}).label,'Ruta registrada');
});
