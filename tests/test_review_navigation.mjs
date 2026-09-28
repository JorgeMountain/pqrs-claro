import test from 'node:test';
import assert from 'node:assert/strict';
import {reviewItems,nextReviewIndex,reviewNavigation,reviewRoute,suggestedReviewer} from '../src/pqrs_claro/static/recorrido/review-navigation.js';
import {initialConfirmation} from '../src/pqrs_claro/static/recorrido/initial-review.js';

const current={id:'ficticio',identification:{requests:Array.from({length:30},(_,i)=>({id:`P${i+1}`,label:String(i+1),title:`Petición ${i+1}`}))}};
const value={revision:2,status:'needs_review',can_prepare:false,report:{document:{proposed_route:'continue'},requests:current.identification.requests.map(r=>({request_id:r.id,petition_type:'information',proposed_route:'continue',checks:[{key:'repetition',state:'unavailable'}]}))}};

test('índice largo conserva todas las peticiones sin convertir antecedentes no disponibles en alerta',()=>{
  const items=reviewItems(current,value);
  assert.equal(items.length,30);assert.equal(items.filter(r=>r.attention).length,0);
  assert.equal(nextReviewIndex(items,28),29);assert.equal(nextReviewIndex(items,29),0);
  const html=reviewNavigation(current,value);
  assert.match(html,/Petición 30/);assert.match(html,/0 con observaciones/);
});
test('siguiente recorre observaciones y no las da por resueltas al visitarlas',()=>{
  const flagged=structuredClone(value);flagged.report.requests[12].checks.push({state:'attention'});
  flagged.report.requests[24].petition_type='undetermined';
  const items=reviewItems(current,flagged);
  assert.equal(nextReviewIndex(items),12);assert.equal(nextReviewIndex(items,12),24);
  assert.equal(nextReviewIndex(items,24),12);assert.equal(items[12].state,'Con observaciones');
});
test('ruta muestra decisión humana y alternativa de una petición',()=>{
  const draft={document:{route:'specialist'},requests:[]};
  assert.match(reviewRoute(value,draft),/especializada/);
  assert.match(reviewRoute(value,{document:{route:'continue'},requests:[{route:'specialist'}]}),/ruta alternativa/);
  assert.match(reviewRoute({...value,stale:true}),/análisis vigente/);
});
test('cierre y análisis pendiente conservan navegación sin ofrecer guardado o confirmación',()=>{
  for(const [record,review] of [[{...current,management:{state:'closed'}},value],[current,{...value,status:'running'}]]){
    const html=reviewNavigation(record,review);
    assert.match(html,/Ir a petición/);assert.doesNotMatch(html,/live-initial-save|live-review-confirm/);
  }
});
test('gestor sugerido no reemplaza nombre guardado ni confirma revisión',()=>{
  const name=suggestedReviewer([{id:'g1',name:'Gestora ficticia'}],'g1');
  assert.equal(name,'Gestora ficticia');assert.equal(suggestedReviewer([],'g1'),'');
  const html=initialConfirmation(current,value,null,{suggestedReviewer:name});
  assert.match(html,/value="Gestora ficticia"/);assert.doesNotMatch(html,/name="reviewed-all"[^>]*checked/);
  assert.match(initialConfirmation(current,{...value,reviewed_by:'Nombre registrado'},null,{suggestedReviewer:name}),/value="Nombre registrado"/);
});
test('índice escapa títulos y no pierde la selección al volver a renderizar',()=>{
  const record={...current,identification:{requests:[{id:'P1',label:'1',title:'<script>ejemplo</script>'}]}};
  const html=reviewNavigation(record,value,null,{cursor:0});
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
  assert.match(html,/value="0" selected/);
});
