import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {esc} from '../src/pqrs_claro/static/recorrido/views.js';
import {deriveDraftReview,draftReviewMarkup} from '../src/pqrs_claro/static/recorrido/draft-review.js';
import {draftSettings} from '../src/pqrs_claro/static/recorrido/draft-settings.js';
import {draftProgress} from '../src/pqrs_claro/static/recorrido/stage-progress.js';

let actor='José',manager='gestor-1';
const deps={esc,managementActor:()=>manager,sessionActor:()=>actor,bindActor:form=>form.querySelector('#office-actor').addEventListener('change',event=>{actor=event.target.value;}),
  createDocumentTools:()=>({refresh(){},record(){},bindSheet(){},destroy(){}}),toolsMarkup:()=>'',
  paginate(root,blocks){root.blocks=blocks.map((block,index)=>Object.assign(element(),{dataset:{block:String(index)},textContent:block.text}));},
  fragmentText:el=>el.textContent,selectionPoint:()=>null,focusPoint(){},deriveDraftReview,draftReviewMarkup,draftSettings,draftProgress,
  createDraftFragment:()=>({clear(){},show:()=>true}),icon:()=>''};
globalThis.__documentFlowDeps=deps;
const source=(await fs.readFile(new URL('../src/pqrs_claro/static/recorrido/live-document.js',import.meta.url),'utf8')).replace(/^import .*;\r?\n/gm,'');
const {createFinal}=await import('data:text/javascript;base64,'+Buffer.from('const {'+Object.keys(deps).join(',')+'}=globalThis.__documentFlowDeps;\n'+source).toString('base64'));

function element(){return {textContent:'',innerHTML:'',value:'',disabled:false,checked:false,hidden:false,childNodes:[],dataset:{},listeners:{},
  classList:{toggle(){},add(){},remove(){}},focus(){},scrollIntoView(){},after(){},setAttribute(){},removeAttribute(){},
  addEventListener(kind,fn){(this.listeners[kind]??=[]).push(fn);},dispatchEvent(event){for(const fn of this.listeners[event.type]||[])fn({target:this});},
  replaceChildren(){this.innerHTML='';},querySelector(){return null;},querySelectorAll(){return [];}};}

function rootElement(){
  const root=element();root.fields=new Map();root.blocks=[];
  Object.defineProperty(root,'innerHTML',{get(){return this.html||'';},set(html){
    this.html=html;this.childNodes=[{}];this.fields=new Map();
    for(const key of ['data-draft-progress','data-save-state','data-downloads','data-adjustments','data-checks','data-operation','data-error','data-review-status','data-confirm-office','data-confirm-label','data-confirm-hint','data-generate-hint','data-clear-fragment','data-reload'])this.fields.set('['+key+']',element());
    this.fields.set('.draft-editor-heading',element());this.fields.set('.document-tool-status',element());
    this.commands=['save','cancel','generate','finalize'].map(command=>Object.assign(element(),{dataset:{command}}));
    this.metas=[...html.matchAll(/data-meta="([^"]+)"[^>]*value="([^"]*)"/g)].map(match=>Object.assign(element(),{dataset:{meta:match[1]},value:match[2]}));
    this.actor=element();this.actor.value=html.match(/id="office-actor"[^>]*value="([^"]*)"/)?.[1]||'';
    this.form=element();this.form.querySelector=query=>query==='#office-actor'?this.actor:null;
    this.details=element();
  }});
  root.querySelector=function(query){
    if(query==='form')return this.form;if(query==='#office-actor')return this.actor;
    if(query==='.document-settings details'||query==='[data-responsible-details]')return this.details;
    const meta=query.match(/^\[data-meta="(.+)"\]$/);if(meta)return this.metas.find(item=>item.dataset.meta===meta[1])||null;
    if(query.startsWith('[data-command='))return this.commands.find(item=>query.includes('"'+item.dataset.command+'"'));
    return this.fields.get(query)||null;
  };
  root.querySelectorAll=function(query){
    if(query==='[data-command]')return this.commands;
    if(query==='[data-meta]')return this.metas;
    if(query==='[data-block]'||query==='[contenteditable]')return this.blocks;
    const block=query.match(/^\[data-block="(\d+)"\]$/);if(block)return this.blocks.filter(item=>item.dataset.block===block[1]);
    if(query==='input:not([data-confirm-office])')return [...this.metas,this.actor];
    return [];
  };
  return root;
}

