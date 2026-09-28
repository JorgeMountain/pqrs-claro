import test from 'node:test';
import assert from 'node:assert/strict';
import {draftEnvelope,restoreDraft,createReviewDraftStore,draftPreview} from '../src/pqrs_claro/static/recorrido/review-drafts.js';
const fixture=()=>{
 const current={id:'qa-drafts',sha256:'hash',identification:{requests:['P1','P2'].map(id=>({id,title:id,description:'Texto '+id,parent_id:null}))}};
 const value={revision:1,fingerprint:'generation1',status:'needs_review',report:{document:{proposed_route:'continue'},requests:['P1','P2'].map(request_id=>({request_id,petition_type:'information'}))}};
 const decision={case_id:current.id,revision:1,reviewed_by:'',document:{route:'continue',note:'Nota humana',reviewed:true},requests:['P1','P2'].map(request_id=>({request_id,petition_type:'documents',note:'Corrección '+request_id,reviewed:true}))};
 return {current,value,decision};
};
const storage=()=>{const map=new Map();return {getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)}};
test('guarda borrador incompleto y lo recupera sin aprobar automáticamente',()=>{
 const {current,value,decision}=fixture(),s=storage();createReviewDraftStore(s).write(current,value,decision);
 const draft=restoreDraft(createReviewDraftStore(s).read(current.id),current,value).draft;
 assert.equal(draft.document.note,'Nota humana');assert.equal(draft.reviewed_by,'');assert.equal(draft.document.reviewed,false);assert.ok(draft.requests.every(r=>!r.reviewed));
});
test('descartar, editar la restante y deshacer conserva correcciones por ID',()=>{
 const {current,value,decision}=fixture(),store=createReviewDraftStore(storage());let saved=store.write(current,value,decision);
 const subset=structuredClone(current);subset.identification.requests=subset.identification.requests.slice(1);
 const selected={...value,revision:2,fingerprint:'subset',selection_basis:{fingerprint:value.fingerprint},report:{...value.report,requests:value.report.requests.slice(1)}};
 const draft=restoreDraft(saved,subset,selected).draft;assert.equal(draft.requests[0].request_id,'P2');draft.requests[0].note='Segunda editada';saved=store.write(subset,selected,draft);
 const undo={...value,revision:3,selection_basis:{fingerprint:value.fingerprint}};
 const restored=restoreDraft(saved,current,undo).draft;
 assert.deepEqual(restored.requests.map(r=>r.note),['Corrección P1','Segunda editada']);assert.equal(restored.revision,3);
});
for(const change of ['revision','fingerprint','document','request','text','stale','hash'])test('no aplica silenciosamente un borrador incompatible: '+change,()=>{
 const {current,value,decision}=fixture(),saved=draftEnvelope(current,value,decision);
 if(change==='revision')value.revision++;
 if(change==='fingerprint')value.fingerprint='nuevo';
 if(change==='document')value.report.document.proposed_route='specialist';
 if(change==='request')value.report.requests[0].petition_type='complaint';
 if(change==='text')current.identification.requests[0].description='Otro texto';
 if(change==='stale')value.stale=true;
 if(change==='hash')current.sha256='otro';
 assert.equal(restoreDraft(saved,current,value).conflict,true);assert.equal(saved.decision.document.note,'Nota humana');
});
test('reordenar y reconectar un hijo mantiene las correcciones asociadas',()=>{
 const {current,value,decision}=fixture(),saved=draftEnvelope(current,value,decision);
 current.identification.requests[1].parent_id='P1';value.report.requests.reverse();
 assert.deepEqual(restoreDraft(saved,current,value).draft.requests.map(r=>r.note),['Corrección P2','Corrección P1']);
});
test('dos pestañas no sobrescriben ni borran el borrador ajeno',()=>{
 const {current,value,decision}=fixture(),s=storage(),a=createReviewDraftStore(s),b=createReviewDraftStore(s);a.read(current.id);b.read(current.id);a.write(current,value,decision);
 assert.throws(()=>b.write(current,value,decision),/Otra pestaña/);b.clear(current.id);assert.equal(a.read(current.id).decision.document.note,'Nota humana');
});
test('fallo de almacenamiento se propaga sin perder la copia anterior',()=>{
 const {current,value,decision}=fixture(),s=storage(),store=createReviewDraftStore(s);store.write(current,value,decision);s.setItem=()=>{throw Error('QuotaExceededError')};
 decision.document.note='Nueva nota';assert.throws(()=>store.write(current,value,decision),/Quota/);assert.equal(store.read(current.id).decision.document.note,'Nota humana');
});
test('separa expedientes y escapa el contenido del borrador',()=>{
 const {current,value,decision}=fixture(),store=createReviewDraftStore(storage());decision.document.note='<script>alert(1)</script>';const saved=store.write(current,value,decision);
 assert.equal(store.read('otro'),null);assert.equal(restoreDraft(saved,{...current,id:'otro'},value).draft,null);assert.ok(!draftPreview(saved).includes('<script>'));
});
