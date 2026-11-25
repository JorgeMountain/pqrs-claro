import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {esc} from '../src/pqrs_claro/static/recorrido/views.js';
import {preanalysisProgress} from '../src/pqrs_claro/static/recorrido/stage-progress.js';
import * as workflowNavigation from '../src/pqrs_claro/static/recorrido/workflow-navigation.js';
import * as documentNavigation from '../src/pqrs_claro/static/recorrido/document-navigation.js';

const source=(await fs.readFile(new URL('../src/pqrs_claro/static/recorrido/preanalysis.js',import.meta.url),'utf8')).replace(/^import .*;\r?\n/gm,'');
const dependencies={esc,preanalysisProgress,...workflowNavigation,...documentNavigation,icon:name=>`<svg data-icon="${name}"></svg>`,
  actor:()=>globalThis.__preanalysisHarness.manager,
  request:(...args)=>globalThis.__preanalysisHarness.request(...args)};
globalThis.__preanalysisDependencies=dependencies;
const {createPreanalysis}=await import('data:text/javascript;base64,'+Buffer.from('const {'+Object.keys(dependencies).join(',')+'}=globalThis.__preanalysisDependencies;\n'+source).toString('base64'));

function savedRecord(overrides={}){
  return {status:'ready',revision:3,page_count:1,
    checks:Object.fromEntries(['requester','respect','integrity'].map(key=>[key,{state:'pass',refs:[{page:1}]}])),
    approval:{actor_id:'manager-a',at:'2026-10-14T10:00:00Z',notes:{respect:'Observación <registrada>'}},...overrides};
}
function harness({record=savedRecord(),failFirstGet=false}={}){
  const calls=[],notices=[],started=[],stages=[],events={},elements=new Map();
  let html='',getFailed=false,backCount=0;
  const element=()=>({innerHTML:'',textContent:'',value:'',disabled:false,checked:false,
    style:{setProperty(){}},focus(){},scrollIntoView(){},addEventListener(){},
    toggleAttribute(name,enabled){if(enabled)this[name]=true;else delete this[name];}});
  const root={...element(),isConnected:true,events:{},
    querySelector(query){
      if(query==='[data-pre-start]'&&!elements.get('[data-pre-actions]')?.innerHTML.includes('data-pre-start'))return null;
      if(!elements.has(query))elements.set(query,element());return elements.get(query);
    },
    addEventListener(name,callback){this.events[name]=callback;}};
  const container={set innerHTML(value){html=value;root.isConnected=true;},get innerHTML(){return html;},querySelector:()=>root};
  const value={id:'demo-case',status:'uploaded',filename:'solicitud.pdf',management:{owner_id:'manager-a',owner_name:'José',revision:2}};
  const state={manager:'manager-a',async request(url,body){
    calls.push({url,body});
    if(failFirstGet&&!getFailed&&body===undefined&&!url.includes('/pages/')){getFailed=true;throw new Error('Lectura interrumpida.');}
    if(url.includes('/pages/'))return {page_count:1,width:600,height:800,marks:[]};
    if(url.endsWith('/start'))return {status:'identifying'};
    return structuredClone(record);
  }};
  globalThis.__preanalysisHarness=state;
  globalThis.ResizeObserver=class {observe(){} disconnect(){}};
  globalThis.window={addEventListener:(name,callback)=>{events[name]=callback;},scrollTo(){}};
  const component=createPreanalysis({container,onBack:async()=>{backCount++;},onStarted:async id=>started.push(id),notice:value=>notices.push(value)});
  const button=(attribute,dataset={})=>({disabled:false,dataset,hasAttribute:name=>name===attribute,textContent:''});
  const click=async(attribute,dataset={})=>root.events.click({target:{closest:()=>button(attribute,dataset)},preventDefault(){},stopPropagation(){}});
  return {component,value,root,calls,notices,started,stages,state,events,elements,click,
    get html(){return html;},get checks(){return elements.get('[data-pre-checks]')?.innerHTML||'';},get backCount(){return backCount;},
    options:{readOnly:true,navigation:'<ol data-test-navigation></ol>',onStage:stage=>stages.push(stage)}};
}

