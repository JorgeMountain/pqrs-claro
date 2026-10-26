import test from 'node:test';
import assert from 'node:assert/strict';
import {responseReading} from '../src/pqrs_claro/static/recorrido/response-reading.js';
import {redactionWorkspace,redactionRows} from '../src/pqrs_claro/static/recorrido/redaction-workspace.js';

const current={id:'reading-demo',filename:'prueba.pdf',identification:{requests:[{id:'P1',title:'Consulta',description:'Una pregunta.'}]}};
const review={requests:[{request_id:'P1',paragraphs:[{text:'Respuesta guardada.'}],pending:[]}],reading_confirmation:{eligible:true,confirmed:false}};
test('one collective control, pending confirmation blocks only the continue action',()=>{
  const html=redactionWorkspace(current,{status:'ready'},{status:'ready'},{status:'ready'},review,{reviewer:'Prueba'});
  assert.equal((html.match(/data-action="live-confirm-responses"/g)||[]).length,1);
  assert.match(html,/data-action="live-continue-draft" disabled/);
  assert.match(html,/Ya revisé todas las respuestas/);
  assert.doesNotMatch(html,/id="response-reading-actor"/);
});
test('saved acknowledgment changes labels and enables continue without calling it approval',()=>{
  const confirmed={...review,reading_confirmation:{eligible:true,confirmed:true,reviewed_by:'Gestora <QA>'}};
  const html=redactionWorkspace(current,{status:'ready'},{status:'ready'},{status:'ready'},confirmed);
  assert.doesNotMatch(html,/data-action="live-confirm-responses"|data-action="live-continue-draft" disabled/);
  assert.match(html,/Gestora &lt;QA&gt;/);
  assert.equal(redactionRows(current,{},{},{},confirmed)[0].label,'Revisión guardada');
  assert.doesNotMatch(html,/Respuesta aprobada/);
});
test('incomplete, changed, saving and failed states remain explicit',()=>{
  assert.match(responseReading({}),/data-action="live-confirm-responses" disabled/);
  assert.match(responseReading({...review,reading_confirmation:{eligible:true,changed_since_confirmation:true}}),/El contenido cambió/);
  assert.match(responseReading(review,{busy:true}),/Guardando revisión/);
  assert.match(responseReading(review,{error:'No se pudo guardar.'}),/role="alert">No se pudo guardar/);
  assert.match(responseReading(review),/id="response-reading-actor"/);
});
