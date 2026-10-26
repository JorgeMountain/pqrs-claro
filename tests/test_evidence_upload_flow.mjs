import test from 'node:test';
import assert from 'node:assert/strict';
import {createEvidenceUpload} from '../src/pqrs_claro/static/evidence-upload.js';

// Execute the upload controller with controlled form, network and dialog adapters.
// No live case, file or API is changed.
function harness({response={},reject=null,onUpdated=async()=>{}}={}){
  let current={id:'case-a',version:7,status:'confirmed'},active=null;
  const opened=[],notices=[],calls=[];
  const node=(value='')=>({value,disabled:false,textContent:'',innerHTML:'',focus(){}});
  function formNode(){
    const controls={file:{...node(),files:[{name:'guia.pdf',size:200}]},title:node('Guía vigente'),
      origin:node('Secretaría académica'),category:node('case_evidence'),document_id:node('')};
    const fields=new Map(['#evidence-cancel','#evidence-submit','#evidence-version','#evidence-error','#evidence-progress'].map(key=>[key,node()]));
    return {isConnected:true,elements:controls,reportValidity:()=>Boolean(controls.origin.value&&controls.title.value&&controls.file.files.length),
      querySelector:key=>fields.get(key),querySelectorAll:()=>[...Object.values(controls),...fields.values()]};
  }
  const open=(title,html)=>{
    if(active)active.isConnected=false;
    if(html.includes('id="evidence-form"'))active=formNode();
    else{const fields=new Map(['#evidence-return','#evidence-return-error'].map(key=>[key,node()]));active={isConnected:true,querySelector:key=>fields.get(key)};}
    opened.push({title,html,node:active});
  };
  const close=()=>{if(active)active.isConnected=false;};
  globalThis.document={querySelector:()=>active,querySelectorAll:()=>[]};
  globalThis.FormData=class{
    constructor(form){this.values=new Map(Object.entries(form.elements).map(([key,value])=>[key,key==='file'?value.files[0]:value.value]));}
    get(key){return this.values.get(key);}set(key,value){this.values.set(key,value);}delete(key){this.values.delete(key);}
  };
  globalThis.fetch=async(url,options)=>{
    calls.push({url,options});
    if(url.startsWith('/api/sources'))return {ok:true,json:async()=>({sources:[]})};
    if(reject)throw reject;
    const value=typeof response==='function'?await response():response;
    return {ok:true,json:async()=>({case_id:'case-a',request_id:'P1',source_id:'source-1',title:'Guía vigente',extraction_status:'ready',search_status:'running',...value})};
  };
  const upload=createEvidenceUpload({open,close,notice:v=>notices.push(v),getData:()=>({requests:[{id:'P1',title:'Constancia académica'}]}),
    getCase:()=>current,changed(){},render(){},onUpdated});
  return {upload,opened,notices,calls,get active(){return active;},changeCase:()=>{current={...current,id:'case-b'};},
    submit:()=>active.onsubmit({preventDefault(){}})};
}

test('contexto visible y cancelar devuelven al pendiente sin cargar ni resolver',async()=>{
  let cancelled=0;const h=harness();
  await h.upload.uploadForm('P1',false,null,null,{description:'Canal <oficial>',onCancel:async()=>{cancelled++;}});
  const html=h.opened[0].html;
  assert.match(html,/Respaldo para este pendiente/);assert.match(html,/Canal &lt;oficial&gt;/);
  assert.match(html,/Constancia académica/);assert.match(html,/Guardar respaldo/);
  assert.match(html,/name="origin"[^>]*required/);
  await h.active.querySelector('#evidence-cancel').onclick();
  assert.equal(cancelled,1);assert.ok(h.calls.every(call=>!call.options?.method));
});