test('las flechas cambian de hoja, conservan la posición al refrescar y permiten reintentar un fallo', async () => {
  const h = harness();
  const request = h.state.request;
  let failOnce = true;
  h.state.request = async (url, body) => {
    const result = await request(url, body);
    if (!url.includes('/pages/')) return result;
    if (url.endsWith('/pages/2') && failOnce) {
      failOnce = false;
      throw new Error('Lectura interrumpida.');
    }
    return {...result, page_count: 2};
  };
  await h.component.show(h.value, h.options);
  const canvas = h.root.querySelector('.pre-canvas');
  const select = h.root.querySelector('[data-pre-page]');
  const previous = h.root.querySelector('[data-page-step="-1"]');
  const next = h.root.querySelector('[data-page-step="1"]');
  assert.ok(previous.disabled && !next.disabled);
  canvas.scrollTop = 150;
  await h.click('data-page-step', {pageStep: '1'});
  assert.equal(select.value, '1');
  assert.equal(canvas.scrollTop, 150);
  assert.ok(previous.disabled && !next.disabled);
  await h.click('data-page-step', {pageStep: '1'});
  assert.equal(select.value, '2');
  assert.equal(canvas.scrollTop, 0);
  assert.ok(!previous.disabled && next.disabled);
  canvas.scrollTop = 90;
  await h.click('data-pre-refresh');
  assert.equal(canvas.scrollTop, 90);
  await h.click('data-page-step', {pageStep: '-1'});
  assert.equal(select.value, '1');
  assert.equal(canvas.scrollTop, 0);
  h.component.leave();
});

test('consultar el preanálisis guardado del propietario solo hace GET y conserva sus observaciones',async()=>{
  const h=harness();await h.component.show(h.value,h.options);
  assert.ok(h.calls.length>=2);
  assert.ok(h.calls.every(call=>call.body===undefined));
  assert.match(h.html,/data-test-navigation/);
  assert.match(h.html,/Consulta la revisión previa/);
  assert.match(h.checks,/Revisión previa confirmada/);
  assert.match(h.elements.get('[data-pre-progress]').innerHTML,/3 de 3 verificaciones realizadas/);
  assert.match(h.elements.get('[data-pre-progress]').innerHTML,/Revisión previa confirmada/);
  assert.match(h.checks,/Observación &lt;registrada&gt;/);
  assert.doesNotMatch(h.checks,/data-pre-start|data-pre-confirm|data-pre-retry|data-pre-note|data-pre-ack/);
  await h.click('data-pre-start');await h.click('data-pre-retry');
  h.events['pqrs-manager-change']();
  await h.click('data-pre-back');
  assert.equal(h.backCount,1);
  assert.equal(h.started.length,0);
  assert.ok(h.calls.every(call=>call.body===undefined));
  assert.ok(h.notices.every(notice=>!notice.includes('identificación sigue pendiente')));
  h.component.leave();
});

test('las comprobaciones arrancan y se muestran mientras el visor aún está abriendo la primera página',async()=>{
  const h=harness();
  const request=h.state.request.bind(h.state);
  let releasePage;
  const waitingForPage=new Promise(resolve=>{releasePage=resolve;});
  h.state.request=async(url,body)=>{
    if(url.includes('/pages/'))await waitingForPage;
    return request(url,body);
  };
  const opening=h.component.show(h.value);
  try{
    await new Promise(resolve=>setImmediate(resolve));
    assert.match(h.html,/Preanálisis del expediente/);
    assert.equal(h.calls.filter(call=>call.url.endsWith('/check')).length,1);
    assert.match(h.checks,/Sin alertas/);
    assert.equal(h.started.length,0);
  }finally{
    releasePage();await opening;h.component.leave();
  }
  assert.equal(h.calls.filter(call=>call.url.includes('/pages/')).length,1);
});

