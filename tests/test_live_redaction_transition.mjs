// Exercise live.js itself with a slow catalog and controllable API responses.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {setImmediate as tick} from 'node:timers/promises';
import * as draftTools from '../src/pqrs_claro/static/recorrido/review-drafts.js';
import * as scopeTools from '../src/pqrs_claro/static/source-scope.js';
import * as confirmation from '../src/pqrs_claro/static/recorrido/initial-confirmation.js';
import {expedienteSteps} from '../src/pqrs_claro/static/recorrido/expediente-workspace.js';
import {responses} from '../src/pqrs_claro/static/recorrido/live-views.js';

const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const stored=new Map(),listeners={},renders=[],calls=[];
globalThis.localStorage={getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
const windowEvents={};
globalThis.window={addEventListener(type,fn){windowEvents[type]=fn;}};
globalThis.location={href:'http://example.invalid/',pathname:'/'};
globalThis.history={replaceState:(_a,_b,url)=>{location.href=new URL(url,location.href).href;}};
const scheduled=new Map();
globalThis.setTimeout=(callback,delay)=>{const id=Symbol();scheduled.set(id,{callback,delay});return id;};
globalThis.clearTimeout=id=>scheduled.delete(id);
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
const previews=new Map();
let sourceRevisions={collection_ids:['public'],correction_revision:'c1',result_revision:'r1'};
globalThis.fetch=async(url,options)=>{
  calls.push({url,method:options?.method});assert.ok(options.signal,'Requests need a bounded wait');
  let value;
  if(url==='/api/config')value={initial_review_enabled:true,management_enabled:true};
  else if(url==='/api/managers')value=[];
  else if(url.includes('/source-collections'))value=sourceRevisions;
  else if(url.endsWith('/initial-review/decision')){
    saveCount++;assert.equal(JSON.parse(options.body).requests[0].note,'Nota conservada');
    record.version++;record.status='confirmed';Object.assign(intake,{revision:2,status:'approved',can_prepare:true});value=intake;
  }else if(url.endsWith('/preparation')&&options?.method){prepareCount++;value=await preparing.promise;job=value;}
  else if(url.endsWith('/preparation'))value=job;
  else if(url.endsWith('/initial-review?compact=true'))value=reads?await reads.initial.promise:intake;
  else if(url.endsWith('/preview')){
    const id=url.split('/').at(-2);
    const aborted=new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true}));
    value=previews.has(id)?await Promise.race([previews.get(id).promise,aborted]):{request_id:id,mapping:{},drafts:{},review:{}};
  }
  else if(url.endsWith('/sources?compact=true'))value=await reads.sources.promise;
  else if(url.endsWith('/drafts'))value=await reads.drafts.promise;
  else if(url.endsWith('/review'))value=await reads.review.promise;
  else value=record;
  return {ok:true,json:async()=>structuredClone(value)};
};
globalThis.__deps={captureRedactionView:()=>null,restoreRedactionView(){},...scopeTools,...draftTools,...confirmation,
  reviewNavigation:()=>'',reviewItems:()=>[],nextReviewIndex:()=>0,focusReviewPetition(){},syncReviewNavigation(){},suggestedReviewer:()=>'',
  identificationWorkspace:(_data,_state,options)=>options.confirmation,bindIdentificationWorkspace:()=>()=>{},expedienteHeading:(_case,_step,options)=>{headingOptions=options;return '<header>Redacción</header>';},
  expedienteSteps,createFinal:()=>({setCase(){},hide(){},discardScope(){},load(){finalLoads++;return Promise.resolve();},view:()=>node('paper')}),renderAnalysis(){},esc:String,renderCaseNavigation(){},
  createProposalPanel:()=>({}),createPendingActions:()=>({}),createResponseEditor:()=>({hasChanges:()=>false,discardScope(){}}),
  identification:()=>'',responses,supports:()=>'',
  createIdentificationActions:()=>({banner:()=>''}),bindOriginal(){},focusOriginal(){},bindSplitPane:()=>()=>{},focusRequest(){},createEvidenceUpload:()=>({}),
  initialReviewSummary:()=>'',initialRequestContent:()=>({}),initialReady:()=>true,initialHistory(){},
  readInitialDecision:()=>structuredClone(decision),initialConfirmation:(_c,_i,_d,{busy})=>busy?'Guardando revisión…':'Confirmar',updateInitialConfirmation(){},pilotReviewControls:()=>''};
