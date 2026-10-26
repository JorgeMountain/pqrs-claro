import test from 'node:test';
import assert from 'node:assert/strict';
import {sectionCases,sectionCounts,needsAttention,caseStep} from '../src/pqrs_claro/static/recorrido/inbox-navigation.js';

const base={status:'confirmed',initial_review_status:'approved',saved_stage:2,management:{owner_id:'ana',state:'in_progress'}};
const example=(id,overrides={})=>({...base,id,...overrides});
const cases=[
  example('writing'),
  example('review',{initial_review_status:'needs_review'}),
  example('worker',{processing:true,preparation:{status:'running'}}),
  example('needs-support',{preparation:{status:'waiting_review'}}),
  example('draft',{saved_stage:3,office_progress:{status:'ready'}}),
  example('old-draft',{initial_review_status:'idle',saved_stage:3}),
  example('closed',{saved_stage:3,management:{owner_id:'ana',state:'closed'}}),
  example('other',{saved_stage:3,management:{owner_id:'luis',state:'in_progress'}}),
  example('available',{status:'uploaded',management:{owner_id:null,state:'received'}}),
  example('deleted',{deleted_at:'2026-10-15'}),
];

test('each sidebar count matches its full view and respects the active manager',()=>{
  const before=JSON.stringify(cases),trash=[example('trash')];
  assert.deepEqual(sectionCounts(cases,trash,'ana'),{mine:6,active:8,pending:2,drafts:2,closed:1,trash:1});
  assert.deepEqual(sectionCounts(cases,trash,'luis'),{mine:1,active:8,pending:0,drafts:1,closed:0,trash:1});
  assert.deepEqual(sectionCases(cases,trash,'closed','ana').map(c=>c.id),['closed']);
  assert.deepEqual(sectionCases(cases,trash,'drafts','ana').map(c=>c.id),['draft','old-draft']);
  assert.equal(JSON.stringify(cases),before);
});

test('selecting a manager is required for personal views, not for the team pool',()=>{
  const counts=sectionCounts(cases,[],'');
  assert.equal(counts.mine,null);assert.equal(counts.pending,null);assert.equal(counts.drafts,null);assert.equal(counts.closed,null);
  assert.equal(counts.active,8);assert.equal(sectionCases(cases,[],'mine','').length,0);
});

test('a running task is never presented as an action for the manager',()=>{
  for(const override of [{processing:true},{preanalysis_status:'running'},{initial_review_status:'running'},
    {preparation:{status:'running'}},{office_progress:{status:'generating'}}]){
    assert.equal(needsAttention(example('busy',{initial_review_status:'needs_review',...override})),false);
  }
  assert.equal(needsAttention(example('complete',{office_progress:{status:'ready'},preparation:{status:'waiting_review'}})),false);
  assert.equal(needsAttention(example('error',{preparation:{status:'error'}})),true);
  assert.equal(needsAttention(example('routed',{initial_review_status:'routed'})),true);
});

test('borradores opens stored work even if old identification metadata is incomplete',()=>{
  const old=example('old',{initial_review_status:'needs_review',saved_stage:3});
  assert.equal(caseStep(old,'drafts'),3);
  assert.equal(caseStep(old,'pending'),1);
  assert.equal(caseStep(example('finished',{management:{owner_id:'ana',state:'closed'}}),'closed'),3);
});
