import test from 'node:test';
import assert from 'node:assert/strict';
import {initialConfirmation,initialRequestContent,readInitialDecision,identificationDetails,updateInitialConfirmation} from '../src/pqrs_claro/static/recorrido/initial-review.js';
import {identificationState,identificationWorkspace,expedienteStages,expedienteSteps,expedienteHeading} from '../src/pqrs_claro/static/recorrido/expediente-workspace.js';
import {confirmationPayload} from '../src/pqrs_claro/static/recorrido/initial-confirmation.js';

const check=key=>({key,state:'no_observation',summary:'Ejemplo',reason:'Ejemplo',original_refs:[],sources:[],pending:[]});
const petitions=Array.from({length:3},(_,i)=>({id:`P${i+1}`,label:String(i+1),title:`Petición ${i+1}`,description:'Contenido de prueba',source_refs:[{page:1}],original_marks:[]}));
const current={id:'demo',filename:'ejemplo.pdf',status:'needs_review',management:{owner_name:'José',reference:'PQRS-DEMO'},identification:{requests:petitions},requests:petitions,original_pages:[],original_url:'/original'};
const initial={revision:2,status:'needs_review',can_prepare:false,report:{document:{checks:[check('requirements'),check('respect')],proposed_route:'continue'},requests:petitions.map(r=>({request_id:r.id,petition_type:'information',proposed_route:'continue',checks:[{...check('repetition'),state:'unavailable'},check('classification')]})),special_treatment:{detected:false},warnings:[]}};

test('identificación integra tipo y contenido, y conserva todas las peticiones con una sola confirmación',()=>{
  const confirmation=initialConfirmation(current,initial,null,{workspace:true,suggestedReviewer:'José'});
  const html=identificationWorkspace(current,{}, {initial,confirmation,requestContent:initialRequestContent(current,initial,null,{workspace:true})});
  assert.deepEqual(expedienteStages,['Preanálisis','Identificación','Redacción','Borrador']);
  assert.equal((html.match(/type="checkbox"/g)||[]).length,1);
  assert.match(html,/He revisado todas las peticiones/);
  assert.match(html,/data-action="live-initial-confirm" disabled/);
  for(const r of petitions)assert.ok(html.includes(r.title));
  assert.doesNotMatch(html,/Analizar trámite|role="tab"|Confirma la revisión de esta petición/);
});

test('la casilla conjunta se traduce a las tres decisiones y conserva sus notas y tipos',()=>{
  const fields=new Map([['reviewed-all','on'],['reviewed_by','José'],['route-document','continue']]);
  for(let i=0;i<3;i++){fields.set(`route-${i}`,'continue');fields.set(`type-${i}`,i===1?'documents':'information');fields.set(`note-${i}`,i===1?'Conservar documentos solicitados.':'');}
  const original=globalThis.FormData;
  globalThis.FormData=class{constructor(form){assert.equal(form,fields);}get(k){return fields.get(k)??null;}has(k){return fields.has(k);}};
  try{
    const view={querySelector:()=>fields};
    const decision=readInitialDecision(view,current,initial);
    const payload=confirmationPayload(decision,initial.report);
    assert.equal(payload.document.reviewed,true);
    assert.deepEqual(payload.requests.map(r=>r.reviewed),[true,true,true]);
    assert.equal(payload.requests[1].petition_type,'documents');
    assert.equal(payload.requests[1].note,'Conservar documentos solicitados.');
    fields.delete('reviewed-all');
    assert.throws(()=>confirmationPayload(readInitialDecision(view,current,initial),initial.report),/Confirma/);
  }finally{globalThis.FormData=original;}
});

test('el resumen de identificación no repite verificaciones ni fuentes de expedientes antiguos',()=>{
  for(const analysis_scope of [undefined,'petition_types_v1']){
    const value={...initial,analysis_scope,scope:{readable_sources:19065}};
    const before=JSON.stringify(value);
    const html=identificationDetails(current,value);
    assert.match(html,/<strong>3<\/strong> Información/);
    assert.match(html,/Ver preanálisis/);
    assert.match(html,/Ver historial/);
    assert.doesNotMatch(html,/Datos y requisitos|Lenguaje y atribución|Fuentes de consulta|19065|Reanalizar todo|Sin observaciones preliminares/);
    assert.equal(JSON.stringify(value),before);
  }
});

test('las opciones generales conservan las rutas alternativas, comunicaciones y observaciones guardadas',()=>{
  const form={case_id:current.id,revision:initial.revision,document:{route:'specialist',note:'Revisión especializada conservada.',communication:'Texto conservado'},requests:initial.report.requests.map(r=>({...r,petition_type:'documents'}))};
  const value={...initial,report:{...initial.report,document:{...initial.report.document,draft:'Texto original'}}};
  const html=identificationDetails(current,value,form);
  assert.match(html,/<strong>3<\/strong> Documentos/);
  assert.match(html,/value="specialist" selected/);
  assert.match(html,/form="initial-decision-form" name="route-document"/);
  assert.match(html,/Revisión especializada conservada/);
  assert.match(html,/Texto conservado/);
  assert.doesNotMatch(initialConfirmation(current,value,form,{workspace:true}),/data-action="live-initial-route" hidden/);
});