const initialWork=()=>({case_id:'qa',revision:1,metadata:{city:'Medellín',issue_date:'2026-10-14',recipient:'Destinataria ficticia',subject:'Asunto ficticio',signer_name:'Firmante ficticio',signer_role:'Gestor'},
  attachment_source_ids:[],attachment_options:[],letterhead:null,blocks:[{kind:'subject',text:'Asunto ficticio'}],
  requests:[{case_id:'qa',request_id:'P1',label:'1',title:'Consulta ficticia',revision:1,status:'ready',stale:false,error:null,
    paragraphs:[{text:'Respuesta respaldada de ejemplo.',cited_chunk_ids:[],cited_fact_ids:[]}],assessment:{status:'passed',input_hash:'h',issues:[]},approval:null}]});
async function settle(predicate){for(let i=0;i<80;i++){if(predicate())return;await new Promise(resolve=>setImmediate(resolve));}assert.fail('El controlador no terminó la operación esperada');}
async function harness({actorName='José',managerId='gestor-1',savedWork=initialWork(),savedRun=null,previewHash='p',previewError=null,onPreview=null,onOffice=null,onClose=null,onApprove=null,onGenerate=null}={}){
  actor=actorName;manager=managerId;let work=structuredClone(savedWork),latest=structuredClone(savedRun),failPut=false,failGet=false,failClose=false,externalChanges=false;
  const serverCase={id:'qa',request_count:savedWork.requests.length,processing:false,management:{state:'in_progress',revision:2,owner_id:'gestor-1',started_at:'today'}};
  let current=structuredClone(serverCase);
  const calls=[],notices=[],summaries=[],finalizations=[],root=rootElement();
  const windowEvents={};globalThis.window={addEventListener(name,callback){windowEvents[name]=callback;}};globalThis.document={createElement:()=>root,activeElement:null};
  globalThis.fetch=async(url,options={})=>{
    const method=options.method||'GET',body=options.body?JSON.parse(options.body):null;calls.push({url,method,body});
    const ok=value=>({ok:true,json:async()=>structuredClone(value)});
    if(url==='/api/cases/qa')return ok(serverCase);
    if(url.endsWith('/management')){
      await onClose?.();if(failClose)throw new Error('No se pudo finalizar; el avance sigue guardado');
      serverCase.management={...serverCase.management,revision:body.revision+1,state:body.state};return ok(serverCase.management);
    }
    if(url.endsWith('/workspace')){
      if(method==='GET'){if(failGet)throw new Error('No se pudo recuperar el borrador');return ok(work);}
      if(failPut)throw new Error('No se pudo guardar el borrador');
      work={...work,revision:work.revision+1,metadata:body.metadata,requests:body.requests.map(row=>({...work.requests.find(r=>r.request_id===row.request_id),...row,status:'editing'}))};
      return ok(work);
    }
    if(url.endsWith('/assess')){work.requests[0].status='ready';return ok(work.requests[0]);}
    if(url.endsWith('/approve')){const row=work.requests.find(row=>url.includes('/'+encodeURIComponent(row.request_id)+'/approve'));await onApprove?.(row.request_id,root);row.status='approved';return ok(row);}
    if(url.endsWith('/review'))return ok({requests:work.requests});
    if(url.endsWith('/preview')){onPreview?.(root);if(previewError)throw new Error(previewError);return ok({preview_hash:previewHash});}
    if(url.endsWith('/generate')){await onGenerate?.(root);latest={id:'run',status:'ready',stale:false,metadata:work.metadata,page_count:0,attachment_count:0,preview_hash:previewHash,prepared_by:body.prepared_by};return ok(latest);}
    if(url.endsWith('/office')){await onOffice?.(root);return ok({approval_snapshot_hash:'h',eligible:work.requests.every(row=>row.status==='approved'),latest});}
    throw new Error('Unexpected fixture URL '+url);
  };
  const final=createFinal({getCase:()=>current,getProgress:()=>{assert.equal(current.id,'qa','No consultar el progreso de otro expediente');return {completed:[true,true]};},hasChanges:()=>externalChanges,notice:value=>notices.push(value),isVisible:()=>true,back(){},onStateChange:value=>summaries.push(value),onFinalized:(id,management)=>{finalizations.push({id,management});current=null;}});
  final.view();await final.load();
  const field=query=>root.querySelector(query);
  const click=command=>root.commands.find(button=>button.dataset.command===command).onclick();
  const invoke=async command=>{click(command);await settle(()=>!root.commands.find(button=>button.dataset.command==='save').disabled||field('[data-review-status]').textContent==='Expediente finalizado');};
  return {root,final,calls,notices,summaries,finalizations,field,invoke,click,
    leave(){current=null;},switchCase(){current={id:'other',request_count:1};},
    confirm(){const input=field('[data-confirm-office]');input.checked=true;input.onchange({target:input});},
    edit(value='Asunto corregido'){const input=field('[data-meta="subject"]');input.value=value;input.oninput();},
    failSave(){failPut=true;},failLoad(){failGet=true;},failClose(value=true){failClose=value;},serverCase,
    selectManager(id){manager=id;windowEvents['pqrs-manager-change']?.();},
    external(){externalChanges=true;},changeVersion(){work.revision++;},staleExport(){latest.stale=true;}};
}