const source=(await fs.readFile(new URL('../src/pqrs_claro/static/recorrido/live.js',import.meta.url),'utf8')).replace(/^import .*;\r?\n/gm,'');
const {createLive}=await import('data:text/javascript;base64,'+Buffer.from('const {'+Object.keys(__deps).join(',')+'}=globalThis.__deps;\n'+source).toString('base64'));
const live=createLive({open(){},close(){},notice(){},releaseDemo(){},onBrowse(){},onPreanalysis:async(current,navigation)=>savedPreanalysis={current,navigation}});
const click=(action,index)=>listeners.click({target:{closest:()=>({dataset:{action,index}})}});
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

// Opening a list and reopening the manager's chosen petition are distinct operations.
record.id='focused-case';record.saved_stage=2;record.request_count=2;
record.identification.requests=[{id:'P1',title:'Primera',source_refs:[]},{id:'P2',title:'Segunda',source_refs:[]}];
const snapshotFor=id=>({request_id:id,mapping:{status:'ready',results:[{request_id:id,supports:[{source_id:'s',page:1,quote:'Cita '+id}]}]},drafts:{status:'idle'},review:{status:'ready',requests:[]}});
const opened=async(url)=>{location.href=new URL(url,'http://example.invalid/').href;delayReads();await live.select(record.id,{step:2});await tick();};
const closeCase=async()=>{finishReads();await tick();live.leave();};
const previewCalls=()=>calls.filter(c=>c.url.endsWith('/preview')).map(c=>c.url.split('/').at(-2));
job={status:'ready'};
await opened('?case=focused-case&step=2');
assert.equal(new URL(location.href).searchParams.has('request'),false);
assert.equal(stored.has('pqrs-response-focused-case'),false);
await closeCase();
await opened('?case=focused-case&step=2');click('live-sources','1');await tick();
assert.deepEqual(previewCalls(),[]);
reads.sources.resolve(snapshotFor('P2').mapping);await tick();
assert.match(view.innerHTML,/Cita P2/,'The normal projections still publish independently during a new opening');
assert.equal(new URL(location.href).searchParams.get('request'),'P2');
assert.deepEqual(JSON.parse(stored.get('pqrs-response-focused-case')),{id:'P2',version:record.version});
await closeCase();
console.log('PASS: fresh opening and selection during loading use only normal reads; automatic P1 is never remembered.');

previews.set('P2',deferred());const start=calls.length;
await opened('?view=cases');
assert.deepEqual(previewCalls(),['P2']);
assert.ok(!calls.slice(start).some(c=>c.url.endsWith('/drafts')));
previews.get('P2').resolve(snapshotFor('P2'));await tick();
assert.match(view.innerHTML,/Cita P2/);assert.match(view.innerHTML,/data-action="live-confirm-responses" disabled/);
assert.ok(calls.slice(start).some(c=>c.url.endsWith('/drafts')));
finishReads();await tick();delayReads();click('live-refresh');await tick();
assert.deepEqual(previewCalls(),['P2'],'Refreshing the same view must not spend a second preview');
await closeCase();
console.log('PASS: reopening a remembered petition prioritizes it once before the complete review.');

