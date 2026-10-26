// Interfaz de carga real. Las respuestas de la maqueta no se presentan como regeneradas.
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = {support_found:'Respaldo encontrado',confirmation_pending:'Confirmación pendiente',document_missing:'Documento faltante',analysis_error:'Error de análisis'};
const types = {case_evidence:'Soporte de esta petición',historical_response:'Respuesta anterior · antecedente',historical_attachment:'Anexo o soporte histórico',institutional_norm:'Normativa institucional',national_norm:'Normativa nacional'};
async function api(path, options={}) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Revisa los campos y vuelve a intentarlo.');
  return value;
}
export function createEvidenceUpload({open, close, render, notice, getData, changed, getCase=null, onUpdated=null}) {
  let caseId, version, connected=false, snapshot=null, timer, uploading=false, lastRender='';
  const original = id => `/api/sources/${encodeURIComponent(id)}/original?case_id=${encodeURIComponent(caseId)}`;
  const receipts = () => snapshot?.receipts || [];
  const post = value => ({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
  async function refresh() {
    if (!connected || !caseId) return;
    clearTimeout(timer);
    try {
      snapshot = await api(`/api/cases/${caseId}/evidence`);
      const key=JSON.stringify([snapshot.version,receipts(),snapshot.mapping.id,snapshot.mapping.status,snapshot.mapping.stale,snapshot.mapping.completed_count]);
      if(key!==lastRender){lastRender=key;changed(receipts().some(r=>r.sources_changed ?? !r.duplicate));render();}
      if (snapshot.mapping.status === 'running') timer=setTimeout(refresh,2500);
    } catch (error) { notice('No se pudo actualizar el estado: '+error.message); }
  }
  async function connect() {
    if(getCase){
      clearTimeout(timer);snapshot=null;lastRender='';
      const current=getCase();caseId=current?.status==='confirmed'?current.id:null;version=current?.version;
      connected=true;
      return;
    }
    caseId = new URLSearchParams(location.search).get('case');
    if (!caseId || !/^[a-f0-9]{32}$/.test(caseId)) return;
    try {
      const [current, config] = await Promise.all([api(`/api/cases/${caseId}`), api('/api/config')]);
      if (!getData().requests.every(r => current.identification?.requests.some(q => q.id===r.request_id && q.description===r.description))) {
        throw new Error('Esta vista no corresponde a las solicitudes del expediente seleccionado.');
      }
      version=current.version; connected=true;
      document.querySelector('.prototype-status').textContent='Fuentes conectadas';
      document.querySelector('.prototype').textContent=(config.validation_mode?'Copia aislada de prueba. ':'')+'La carga, lectura y búsqueda de fuentes son reales. La redacción y aprobación de esta vista siguen siendo de demostración.';
      await refresh();
    } catch (error) { notice(error.message); }
  }
  function panel(requestId) {
    if (!connected || !receipts().length) return '';
    const rows=receipts().filter(r=>!r.request_id || r.request_id===requestId);
    const mapping=snapshot.mapping;
    const finding=!mapping.stale && mapping.results?.find(f=>f.request_id===requestId);
    const current=finding;
    return `<section class="evidence-update" aria-label="Estado de fuentes actualizado"><strong>${mapping.status==='running'?'Revisando fuentes…':mapping.stale?'Fuentes actualizadas · búsqueda pendiente':'Revisión de fuentes'}</strong>
      ${rows.map(r=>`<p><a href="${original(r.source_id)}" target="_blank" rel="noopener">${escape(r.title)}</a> · versión ${r.source_version}<br><small>${r.duplicate?'Archivo ya existente, reutilizado. ':''}${r.extraction_status==='error'?'Error de lectura: '+escape(r.extraction_error):'Archivo guardado y leído.'}${finding && finding.status!=='error' && r.extraction_status!=='error'?(finding.supports?.some(s=>s.source_id===r.source_id)?' Se seleccionó como respaldo de este punto.':' No fue seleccionado como respaldo de este punto.'):''}</small></p>`).join('')}
      ${current?`<p>${(finding.evidence_states||[]).map(s=>escape(labels[s]||s)).join(' · ')}</p><p>${escape(finding.summary)}</p>`:''}
      ${finding?.status==='error'?`<p role="alert">${escape(finding.summary)}</p>`:''}
      <p class="muted">La respuesta guardada se conserva. Los archivos nuevos no aprueban ni reescriben el oficio automáticamente.</p>
      <button data-evidence-results="${escape(requestId)}">Ver resultado y pendientes</button></section>`;
  }
  function decorate() {
    document.querySelectorAll('[data-evidence-add]').forEach(b=>{b.disabled=!connected || uploading;b.title=connected?'':'Abre esta vista desde el servidor conectado.';b.onclick=()=>uploadForm(b.dataset.evidenceAdd);});
    document.querySelectorAll('[data-evidence-results]').forEach(b=>{b.onclick=()=>results(b.dataset.evidenceResults);});
  }
  async function results(requestId) {
    await refresh();
    const mapping=snapshot.mapping, finding=mapping.results?.find(f=>f.request_id===requestId);
    const rows=receipts().filter(r=>!r.request_id || r.request_id===requestId);
    const latest=receipts()[0];
    open('Resultado de la revisión de fuentes',`<p>${mapping.status==='running'?'La búsqueda está en curso. Puedes cerrar este panel; continuará y verás el resultado en la tarjeta.':mapping.stale?'Las fuentes cambiaron; hay que actualizar la búsqueda.':'Estos son los resultados de la búsqueda real.'}</p>
      ${rows.map(r=>`<section class="source"><h3>${escape(r.title)}</h3><p>${r.extraction_status==='error'?'Error de lectura: '+escape(r.extraction_error):'Contenido extraído y disponible para consulta.'}</p><a href="${original(r.source_id)}" target="_blank" rel="noopener">Abrir archivo guardado ↗</a>${r.search_error?`<p role="alert">${escape(r.search_error)}</p>`:''}</section>`).join('')}
      ${!mapping.stale && finding?`<p>${escape(finding.summary)}</p><h3>Pasajes seleccionados</h3>${finding.supports?.length?finding.supports.map(s=>`<section class="source"><strong>${escape(s.title)}</strong><small> · ${s.location_kind==='section'?'Sección':'Página'} ${s.page}</small><blockquote>${escape(s.quote)}</blockquote><p>${escape(s.reason)}</p><a href="${original(s.source_id)}" target="_blank" rel="noopener">Abrir original ↗</a></section>`).join(''):'<p>No se seleccionaron pasajes pertinentes. Esto no demuestra que el documento solicitado no exista.</p>'}<h3>Pendientes concretos</h3>${(finding.missing||[]).length?`<ul>${finding.missing.map(m=>`<li>${escape(m.description)}</li>`).join('')}</ul>`:'<p>No hay pendientes de evidencia registrados en este resultado. La revisión de la redacción sigue siendo independiente.</p>'}`:''}
      ${latest && mapping.status!=='running'?'<button id="evidence-retry">Actualizar búsqueda</button>':''}<button id="evidence-more">Agregar otra evidencia</button><p id="evidence-error" role="alert"></p>`);
    document.querySelector('#evidence-more').onclick=()=>uploadForm(requestId);
    document.querySelector('#evidence-retry')?.addEventListener('click',async e=>{
      e.target.disabled=true;
      try {const row=await api(`/api/cases/${caseId}/evidence/${latest.id}/search`,post({version}));if(row.search_error)throw new Error(row.search_error);close();await refresh();}
      catch(error){document.querySelector('#evidence-error').textContent=error.message;e.target.disabled=false;}
    });
  }
  async function uploadForm(requestId='', shared=false, previous=null, initialFile=null, context=null) {
    if(getCase)await connect();
    if(context&&!caseId){notice('Abre el expediente confirmado para agregar respaldo a este pendiente.');return;}
    if(!caseId&&previous?.case_id){notice('Confirma la identificación del expediente antes de agregar una versión de su evidencia.');return;}
    if(!caseId)shared=true;
    if (!connected) {notice('La carga necesita la versión conectada al expediente.');return;}
    const targetCaseId=caseId,targetVersion=version,openedCaseId=getCase?.()?.id||null;
    const sameCase=()=>!getCase||(getCase()?.id||null)===openedCaseId;
    const request=getData().requests.find(r=>(r.request_id||r.id)===requestId);
    open(shared?'Agregar fuente a la biblioteca':context?'Agregar respaldo':'Agregar evidencia',`${context?.description?`<section class="redaction-context-request"><strong>Respaldo para este pendiente</strong><p>${escape(context.description)}</p></section>`:''}<p>${request?escape(request.title):targetCaseId?'El documento podrá servir como fuente para las solicitudes de esta petición.':'El documento quedará disponible en la biblioteca de fuentes.'}</p><form id="evidence-form">
      <label class="field">Archivo<input id="evidence-file" name="file" type="file" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg" required></label><p class="muted"><small>PDF, Word, texto o imagen · hasta 20 MB. Se conserva el original.</small></p>
      <label class="field">Título<input name="title" id="evidence-title" maxlength="300" required></label>
      <label class="field">De dónde viene<input name="origin" maxlength="2000" placeholder="Por ejemplo: Secretaría, correo recibido el…" required></label>
      ${context?'<details><summary>Tipo de documento</summary>':''}<label class="field">Tipo de documento<select name="category" id="evidence-category">${Object.entries(types).filter(([key])=>!shared || key!=='case_evidence').map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label>${context?'<p class="muted">Por defecto, se agrega como soporte de esta petición.</p></details>':''}
      <details><summary>¿Es una nueva versión de un documento?</summary><label class="field">Documento que actualiza<select name="document_id" id="evidence-version"><option value="">Es otro documento</option></select></label><p class="muted">Conservaremos las versiones anteriores. Un nombre parecido no reemplaza un archivo.</p></details>
      <p class="muted">${shared?'Se guardará en la biblioteca compartida.'+(caseId?' Se incluirá en la búsqueda de esta petición.':''):'Se guardará como fuente de este expediente, vinculada a la solicitud.'} La carga no declara el archivo verificado.</p>
      <div class="dialog-actions"><button class="primary" id="evidence-submit" type="submit">${context?'Guardar respaldo':'Guardar y revisar fuentes'}</button><button id="evidence-cancel" type="button">${context?'Volver sin subir':'Cancelar'}</button></div><p id="evidence-progress" role="status"></p><p id="evidence-error" role="alert"></p></form>`);
    const form=document.querySelector('#evidence-form');
    form.querySelector('#evidence-cancel').onclick=async()=>{
      if(uploading)return;
      try{if(context?.onCancel&&sameCase())await context.onCancel();else close();}
      catch(error){if(form.isConnected)form.querySelector('#evidence-error').textContent=error.message;else notice(error.message);}
    };
    let sources=[];
    const versions=()=>{const category=form.elements.category.value;form.querySelector('#evidence-version').innerHTML='<option value="">Es otro documento</option>'+sources.filter(s=>s.is_latest && s.category===category && (shared?s.case_id===null:s.case_id===targetCaseId)).map(s=>`<option value="${escape(s.document_id)}">${escape(s.title)} · v${s.version}</option>`).join('');};
    form.elements.category.onchange=versions;
    form.elements.file.onchange=()=>{if(!form.elements.title.value)form.elements.title.value=form.elements.file.files[0]?.name.replace(/\.[^.]+$/,'')||'';};
    if(initialFile){const transfer=new DataTransfer();transfer.items.add(initialFile);form.elements.file.files=transfer.files;form.elements.file.onchange();}
    if(previous){form.elements.category.value=previous.category;form.elements.title.value=previous.title;}
    api('/api/sources'+(targetCaseId?`?case_id=${targetCaseId}`:'')).then(v=>{if(form.isConnected){sources=v.sources;versions();if(previous)form.elements.document_id.value=previous.document_id;}}).catch(error=>{if(form.isConnected)form.querySelector('#evidence-error').textContent='No se cargaron las versiones: '+error.message;});
    form.onsubmit=async event=>{
      event.preventDefault();if(uploading || !form.reportValidity())return;
      if(!sameCase()){form.querySelector('#evidence-error').textContent='El expediente cambió. Vuelve a abrir la carga desde el pendiente correspondiente.';return;}
      if(form.elements.file.files[0].size>20*1024*1024){form.querySelector('#evidence-error').textContent='El archivo supera 20 MB.';return;}
      const payload=new FormData(form);if(!payload.get('document_id'))payload.delete('document_id');
      if(targetCaseId){payload.set('case_id',targetCaseId);payload.set('version',targetVersion);}payload.set('shared',shared);
      if(requestId)payload.set('request_id',requestId);
      uploading=true;form.querySelectorAll('button,input,select').forEach(b=>b.disabled=true);
      form.querySelector('#evidence-error').textContent='';form.querySelector('#evidence-progress').textContent='Guardando y leyendo el archivo…';
      try {
        const receipt=await api('/api/evidence',{method:'POST',body:payload});
        if(!context&&form.isConnected)close();
        let updateError='';
        try{if(sameCase()){if(onUpdated)await onUpdated(receipt);else await refresh();}}
        catch(error){updateError=error.message;}
        if(context&&form.isConnected&&sameCase()){
          const reading=receipt.extraction_status==='error'?`El original está guardado, pero no pudo leerse. ${receipt.extraction_error||'Aporta una copia legible para revisar este punto.'}`:receipt.extraction_status==='partial'?'El archivo se leyó parcialmente. Revisa los pasajes y el original antes de utilizarlo.':'El archivo se guardó y su texto está disponible.';
          const search=receipt.search_status==='running'?'La búsqueda de respaldo está en curso. Puedes volver al pendiente mientras termina.':receipt.search_error?'La búsqueda necesita atención. El archivo ya está guardado; no necesitas subirlo otra vez.':receipt.search_status==='ready'?'La búsqueda terminó. Revisa si el pasaje responde al pendiente.':'El pendiente se actualizará al revisar las fuentes del expediente.';
          open('Respaldo guardado',`<section id="evidence-saved"><p><strong>${escape(receipt.title||form.elements.title.value)}</strong>${receipt.duplicate?' · archivo existente reutilizado':''}</p><p role="status">${escape(reading)}</p>${receipt.extraction_status!=='error'?`<p>${escape(search)}</p>`:''}${receipt.search_error?`<p role="alert">${escape(receipt.search_error)}</p>`:''}${updateError?`<p role="alert">El archivo está guardado. No se pudo actualizar el estado: ${escape(updateError)}</p>`:''}<p class="muted">Subir el archivo no confirma ni resuelve este pendiente. Revisa su contenido antes de decidir.</p><button class="primary" id="evidence-return" type="button">Volver al pendiente</button><p id="evidence-return-error" role="alert"></p></section>`);
          const saved=document.querySelector('#evidence-saved'),back=saved.querySelector('#evidence-return');
          back.onclick=async()=>{
            if(!sameCase()){close();notice('El respaldo quedó guardado en el expediente original.');return;}
            back.disabled=true;
            try{if(context.onUploaded)await context.onUploaded(receipt);else close();}
            catch(error){if(saved.isConnected)saved.querySelector('#evidence-return-error').textContent='El archivo está guardado. '+error.message;else notice('El archivo está guardado. '+error.message);}
            finally{if(saved.isConnected)back.disabled=false;}
          };
          back.focus();
        }else if(updateError)notice('El archivo se guardó. No se pudo actualizar el estado: '+updateError);
        notice(receipt.extraction_status==='error'?'Archivo conservado. Hay un error de lectura que puedes consultar en la tarjeta.':receipt.duplicate?'Archivo existente reutilizado; no se creó otra copia.':receipt.case_id?'Archivo guardado. Se está revisando su respaldo a las solicitudes.':'Fuente guardada en la biblioteca compartida.');
        if(receipt.search_error)notice('Archivo guardado. '+receipt.search_error);
      } catch(error) {if(form.isConnected){form.querySelector('#evidence-error').textContent=error.message;form.querySelector('#evidence-progress').textContent='';}else notice('No se pudo guardar: '+error.message);}
      finally {uploading=false;if(form.isConnected)form.querySelectorAll('button,input,select').forEach(b=>b.disabled=false);decorate();}
    };
  }
  async function library() {
    if(!connected)return false;
    open('Biblioteca de fuentes',`<p>Originales conservados en la base local. Añadir no equivale a verificar su contenido.</p><button class="primary" id="evidence-library-add">Agregar fuente</button><label class="field">Buscar documentos<input id="evidence-library-filter" type="search"></label><div id="evidence-library-rows" role="status">Cargando biblioteca…</div>`);
    document.querySelector('#evidence-library-add').onclick=()=>uploadForm('',true);
    const container=document.querySelector('#evidence-library-rows');
    try {
      const result=await api(`/api/sources?case_id=${caseId}`);
      if(!container.isConnected)return true;
      const show=()=>{const q=document.querySelector('#evidence-library-filter').value.toLocaleLowerCase('es');const matches=result.sources.filter(s=>s.is_latest && (s.title+' '+s.origin).toLocaleLowerCase('es').includes(q));container.innerHTML=`<p>${matches.length} documentos${matches.length>50?' · primeros 50; busca para acotar':''}</p>`+matches.slice(0,50).map(s=>`<section class="source"><h3>${escape(s.title)}</h3><p>Versión ${s.version} · ${s.case_id?'Este expediente':'Biblioteca compartida'} · ${escape(({error:'Error de lectura',pending:'Lectura pendiente',unsupported:'Formato sin lectura',partial:'Lectura parcial'})[s.extraction_status]||'Texto disponible')}</p><p>${escape(s.origin)}</p><a href="${original(s.id)}" target="_blank" rel="noopener">Abrir original ↗</a></section>`).join('');};
      document.querySelector('#evidence-library-filter').oninput=show;show();
    } catch(error){if(container.isConnected)container.textContent=error.message;}
    return true;
  }
  return {connect, panel, decorate, library, uploadForm, isConnected:()=>connected};
}