test('abrir y consultar un borrador listo no aprueba ni genera automáticamente',async()=>{
  const h=await harness();assert.ok(h.calls.every(call=>call.method==='GET'));
  assert.equal(h.field('[data-confirm-office]').checked,false);
  assert.equal(h.root.commands.find(button=>button.dataset.command==='generate').disabled,true);
  assert.equal(h.summaries.at(-1).draftComplete,false);
  assert.equal(h.field('[data-command="finalize"]').hidden,true);
});

for(const destination of ['leave','switchCase'])test(`una carga tardía del borrador no actualiza la pantalla tras ${destination}`,async()=>{
  let defer=false,release,started;
  const waiting=new Promise(resolve=>{started=resolve;});
  const work=initialWork();work.requests[0].status='approved';
  const h=await harness({savedWork:work,savedRun:{id:'run',status:'ready',stale:false,prepared_by:'José',preview_hash:'p'},
    onOffice:async()=>{if(defer){started();await new Promise(resolve=>{release=resolve;});}}});
  defer=true;const loading=h.final.load();await waiting;
  const before=h.summaries.length;h[destination]();release();await loading;
  assert.equal(h.summaries.length,before,'Una carga anterior no actualiza otra pantalla');
  assert.equal(h.field('[data-error]').textContent,'');
  assert.ok(h.calls.every(call=>call.method==='GET'||call.url.endsWith('/preview')));
  assert.ok(!h.calls.some(call=>call.url.endsWith('/generate')||call.url.endsWith('/approve')));
});

test('el controlador exige confirmación aunque se invoque directamente el botón deshabilitado',async()=>{
  const h=await harness();await h.invoke('generate');
  assert.match(h.field('[data-error]').textContent,/Confirma/);
  assert.ok(h.calls.every(call=>call.method==='GET'));
});

test('editar invalida la confirmación; guardar comprueba sin aprobar y exige nueva revisión',async()=>{
  const h=await harness();h.confirm();assert.equal(h.root.commands.find(button=>button.dataset.command==='generate').disabled,false);
  h.edit();assert.equal(h.field('[data-confirm-office]').checked,false);assert.equal(h.final.hasChanges('qa'),true);
  await h.invoke('save');assert.equal(h.final.hasChanges('qa'),false);
  assert.ok(h.calls.some(call=>call.method==='PUT'));assert.ok(h.calls.some(call=>call.url.endsWith('/assess')));
  assert.ok(!h.calls.some(call=>call.url.endsWith('/approve')||call.url.endsWith('/generate')));
  assert.equal(h.field('[data-confirm-office]').checked,false);
});