previews.set('P2',deferred());const startSwitch=calls.length;
await opened('?case=focused-case&step=2&request=P2');click('live-sources','0');await tick();
assert.ok(calls.slice(startSwitch).some(c=>c.url.endsWith('/drafts')),'Hydration does not wait for the abandoned preview');
assert.deepEqual(previewCalls(),['P2','P2']);
reads.sources.resolve(snapshotFor('P1').mapping);await tick();
previews.get('P2').resolve(snapshotFor('P2'));await tick();
assert.match(view.innerHTML,/Cita P1/);assert.doesNotMatch(view.innerHTML,/Cita P2/);
const oldLink=location.href;
assert.equal(new URL(oldLink).searchParams.get('request_version'),String(record.version));
await closeCase();
await opened('?view=cases');await closeCase();
assert.deepEqual(previewCalls(),['P2','P2','P1'],'A deliberately chosen P1 can be resumed');
console.log('PASS: changing selection cancels the preview, and the normal reads serve the new selection.');

record.version++;
await opened(oldLink);assert.equal(new URL(location.href).searchParams.has('request'),false);await closeCase();
await opened('?view=cases');await closeCase();
await opened('?case=focused-case&step=2&request=removed');await closeCase();
record.id='another-case';
await opened('?case=focused-case&step=2&request=P2');await closeCase();
assert.deepEqual(previewCalls(),['P2','P2','P1']);
console.log('PASS: stale versions, removed petitions, and other cases cannot select a preview.');

record.id='correction-case';
const publishVersion=(pending,version,staleReview=false)=>{
  pending.initial.resolve(intake);
  pending.sources.resolve({status:'ready',results:[{request_id:'P2',supports:[{source_id:'s',version,page:1,quote:'Cita versión '+version}]}]});
  pending.drafts.resolve({status:'idle',results:[]});
  pending.review.resolve({status:staleReview?'stale':'editing',stale:staleReview,requests:[{
    request_id:'P2',stale:staleReview,paragraphs:[],pending:[{id:'F',state:'confirmation_pending',kind:'fact',description:'Pendiente versión '+version}],
  }]});
};
const expectWaiting=()=>{
  assert.match(view.innerHTML,/data-redaction-correction="waiting"/);
  assert.doesNotMatch(view.innerHTML,/Cita versión|Pendiente versión|data-redaction-correction="updated"/);
  assert.equal(new URL(location.href).searchParams.get('request'),'P2');
};
job={status:'waiting_review'};
await opened('?view=cases');click('live-sources','1');publishVersion(reads,1);await tick();
assert.match(view.innerHTML,/Cita versión 1/);assert.match(view.innerHTML,/Pendiente versión 1/);
const lateReads=delayReads();click('live-refresh');await tick();
delayReads();sourceRevisions.correction_revision='c2';await windowEvents.focus();await tick();expectWaiting();
publishVersion(lateReads,1);await tick();expectWaiting();
publishVersion(reads,2,true);await tick();expectWaiting();
const previousHeavy=calls.filter(c=>c.url.endsWith('/sources?compact=true')).length;
await windowEvents.focus();await windowEvents.focus();await tick();
assert.equal(calls.filter(c=>c.url.endsWith('/sources?compact=true')).length,previousHeavy,'Stable checks must not read full projections');
delayReads();sourceRevisions.result_revision='r2';await windowEvents.focus();await tick();
assert.match(view.innerHTML,/Consultando las citas y los pendientes actualizados/);
assert.doesNotMatch(view.innerHTML,/Recalcular preparación/);
reads.review.promise.catch(()=>{});reads.review.reject(new Error('Fallo temporal'));
publishVersion(reads,2);await tick();expectWaiting();
assert.match(view.innerHTML,/Fallo temporal/);
const retry=[...scheduled.values()].find(({delay})=>delay===15000);
assert.ok(retry,'A transient projection failure must retry even after the terminal result signal was consumed');
delayReads();void retry.callback();await tick();publishVersion(reads,2);await tick();
assert.match(view.innerHTML,/data-redaction-correction="updated"/);
assert.match(view.innerHTML,/Cita versión 2/);assert.match(view.innerHTML,/Pendiente versión 2/);
assert.doesNotMatch(view.innerHTML,/Cita versión 1|Pendiente versión 1/);
assert.equal(new URL(location.href).searchParams.get('request'),'P2');
live.leave();
console.log('PASS: corrections hide late and mixed results; a terminal change recovers from a transient read error without losing the selection.');
