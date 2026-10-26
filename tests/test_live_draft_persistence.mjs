// Audit-only harness: executes the current live.js with DOM/render/API adapters.
// No network, files/cases, or model requests are changed.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import * as navigationTools from '../src/pqrs_claro/static/recorrido/review-navigation.js';
import * as draftTools from '../src/pqrs_claro/static/recorrido/review-drafts.js';
const stored=new Map();globalThis.localStorage={getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};globalThis.window={addEventListener(){}};
process.on('uncaughtException',error=>{console.error(error.message);process.exitCode=1;});

const listeners={}, rendered=[],workspaceRendered=[];
const blank=()=>({innerHTML:'',textContent:'',hidden:false,disabled:false,checked:false,dataset:{},
  classList:{add(){},remove(){}},setAttribute(){},removeAttribute(){},focus(){},
  querySelector:()=>null,querySelectorAll:()=>[],addEventListener(){}});
const nodes=new Map();
const node=key=>{if(!nodes.has(key))nodes.set(key,blank());return nodes.get(key);};
const view={...blank(),insertAdjacentHTML(){},addEventListener:(kind,fn)=>{listeners[kind]=fn;},
  querySelector:key=>key==='#initial-decision-form'?null:node('view:'+key)};
globalThis.document={querySelector:key=>key==='#view'?view:node(key),querySelectorAll:()=>[],activeElement:null};
globalThis.location={href:'http://example.invalid/',pathname:'/'};
globalThis.history={replaceState:(_a,_b,url)=>{location.href=new URL(url,location.href).href;}};
globalThis.clearTimeout=()=>{};
globalThis.setTimeout=()=>{throw new Error('Unexpected polling');};
let pendingDecision;
const record={id:'audit-case',version:1,status:'needs_review',pages:[],identification:{requests:[{id:'P1',source_refs:[]}]} };
const intake={revision:1,status:'needs_review',report:{document:{},requests:[{request_id:'P1'}]},can_prepare:false};
const calls=[];
globalThis.fetch=async (url,options)=>{assert.ok(!options?.method,'Draft actions must not call mutation APIs');
  calls.push(url);
  const data=url==='/api/config'?{initial_review_enabled:true,automatic_initial_review:true}:
    url.endsWith('/initial-review?compact=true')?intake:record;
  return {ok:true,json:async()=>structuredClone(data)};
};
let afterIdentificationSave;
globalThis.__deps={captureRedactionView:()=>null,restoreRedactionView(){},...draftTools,...navigationTools,pilotReviewControls:()=>'',
  identificationWorkspace:data=>{workspaceRendered.push(structuredClone(data));return '';},bindIdentificationWorkspace:()=>()=>{},expedienteHeading:()=>'',
  createFinal:()=>({setCase(){},hide(){}}),renderAnalysis(){},esc:x=>x,renderCaseNavigation(){},
  createProposalPanel:()=>({}),createPendingActions:()=>({}),createResponseEditor:()=>({hasChanges:()=>false}),
  identification:()=>'',responses:()=>'',supports:()=>'',
  createIdentificationActions:opts=>{afterIdentificationSave=opts.onSaved;return {banner:()=>''};},
  bindOriginal(){},focusOriginal(){},bindSplitPane:()=>()=>{},focusRequest(){},createEvidenceUpload:()=>({}),
  initialReviewSummary:(_c,_i,draft)=>{rendered.push(structuredClone(draft));return '';},
  initialRequestContent:()=>({}),initialReady:()=>false,initialHistory(){},
  readInitialDecision:()=>structuredClone(pendingDecision),initialConfirmation:()=>'',updateInitialConfirmation(){},confirmAndPrepare(){}
};
const source=await fs.readFile(new URL('../src/pqrs_claro/static/recorrido/live.js',import.meta.url),'utf8');
const executable=source.replace(/^import .*;\r?\n/gm,'');
const {createLive}=await import('data:text/javascript;base64,'+Buffer.from('const {'+Object.keys(__deps).join(',')+'}=globalThis.__deps;\n'+executable).toString('base64'));
const live=createLive({open(){},close(){},notice(){},releaseDemo(){},onBrowse(){}});
// select now paints immediately; drain the mocked background reads before assertions.
const select=async id=>{await live.select(id);await new Promise(setImmediate);};
const edit=()=>{
  pendingDecision={case_id:record.id,revision:1,reviewed_by:'Gestor ficticio',document:{route:'specialist',note:'Nota escrita por el gestor',reviewed:false},requests:[{request_id:'P1',petition_type:'documents',note:'Corrección humana',route:'continue',reviewed:false}]};
  listeners.input({target:{form:{id:'initial-decision-form'},name:'note-document'}});
  live.go(1);
  assert.equal(rendered.at(-1).document.note,'Nota escrita por el gestor');
};
await select(record.id);
edit();
await afterIdentificationSave(record.id); // Actual callback used after discard/restore.
await new Promise(setImmediate);
assert.equal(rendered.at(-1).document.note,'Nota escrita por el gestor');assert.equal(rendered.at(-1).requests[0].petition_type,'documents');
console.log('PASS: discard/restore callback preserves draft types, routes and notes.');
edit();
live.leave();
await select(record.id);
assert.equal(rendered.at(-1).document.note,'Nota escrita por el gestor');assert.equal(rendered.at(-1).requests[0].petition_type,'documents');
console.log('PASS: leaving for queue and reopening preserves draft review.');
assert.ok(calls.every(path=>path==='/api/config'||path.startsWith('/api/cases/audit-case')));
console.log('All API responses mocked; zero real network or model calls.');

record.management={owner_id:'gestor',owner_name:'Gestor',started_at:'2026-10-13'};
let caseReads=0;
globalThis.fetch=async(url,options)=>{
  assert.ok(!options?.method);
  const data=url.endsWith('/initial-review?compact=true')?intake:{...record,analysis_running:++caseReads===1};
  return {ok:true,json:async()=>structuredClone(data)};
};
await select(record.id);
assert.equal(workspaceRendered[0].analysis_running,true);
assert.equal(workspaceRendered.at(-1).analysis_running,false);
assert.equal(workspaceRendered[0].version,workspaceRendered.at(-1).version);
console.log('PASS: finished analysis clears its running state without a case version change.');