test('solo la acción confirmada aprueba antes de generar y editar vuelve a invalidar la versión visible',async()=>{
  const h=await harness();
  assert.match(h.field('[data-draft-progress]').innerHTML,/1 de 1 respuesta comprobada/);
  assert.match(h.field('[data-draft-progress]').innerHTML,/Pendiente de tu revisión final/);
  h.confirm();
  assert.match(h.field('[data-draft-progress]').innerHTML,/falta generar el oficio/);
  await h.invoke('generate');
  const writes=h.calls.filter(call=>call.method!=='GET');
  assert.deepEqual(writes.map(call=>call.url.split('/').at(-1)),['approve','preview','generate']);
  assert.equal(writes[0].body.confirmed,true);assert.equal(writes[0].body.approved_by,'José');
  assert.match(h.field('[data-downloads]').innerHTML,/Descargar Word/);assert.match(h.field('[data-downloads]').innerHTML,/Descargar PDF/);
  assert.equal(h.summaries.at(-1).draftComplete,true);
  assert.match(h.field('[data-draft-progress]').innerHTML,/Versión final generada/);
  h.edit();assert.equal(h.summaries.at(-1).draftComplete,false);assert.equal(h.field('[data-downloads]').innerHTML,'');
  assert.match(h.field('[data-draft-progress]').innerHTML,/Cambios pendientes de comprobar/);
  assert.doesNotMatch(h.field('[data-draft-progress]').innerHTML,/Versión final generada/);
});

test('una revisión que cambió en otra ventana se rechaza antes de aprobar',async()=>{
  const h=await harness();h.confirm();h.changeVersion();await h.invoke('generate');
  assert.match(h.field('[data-error]').textContent,/otra ventana/);
  assert.ok(!h.calls.some(call=>call.method!=='GET'));
});

function multiResponseWork(count=3){
  const work=initialWork();work.requests=Array.from({length:count},(_,index)=>({...structuredClone(work.requests[0]),request_id:`P${index+1}`,label:String(index+1)}));return work;
}

test('el contador avanza después de guardar cada aprobación y distingue la creación de archivos',async()=>{
  const work=multiResponseWork();work.requests[0].status='approved';
  let release;
  const seen=[];
  const h=await harness({savedWork:work,onApprove:async(id,root)=>{
    seen.push(id);await new Promise(resolve=>{release=resolve;});
  },onGenerate:async root=>{
    assert.match(root.querySelector('[data-draft-progress]').innerHTML,/3 de 3 respuestas aprobadas/);
    assert.match(root.querySelector('[data-draft-progress]').innerHTML,/Creando Word y PDF/);
    assert.doesNotMatch(root.querySelector('[data-draft-progress]').innerHTML,/Versión final generada/);
    assert.equal(root.querySelector('[data-command="generate"]').innerHTML,'Generando Word y PDF…');
  }});
  h.confirm();h.click('generate');
  try{
    await settle(()=>seen.length===1);
    assert.match(h.field('[data-draft-progress]').innerHTML,/1 de 3 respuestas aprobadas/);
    assert.match(h.field('[data-command="generate"]').innerHTML,/Aprobadas 1\/3/);
    release();await settle(()=>seen.length===2);
    assert.match(h.field('[data-draft-progress]').innerHTML,/2 de 3 respuestas aprobadas/);
    assert.match(h.field('[data-operation]').textContent,/Aprobando la respuesta 3 de 3/);
  }finally{release?.();}
  await settle(()=>!h.field('[data-command="save"]').disabled);
  assert.deepEqual(seen,['P2','P3']);
  assert.match(h.field('[data-draft-progress]').innerHTML,/Versión final generada/);
});

test('un fallo parcial conserva el contador y el reintento omite respuestas ya aprobadas',async()=>{
  let fail=true;const seen=[];
  const h=await harness({savedWork:multiResponseWork(),onApprove:async id=>{seen.push(id);if(id==='P2'&&fail)throw new Error('Interrupción de prueba');}});
  h.confirm();await h.invoke('generate');
  assert.deepEqual(seen,['P1','P2']);
  assert.match(h.field('[data-draft-progress]').innerHTML,/1 de 3 respuestas aprobadas/);
  assert.match(h.field('[data-draft-progress]').innerHTML,/El avance guardado se conserva/);
  assert.doesNotMatch(h.field('[data-draft-progress]').innerHTML,/source-spinner/);
  assert.ok(!h.calls.some(call=>call.url.endsWith('/generate')));
  fail=false;await h.invoke('generate');
  assert.deepEqual(seen,['P1','P2','P2','P3']);
  assert.match(h.field('[data-downloads]').innerHTML,/Descargar PDF/);
  assert.equal(h.summaries.at(-1).draftComplete,true);
});

