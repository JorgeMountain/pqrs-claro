import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {decisionForm,factForm,when,isOpen,pendingCards} from '../src/pqrs_claro/static/recorrido/live-pending-view.js';
import {documentDecisionForm,documentTarget} from '../src/pqrs_claro/static/recorrido/document-decision.js';
import {pendingAction} from '../src/pqrs_claro/static/recorrido/pending-guidance.js';
import {esc} from '../src/pqrs_claro/static/recorrido/views.js';

let rememberedActor='';
const dependencies={bindSupportPicker(){},bindActor:form=>{form.fields.get('#pending-actor').value=rememberedActor;},
  rememberActor:value=>{rememberedActor=value;},decisionForm,factForm,when,isOpen,documentDecisionForm,documentTarget,pendingAction,esc};
globalThis.__pendingTestDependencies=dependencies;
const source=(await fs.readFile(new URL('../src/pqrs_claro/static/recorrido/live-pending.js',import.meta.url),'utf8')).replace(/^import .*;\r?\n/gm,'');
const {createPendingActions}=await import('data:text/javascript;base64,'+Buffer.from('const {'+Object.keys(dependencies).join(',')+'}=globalThis.__pendingTestDependencies;\n'+source).toString('base64'));

const originalRow=()=>({case_id:'case-a',request_id:'P1',revision:1,pre_draft:true,stale:false,paragraphs:[],facts:[],
  pending:[{id:'pending-1',kind:'fact',description:'Confirmar el canal vigente',reason_code:'fact_confirmation',blocks_approval:true,resolution:null}],
  available_supports:[{source_id:'source-1',chunk_id:'chunk-1',title:'Guía',quote:'Canal de atención',page:1,version:1},
    {source_id:'source-2',chunk_id:'chunk-2',title:'Procedimiento',quote:'Pasos del trámite',page:2,version:1}]});

function harness({onSaved=async()=>{},put=null}={}){
  let current={id:'case-a'},row=originalRow(),manager='José',body,marker,form,uploaded;
  const calls=[],notices=[],opened=[];
  const element=(value='')=>({value,disabled:false,hidden:false,checked:false,isConnected:true,textContent:'',dataset:{},listeners:{},
    focus(){},setAttribute(name){if(name==='hidden')this.hidden=true;},removeAttribute(name){if(name==='hidden')this.hidden=false;},addEventListener(name,callback){this.listeners[name]=callback;},
    dispatchEvent(event){this.listeners[event.type]?.(event);form?.listeners[event.type]?.(event);}});
  function makeForm(html){
    const fields=new Map(['#pending-note','#pending-actor','#pending-upload','#pending-not-applicable','#pending-cancel','#pending-error','submit'].map(key=>[key,element()]));
    const choices=row.available_supports.map(s=>({...element('source:'+s.chunk_id),name:'pending-support'}));
    fields.get('submit').disabled=/<button class="primary" type="submit" disabled/.test(html);
    fields.get('#pending-error').insertAdjacentHTML=(position,markup)=>{
      assert.equal(position,'afterend');assert.match(markup,/id="pending-reload"/);
      fields.set('#pending-reload',{...element(),hidden:/\bhidden\b/.test(markup)});
    };
    const result={isConnected:true,fields,choices,listeners:{},setAttribute(){},removeAttribute(){},
      addEventListener(name,fn){this.listeners[name]=fn;},
      querySelector(query){
        if(query==='input[name="pending-support"]:checked')return choices.find(v=>v.checked)||null;
        if(['button[type="submit"]','[type="submit"]'].includes(query))return fields.get('submit');
        if(query.includes(','))return fields.get('#pending-upload');
        return fields.get(query)||null;
      },
      querySelectorAll(query){return query==='[name="pending-support"]'?choices:[...fields.values(),...choices];}};
    return result;
  }
  const open=(title,html)=>{
    if(marker)marker.isConnected=false;if(form)form.isConnected=false;
    marker=html.includes('id="pending-loading"')?element():null;
    form=null;
    const buttons=new Map(['#pending-next','#pending-back','#pending-reload'].map(key=>[key,element()]));
    body={text:html,scrollTop:0,querySelector:query=>buttons.get(query),
      set innerHTML(value){this.text=value;if(marker)marker.isConnected=false;if(form)form.isConnected=false;form=value.includes('id="pending-decision-form"')?makeForm(value):null;},
      get innerHTML(){return this.text;}};
    opened.push({title,html,body});
  };
  globalThis.document={querySelector:query=>query==='#pending-loading'?marker:query==='#drawer-body'?body:query==='#pending-decision-form'?form:body?.querySelector(query.includes(',')?'#pending-back':query)};
  globalThis.FormData=class{[Symbol.iterator](){return [][Symbol.iterator]();}};
  globalThis.fetch=async(url,options)=>{
    calls.push({url,options});
    if(!options.method)return {ok:true,json:async()=>({requests:[structuredClone(row)]})};
    if(put)return put(JSON.parse(options.body),row);
    const saved={...row,pending:row.pending.map(p=>({...p,resolution:{action:'resolved',note:'Comprobado'}}))};
    return {ok:true,json:async()=>saved};
  };
  const actions=createPendingActions({open,close(){if(form)form.isConnected=false;},notice:v=>notices.push(v),getCase:()=>current,
    getActor:()=>manager,onSaved,upload:(requestId,context)=>{uploaded={requestId,context};open('Carga','<p>Subir archivo</p>');}});
  return {actions,calls,notices,opened,get form(){return form;},get uploaded(){return uploaded;},get row(){return row;},
    setRow:value=>{row=value;},setManager:value=>{manager=value;},changeCase:()=>{current={id:'case-b'};},
    remember:()=>form.listeners.input?.({}),
    reload:()=>form?form.fields.get('#pending-reload').onclick():body.querySelector('#pending-reload').onclick(),
    submit:()=>form.fields.get('submit').disabled?undefined:form.onsubmit({preventDefault(){}})};
}

