import {esc} from './views.js';

export function showPetitionUpload({container,upload,choose,demo}){
  container.innerHTML=`<div class="petition-home"><h1>Prepara respuestas con respaldo</h1><p class="home-subtitle">Carga una petición o continúa uno de tus expedientes.</p><section class="petition-home-card"><h2>Comienza con una petición</h2><form id="petition-upload-form">
    <div id="petition-dropzone" class="petition-dropzone"><span class="petition-document-icon" aria-hidden="true">PDF</span><div class="petition-drop-copy"><h3>PDF de la petición</h3><p>Arrastra tu archivo aquí</p></div><label class="petition-file-label">Seleccionar un PDF<input id="petition-pdf" type="file" accept=".pdf,application/pdf"></label><p class="upload-limit">Un PDF por expediente</p></div>
    <div id="petition-selection" role="status" aria-live="polite"></div><p id="petition-upload-error" role="alert"></p>
    <div class="petition-upload-actions"><details class="petition-next"><summary>¿Qué pasa después?</summary><p>Verás las solicitudes identificadas junto al documento original. Podrás revisarlas antes de buscar fuentes y preparar las respuestas.</p><p>Los antecedentes y anexos se agregan en la biblioteca o como evidencia de una respuesta.</p></details><button type="submit" class="primary" disabled id="petition-upload-submit">Cargar y analizar</button></div></form></section><section class="petition-home-continue"><p>¿Ya tienes un expediente?</p><div class="home-links"><button id="home-cases">Mis expedientes</button><button id="home-demo">Ver demostración</button></div></section></div>`;
  container.querySelector('#home-cases').onclick=choose;container.querySelector('#home-demo').onclick=demo;
  const form=container.querySelector('form'),zone=form.querySelector('#petition-dropzone'),input=form.querySelector('#petition-pdf'),selection=form.querySelector('#petition-selection'),error=form.querySelector('#petition-upload-error'),submit=form.querySelector('#petition-upload-submit');
  let selected=null,depth=0,maxBytes=null;
  const size=bytes=>bytes>=1048576?`${(bytes/1048576).toFixed(1)} MB`:`${Math.ceil(bytes/1024)} KB`;
  function chooseFile(files){
    error.textContent='';selected=null;selection.innerHTML='';submit.disabled=true;
    if(files.length!==1){error.textContent='Selecciona un solo PDF para esta petición.';return;}
    const file=files[0];
    if(!file.name.toLowerCase().endsWith('.pdf')){error.textContent='El documento de la petición debe estar en formato PDF.';return;}
    if(!file.size){error.textContent='El archivo está vacío. Selecciona otro PDF.';return;}
    if(maxBytes&&file.size>maxBytes){error.textContent=`El PDF supera el límite de ${size(maxBytes)}.`;return;}
    selected=file;submit.disabled=false;
    selection.innerHTML=`<div class="petition-selected"><div><strong>${esc(file.name)}</strong><span>${size(file.size)} · Listo para cargar</span></div><button type="button" id="petition-remove">Quitar archivo</button></div>`;
    selection.querySelector('button').onclick=()=>{selected=null;input.value='';selection.innerHTML='';submit.disabled=true;input.focus();};
  }
  input.onchange=()=>{if(input.files.length)chooseFile(input.files);};
  zone.ondragenter=event=>{event.preventDefault();depth++;zone.classList.add('dragover');};
  zone.ondragover=event=>{event.preventDefault();event.dataTransfer.dropEffect='copy';};
  zone.ondragleave=event=>{event.preventDefault();if(--depth<=0)zone.classList.remove('dragover');};
  zone.ondrop=event=>{event.preventDefault();depth=0;zone.classList.remove('dragover');chooseFile(event.dataTransfer.files);};
  form.onsubmit=event=>{event.preventDefault();if(!selected||submit.disabled)return;if(maxBytes&&selected.size>maxBytes){error.textContent=`El PDF supera el límite de ${size(maxBytes)}.`;return;}submit.disabled=true;submit.textContent='Cargando petición…';Promise.resolve(upload(selected)).finally(()=>{if(form.isConnected){submit.disabled=false;submit.textContent='Cargar y analizar';}});};
  fetch('/api/config').then(r=>r.ok?r.json():null).then(config=>{if(!form.isConnected||!config)return;maxBytes=config.max_upload_mb*1048576||null;form.querySelector('.upload-limit').textContent=`Un PDF por expediente${maxBytes?' · Hasta '+size(maxBytes):''}${config.max_pages?' · '+config.max_pages+' páginas como máximo':''}`;}).catch(()=>{});
}