test('un fallo de exportación conserva todas las aprobaciones sin anunciar que el oficio está generado',async()=>{
  let fail=true;const h=await harness({savedWork:multiResponseWork(),onGenerate:async()=>{if(fail)throw new Error('No se pudo crear el PDF');}});
  h.confirm();await h.invoke('generate');
  assert.match(h.field('[data-draft-progress]').innerHTML,/3 de 3 respuestas aprobadas/);
  assert.doesNotMatch(h.field('[data-draft-progress]').innerHTML,/Versión final generada/);
  assert.equal(h.field('[data-downloads]').innerHTML,'');
  const before=h.calls.length;fail=false;await h.invoke('generate');
  assert.ok(!h.calls.slice(before).some(call=>call.url.endsWith('/approve')));
  assert.match(h.field('[data-draft-progress]').innerHTML,/Versión final generada/);
});

test('un error de guardado conserva el cambio local y no aprueba ni inicia exportación',async()=>{
  const h=await harness();h.edit('Texto local a conservar');h.failSave();await h.invoke('save');
  assert.equal(h.final.hasChanges('qa'),true);assert.equal(h.field('[data-meta="subject"]').value,'Texto local a conservar');
  assert.match(h.field('[data-error]').textContent,/No se pudo guardar/);
  assert.ok(!h.calls.some(call=>call.url.endsWith('/approve')||call.url.endsWith('/generate')));
});

test('un fallo al recargar para descartar no anuncia que se descartó la edición conservada',async()=>{
  const h=await harness();h.edit('Texto que aún permanece');h.failLoad();await h.invoke('cancel');
  assert.equal(h.final.hasChanges('qa'),true);assert.equal(h.field('[data-meta="subject"]').value,'Texto que aún permanece');
  assert.match(h.field('[data-error]').textContent,/No se pudo recuperar/);
  assert.ok(!h.notices.some(value=>/Se descartaron/.test(value)));
});

test('el primer responsable se registra antes de capturar la confirmación del oficio',async()=>{
  const h=await harness({actorName:''});
  h.field('#office-actor').value='Ana';
  h.confirm();
  assert.equal(actor,'Ana');assert.equal(h.field('[data-confirm-office]').checked,true);
  assert.equal(h.root.commands.find(button=>button.dataset.command==='generate').disabled,false);
  assert.ok(!h.calls.some(call=>call.url.endsWith('/approve')));
  await h.invoke('generate');
  assert.equal(h.calls.find(call=>call.url.endsWith('/approve')).body.approved_by,'Ana');
});

test('sin responsable no queda confirmada la revisión y se abre el apartado correspondiente',async()=>{
  const h=await harness({actorName:''});h.confirm();
  assert.equal(h.field('[data-confirm-office]').checked,false);
  assert.equal(h.field('[data-responsible-details]').open,true);
  assert.match(h.field('[data-error]').textContent,/responsable/i);
  assert.ok(!h.calls.some(call=>call.method!=='GET'));
});

function generatedWithAttachments(){
  const work=initialWork();work.requests[0].status='approved';
  work.attachment_source_ids=['qa-source'];work.attachment_options=[{source_id:'qa-source',title:'Anexo ficticio'}];
  const run={id:'existing',status:'ready',stale:false,metadata:structuredClone(work.metadata),page_count:0,attachment_count:1,preview_hash:'p',prepared_by:'Gestor de la versión anterior'};
  return {savedWork:work,savedRun:run};
}

test('restaurar una versión con anexos valida su preview sin volver a aprobar ni generar',async()=>{
  const h=await harness(generatedWithAttachments());
  const preview=h.calls.find(call=>call.url.endsWith('/preview'));
  assert.ok(preview);assert.deepEqual(preview.body.attachment_source_ids,['qa-source']);
  assert.equal(preview.body.prepared_by,'Gestor de la versión anterior');assert.equal(actor,'José');
  assert.match(h.field('[data-downloads]').innerHTML,/Descargar paquete con anexos/);
  assert.equal(h.summaries.at(-1).draftComplete,true);
  assert.ok(!h.calls.some(call=>call.url.endsWith('/approve')||call.url.endsWith('/generate')));
  assert.equal(h.field('[data-confirm-office]').checked,false);
  assert.equal(h.field('[data-confirm-office]').hidden,true);
  assert.equal(h.field('[data-review-status]').textContent,'Oficio generado');
  assert.equal(h.field('[data-confirm-label]').textContent,'Revisión del oficio registrada');
  assert.equal(h.root.commands.find(button=>button.dataset.command==='generate').disabled,true);
  h.edit();
  assert.equal(h.field('[data-confirm-office]').hidden,false);
  assert.equal(h.field('[data-confirm-office]').checked,false);
  assert.equal(h.field('[data-confirm-label]').textContent,'He revisado el oficio completo');
  assert.equal(h.field('[data-review-status]').textContent,'Sin guardar');
});