test('carga y retorno recuperan explicación y respaldo, y usan la revisión y actor actuales',async()=>{
  rememberedActor='Nombre anterior';const h=harness();
  await h.actions.decide('P1','pending-1','resolved');
  assert.equal(h.form.fields.get('#pending-actor').value,'José');
  h.form.fields.get('#pending-note').value='Comprobé el canal en la guía.';h.form.choices[1].checked=true;
  h.form.fields.get('#pending-upload').listeners.click();
  assert.equal(h.uploaded.requestId,'P1');assert.equal(h.uploaded.context.description,'Confirmar el canal vigente');
  h.setRow({...h.row,revision:3});h.setManager('Ana');
  await h.uploaded.context.onUploaded({source_id:'new-source'});
  assert.equal(h.form.fields.get('#pending-note').value,'Comprobé el canal en la guía.');
  assert.equal(h.form.choices[1].checked,true);assert.equal(h.form.fields.get('#pending-actor').value,'Ana');
  assert.ok(!h.calls.some(call=>call.options.method));
  await h.submit();
  const body=JSON.parse(h.calls.find(call=>call.options.method==='PUT').options.body);
  assert.equal(body.revision,3);assert.equal(body.edited_by,'Ana');
  assert.deepEqual(body.pending_resolutions[0].cited_chunk_ids,['chunk-2']);
  assert.deepEqual(body.paragraphs,[]);
});

test('cancelar una carga recupera el borrador sin guardar una decisión',async()=>{
  const h=harness();await h.actions.decide('P1','pending-1','resolved');
  h.form.fields.get('#pending-note').value='Explicación todavía sin guardar';h.form.choices[0].checked=true;
  h.form.fields.get('#pending-upload').listeners.click();await h.uploaded.context.onCancel();
  assert.equal(h.form.fields.get('#pending-note').value,'Explicación todavía sin guardar');
  assert.equal(h.form.choices[0].checked,true);assert.ok(!h.calls.some(call=>call.options.method));
});

test('un pasaje retirado al actualizar nunca queda seleccionado por coincidencia de posición',async()=>{
  const h=harness();await h.actions.decide('P1','pending-1','resolved');
  h.form.fields.get('#pending-note').value='Nota que debe conservarse';h.form.choices[0].checked=true;
  h.form.fields.get('#pending-upload').listeners.click();
  h.setRow({...h.row,revision:2,available_supports:[h.row.available_supports[1]]});
  await h.uploaded.context.onUploaded({});
  assert.equal(h.form.fields.get('#pending-note').value,'Nota que debe conservarse');
  assert.ok(h.form.choices.every(choice=>!choice.checked));await h.submit();
  assert.match(h.form.fields.get('#pending-error').textContent,/Selecciona el respaldo/);
  assert.ok(!h.calls.some(call=>call.options.method));
});