test('el círculo de preanálisis se retira al llegar el resultado para revisión',async t=>{
  const record=savedRecord({status:'running',revision:1,approval:null});
  const h=harness({record});
  let poll;
  t.mock.method(globalThis,'setTimeout',fn=>{poll=fn;return 0;});
  try{
    await h.component.show(h.value);
    const marker=h.root.querySelector('.pre-step-number');
    const label=h.root.querySelector('[data-pre-working-label]');
    assert.ok(marker['data-stage-running']);
    assert.equal(label.hidden,false);
    record.status='ready';
    record.revision++;
    await poll();
    assert.equal(marker['data-stage-running'],undefined);
    assert.equal(label.hidden,true);
    assert.equal(h.started.length,0);
  }finally{h.component.leave();}
});

test('un expediente identificado entra automáticamente en consulta y vuelve a la etapa elegida',async()=>{
  const h=harness();h.value.status='confirmed';h.value.identification={requests:[{id:'P1'}]};
  await h.component.show(h.value,{navigation:h.options.navigation,onStage:h.options.onStage});
  for(const action of ['live-identification','live-responses','live-final'])await h.click('',{action});
  assert.deepEqual(h.stages,[1,2,3]);
  assert.ok(h.calls.every(call=>call.body===undefined));
  assert.doesNotMatch(h.checks,/identificación de peticiones aún no ha comenzado|Iniciar análisis/);
  h.component.leave();
});

test('la consulta de un caso antiguo sin verificaciones no inventa aprobación ni inicia comprobaciones',async()=>{
  const h=harness({record:savedRecord({status:'idle',revision:0,checks:{},approval:null})});
  h.value.identification={requests:[]};
  await h.component.show(h.value,h.options);
  assert.match(h.checks,/no tiene verificaciones previas guardadas/);
  assert.match(h.elements.get('[data-pre-progress]').innerHTML,/0 de 3 verificaciones realizadas/);
  h.state.manager='otra-persona';h.events['pqrs-manager-change']();
  h.state.manager='manager-a';h.events['pqrs-manager-change']();
  assert.ok(h.calls.every(call=>call.body===undefined));
  assert.doesNotMatch(h.checks,/Revisión previa confirmada|data-pre-start/);
  h.component.leave();
});

test('reintentar la carga de consulta después de un fallo de red sigue sin ejecutar un análisis',async()=>{
  const h=harness({failFirstGet:true});await h.component.show(h.value,h.options);
  assert.match(h.checks,/Lectura interrumpida/);assert.match(h.checks,/data-pre-refresh/);
  await h.click('data-pre-refresh');
  assert.match(h.checks,/Revisión previa confirmada/);
  assert.ok(h.calls.every(call=>call.body===undefined));
  h.component.leave();
});

test('el ingreso nuevo mantiene el inicio explícito después de la confirmación del gestor',async()=>{
  const h=harness({record:savedRecord({approval:null})});
  await h.component.show(h.value);
  assert.equal(h.calls.filter(call=>call.url.endsWith('/check')&&call.body).length,1);
  assert.equal(h.calls.filter(call=>call.url.endsWith('/start')).length,0);
  await h.click('data-pre-start');
  assert.equal(h.started.length,0);
  h.root.events.input({target:{hasAttribute:key=>key==='data-pre-confirm',checked:true,dataset:{}}});
  await h.click('data-pre-start');
  const start=h.calls.find(call=>call.url.endsWith('/start'));
  assert.equal(start.body.confirmed,true);
  assert.deepEqual(h.started,['demo-case']);
  h.component.leave();
});

test('un expediente cerrado tampoco ejecuta verificaciones aunque aún no tenga identificación',async()=>{
  const h=harness();h.value.management.state='closed';
  await h.component.show(h.value);
  assert.ok(h.calls.every(call=>call.body===undefined));
  assert.doesNotMatch(h.checks,/data-pre-start|data-pre-retry/);
  h.component.leave();
});

test('cada expresión observada enlaza su evidencia y escapa el texto del documento',async()=>{
  const record=savedRecord();
  record.checks.respect={state:'attention',summary:'Revisa el lenguaje dirigido a personas.',refs:[
    {page:1,quote:'Primera <cita>'},{page:2,quote:'Segunda cita'}]};
  const h=harness({record});await h.component.show(h.value,h.options);
  assert.match(h.checks,/Primera &lt;cita&gt;/);
  assert.match(h.checks,/Segunda cita/);
  assert.match(h.checks,/data-page="1" data-ref-index="0"/);
  assert.match(h.checks,/data-page="2" data-ref-index="1"/);
  await h.click('data-ref-index',{preEvidence:'respect',page:'2',refIndex:'1'});
  assert.ok(h.calls.at(-1).url.endsWith('/pages/2'));
  h.component.leave();
});