test('una versión con distinto conjunto de anexos no se presenta como el oficio vigente',async()=>{
  const h=await harness({...generatedWithAttachments(),previewHash:'different-selection'});
  assert.ok(h.calls.some(call=>call.url.endsWith('/preview')));
  assert.equal(h.field('[data-downloads]').innerHTML,'');assert.equal(h.summaries.at(-1).draftComplete,false);
  assert.ok(!h.calls.some(call=>call.url.endsWith('/approve')||call.url.endsWith('/generate')));
});

test('un fallo al comprobar la exportación anterior conserva el editor y no habilita sus descargas',async()=>{
  const h=await harness({...generatedWithAttachments(),previewError:'No se pudo comprobar la versión anterior'});
  assert.ok(h.calls.some(call=>call.url.endsWith('/preview')));
  assert.equal(h.field('[data-meta="subject"]').value,'Asunto ficticio');
  assert.equal(h.field('[data-downloads]').innerHTML,'');assert.equal(h.summaries.at(-1).draftComplete,false);
  assert.equal(h.root.commands.find(button=>button.dataset.command==='save').disabled,false);
  assert.ok(!h.calls.some(call=>call.url.endsWith('/approve')||call.url.endsWith('/generate')));
});

test('una edición durante la validación de descargas no se confunde con la versión generada',async()=>{
  const h=await harness({...generatedWithAttachments(),onPreview:root=>{
    const input=root.querySelector('[data-meta="subject"]');input.value='Edición durante la consulta';input.oninput();
  }});
  assert.equal(h.final.hasChanges('qa'),true);assert.equal(h.field('[data-meta="subject"]').value,'Edición durante la consulta');
  assert.equal(h.field('[data-downloads]').innerHTML,'');assert.equal(h.summaries.at(-1).draftComplete,false);
  assert.ok(!h.calls.some(call=>call.url.endsWith('/approve')||call.url.endsWith('/generate')));
});

test('un expediente sin respuestas no se anuncia como redacción preparada',async()=>{
  const work=initialWork();work.requests=[];work.blocks=[];
  const h=await harness({savedWork:work});
  assert.equal(h.summaries.at(-1).redactionComplete,false);
  assert.equal(h.field('[data-confirm-office]').disabled,true);
  assert.ok(h.calls.every(call=>call.method==='GET'));
});

test('cargar respuestas sin aprobar omite la consulta profunda del historial de exportación',async()=>{
  for(const status of ['ready','needs_changes','needs_evidence']){
    const work=initialWork();work.requests[0].status=status;
    const h=await harness({savedWork:work});
    assert.ok(!h.calls.some(call=>call.url.endsWith('/office')),status);
    assert.equal(h.field('[data-meta="subject"]').value,'Asunto ficticio');
    assert.ok(!h.calls.some(call=>call.method!=='GET'));
  }
  const work=initialWork();work.requests=[];work.blocks=[];
  const h=await harness({savedWork:work});
  assert.ok(!h.calls.some(call=>call.url.endsWith('/office')));
});

test('el documento aprobado se muestra mientras sigue pendiente consultar su exportación',async()=>{
  let resolveOffice,startedRoot;
  const gate=new Promise(resolve=>{resolveOffice=resolve;});
  const loaded=harness({...generatedWithAttachments(),onOffice:async root=>{startedRoot=root;await gate;}});
  try{
    await settle(()=>Boolean(startedRoot));
    assert.match(startedRoot.innerHTML,/Documento del oficio/);
    assert.equal(startedRoot.querySelector('[data-meta="subject"]').value,'Asunto ficticio');
    assert.equal(startedRoot.querySelector('[data-downloads]').innerHTML,'');
    assert.equal(startedRoot.commands.find(button=>button.dataset.command==='save').disabled,false);
    assert.equal(startedRoot.commands.find(button=>button.dataset.command==='generate').disabled,true);
  }finally{resolveOffice();}
  const h=await loaded;
  assert.match(h.field('[data-downloads]').innerHTML,/Descargar Word/);
  assert.ok(!h.calls.some(call=>call.url.endsWith('/approve')||call.url.endsWith('/generate')));
});