test('doble envío y fallo del refresco posterior no repiten una decisión ya guardada',async()=>{
  let release;const pending=new Promise(resolve=>{release=resolve;});
  const h=harness({put:async(_body,row)=>{await pending;return {ok:true,json:async()=>({...row,pending:[]})};},
    onSaved:async()=>{throw new Error('Vista temporalmente no disponible');}});
  await h.actions.decide('P1','pending-1','resolved');h.form.fields.get('#pending-note').value='Cotejado';h.form.choices[0].checked=true;
  const work=h.submit();await h.submit();
  assert.equal(h.calls.filter(call=>call.options.method==='PUT').length,1);release();await work;
  assert.equal(h.opened.at(-1).title,'Decisión guardada');
  assert.match(h.opened.at(-1).html,/decisión se guardó, pero no se pudo actualizar/);
  assert.equal(h.calls.filter(call=>call.options.method==='PUT').length,1);
});

test('error de guardado conserva campos y permite un reintento explícito',async()=>{
  let attempts=0;
  const h=harness({put:async(_body,row)=>++attempts===1?{ok:false,status:503,json:async()=>({detail:'Servicio temporalmente no disponible'})}:{ok:true,json:async()=>({...row,pending:[]})}});
  await h.actions.decide('P1','pending-1','resolved');const form=h.form;
  form.fields.get('#pending-note').value='Canal comprobado';form.choices[0].checked=true;
  await h.submit();assert.equal(h.form,form);assert.equal(form.fields.get('#pending-note').value,'Canal comprobado');
  assert.equal(form.choices[0].checked,true);assert.equal(form.fields.get('submit').disabled,false);
  assert.match(form.fields.get('#pending-error').textContent,/temporalmente/);
  await h.submit();assert.equal(attempts,2);assert.equal(h.opened.at(-1).title,'Decisión guardada');
});

test('cambiar de gestor con el panel abierto exige consultar y conserva el borrador',async()=>{
  const h=harness();await h.actions.decide('P1','pending-1','resolved');
  h.form.fields.get('#pending-note').value='Canal cotejado por el gestor';h.form.choices[1].checked=true;h.remember();
  h.setManager('Ana');await h.submit();
  assert.match(h.form.fields.get('#pending-error').textContent,/Cambió el gestor activo/);
  assert.equal(h.form.fields.get('#pending-reload').hidden,false);
  assert.equal(h.calls.filter(call=>call.options.method==='PUT').length,0);
  await h.reload();
  assert.equal(h.form.fields.get('#pending-actor').value,'Ana');
  assert.equal(h.form.fields.get('#pending-note').value,'Canal cotejado por el gestor');
  assert.equal(h.form.choices[1].checked,true);
  assert.equal(h.calls.filter(call=>call.options.method==='PUT').length,0);
  await h.submit();
  const payload=JSON.parse(h.calls.find(call=>call.options.method==='PUT').options.body);
  assert.equal(payload.edited_by,'Ana');assert.deepEqual(payload.pending_resolutions[0].cited_chunk_ids,['chunk-2']);
});

test('un punto retirado durante la carga muestra los pendientes actuales sin aplicar la decisión a otro',async()=>{
  const refreshed=[];const h=harness({onSaved:async row=>refreshed.push(row)});
  await h.actions.decide('P1','pending-1','resolved');
  h.form.fields.get('#pending-note').value='Comprobación aún sin confirmar';h.form.choices[0].checked=true;
  h.form.fields.get('#pending-upload').listeners.click();
  h.setRow({...h.row,revision:2,pending:[{...h.row.pending[0],id:'pending-replacement'}]});
  await h.uploaded.context.onUploaded({});
  assert.equal(h.form,null);
  assert.match(h.opened.at(-1).body.innerHTML,/Los pendientes se actualizaron/);
  assert.match(h.opened.at(-1).body.innerHTML,/No se ha aplicado tu decisión a otro punto/);
  assert.equal(h.calls.filter(call=>call.options.method==='PUT').length,0);
  await h.opened.at(-1).body.querySelector('#pending-back').onclick();
  assert.equal(refreshed.length,1);assert.equal(refreshed[0].revision,2);
  assert.equal(refreshed[0].pending[0].id,'pending-replacement');
});

