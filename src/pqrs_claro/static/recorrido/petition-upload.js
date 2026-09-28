import {esc} from './views.js';
export function showPetitionUpload({container,upload,choose,demo,gmail}){
  container.innerHTML=`<section class="petition-home receipt-page">
    <div class="receipt-heading"><div><p class="eyebrow">NUEVO INGRESO</p><h1>Recibir expedientes</h1><p class="home-subtitle">${gmail?'Desde un PDF o desde Gmail. Elige cómo recibir la solicitud.':'Carga los documentos y déjalos listos para asignar.'}</p></div><button type="button" class="receipt-back" id="home-cases"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16v16H4zM4 14h5l2 3h2l2-3h5"/></svg>Bandeja de PQRS</button></div>
    <div class="receipt-body">

    <div class="receipt-layout receipt-inputs"><section class="petition-home-card receipt-main" aria-labelledby="receipt-documents-title">
      <div class="receipt-section-heading"><h2 id="receipt-documents-title">Archivos PDF</h2><span id="receipt-count">Sin archivos</span></div>
      <form id="petition-upload-form">
        <div id="petition-dropzone" class="petition-dropzone receipt-dropzone">
          <span class="receipt-upload-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M12 17v-6m-3 3 3-3 3 3"/></svg></span>
          <h3>Arrastra tus PDF aquí</h3><p>Un documento por expediente, con todas sus peticiones.</p>
          <label class="petition-file-label">Seleccionar archivos<input id="petition-pdf" type="file" multiple accept=".pdf,application/pdf" aria-label="Seleccionar archivos PDF"></label>
          <p class="upload-limit">Hasta 20 archivos por carga</p>
        </div>
        <div class="receipt-date-row"><label class="field">Fecha de recepción<input type="date" name="received_date" required aria-describedby="receipt-date-help"></label><p id="receipt-date-help">Se aplicará a todos los documentos de esta carga.</p></div>
        <div id="petition-selection" aria-live="polite"></div><p id="petition-upload-error" role="alert"></p>
        <div class="petition-upload-actions receipt-footer"><p id="receipt-action-help">Selecciona los documentos para continuar.</p><button type="submit" class="primary" disabled id="petition-upload-submit">Recibir expedientes</button></div>
      </form>
    </section>
    ${gmail?`<section class="petition-home-card receipt-main receipt-email" aria-labelledby="receipt-email-title">
      <div class="receipt-section-heading"><h2 id="receipt-email-title">Correos electrónicos</h2><span class="receipt-provider">Gmail</span></div>
      <div class="receipt-email-zone">
        <span class="receipt-upload-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/></svg></span>
        <h3>Recibe solicitudes desde tu correo</h3><p>Consulta los mensajes y elige cuál incorporar como expediente.</p>
        <button type="button" id="home-gmail">Abrir correos de Gmail <span aria-hidden="true">→</span></button>
        <p class="receipt-email-hint">Selecciona el mensaje o su PDF adjunto.</p>
      </div>
      <p class="receipt-email-note">Revisa el contenido del correo antes de recibirlo. También puedes vincularlo a un expediente existente.</p>
      <div class="receipt-email-footer">Tú eliges qué correos incorporar a la bandeja de PQRS.</div>
    </section>`:''}</div>
    <aside class="receipt-guidance" aria-label="Proceso de recepción"><section class="receipt-next"><h2>¿Qué pasa después?</h2><ol><li><span>01</span><div><strong>Recibe</strong><p>El expediente queda en la bandeja, sin asignar.</p></div></li><li><span>02</span><div><strong>Asigna</strong><p>Un gestor toma el expediente completo.</p></div></li><li><span>03</span><div><strong>Inicia la gestión</strong><p>Se identifican sus peticiones para preparar la respuesta.</p></div></li></ol></section><button class="receipt-demo" id="home-demo">Explorar la demostración →</button></aside>
    </div>

  </section>`;
  const form=container.querySelector('form'),input=form.querySelector('#petition-pdf'),zone=form.querySelector('#petition-dropzone'),selection=form.querySelector('#petition-selection'),error=form.querySelector('[role=alert]'),submit=form.querySelector('[type=submit]');
  container.querySelector('#home-cases').onclick=choose;container.querySelector('#home-demo').onclick=demo;if(gmail)container.querySelector('#home-gmail').onclick=gmail;
  const today=new Date();form.elements.received_date.value=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  let selected=[],maxBytes=20*1048576,busy=false;
  function pick(files){if(busy)return;error.textContent='';selected=[];selection.innerHTML='';submit.disabled=true;container.querySelector('#receipt-count').textContent='Sin archivos';container.querySelector('#receipt-action-help').textContent='Selecciona los documentos para continuar.';if(!files.length||files.length>20){error.textContent='Selecciona entre 1 y 20 PDF.';return;}if([...files].some(f=>!f.name.toLowerCase().endsWith('.pdf')||!f.size||f.size>maxBytes)){error.textContent='Todos los archivos deben ser PDF no vacíos dentro del límite de tamaño.';return;}
    selected=[...files].map(file=>({file,done:false}));submit.disabled=false;submit.textContent='Recibir expedientes';container.querySelector('#receipt-count').textContent=`${selected.length} ${selected.length===1?'archivo':'archivos'}`;container.querySelector('#receipt-action-help').textContent='Quedarán en Por asignar, sin iniciar el análisis.';
    selection.innerHTML=selected.map((item,i)=>`<fieldset class="receipt-file" data-receipt="${i}"><legend>${esc(item.file.name)}</legend><div class="receipt-file-fields"><label class="field">Asunto<input name="subject-${i}" maxlength="240" value="${esc(item.file.name.replace(/\.pdf$/i,''))}"></label><label class="field">Radicado (opcional)<input name="reference-${i}" maxlength="100"></label><label class="field">Fecha límite registrada (opcional)<input name="due-${i}" type="date"></label></div><p data-receipt-status>Listo para recibir · ${(item.file.size/1024).toFixed(0)} KB</p></fieldset>`).join('');
  }
  input.onchange=()=>pick(input.files);zone.ondragover=e=>{e.preventDefault();zone.classList.add('dragover');};zone.ondragleave=()=>zone.classList.remove('dragover');zone.ondrop=e=>{e.preventDefault();zone.classList.remove('dragover');pick(e.dataTransfer.files);};
  form.onsubmit=async event=>{event.preventDefault();if(busy||!selected.length)return;busy=true;submit.disabled=true;input.disabled=true;error.textContent='';
    const date=form.elements.received_date.value;
    try{for(const [i,item] of selected.entries()){if(item.done)continue;const row=selection.querySelector(`[data-receipt="${i}"]`);row.querySelector('[data-receipt-status]').textContent='Guardando…';try{const result=await upload(item.file,{subject:form.elements[`subject-${i}`].value,reference:form.elements[`reference-${i}`].value,received_date:date,due_date:form.elements[`due-${i}`].value});item.done=true;row.querySelector('[data-receipt-status]').textContent='Recibido · PQRS-'+result.id.slice(0,12).toUpperCase();row.querySelectorAll('input').forEach(el=>el.disabled=true);}catch(e){row.querySelector('[data-receipt-status]').textContent='No recibido: '+e.message;}}
      const received=selected.filter(i=>i.done).length;error.textContent=received===selected.length?'':`${received} de ${selected.length} recibidos. Puedes reintentar únicamente los pendientes.`;submit.textContent=received===selected.length?'Expedientes recibidos':'Reintentar pendientes';container.querySelector('#receipt-action-help').textContent=received===selected.length?'Listo. Puedes continuar en la bandeja.':'Los documentos recibidos ya están guardados.';
    }finally{busy=false;submit.disabled=selected.every(i=>i.done);input.disabled=false;}
  };
  fetch('/api/config').then(r=>r.json()).then(config=>{if(!form.isConnected)return;maxBytes=config.max_upload_mb*1048576;form.querySelector('.upload-limit').textContent=`Hasta 20 archivos · ${config.max_upload_mb} MB y ${config.max_pages} páginas por PDF`;}).catch(()=>{});
}
