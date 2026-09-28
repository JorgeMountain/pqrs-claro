import test from 'node:test';
import assert from 'node:assert/strict';
import {status} from '../src/pqrs_claro/static/recorrido/case-browser-views.js';
import {cards} from '../src/pqrs_claro/static/recorrido/management-ui.js';
test('un expediente finalizado se consulta y no aumenta pendientes de revisión',()=>{
 const item={id:'qa',status:'needs_review',subject:'Ficticio',management:{state:'closed',owner_id:'m',started_at:'2026-09-28',updated_at:'2026-09-28',received_date:'2026-09-28'}};
 assert.equal(status(item)[1],'Finalizada');assert.notEqual(status(item)[0],'review');assert.match(cards([item]),/>Consultar<\/button>/);
});