test('finalizar desde el oficio generado solo cambia gestión y vuelve a Finalizadas',async()=>{
  const h=await harness(generatedWithAttachments());
  assert.equal(h.field('[data-command="finalize"]').hidden,false);
  assert.equal(h.field('[data-command="finalize"]').disabled,false);
  assert.equal(h.field('[data-command="generate"]').hidden,true);
  const downloads=h.field('[data-downloads]').innerHTML,start=h.calls.length;
  await h.invoke('finalize');
  assert.deepEqual(h.calls.slice(start).filter(call=>call.method!=='GET'),[{url:'/api/cases/qa/management',method:'POST',body:{revision:2,actor_id:'gestor-1',action:'state',state:'closed',note:'Finalizado desde Borrador con el oficio revisado y generado. Se conservan las respuestas, revisiones y archivos.'}}]);
  assert.equal(h.finalizations.length,1);assert.equal(h.finalizations[0].id,'qa');
  assert.equal(h.finalizations[0].management.state,'closed');
  assert.equal(h.field('[data-review-status]').textContent,'Expediente finalizado');
  assert.equal(h.field('[data-downloads]').innerHTML,downloads);
  assert.equal(h.field('[data-command="finalize"]').hidden,true);
  assert.equal(h.final.hasChanges('qa'),false);
  assert.match(h.notices.at(-1),/Finalizadas/);
});

test('no se cierra con cambios locales, otra revisión, otra persona o generación desactualizada',async()=>{
  for(const change of [h=>h.edit(),h=>h.external(),h=>h.changeVersion(),h=>h.staleExport(),h=>{h.serverCase.processing=true;},h=>{h.serverCase.management.owner_id='gestor-2';}]){
    const h=await harness(generatedWithAttachments());change(h);const start=h.calls.length;
    await h.invoke('finalize');
    assert.equal(h.finalizations.length,0);
    assert.ok(h.field('[data-error]').textContent);
    assert.ok(h.calls.slice(start).every(call=>call.method==='GET'));
    assert.equal(h.serverCase.management.state,'in_progress');
  }
  const h=await harness({...generatedWithAttachments(),managerId:'gestor-2'});
  assert.equal(h.field('[data-command="finalize"]').disabled,true);
  await h.invoke('finalize');assert.equal(h.finalizations.length,0);
  assert.ok(!h.calls.some(call=>call.url.endsWith('/management')));
  h.selectManager('gestor-1');assert.equal(h.field('[data-command="finalize"]').disabled,false);
  await h.invoke('finalize');assert.equal(h.finalizations.length,1);
});

test('fallar el cierre conserva el oficio y permite reintentar con la revisión de gestión actual',async()=>{
  const h=await harness(generatedWithAttachments());h.failClose();
  const downloads=h.field('[data-downloads]').innerHTML;
  await h.invoke('finalize');
  assert.match(h.field('[data-error]').textContent,/No se pudo finalizar/);
  assert.equal(h.finalizations.length,0);assert.equal(h.field('[data-downloads]').innerHTML,downloads);
  assert.equal(h.field('[data-command="finalize"]').disabled,false);
  h.failClose(false);h.serverCase.management.revision=4;
  await h.invoke('finalize');
  assert.equal(h.calls.filter(call=>call.url.endsWith('/management')).at(-1).body.revision,4);
  assert.equal(h.finalizations.length,1);
});

test('doble clic solo registra un cierre y recuperar un cierre aceptado no lo repite',async()=>{
  let release;const gate=new Promise(resolve=>{release=resolve;});
  const h=await harness({...generatedWithAttachments(),onClose:()=>gate});
  h.click('finalize');await settle(()=>h.calls.some(call=>call.url.endsWith('/management')));
  h.click('finalize');release();await settle(()=>h.finalizations.length===1);
  assert.equal(h.calls.filter(call=>call.url.endsWith('/management')).length,1);
  const recovered=await harness(generatedWithAttachments());recovered.serverCase.management.state='closed';
  await recovered.invoke('finalize');assert.equal(recovered.finalizations.length,1);
  assert.ok(!recovered.calls.some(call=>call.url.endsWith('/management')));
});
