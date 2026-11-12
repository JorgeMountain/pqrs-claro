import {esc} from './views.js';
import {icon} from './inbox-icons.js';
import {receiveDocument} from './receipt-flow.js';
import {actor,request} from './management-ui.js?v=phase2';

export function createReceiptPanel({container,upload,gmail,onSaved,onComplete,getManager}){
  let items=[],busy=false,maxBytes=20*1048576,receivedMode=null;
  container.innerHTML=`<section class="inbox-receipt"><h2>Nuevo expediente</h2>
    <div class="receipt-source-tabs" role="group" aria-label="Origen del documento"><button type="button" data-receipt-source="pdf" aria-pressed="true">Archivo PDF</button><button type="button" data-receipt-source="gmail" aria-pressed="false">Correo Gmail</button></div>
    <div data-receipt-gmail hidden><p>Elige un correo o su PDF adjunto para incorporarlo como expediente.</p><button type="button" class="primary" data-receipt-mail>Elegir correo de Gmail</button></div>
    <form data-receipt-form>
      <div class="inbox-dropzone" data-receipt-drop>${icon('file-up')}<strong>Arrastra tus PDF aquí</strong><p>Un documento por expediente, con todas sus peticiones.</p><label class="inbox-file-picker">Seleccionar archivos<input type="file" multiple accept=".pdf,application/pdf" aria-label="Seleccionar archivos PDF"></label><small data-receipt-limit>Hasta 20 archivos</small></div>
      <div class="inbox-file-list" data-receipt-files aria-live="polite"></div>
      <label class="field">Fecha de recepción<input type="date" name="received_date" required></label>
      <details class="receipt-extra"><summary>Datos de recepción (opcional)</summary><label class="field">Asunto<input name="subject" maxlength="240" placeholder="Se usará el nombre del archivo"></label><label class="field">Radicado<input name="reference" maxlength="100"></label><label class="field">Fecha límite registrada<input type="date" name="due_date"></label><small>En una carga múltiple, estos datos se aplican a todos los archivos.</small></details>
      <p role="alert" data-receipt-error></p>
      <div class="receipt-destinations" role="group" aria-label="Destino del documento">
        <div><button type="button" class="inbox-receipt-submit" data-receipt-action="save" aria-describedby="receipt-pool-help" disabled>Agregar al pool</button><small id="receipt-pool-help">Queda sin asignar para que lo tome un gestor.</small></div>
        <div><button type="button" class="primary inbox-receipt-submit" data-receipt-action="analyze" aria-describedby="receipt-analysis-help" disabled>Iniciar análisis</button><small id="receipt-analysis-help"></small></div>
      </div>
      <p role="status" data-receipt-message></p>
    </form></section>`;
  const form=container.querySelector('form'),input=form.querySelector('[type=file]');
  const error=form.querySelector('[data-receipt-error]'),list=form.querySelector('[data-receipt-files]');
  const message=form.querySelector('[data-receipt-message]');
  const save=form.querySelector('[data-receipt-action="save"]'),analyze=form.querySelector('[data-receipt-action="analyze"]');
  const date=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Bogota',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  form.elements.received_date.value=date;

  function syncActions(){
    const manager=getManager();
    save.disabled=busy||!items.length||receivedMode==='analyze';
    analyze.disabled=busy||items.length!==1||!manager||receivedMode==='save';
    const help=form.querySelector('#receipt-analysis-help');
    if(items.length>1)help.textContent='Para iniciar el análisis, selecciona un solo PDF. Puedes agregar todos los archivos al pool.';
    else if(!manager)help.textContent='Selecciona tu gestor en la cabecera para iniciar el análisis.';
    else help.textContent=`Se asigna a ${manager.name} y abre el preanálisis para revisar el documento.`;
  }
  function draw(){
    list.innerHTML=items.map((item,i)=>`<div class="inbox-file-row"><span class="receipt-pdf-icon" aria-hidden="true">${icon('file')}<span>PDF</span></span><div><strong>${esc(item.file.name)}</strong><small data-file-state="${i}">${item.done?'Guardado':item.caseId?'Original guardado':item.file.size<1048576?Math.max(1,Math.round(item.file.size/1024))+' KB':(item.file.size/1048576).toFixed(1)+' MB'}</small></div>${!item.caseId?`<button type="button" data-file-remove="${i}" aria-label="Quitar ${esc(item.file.name)}">${icon('close')}</button>`:''}</div>`).join('');
    syncActions();
  }
  function pick(files){
    if(busy||!files.length)return;
    if(receivedMode){error.textContent='Termina la recepción pendiente antes de elegir otros archivos.';return;}
    const selected=[...files];
    if(selected.length>20){error.textContent='Selecciona hasta 20 archivos PDF.';return;}
    if(selected.some(f=>!f.name.toLowerCase().endsWith('.pdf')||!f.size||f.size>maxBytes)){error.textContent='Selecciona PDF no vacíos dentro del límite de tamaño.';return;}
    items=selected.map(file=>({file}));
    error.textContent='';message.textContent='';draw();
  }
  input.onchange=()=>pick(input.files);
  const zone=form.querySelector('[data-receipt-drop]');
  zone.ondragover=e=>{e.preventDefault();if(!busy)zone.classList.add('dragover');};
  zone.ondragleave=()=>zone.classList.remove('dragover');
  zone.ondrop=e=>{e.preventDefault();zone.classList.remove('dragover');pick(e.dataTransfer.files);};
  list.onclick=e=>{
    const b=e.target.closest('[data-file-remove]');if(!b||busy||items[Number(b.dataset.fileRemove)]?.caseId)return;
    items.splice(Number(b.dataset.fileRemove),1);input.value='';draw();
  };
  container.querySelectorAll('[data-receipt-source]').forEach(b=>b.onclick=()=>{
    if(busy)return;
    container.querySelectorAll('[data-receipt-source]').forEach(n=>n.setAttribute('aria-pressed',String(n===b)));
    form.hidden=b.dataset.receiptSource!=='pdf';container.querySelector('[data-receipt-gmail]').hidden=!form.hidden;
  });
  container.querySelector('[data-receipt-mail]').onclick=()=>gmail();
  form.onsubmit=e=>e.preventDefault();

  async function submit(mode){
    if(busy||!items.length||(receivedMode&&receivedMode!==mode)||!form.reportValidity())return;
    const manager=actor();
    if(mode==='analyze'&&(items.length!==1||!manager))return;
    if(form.elements.due_date.value&&form.elements.due_date.value<form.elements.received_date.value){
      error.textContent='La fecha límite no puede ser anterior a la recepción.';return;
    }
    const metadata=Object.fromEntries(new FormData(form));
    busy=true;error.textContent='';message.textContent='Guardando…';
    form.querySelectorAll('input,button').forEach(n=>n.disabled=true);
    try{
      for(const [i,item] of items.entries()){
        if(item.done)continue;
        const row=list.querySelector(`[data-file-state="${i}"]`);
        row.textContent=item.caseId?'Retomando el expediente…':'Guardando documento…';
        try{
          await receiveDocument(item,{mode,manager,metadata:{...metadata,subject:metadata.subject||item.file.name.replace(/\.pdf$/i,'')},upload,request});
          item.done=true;row.textContent=mode==='save'?'Guardado en el pool':'Asignado para preanálisis';
        }catch(err){row.textContent=item.caseId?'Original guardado · asignación pendiente':'No guardado';error.textContent=err.message;}
      }
      if(items.some(item=>item.caseId))receivedMode=mode;
      if(items.some(item=>!item.done)){
        list.querySelectorAll('[data-file-remove]').forEach(b=>{if(items[Number(b.dataset.fileRemove)].caseId)b.remove();});
        message.textContent=`${items.filter(item=>item.done).length} de ${items.length} completados. Puedes corregir los datos y reintentar los pendientes.`;
        await onSaved();return;
      }
      await onComplete(items[0].caseId,mode);
      items=[];receivedMode=null;form.reset();form.elements.received_date.value=date;message.textContent='';draw();
    }catch(err){error.textContent=err.message;message.textContent='Vuelve a pulsar la acción para continuar con los documentos guardados.';}
    finally{
      busy=false;form.querySelectorAll('input,button').forEach(n=>n.disabled=false);syncActions();
    }
  }
  save.onclick=()=>submit('save');analyze.onclick=()=>submit('analyze');
  syncActions();
  request('/api/config').then(config=>{if(!form.isConnected)return;maxBytes=config.max_upload_mb*1048576;form.querySelector('[data-receipt-limit]').textContent=`Hasta 20 archivos · ${config.max_upload_mb} MB y ${config.max_pages} páginas por PDF.`;}).catch(()=>{});
  return {busy:()=>busy,syncManager:syncActions};
}