test('un PUT guardado cuya respuesta se pierde se consulta sin volver a enviar la decisión',async()=>{
  let h;
  h=harness({put:async(_payload,row)=>{
    h.setRow({...row,revision:2,pending:row.pending.map(p=>({...p,resolution:{action:'resolved',note:'Canal cotejado'}}))});
    throw new DOMException('La respuesta agotó el tiempo de espera','TimeoutError');
  }});
  await h.actions.decide('P1','pending-1','resolved');
  h.form.fields.get('#pending-note').value='Canal cotejado';h.form.choices[0].checked=true;h.remember();
  const form=h.form;await h.submit();
  assert.equal(h.form,form);assert.equal(form.fields.get('#pending-note').value,'Canal cotejado');
  assert.equal(form.choices[0].checked,true);assert.equal(form.fields.get('submit').disabled,true);
  assert.equal(form.fields.get('#pending-reload').hidden,false);
  assert.match(form.fields.get('#pending-error').textContent,/No se pudo confirmar el estado del guardado/);
  await h.submit();assert.equal(h.calls.filter(call=>call.options.method==='PUT').length,1);
  await h.reload();
  assert.equal(h.opened.at(-1).title,'Decisión guardada');
  assert.deepEqual(h.calls.map(call=>call.options.method||'GET'),['GET','PUT','GET']);
});

test('un conflicto 409 obliga a consultar la revisión vigente antes de otro envío explícito',async()=>{
  let h,attempts=0;
  h=harness({put:async(_payload,row)=>{
    if(++attempts===1){h.setRow({...row,revision:4});return {ok:false,status:409,json:async()=>({detail:'Revisión anterior'})};}
    return {ok:true,json:async()=>({...row,pending:[]})};
  }});
  await h.actions.decide('P1','pending-1','resolved');
  h.form.fields.get('#pending-note').value='Mantener esta explicación';h.form.choices[1].checked=true;h.remember();
  await h.submit();
  assert.equal(h.form.fields.get('submit').disabled,true);assert.equal(h.form.fields.get('#pending-reload').hidden,false);
  await h.submit();assert.equal(attempts,1);
  await h.reload();
  assert.equal(h.form.fields.get('#pending-note').value,'Mantener esta explicación');
  assert.equal(h.form.choices[1].checked,true);assert.equal(h.form.fields.get('submit').disabled,false);
  assert.equal(attempts,1);
  await h.submit();
  const payloads=h.calls.filter(call=>call.options.method==='PUT').map(call=>JSON.parse(call.options.body));
  assert.deepEqual(payloads.map(payload=>payload.revision),[1,4]);
  assert.equal(payloads[1].pending_resolutions[0].note,'Mantener esta explicación');
  assert.deepEqual(payloads[1].pending_resolutions[0].cited_chunk_ids,['chunk-2']);
  assert.deepEqual(h.calls.map(call=>call.options.method||'GET'),['GET','PUT','GET','PUT']);
});

test('un fallo de transporte sin guardar recupera el borrador y solo reintenta tras consulta y confirmación',async()=>{
  let attempts=0;
  const h=harness({put:async(_payload,row)=>{
    if(++attempts===1)throw new TypeError('Failed to fetch');
    return {ok:true,json:async()=>({...row,pending:[]})};
  }});
  await h.actions.decide('P1','pending-1','resolved');
  h.form.fields.get('#pending-note').value='Explicación recuperable';h.form.choices[0].checked=true;h.remember();
  await h.submit();await h.submit();assert.equal(attempts,1);
  await h.reload();assert.equal(attempts,1);
  assert.equal(h.form.fields.get('#pending-note').value,'Explicación recuperable');assert.equal(h.form.choices[0].checked,true);
  await h.submit();assert.equal(attempts,2);
  assert.deepEqual(h.calls.map(call=>call.options.method||'GET'),['GET','PUT','GET','PUT']);
});

test('retorno tras cambiar de expediente no abre ni guarda sobre otro caso',async()=>{
  const h=harness();await h.actions.decide('P1','pending-1','resolved');
  h.form.fields.get('#pending-upload').listeners.click();const reads=h.calls.length;
  h.changeCase();await h.uploaded.context.onUploaded({});await h.uploaded.context.onCancel();
  assert.equal(h.calls.length,reads);assert.ok(!h.calls.some(call=>call.options.method));
});

test('presentación mantiene alternativas explícitas y no equipara falta de respaldo con no aplicable',()=>{
  const row=originalRow(),point=row.pending[0];
  const missing=decisionForm({...row,available_supports:[]},point,'resolved','José').html;
  assert.match(missing,/id="pending-upload"/);assert.match(missing,/type="submit" disabled/);
  const alternative=decisionForm(row,point,'not_applicable','José').html;
  assert.match(alternative,/falta de respaldo por sí sola no lo hace innecesario/);
  assert.match(alternative,/id="pending-note" required/);
  const error=pendingCards({...row,pending:[{...point,state:'analysis_error'}]},0);
  assert.match(error,/Reintentar análisis/);assert.doesNotMatch(error,/data-decision="resolved"/);
});