test('las notas guardadas permanecen visibles aunque las observaciones vacías se desplieguen a petición',()=>{
  const draft={case_id:current.id,revision:initial.revision,requests:[{request_id:'P1',petition_type:'information',note:'Conservar esta aclaración.'}]};
  const content=initialRequestContent(current,initial,draft,{workspace:true});
  assert.match(content.P1.notes,/<details[^>]* open>/);
  assert.match(content.P1.notes,/Conservar esta aclaración/);
  assert.doesNotMatch(content.P2.notes,/<details[^>]* open>/);
  assert.match(content.P2.notes,/form="initial-decision-form" name="note-1"/);
});

test('el resumen de tipos se actualiza al corregir una clasificación sin confirmar la revisión',()=>{
  const counts={innerHTML:''},button={},status={};
  const elements=new Map([['[data-identification-types]',counts],['#initial-decision-form',{dataset:{workspace:'true'}}],['[data-action="live-initial-confirm"]',button],['[data-global-review]',status]]);
  const view={querySelector:selector=>elements.get(selector),getAttribute:()=>null};
  const decision={reviewed_by:'José',document:{route:'continue',reviewed:false},requests:initial.report.requests.map((r,i)=>({...r,route:'continue',reviewed:false,petition_type:i?'documents':'information'}))};
  updateInitialConfirmation(view,initial,decision);
  assert.match(counts.innerHTML,/<strong>2<\/strong> Documentos/);
  assert.match(counts.innerHTML,/<strong>1<\/strong> Información/);
  assert.equal(button.disabled,true);
  assert.match(status.textContent,/Confirma la revisión/);
});

test('explica la ruta general que bloquea aunque todas las peticiones permitan continuar',()=>{
  const value={...initial,report:{...initial.report,document:{...initial.report.document,proposed_route:'reject'}}};
  const before=JSON.stringify(value);
  const html=initialConfirmation(current,value,null,{workspace:true,suggestedReviewer:'José'});
  assert.match(html,/Las 3 peticiones están en «Continuar a redacción». Falta revisar la ruta general/);
  assert.match(html,/Ruta general del expediente/);
  assert.match(html,/Revisar propuesta de rechazo/);
  assert.match(html,/data-action="live-initial-route-edit" data-route-key="document"/);
  assert.match(html,/data-action="live-initial-confirm" disabled/);
  assert.equal(JSON.stringify(value),before);
});

test('la corrección explícita de la ruta actualiza el bloqueo sin marcar la revisión humana',()=>{
  const value={...initial,report:{...initial.report,document:{...initial.report.document,proposed_route:'reject'}}};
  const message={},button={},alternative={};
  const elements=new Map([['[data-confirmation-message]',message],['[data-action="live-initial-confirm"]',button],['[data-action="live-initial-route"]',alternative],['#initial-decision-form',{dataset:{workspace:'true'}}]]);
  const view={querySelector:selector=>elements.get(selector),getAttribute:()=>null};
  const decision={reviewed_by:'José',document:{route:'reject',reviewed:false},requests:initial.report.requests.map(r=>({...r,route:'continue',reviewed:false}))};
  updateInitialConfirmation(view,value,decision);
  assert.equal(message.hidden,false);assert.match(message.innerHTML,/Revisar propuesta de rechazo/);
  decision.document.route='continue';
  updateInitialConfirmation(view,value,decision);
  assert.equal(message.hidden,true);assert.equal(alternative.hidden,true);
  assert.equal(button.disabled,true);assert.equal(decision.document.reviewed,false);
  decision.document.reviewed=true;decision.requests.forEach(r=>r.reviewed=true);
  updateInitialConfirmation(view,value,decision);
  assert.equal(button.disabled,false);
  assert.equal(value.report.document.proposed_route,'reject');
});

test('las rutas guardadas prevalecen sobre las propuestas y el aviso identifica la petición pendiente',()=>{
  const value={...initial,report:{...initial.report,document:{...initial.report.document,proposed_route:'reject'}},document_decision:{route:'continue',reviewed:true},decisions:initial.report.requests.map((r,i)=>({...r,route:i===1?'specialist':'continue',reviewed:true})).reverse(),reviewed_by:'José'};
  const html=initialConfirmation(current,value,null,{workspace:true});
  assert.match(html,/data-action="live-initial-route-edit" data-route-key="1"/);
  assert.match(html,/Remitir a revisión especializada/);
  assert.doesNotMatch(html,/data-route-key="document"|Falta revisar la ruta general/);
  assert.match(html,/data-action="live-initial-confirm" disabled/);
});

