import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {esc} from '../src/pqrs_claro/static/recorrido/views.js';
import {preanalysisProgress} from '../src/pqrs_claro/static/recorrido/stage-progress.js';

const source=(await fs.readFile(new URL('../src/pqrs_claro/static/recorrido/preanalysis.js',import.meta.url),'utf8')).replace(/^import .*;\r?\n/gm,'');
const dependencies={esc,preanalysisProgress,icon:name=>`<svg data-icon="${name}"></svg>`,
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
    style:{setProperty(){}},focus(){},scrollIntoView(){}});
  const root={...element(),isConnected:true,events:{},
    querySelector(query){
      if(query==='[data-pre-start]'&&!elements.get('[data-pre-checks]')?.innerHTML.includes('data-pre-start'))return null;
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
  globalThis.window={addEventListener:(name,callback)=>{events[name]=callback;},scrollTo(){}};
  const component=createPreanalysis({container,onBack:async()=>{backCount++;},onStarted:async id=>started.push(id),notice:value=>notices.push(value)});
  const button=(attribute,dataset={})=>({disabled:false,dataset,hasAttribute:name=>name===attribute,textContent:''});
  const click=async(attribute,dataset={})=>root.events.click({target:{closest:()=>button(attribute,dataset)},preventDefault(){},stopPropagation(){}});
  return {component,value,root,calls,notices,started,stages,state,events,elements,click,
    get html(){return html;},get checks(){return elements.get('[data-pre-checks]')?.innerHTML||'';},get backCount(){return backCount;},
    options:{readOnly:true,navigation:'<ol data-test-navigation></ol>',onStage:stage=>stages.push(stage)}};
}

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
