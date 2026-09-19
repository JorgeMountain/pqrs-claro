import {esc} from './views.js';
import {connectionView,messageList,importView,originalView} from './gmail-views.js?v=20260916-mail';

async function api(path,body,method='POST'){
  const response=await fetch('/api/gmail'+path,body===undefined?{}:{method,body:body instanceof FormData?body:JSON.stringify(body),headers:body instanceof FormData?{}:{'Content-Type':'application/json'}});
  const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'No se pudo completar la operación con Gmail.');return value;
}
export function createGmail({open,close,notice,onOpenCase}){
  let poll, label='PQRS-Pruebas';
  const panel=()=>document.querySelector('#gmail-panel');
  function shell(title){clearTimeout(poll);open(title,'<section id="gmail-panel" class="gmail-panel"><div id="gmail-content"><p role="status">Cargando…</p></div><p id="gmail-operation" role="status"></p><p id="gmail-error" role="alert"></p></section>');return panel();}
  async function action(node,work){
    if(node.dataset.busy)return;node.dataset.busy='true';node.setAttribute('aria-busy','true');
    node.querySelector('#gmail-error').textContent='';node.querySelector('#gmail-operation').textContent='Procesando…';
    node.querySelectorAll('button,input,select').forEach(b=>b.disabled=true);
    try{await work();}catch(e){if(node.isConnected)node.querySelector('#gmail-error').textContent=e.message;}
    finally{delete node.dataset.busy;node.removeAttribute('aria-busy');if(node.isConnected){node.querySelector('#gmail-operation').textContent='';node.querySelectorAll('button,input,select').forEach(b=>b.disabled=false);}}
  }
  async function show(){
    const node=shell('Peticiones recibidas · Gmail');
    await action(node,async()=>{const status=await api('/status');if(!node.isConnected)return;node.querySelector('#gmail-content').innerHTML=connectionView(status);if(status.configured&&!status.connected)node.querySelector('#gmail-content').insertAdjacentHTML('beforeend','<details><summary>Cambiar configuración de Google</summary><form id="gmail-config"><label class="field">Nuevo archivo de configuración de Google<input name="file" type="file" accept=".json,application/json" required></label><button>Guardar configuración</button></form></details>');bind(node,status);});
  }
  function bind(node,status){
    const content=node.querySelector('#gmail-content');
    content.querySelector('#gmail-config')?.addEventListener('submit',event=>{event.preventDefault();const data=new FormData(event.currentTarget);void action(node,async()=>{const file=data.get('file');if(!file?.size||file.size>65536)throw new Error('Selecciona el JSON de Google, de hasta 64 KB.');await api('/configure',data);await show();});});
    content.querySelector('[data-mail="disconnect"]')?.addEventListener('click',()=>void action(node,async()=>{await api('/disconnect',{});await show();notice('Cuenta desconectada en este equipo. Los expedientes importados se conservan.');}));
    content.querySelector('[data-mail="connect"]')?.addEventListener('click',()=>{
      const popup=window.open('about:blank','pqrs-gmail-oauth','width=620,height=740');
      if(!popup){node.querySelector('#gmail-error').textContent='Permite la ventana de Google para conectar tu cuenta.';return;}
      popup.opener=null;
      void action(node,async()=>{try{const auth=await api('/authorize',{});popup.location.href=auth.url;watch(node,Date.now()+600000);notice('Completa la autorización en la ventana de Google.');}catch(e){popup.close();throw e;}});
    });
    const query=content.querySelector('#gmail-query');
    if(query){query.elements.label.value=label;query.addEventListener('submit',event=>{event.preventDefault();label=query.elements.label.value.trim();void load(node,status.account);});}
  }
  function watch(node,deadline){
    clearTimeout(poll);if(!node.isConnected||Date.now()>deadline)return;
    poll=setTimeout(async()=>{if(!node.isConnected)return;try{const status=await api('/status');if(status.connected){await show();notice('Conectado a '+status.account);return;}}catch(e){if(node.isConnected)node.querySelector('#gmail-error').textContent=e.message;}watch(node,deadline);},2000);
  }
  async function load(node,account,pageToken='',previous=[]){
    await action(node,async()=>{
      const data=await api('/messages?'+new URLSearchParams({label,page_token:pageToken}));
      if(!node.isConnected)return;if(data.account!==account)throw new Error('La cuenta cambió. Cierra y vuelve a abrir la bandeja.');
      data.messages=[...new Map([...previous,...data.messages].map(m=>[m.id,m])).values()];
      const list=node.querySelector('#gmail-list');list.innerHTML=messageList(data);
      list.querySelectorAll('[data-message]').forEach(b=>b.onclick=()=>void detail(b.dataset.message,account));
      list.querySelector('[data-mail="more"]')?.addEventListener('click',()=>void load(node,account,data.next_page,data.messages));
    });
  }
  async function detail(id,account){
    const node=shell('Correo recibido');
    await action(node,async()=>{
      const [message,response]=await Promise.all([api(`/messages/${encodeURIComponent(id)}?`+new URLSearchParams({account})),fetch('/api/cases')]);
      if(!response.ok)throw new Error('No se pudieron consultar los expedientes.');const cases=await response.json();
      if(!node.isConnected)return;const content=node.querySelector('#gmail-content');
      content.innerHTML='<button class="text-button" data-mail="back">← Volver a la bandeja</button>'+importView(message,cases);
      content.querySelector('[data-mail="back"]').onclick=()=>void show();
      content.querySelector('[data-open-case]')?.addEventListener('click',()=>void action(node,async()=>{await onOpenCase(message.case_id);close();}));
      const form=content.querySelector('#gmail-import');if(!form)return;
      const update=()=>{const mode=form.elements.mode.value;form.querySelectorAll('[data-mode]').forEach(e=>e.hidden=e.dataset.mode!==mode);form.querySelector('#gmail-import-submit').textContent=mode==='link'?'Vincular correo':'Crear expediente y analizar';};
      form.elements.mode.onchange=update;update();
      form.onsubmit=event=>{event.preventDefault();const body={account,mode:form.elements.mode.value,case_number:form.elements.case_number.value,attachment_id:form.elements.attachment_id?.value||null,body_confirmed:form.elements.body_confirmed.checked,target_case_id:form.elements.target_case_id?.value||null};void action(node,async()=>{
        const result=await api(`/messages/${encodeURIComponent(id)}/import`,body);
        if(!result.duplicate&&!result.linked){const response=await fetch(`/api/cases/${result.case_id}/analyze`,{method:'POST'});if(!response.ok){const error=await response.json();await onOpenCase(result.case_id);close();notice('Expediente guardado. '+(error.detail||'Puedes reintentar el análisis.'));return;}}
        await onOpenCase(result.case_id);close();notice(result.duplicate?'Este correo ya estaba incorporado.':result.linked?'Correo vinculado al expediente.':'Petición incorporada desde Gmail.');
      });};
    });
  }
  async function showCase(caseId){
    const node=shell('Correos del expediente');
    await action(node,async()=>{const data=await api('/cases/'+encodeURIComponent(caseId));if(!node.isConnected)return;node.querySelector('#gmail-content').innerHTML=data.messages.length?data.messages.map(m=>`<section class="gmail-saved-message">${originalView(m)}<p class="gmail-hint">Número de caso registrado: ${esc(m.reported_case_number||'Sin número')}</p></section>`).join(''):'<p>Este expediente no tiene correos incorporados.</p>';});
  }
  return {show,showCase};
}