test('guardar conserva vínculo, espera confirmación manual para volver y nunca resuelve',async()=>{
  const order=[];let receipt;
  const h=harness({onUpdated:async value=>{order.push('updated');receipt=value;}});
  await h.upload.uploadForm('P1',false,null,null,{description:'Documentos requeridos',onUploaded:async value=>{assert.equal(value,receipt);order.push('return');}});
  const form=h.active,file=form.elements.file.files[0];
  await h.submit();
  assert.deepEqual(order,['updated']);
  const post=h.calls.find(call=>call.options?.method==='POST');
  assert.equal(post.url,'/api/evidence');assert.equal(post.options.body.get('case_id'),'case-a');
  assert.equal(post.options.body.get('version'),7);assert.equal(post.options.body.get('request_id'),'P1');
  assert.equal(post.options.body.get('origin'),'Secretaría académica');assert.equal(post.options.body.get('file'),file);
  assert.match(h.opened.at(-1).html,/búsqueda de respaldo está en curso/);
  assert.match(h.opened.at(-1).html,/no confirma ni resuelve/);
  assert.ok(!h.calls.some(call=>/review|approve/.test(call.url)));
  await h.active.querySelector('#evidence-return').onclick();
  assert.deepEqual(order,['updated','return']);
});

test('error de carga conserva archivo y campos; origen sigue siendo obligatorio',async()=>{
  const h=harness({reject:new Error('No se pudo leer la respuesta del servidor')});
  await h.upload.uploadForm('P1',false,null,null,{description:'Comprobar canal'});
  const form=h.active,file=form.elements.file.files[0];
  form.elements.origin.value='';await h.submit();
  assert.ok(!h.calls.some(call=>call.options?.method));
  form.elements.origin.value='Dependencia consultada';await h.submit();
  assert.equal(h.active,form);assert.equal(form.elements.file.files[0],file);
  assert.equal(form.elements.title.value,'Guía vigente');assert.equal(form.elements.origin.value,'Dependencia consultada');
  assert.match(form.querySelector('#evidence-error').textContent,/servidor/);
  assert.equal(form.querySelector('#evidence-submit').disabled,false);
});

test('fallos de actualización o retorno no se confunden con un archivo no guardado',async()=>{
  const h=harness({onUpdated:async()=>{throw new Error('Estado temporalmente no disponible');}});
  await h.upload.uploadForm('P1',false,null,null,{description:'Canal',onUploaded:async()=>{throw new Error('No se pudo abrir el pendiente');}});
  await h.submit();
  assert.equal(h.opened.at(-1).title,'Respaldo guardado');
  assert.match(h.opened.at(-1).html,/No se pudo actualizar el estado/);
  const saved=h.active;await saved.querySelector('#evidence-return').onclick();
  assert.match(saved.querySelector('#evidence-return-error').textContent,/El archivo está guardado/);
  assert.equal(saved.querySelector('#evidence-return').disabled,false);
  assert.equal(h.calls.filter(call=>call.options?.method==='POST').length,1);
});

test('cambiar de expediente bloquea enviar o retornar al caso incorrecto',async()=>{
  const h=harness();await h.upload.uploadForm('P1',false,null,null,{description:'Canal'});
  h.changeCase();await h.submit();
  assert.match(h.active.querySelector('#evidence-error').textContent,/expediente cambió/);
  assert.ok(!h.calls.some(call=>call.options?.method));
  let updated=0,returned=0,release;
  const pending=new Promise(resolve=>{release=resolve;});
  const second=harness({response:()=>pending,onUpdated:async()=>{updated++;}});
  await second.upload.uploadForm('P1',false,null,null,{description:'Canal',onUploaded:async()=>{returned++;}});
  const work=second.submit();second.changeCase();release({});await work;
  assert.equal(updated,0);assert.equal(returned,0);
  assert.equal(second.opened.length,1);
});

test('lectura fallida distingue original conservado de respaldo utilizable',async()=>{
  const h=harness({response:{extraction_status:'error',extraction_error:'El PDF no tiene texto legible',search_status:'not_requested'}});
  await h.upload.uploadForm('P1',false,null,null,{description:'Canal'});await h.submit();
  assert.match(h.opened.at(-1).html,/original está guardado, pero no pudo leerse/);
  assert.match(h.opened.at(-1).html,/no confirma ni resuelve/);
  assert.doesNotMatch(h.opened.at(-1).html,/búsqueda de respaldo está en curso/);
});

test('llamadas sin contexto conservan el flujo público de cuatro argumentos',async()=>{
  let updated=0;const h=harness({onUpdated:async()=>{updated++;}});
  await h.upload.uploadForm('P1',false,null,null);assert.match(h.opened[0].html,/Guardar y revisar fuentes/);
  const form=h.active;await h.submit();
  assert.equal(updated,1);assert.equal(form.isConnected,false);assert.equal(h.opened.length,1);
});