test('los resultados conservados no habilitan confirmación durante un reintento',()=>{
  const processing={...current,status:'identifying',analysis_running:true};
  assert.equal(identificationState(processing,initial).tone,'processing');
  const html=identificationWorkspace(processing,{}, {initial,confirmation:'<button>Confirmación no disponible</button>'});
  assert.doesNotMatch(html,/Confirmación no disponible/);
  assert.match(html,/Identificación en curso/);
  assert.equal(identificationState({...current,error:'Fallo simulado'},initial).tone,'error');
});

test('el análisis del contenido sigue dentro de Identificación y ofrece recuperación de errores',()=>{
  assert.equal(identificationState(current,{status:'running'}).label,'Identificando');
  assert.match(identificationState(current,{status:'running'}).text,/contenido y el tipo/);
  assert.equal(identificationState(current,{status:'idle'}).actionLabel,'Revisar contenido y tipos');
  assert.equal(identificationState(current,{status:'idle'}).label,'Identificación guardada');
  assert.match(identificationState(current,{status:'idle'}).text,/no vuelve a extraer/);
  assert.equal(identificationState(current,{status:'interrupted'}).actionLabel,'Reintentar pendientes');
});

test('visitar Borrador no da por terminada una redacción sin respuestas',()=>{
  const waiting=expedienteSteps(3,{canContinue:true}),prepared=expedienteSteps(3,{canContinue:true,redactionComplete:true});
  assert.match(waiting,/<strong>Redacción<\/strong><small>Por completar/);
  assert.doesNotMatch(waiting,/class="complete stage-2"/);
  assert.match(waiting,/<strong>Borrador<\/strong><small>En revisión/);
  assert.match(prepared,/<strong>Redacción<\/strong><small>Preparada/);
  assert.match(prepared,/class="complete stage-2"/);
  assert.doesNotMatch(prepared,/class="complete stage-3"|Versión generada/);
});

test('la versión generada completa Borrador sin confundir la etapa actual con una aprobación nueva',()=>{
  const html=expedienteHeading(current,3,{canContinue:true,redactionComplete:true,draftComplete:true,activeLabel:'En revisión'});
  assert.match(html,/class="complete stage-3" aria-current="step"/);
  assert.match(html,/<strong>Borrador<\/strong><small>Versión generada/);
  assert.match(html,/data-action="live-final"/);
  assert.equal((html.match(/aria-current="step"/g)||[]).length,1);
  const incomplete=expedienteSteps(3,{draftComplete:true});
  assert.match(incomplete,/<strong>Redacción<\/strong><small>Por completar/);
  assert.doesNotMatch(incomplete,/class="complete stage-2"/);
});

test('los estados de las etapas anteriores y las etiquetas activas conservan su contrato',()=>{
  const identifying=expedienteSteps(1,{reviewing:true});
  assert.match(identifying,/<strong>Preanálisis<\/strong><small>Completado/);
  assert.match(identifying,/<strong>Identificación<\/strong><small>Tu revisión/);
  assert.match(identifying,/<strong>Redacción<\/strong><small>Pendiente/);
  const writing=expedienteSteps(2,{canContinue:true,activeLabel:'En preparación'});
  assert.match(writing,/<strong>Redacción<\/strong><small>En preparación/);
  assert.match(writing,/<strong>Borrador<\/strong><small>Pendiente/);
  assert.doesNotMatch(expedienteSteps(2,{draftComplete:true}),/Versión generada/);
  assert.match(expedienteSteps(3,{activeLabel:'Comprobando <respuestas>'}),/<strong>Borrador<\/strong><small>Comprobando &lt;respuestas&gt;/);
});


test('consultar una etapa anterior conserva las etapas completadas y cuatro controles accesibles',()=>{
  const html=expedienteSteps(0,{activeLabel:'Consulta guardada',navigation:{available:[true,true,true,true],completed:[true,true,true,false],labels:['','','','Guardado']}});
  assert.equal((html.match(/data-action="live-/g)||[]).length,4);
  assert.match(html,/data-action="live-preanalysis"/);
  assert.match(html,/<strong>Identificación<\/strong><small>Completado/);
  assert.match(html,/<strong>Redacción<\/strong><small>Completado/);
  assert.match(html,/<strong>Borrador<\/strong><small>Guardado/);
  assert.equal((html.match(/aria-current="step"/g)||[]).length,1);
});

test('recuperar resultados guardados no se presenta como otra identificación con IA',()=>{
  const progress=identificationState(current,{});
  assert.equal(progress.tone,'loading');assert.match(progress.label,/guardada/);
  const html=identificationWorkspace(current,{},{});
  assert.doesNotMatch(html,/Identificación en curso|Tipo de petición pendiente de identificar/);
  assert.match(html,/Cargando el tipo de petición guardado/);
  assert.equal(identificationState(current,{loadError:'Falló la consulta'}).action,'live-refresh');
});
