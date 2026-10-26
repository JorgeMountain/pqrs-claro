import {esc} from './views.js';
import {icon} from './inbox-icons.js';
import {receiveDocument} from './receipt-flow.js';
import {actor,request} from './management-ui.js?v=phase2';

export function createReceiptPanel({container,mode,upload,gmail,onSaved,onComplete,getManager}){
  const direct=mode==='analyze';
  let items=[],busy=false,maxBytes=20*1048576,source='pdf';
  container.innerHTML=`<section class="inbox-receipt"><h2>${direct?'Nuevo expediente':'Subir a bandeja'}</h2><p class="muted">${direct?'Carga un documento para trabajarlo ahora.':'Guarda documentos en el pool, disponibles para el equipo.'}</p>
    <div class="receipt-source-tabs" role="group" aria-label="Origen del documento"><button type="button" data-receipt-source="pdf" aria-pressed="true">Archivo PDF</button><button type="button" data-receipt-source="gmail" aria-pressed="false">Correo Gmail</button></div>
    <div data-receipt-gmail hidden><p>Elige un correo o su PDF adjunto y revisa el contenido antes de incorporarlo.</p><button type="button" class="primary" data-receipt-mail>Elegir correo de Gmail</button><p class="inbox-panel-hint">${direct?'Al pulsar «Revisar documento» en la recepción del correo se asignará a ti y abrirá el preanálisis.':'El correo se guardará sin revisar el documento.'}</p></div>
    <form data-receipt-form><div class="inbox-dropzone" data-receipt-drop>${icon('file-up')}<strong>${direct?'Arrastra tu PDF aquí':'Arrastra tus PDF aquí'}</strong><p>Un documento por expediente, con todas sus peticiones.</p><label class="inbox-file-picker">${direct?'Seleccionar archivo':'Seleccionar archivos'}<input type="file" ${direct?'':'multiple'} accept=".pdf,application/pdf" aria-label="${direct?'Seleccionar archivo PDF':'Seleccionar archivos PDF'}"></label><small data-receipt-limit>Hasta ${direct?'1 archivo':'20 archivos'}</small></div>
    <div class="inbox-file-list" data-receipt-files aria-live="polite"></div>
    <label class="field">Fecha de recepción<input type="date" name="received_date" required></label>
    ${direct?`<div class="receipt-manager"><span>Responsable</span><div>${icon('user')}<span data-receipt-manager></span></div></div>`:''}<p role="alert" data-receipt-error></p><button class="primary inbox-receipt-submit" type="submit" disabled>${direct?'Revisar documento':'Guardar en el pool'}</button><p class="inbox-panel-hint">${direct?'Se asignará a ti y abrirá el preanálisis. Tú decides cuándo iniciar la identificación.':'Quedarán sin asignar y sin analizar para que un gestor los tome.'}</p><div class="receipt-human-note">${icon('info')}<p>Revisión humana requerida.<br>No se aprueban respuestas automáticamente.</p></div><details class="receipt-extra"><summary>Datos de recepción (opcional)</summary><label class="field">Asunto<input name="subject" maxlength="240" placeholder="Se usará el nombre del archivo"></label><label class="field">Radicado<input name="reference" maxlength="100"></label><label class="field">Fecha límite registrada<input type="date" name="due_date"></label><small>Para cargas múltiples, estos datos se aplican a todos los archivos. La fecha límite es manual.</small></details><p role="status" data-receipt-message></p></form></section>`;
  const form=container.querySelector('form'),input=form.querySelector('[type=file]'),submit=form.querySelector('[type=submit]'),error=form.querySelector('[role=alert]'),list=form.querySelector('[data-receipt-files]');
  const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Bogota',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  form.elements.received_date.value=date;
  const syncManager=()=>{const n=form.querySelector('[data-receipt-manager]');if(n)n.textContent=getManager()?.name||'Selecciona tu gestor en la cabecera';};
  syncManager();
  function draw(){
    list.innerHTML=items.map((item,i)=>`<div class="inbox-file-row"><span class="receipt-pdf-icon" aria-hidden="true">${icon('file')}<span>PDF</span></span><div><strong>${esc(item.file.name)}</strong><small data-file-state="${i}">${item.done?'Guardado':item.caseId?'Guardado · pendiente de iniciar':`${item.file.size<1048576?Math.max(1,Math.round(item.file.size/1024))+' KB':(item.file.size/1048576).toFixed(1)+' MB'}`}</small></div><span class="receipt-file-ready" title="Archivo seleccionado">${icon('check')}</span>${!item.caseId?`<button type="button" data-file-remove="${i}" aria-label="Quitar ${esc(item.file.name)}">${icon('close')}</button>`:''}</div>`).join('');
    submit.disabled=busy||!items.length||items.every(i=>i.done);
  }
  function pick(files){
    if(busy)return;
    error.textContent='';
    if(items.some(i=>i.caseId&&!i.done)){error.textContent='Hay un expediente guardado pendiente de iniciar. Reintenta antes de elegir otro archivo.';return;}
    const selected=[...files];
    if(!selected.length||selected.length>(direct?1:20)){error.textContent=`Selecciona ${direct?'un PDF':'entre 1 y 20 PDF'}.`;return;}
    if(selected.some(f=>!f.name.toLowerCase().endsWith('.pdf')||!f.size||f.size>maxBytes)){error.textContent='Selecciona PDF no vacíos dentro del límite de tamaño.';return;}
    items=selected.map(file=>({file}));submit.textContent=direct?'Revisar documento':'Guardar en el pool';form.querySelector('[data-receipt-message]').textContent='';draw();
  }
  input.onchange=()=>pick(input.files);
  const zone=form.querySelector('[data-receipt-drop]');
  zone.ondragover=e=>{e.preventDefault();if(!busy)zone.classList.add('dragover');};
  zone.ondragleave=()=>zone.classList.remove('dragover');
  zone.ondrop=e=>{e.preventDefault();zone.classList.remove('dragover');pick(e.dataTransfer.files);};
  list.onclick=e=>{const b=e.target.closest('[data-file-remove]');if(b&&!busy){items.splice(Number(b.dataset.fileRemove),1);input.value='';draw();}};
  container.querySelectorAll('[data-receipt-source]').forEach(b=>b.onclick=()=>{
    if(busy)return;source=b.dataset.receiptSource;
    container.querySelectorAll('[data-receipt-source]').forEach(n=>n.setAttribute('aria-pressed',String(n===b)));
    form.hidden=source!=='pdf';container.querySelector('[data-receipt-gmail]').hidden=source!=='gmail';
  });
  container.querySelector('[data-receipt-mail]').onclick=()=>gmail(mode);
  form.onsubmit=async e=>{
    e.preventDefault();if(busy||!items.length)return;
    if(direct&&!actor()){error.textContent='Selecciona tu gestor en la cabecera antes de revisar el documento.';return;}
    if(form.elements.due_date.value&&form.elements.due_date.value<form.elements.received_date.value){error.textContent='La fecha límite no puede ser anterior a la recepción.';return;}
    const manager=actor(),metadata=Object.fromEntries(new FormData(form));
    busy=true;error.textContent='';form.querySelectorAll('input,button').forEach(n=>n.disabled=true);
    try{
      for(const [i,item] of items.entries()){
        if(item.done)continue;
        const row=list.querySelector(`[data-file-state="${i}"]`);row.textContent=item.caseId?'Abriendo preanálisis…':'Guardando documento…';
        try{await receiveDocument(item,{mode,manager,metadata:{...metadata,subject:metadata.subject||item.file.name.replace(/\.pdf$/i,'')},upload,request,saved:onSaved});item.done=true;row.textContent=direct?'Listo para preanálisis':'Guardado en el pool';}
        catch(err){row.textContent=item.caseId?'Original guardado · inicio pendiente':'No guardado';error.textContent=err.message;}
      }
    }finally{busy=false;form.querySelectorAll('input,button').forEach(n=>n.disabled=false);submit.disabled=items.every(i=>i.done);submit.textContent=submit.disabled?(direct?'Listo para preanálisis':'Documentos guardados'):'Reintentar pendientes';}
    const complete=items.filter(i=>i.done);
    form.querySelector('[data-receipt-message]').textContent=`${complete.length} de ${items.length} ${direct?'documentos listos para preanálisis':'documentos guardados'}.`;
    await onSaved();
    if(direct&&items.every(i=>i.done)){const id=items[0].caseId;items=[];input.value='';draw();form.querySelector('[data-receipt-message]').textContent='';await onComplete(id);}
  };
  request('/api/config').then(config=>{if(!form.isConnected)return;maxBytes=config.max_upload_mb*1048576;form.querySelector('[data-receipt-limit]').textContent=`Hasta ${direct?'':'20 archivos · '}${config.max_upload_mb} MB y ${config.max_pages} páginas por PDF.`;}).catch(()=>{});
  return {busy:()=>busy,syncManager};
}