test('una ofensa citada conserva la explicación de quién la dijo y el enlace al original',async()=>{
  const record=savedRecord();
  record.checks.respect={state:'pass',summary:'La persona solicitante denuncia lo dicho por <un tercero>.',
    refs:[{page:2,quote:'La vecina relata lo sucedido.'}]};
  const h=harness({record});await h.component.show(h.value,h.options);
  assert.match(h.checks,/Sin alertas</);
  assert.match(h.checks,/denuncia lo dicho por &lt;un tercero&gt;/);
  assert.match(h.checks,/data-pre-evidence="respect" data-page="2"/);
  assert.doesNotMatch(h.checks,/No se detectaron expresiones irrespetuosas/);
  h.component.leave();
});

test('un resultado guardado sin explicación limita el mensaje al lenguaje del solicitante',async()=>{
  const h=harness();await h.component.show(h.value,h.options);
  assert.match(h.checks,/Sin alertas de lenguaje atribuidas al solicitante/);
  h.component.leave();
});

test('un fallo automático muestra el motivo y permite reintentar conservando las notas manuales',async()=>{
  const record=savedRecord({error:'La respuesta del servicio quedó incompleta.',approval:null,
    checks:Object.fromEntries(['requester','respect','integrity'].map(k=>[k,{state:'unverified',refs:[]}]))});
  const h=harness({record});await h.component.show(h.value);
  const retry=h.checks.indexOf('data-pre-retry'),firstFinding=h.checks.indexOf('Datos del solicitante');
  assert.ok(retry>=0&&retry<firstFinding);
  assert.match(h.checks,/La respuesta del servicio quedó incompleta/);
  assert.equal(h.checks.match(/Sin resultado automático/g)?.length,3);
  assert.doesNotMatch(h.checks,/No identificado|página revisada|La alerta queda registrada/);
  assert.equal(h.checks.match(/data-pre-ack=/g)?.length,3);
  h.root.events.input({target:{hasAttribute:()=>false,dataset:{preNote:'respect'},value:'Trabajo de revisión en curso.'}});
  await h.click('data-pre-retry');
  const relevant=h.calls.filter(c=>c.url.endsWith('/draft')||c.body?.retry);
  assert.equal(relevant.length,2);
  assert.equal(relevant[0].body.notes.respect,'Trabajo de revisión en curso.');
  assert.equal(relevant[1].body.retry,true);
  assert.equal(h.started.length,0);
  h.component.leave();
});

test('tras un reintento fallido se identifican los resultados conservados y sus hallazgos',async()=>{
  const record=savedRecord({error:'El servicio no respondió.',retained_checks:true,approval:null});
  record.checks.respect={state:'attention',summary:'Revisa este pasaje.',refs:[{page:1,quote:'Evidencia guardada'}]};
  const h=harness({record});await h.component.show(h.value);
  assert.match(h.checks,/últimos resultados comprobados/);
  assert.match(h.checks,/Evidencia guardada/);
  assert.match(h.checks,/Revisar</);
  assert.doesNotMatch(h.checks,/Sin resultado automático/);
  h.component.leave();
});

test('una referencia incompleta del solicitante permite consultar los otros hallazgos',async()=>{
  const record=savedRecord({approval:null});
  record.checks.requester={state:'unverified',summary:'Contrasta el contacto en el original.',
    name:'Persona de Prueba',contact:null,refs:[]};
  const h=harness({record});await h.component.show(h.value);
  assert.match(h.checks,/Persona de Prueba/);
  assert.match(h.checks,/Por comprobar/);
  assert.match(h.checks,/Sin alertas</);
  assert.match(h.checks,/Verificado</);
  assert.equal(h.checks.match(/data-pre-ack=/g)?.length,1);
  assert.doesNotMatch(h.checks,/Sin resultado automático|data-pre-retry/);
  h.component.leave();
});
