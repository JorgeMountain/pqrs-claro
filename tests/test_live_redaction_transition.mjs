// Exercise live.js itself with a slow catalog and controllable API responses.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {setImmediate as tick} from 'node:timers/promises';
import * as draftTools from '../src/pqrs_claro/static/recorrido/review-drafts.js';
import * as confirmation from '../src/pqrs_claro/static/recorrido/initial-confirmation.js';
import {expedienteSteps} from '../src/pqrs_claro/static/recorrido/expediente-workspace.js';
import {responses} from '../src/pqrs_claro/static/recorrido/live-views.js';

const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const stored=new Map(),listeners={},renders=[],calls=[];
globalThis.localStorage={getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
globalThis.window={addEventListener(){}};
globalThis.location={href:'http://example.invalid/',pathname:'/'};
globalThis.history={replaceState:(_a,_b,url)=>{location.href=new URL(url,location.href).href;}};
// Poll callbacks are deliberately not run; these checks concern in-flight loads.
globalThis.setTimeout=()=>1;globalThis.clearTimeout=()=>{};
const blank=()=>({textContent:'',hidden:false,disabled:false,dataset:{},classList:{add(){},remove(){}},
  setAttribute(name,value){this[name]=value;},removeAttribute(){},focus(){},
  querySelector:()=>null,querySelectorAll:()=>[],addEventListener(){}});
const nodes=new Map();const node=key=>{if(!nodes.has(key))nodes.set(key,blank());return nodes.get(key);};
const form={elements:[],reportValidity:()=>true};
const view={...blank(),insertAdjacentHTML(){},addEventListener:(kind,fn)=>listeners[kind]=fn,
  querySelector:key=>key==='#initial-decision-form'?form:null,
  set innerHTML(value){this.html=value;renders.push(value);},get innerHTML(){return this.html||'';}};
globalThis.document={querySelector:key=>key==='#view'?view:node(key),querySelectorAll:()=>[],activeElement:null};
const record={id:'slow-case',version:1,status:'needs_review',pages:[],request_count:1,
  management:{owner_id:'qa',owner_name:'QA',started_at:'2026-10-13'},
  identification:{requests:[{id:'P1',source_refs:[]}]}};
const intake={revision:1,status:'needs_review',report:{document:{},requests:[{request_id:'P1'}]},can_prepare:false};
const decision={case_id:record.id,revision:1,reviewed_by:'QA',document:{route:'continue',reviewed:true,note:''},requests:[{request_id:'P1',petition_type:'information',route:'continue',reviewed:true,note:'Nota conservada'}]};
let finalLoads=0,savedPreanalysis=null,headingOptions=null;
let reads=null,preparing=null,job={status:'idle'},saveCount=0,prepareCount=0;
globalThis.fetch=async(url,options)=>{
  calls.push({url,method:options?.method});assert.ok(options.signal,'Requests need a bounded wait');
  let value;
  if(url==='/api/config')value={initial_review_enabled:true,management_enabled:true};
  else if(url==='/api/managers')value=[];
  else if(url.endsWith('/initial-review/decision')){
    saveCount++;assert.equal(JSON.parse(options.body).requests[0].note,'Nota conservada');
    record.version++;record.status='confirmed';Object.assign(intake,{revision:2,status:'approved',can_prepare:true});value=intake;
  }else if(url.endsWith('/preparation')&&options?.method){prepareCount++;value=await preparing.promise;job=value;}
  else if(url.endsWith('/preparation'))value=job;
  else if(url.endsWith('/initial-review?compact=true'))value=reads?await reads.initial.promise:intake;
  else if(url.endsWith('/sources?compact=true'))value=await reads.sources.promise;
  else if(url.endsWith('/drafts'))value=await reads.drafts.promise;
  else if(url.endsWith('/review'))value=await reads.review.promise;
  else value=record;
  return {ok:true,json:async()=>structuredClone(value)};
};
globalThis.__deps={captureRedactionView:()=>null,restoreRedactionView(){},...draftTools,...confirmation,
  reviewNavigation:()=>'',reviewItems:()=>[],nextReviewIndex:()=>0,focusReviewPetition(){},syncReviewNavigation(){},suggestedReviewer:()=>'',
  identificationWorkspace:(_data,_state,options)=>options.confirmation,bindIdentificationWorkspace:()=>()=>{},expedienteHeading:(_case,_step,options)=>{headingOptions=options;return '<header>Redacción</header>';},
  expedienteSteps,createFinal:()=>({setCase(){},hide(){},load(){finalLoads++;return Promise.resolve();},view:()=>node('paper')}),renderAnalysis(){},esc:String,renderCaseNavigation(){},
  createProposalPanel:()=>({}),createPendingActions:()=>({}),createResponseEditor:()=>({hasChanges:()=>false}),
  identification:()=>'',responses,supports:()=>'',
  createIdentificationActions:()=>({banner:()=>''}),bindOriginal(){},focusOriginal(){},bindSplitPane:()=>()=>{},focusRequest(){},createEvidenceUpload:()=>({}),
  initialReviewSummary:()=>'',initialRequestContent:()=>({}),initialReady:()=>true,initialHistory(){},
  readInitialDecision:()=>structuredClone(decision),initialConfirmation:(_c,_i,_d,{busy})=>busy?'Guardando revisión…':'Confirmar',updateInitialConfirmation(){},pilotReviewControls:()=>''};
const source=(await fs.readFile(new URL('../src/pqrs_claro/static/recorrido/live.js',import.meta.url),'utf8')).replace(/^import .*;\r?\n/gm,'');
const {createLive}=await import('data:text/javascript;base64,'+Buffer.from('const {'+Object.keys(__deps).join(',')+'}=globalThis.__deps;\n'+source).toString('base64'));
const live=createLive({open(){},close(){},notice(){},releaseDemo(){},onBrowse(){},onPreanalysis:async(current,navigation)=>savedPreanalysis={current,navigation}});
const click=action=>listeners.click({target:{closest:()=>({dataset:{action}})}});
const delayReads=()=>reads={initial:deferred(),sources:deferred(),drafts:deferred(),review:deferred()};
const finishReads=()=>{reads.initial.resolve(intake);reads.sources.resolve({status:'running',results:[]});reads.drafts.resolve({status:'idle',results:[]});reads.review.resolve({status:'idle',requests:[]});};

await live.select(record.id);
preparing=deferred();click('live-initial-confirm');await tick();
assert.equal(saveCount,1);assert.equal(prepareCount,1);
assert.equal(new URL(location.href).searchParams.get('step'),'2');
assert.match(view.innerHTML,/Redacción/);assert.match(view.innerHTML,/Iniciando la preparación/);
assert.doesNotMatch(view.innerHTML,/Guardando revisión/);
console.log('PASS: saved review enters Redacción while preparation POST is still pending.');

delayReads();preparing.resolve({status:'running',stage:'sources',stale:false});await tick();await tick();
assert.equal(view['aria-busy'],'false');assert.match(view.innerHTML,/Preparando la búsqueda de fuentes/);
assert.equal(saveCount,1);
assert.ok(!calls.some(call=>call.url.endsWith('/drafts')||call.url.endsWith('/review')),
  'Do not scan the catalog again for drafts and review while sources are still running');
const before=calls.length;click('live-refresh');await tick();
assert.equal(calls.length,before,'A pending refresh is reused, not duplicated');
finishReads();await tick();
console.log('PASS: slow catalog does not lock the page or duplicate polling/confirmation.');

live.go(1);delayReads();click('live-initial-confirm');await tick();await tick();
assert.equal(saveCount,1);assert.equal(prepareCount,1,'Existing running preparation must be reused');
assert.equal(new URL(location.href).searchParams.get('step'),'2');
finishReads();await tick();
console.log('PASS: returning to Redacción reuses the recorded decision and running job.');

live.leave();location.href='http://example.invalid/?case=slow-case&step=2';delayReads();
await live.init();await tick();
assert.equal(view['aria-busy'],'false');assert.match(view.innerHTML,/Preparando la búsqueda de fuentes/);
reads.initial.resolve(intake);reads.sources.reject(new DOMException('Timed out','TimeoutError'));
reads.drafts.resolve({status:'idle',results:[]});reads.review.resolve({status:'idle',requests:[]});await tick();
assert.match(view.innerHTML,/Actualizar estado/);assert.match(view.innerHTML,/avance guardado se conserva/);
assert.match(view.innerHTML,/Preparando la búsqueda de fuentes/);assert.equal(view['aria-busy'],'false');
delayReads();click('live-refresh');await tick();finishReads();await tick();
assert.doesNotMatch(view.innerHTML,/Actualizar estado/);assert.equal(saveCount,1);assert.equal(prepareCount,1);
live.go(1);job={status:'idle'};preparing=deferred();delayReads();
click('live-initial-confirm');await tick();
assert.equal(prepareCount,2);
// The server accepted the start, but the browser did not receive its response.
job={status:'running',stage:'sources',stale:false};
preparing.reject(new DOMException('Lost response','TimeoutError'));await tick();await tick();
assert.match(view.innerHTML,/Redacción/);assert.match(view.innerHTML,/Preparando la búsqueda de fuentes/);
finishReads();await tick();
assert.equal(saveCount,1);assert.equal(prepareCount,2);
assert.doesNotMatch(view.innerHTML,/Actualizar estado/);
live.leave();
console.log('PASS: reopening is responsive; timed-out reads retain progress and recover without writes.');
console.log('PASS: a lost start response is recovered by reading the accepted job, without resubmission.');

// Stage changes are read operations, including when expensive projections are pending.
const writesBefore=calls.filter(c=>c.method).length;
location.href='http://example.invalid/?view=cases';job={status:'ready',stage:'ready',stale:false};delayReads();
await live.select(record.id,{step:2});
assert.equal(new URL(location.href).searchParams.get('step'),'2');
assert.match(view.innerHTML,/Redacción/);assert.equal(view['aria-busy'],'false');
click('live-preanalysis');await tick();
assert.equal(savedPreanalysis.current.id,record.id);
assert.match(savedPreanalysis.navigation,/live-identification/);assert.match(savedPreanalysis.navigation,/live-responses/);
const snapshot=view.innerHTML;
finishReads();await tick();await tick();
assert.equal(view.innerHTML,snapshot,'Background reads must not replace the preanalysis view');
live.resume(1);assert.equal(new URL(location.href).searchParams.get('step'),'1');
click('live-responses');assert.equal(new URL(location.href).searchParams.get('step'),'2');
// Minimal document host for the real controller's draft navigation branch.
let frame=null;
const originalQuery=view.querySelector;
view.querySelector=selector=>selector==='.expediente-later'?frame:originalQuery(selector);
document.createElement=()=>({...blank(),contains:()=>true,append(){},querySelector:()=>blank()});
view.replaceChildren=value=>{frame=value;};
click('live-final');await tick();
assert.equal(new URL(location.href).searchParams.get('step'),'3');assert.equal(finalLoads,1);
click('live-identification');await tick();
assert.equal(new URL(location.href).searchParams.get('step'),'1');
assert.equal(calls.filter(c=>c.method).length,writesBefore,'Visiting all four stages must not write or start a worker');
assert.ok(!calls.some(c=>c.method&&/\/(analyze|check|start)$/.test(c.url)));
live.leave();location.href='http://example.invalid/?view=cases';delayReads();
await live.select(record.id,{step:2});await tick();
assert.equal(new URL(location.href).searchParams.get('step'),'2','Continue opens the saved progress shown in the inbox');
finishReads();await tick();live.leave();
console.log('PASS: all four saved stages can be visited without identification, confirmation or preparation writes.');
console.log('PASS: Continue opens the inbox stage and paints it before slow projections finish.');

// An older case has durable responses but no modern initial-review/preparation.
record.id='legacy-case';record.saved_stage=2;record.initial_review_status='idle';
Object.assign(intake,{revision:0,status:'idle',can_prepare:false,report:null});
job={status:'idle'};location.href='http://example.invalid/?view=cases';delayReads();
const oldWrites=calls.filter(c=>c.method).length;
await live.select(record.id);await tick();
assert.equal(new URL(location.href).searchParams.get('step'),'2');
assert.match(view.innerHTML,/Avance anterior conservado/);
finishReads();await tick();await tick();
assert.equal(new URL(location.href).searchParams.get('step'),'2');
assert.equal(calls.filter(c=>c.method).length,oldWrites);
live.leave();
console.log('PASS: legacy stored responses reopen without another identification or approval.');

record.id='generated-case';record.saved_stage=3;record.initial_review_status='approved';
record.office_progress={id:'export',status:'ready'};
Object.assign(intake,{status:'approved',can_prepare:true});
location.href='http://example.invalid/?view=cases';delayReads();
const generatedWrites=calls.filter(c=>c.method).length;
await live.select(record.id,{step:3});
assert.equal(new URL(location.href).searchParams.get('step'),'3');
assert.equal(headingOptions.redactionComplete,true);
assert.equal(headingOptions.draftComplete,true);
assert.equal(headingOptions.navigation.completed[3],true);
finishReads();await tick();await tick();live.leave();
assert.equal(calls.filter(c=>c.method).length,generatedWrites);
console.log('PASS: opening a generated office retains recorded completion while details load.');
