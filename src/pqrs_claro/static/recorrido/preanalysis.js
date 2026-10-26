import {esc} from './views.js';
import {icon} from './inbox-icons.js';
import {actor,request} from './management-ui.js?v=phase2';
import {preanalysisProgress} from './stage-progress.js?v=stage-progress1';

const checks=[['requester','Datos del solicitante','Encontrados'],['respect','Contenido respetuoso','Sin alertas'],['integrity','Legibilidad e integridad','Verificado']];

export function createPreanalysis({container,onBack,onStarted,notice}){
  let root,current,record={},page=1,zoom=100,marks='requester',timer,token=0,pageToken=0,busy=false;
  let confirmed=false,ack={},notes={},readOnly=false,viewOptions={};
  const own=()=>current?.management?.owner_id===actor();
  const editable=()=>own()&&!readOnly;
  const visible=()=>Boolean(root?.isConnected);
  const prefix=()=>`/api/cases/${encodeURIComponent(current.id)}/preanalysis`;
  function leave(){clearTimeout(timer);token++;pageToken++;root=null;current=null;busy=false;}
  function enabled(){return editable()&&record.status==='ready'&&confirmed&&!busy&&checks.every(([key])=>record.checks?.[key]?.state==='pass'||ack[key]&&notes[key]?.trim().length>=8);}
  function syncStart(){const button=root?.querySelector('[data-pre-start]');if(button)button.disabled=!enabled();}
  function restoreDraft(){if(record.draft?.actor_id===actor()){notes={...record.draft.notes};ack=Object.fromEntries(record.draft.acknowledged.map(key=>[key,true]));}}
  function verification([key,title,okLabel]){
    const finding=record.checks?.[key],ready=record.status==='ready',ok=ready&&finding?.state==='pass';
    const label=ok?okLabel:!ready?record.status==='running'?'Comprobando…':record.status==='loading'?'Consultando…':'Sin verificar':finding?.state==='attention'?'Revisar':'Por verificar';
    const data=key==='requester'&&ready?`<dl class="pre-requester"><div><dt>Nombre:</dt><dd>${finding?.name?`<mark>${esc(finding.name)}</mark>`:'No identificado'}</dd></div><div><dt>Contacto:</dt><dd>${finding?.contact?`<mark>${esc(finding.contact)}</mark>`:'No identificado'}</dd></div></dl>`:'';
    const copy=key==='requester'&&ok?'':ok&&key==='respect'?'No se detectaron expresiones irrespetuosas.':ok&&key==='integrity'?'El archivo abre y sus páginas son legibles.':finding?.summary||(record.status==='running'?'Comprobando el documento original…':record.status==='loading'?'Consultando el resultado guardado…':readOnly?'No hay verificación guardada para este punto.':'Las verificaciones aún no han comenzado.');
    const source=finding?.refs?.[0],savedNote=record.approval?.notes?.[key]||record.draft?.notes?.[key];
    return `<section class="pre-verification ${ok?'passed':'pending'}"><span class="pre-check-icon" aria-hidden="true">${icon(ok?'check':ready?'info':'refresh')}</span><div class="pre-check-content"><div class="pre-check-heading"><h3>${title}</h3><span class="pre-check-state ${ok?'passed':''}">${label}</span></div>${data}${copy?`<p>${esc(copy)}</p>`:''}${key==='respect'&&ok&&!readOnly?'<small>Confirma esta revisión al leer el original.</small>':''}${key==='integrity'&&ready?`<small>${record.page_count} ${record.page_count===1?'página revisada':'páginas revisadas'}.</small>`:''}${source?`<button class="text-button pre-evidence" type="button" data-pre-evidence="${key}" data-page="${source.page}">Ver en el documento ${icon('external-link')}</button>`:''}${readOnly&&savedNote?`<div class="pre-resolution"><strong>Observación registrada</strong><p>${esc(savedNote)}</p></div>`:''}${ready&&!ok&&editable()?`<div class="pre-resolution"><label><input type="checkbox" data-pre-ack="${key}" ${ack[key]?'checked':''}> He revisado este punto en el original</label><label for="pre-note-${key}">Observación para continuar</label><textarea id="pre-note-${key}" data-pre-note="${key}" rows="2" maxlength="1500" placeholder="Explica cómo se puede continuar con este hallazgo.">${esc(notes[key]||'')}</textarea><small>La alerta queda registrada; no rechaza automáticamente la solicitud.</small></div>`:''}</div></section>`;
  }
  function renderChecks(){
    if(!visible())return;
    root.querySelector('[data-pre-progress]').innerHTML=preanalysisProgress(record,viewOptions.progress);
    const savedLabel=record.approval?'Revisión previa confirmada.':record.status==='ready'?'Verificaciones guardadas.':record.status==='idle'?'Este expediente no tiene verificaciones previas guardadas.':'Consulta de las verificaciones guardadas.';
    root.querySelector('[data-pre-checks]').innerHTML=`<div class="pre-checks-title"><h2>Verificaciones previas</h2><p>${readOnly?'Consulta los hallazgos registrados junto al documento.':'Comprueba los hallazgos con el documento.'}</p></div><div aria-live="polite" aria-busy="${record.status==='running'}">${checks.map(verification).join('')}</div>${record.error?`<div class="pre-warning" role="alert"><p>${esc(record.error)}</p>${editable()?'<button type="button" data-pre-retry>Reintentar verificaciones</button>':readOnly?'<button type="button" data-pre-refresh>Volver a cargar la consulta</button>':''}</div>`:''}<div class="pre-not-started">${icon('info')}<span>${readOnly?`${savedLabel} El avance del expediente se conserva.`:current.status==='error'?'El intento anterior se detuvo. Revisa el documento antes de reintentar.':'La identificación de peticiones aún no ha comenzado.'}</span></div>${editable()?`<label class="pre-confirm"><input type="checkbox" data-pre-confirm ${confirmed?'checked':''} ${record.status!=='ready'?'disabled':''}> Confirmo la revisión previa del documento</label><button type="button" class="primary pre-start" data-pre-start ${enabled()?'':'disabled'}>${busy?'Iniciando análisis…':'Iniciar análisis'} ${icon('arrow-right')}</button><p class="pre-start-hint">Se identificarán las peticiones, su tipo y su contenido.</p>`:readOnly?'<p class="pre-readonly">Puedes volver a las otras etapas desde la barra superior.</p>':'<p class="pre-readonly">Solo el gestor responsable puede confirmar e iniciar el análisis.</p>'}<p class="pre-error" role="alert" data-pre-error></p><button type="button" class="text-button pre-save" data-pre-back>${readOnly?'Volver a la bandeja':'Guardar y volver a la bandeja'}</button>`;
  }
  async function loadPage(number){
    const generation=token,sequence=++pageToken,url=prefix();page=number;
    root.querySelector('[data-pre-page-status]').textContent='Cargando página…';
    try{
      const meta=await request(`${url}/pages/${number}`);
      if(generation!==token||sequence!==pageToken||!visible())return;
      const select=root.querySelector('[data-pre-page]');
      select.innerHTML=Array.from({length:meta.page_count},(_,i)=>`<option value="${i+1}" ${i+1===page?'selected':''}>${i+1}</option>`).join('');
      root.querySelector('[data-pre-page-count]').textContent=`de ${meta.page_count}`;
      root.querySelector('[data-pre-paper]').innerHTML=`<img src="/api/cases/${encodeURIComponent(current.id)}/pages/${page}.png" alt="Documento original, página ${page} de ${meta.page_count}" width="${meta.width}" height="${meta.height}">${meta.marks.filter(m=>m.key===marks).map(m=>`<span class="pre-pdf-mark ${m.key}" aria-hidden="true" style="left:${m.x/meta.width*100}%;top:${m.y/meta.height*100}%;width:${m.width/meta.width*100}%;height:${m.height/meta.height*100}%"></span>`).join('')}`;
      const img=root.querySelector('[data-pre-paper] img');
      img.onload=()=>{if(generation===token&&sequence===pageToken&&visible())root.querySelector('[data-pre-page-status]').textContent='';};
      img.onerror=()=>{if(generation===token&&sequence===pageToken&&visible())root.querySelector('[data-pre-page-status]').textContent='No se pudo mostrar la página. Puedes abrir el PDF original o cambiar de página para reintentar.';};
    }catch(e){if(generation===token&&visible())root.querySelector('[data-pre-page-status]').textContent=e.message;}
  }
  async function refresh(generation){
    try{
      const value=await request(prefix());
      if(generation!==token||!visible())return;
      if(value.revision!==record.revision){record=value;renderChecks();if(value.status==='ready')await loadPage(page);}
      if(value.status==='running')timer=setTimeout(()=>refresh(generation),1200);
    }catch(e){if(generation===token&&visible()){root.querySelector('[data-pre-error]').textContent=e.message;timer=setTimeout(()=>refresh(generation),4000);}}
  }
  async function check(retry=false){
    if(!editable())return;
    const generation=token;
    clearTimeout(timer);confirmed=false;
    try{
      const value=await request(prefix()+'/check',{actor_id:actor(),retry});
      if(generation!==token||!visible())return;
      record=value;restoreDraft();
      renderChecks();if(record.status==='running')timer=setTimeout(()=>refresh(generation),1000);else await loadPage(page);
    }catch(e){if(generation===token&&visible()){record={status:'error',error:e.message};renderChecks();}}
  }
  async function loadSaved(generation){
    try{
      const value=await request(prefix());
      if(generation!==token||!visible())return;
      record=value;renderChecks();
      if(record.status==='running')timer=setTimeout(()=>refresh(generation),1200);
      await loadPage(page);
    }catch(error){if(generation===token&&visible()){record={status:'error',error:error.message};renderChecks();}}
  }
  async function show(value,options={}){
    leave();const generation=token;current=value;viewOptions=options;
    readOnly=Boolean(options.readOnly||value.identification||value.management?.state==='closed'||!['uploaded','error'].includes(value.status));
    page=1;zoom=100;marks='requester';record={status:readOnly?'loading':'running'};confirmed=false;ack={};notes={};
    const owner=current.management?.owner_name||'Sin asignar',id=current.management?.reference||current.case_number||current.internal_number||`PQRS-${current.id.slice(0,12).toUpperCase()}`;
    const stages=viewOptions.navigation||`<ol class="pre-steps" aria-label="Etapas del expediente">${['Preanálisis','Identificación','Redacción','Borrador'].map((name,i)=>`<li ${i===0?'aria-current="step"':''}><span class="pre-step-number">${i+1}</span><div><strong>${name}</strong>${i?`<small>${readOnly?'Consulta':i===1&&current.status==='error'?'Por reintentar':'Sin iniciar'}</small>`:''}</div></li>`).join('')}</ol>`;
    container.innerHTML=`<section class="preanalysis" aria-labelledby="pre-title"><button type="button" class="text-button pre-back" data-pre-back>${icon('arrow-left')}Volver a la bandeja</button><h1 id="pre-title" tabindex="-1">Preanálisis del expediente</h1><p class="pre-subtitle">${readOnly?'Consulta la revisión previa del documento.':'Revisa el documento antes de identificar sus peticiones.'}</p><div class="pre-meta"><span class="pre-file">${icon('file')}<span>${esc(id)} <span class="muted">· ${esc(current.filename)}</span></span></span><span class="pre-owner"><span class="inbox-avatar is-mine">${esc(owner.slice(0,1).toUpperCase())}</span><span data-pre-owner>${esc(owner)}${own()?' (tú)':''}</span></span><span class="pre-status">${readOnly?'Consulta':'Preanálisis'}</span></div>${stages}<div data-pre-progress></div><div class="pre-columns"><section class="pre-checks" data-pre-checks></section><section class="pre-viewer" aria-label="Documento original"><div class="pre-viewer-heading"><h2>Documento original</h2><a href="/api/cases/${encodeURIComponent(current.id)}/original" target="_blank" rel="noopener">Abrir PDF ${icon('external-link')}</a></div><div class="pre-viewer-tools"><label>Página <select data-pre-page aria-label="Página del documento"><option>1</option></select></label><span data-pre-page-count></span><div class="pre-zoom"><button type="button" data-pre-zoom="-25" aria-label="Reducir documento">${icon('minus')}</button><output data-pre-zoom-value>100%</output><button type="button" data-pre-zoom="25" aria-label="Ampliar documento">${icon('plus')}</button></div></div><div class="pre-canvas" tabindex="0" aria-label="Vista del PDF; desplázate para leer el documento"><div class="pre-paper" data-pre-paper></div></div><p class="pre-page-status" role="status" data-pre-page-status></p></section></div></section>`;
    root=container.querySelector('.preanalysis');renderChecks();
    root.addEventListener('input',event=>{const el=event.target;if(el.hasAttribute('data-pre-confirm'))confirmed=el.checked;if(el.dataset.preAck)ack[el.dataset.preAck]=el.checked;if(el.dataset.preNote)notes[el.dataset.preNote]=el.value;syncStart();});
    root.addEventListener('change',event=>{if(event.target.hasAttribute('data-pre-page'))void loadPage(Number(event.target.value));});
    root.addEventListener('click',async event=>{
      const b=event.target.closest('button');if(!b||b.disabled)return;
      const stage={'live-identification':1,'live-responses':2,'live-final':3}[b.dataset.action];
      if(readOnly&&stage&&viewOptions.onStage){event.preventDefault();event.stopPropagation();await viewOptions.onStage(stage);return;}
      if(b.hasAttribute('data-pre-back')){
        if(busy)return;busy=true;b.disabled=true;syncStart();
        try{
          if(editable()&&record.status==='ready'&&Object.keys(notes).length)record=await request(prefix()+'/draft',{actor_id:actor(),revision:record.revision,acknowledged:Object.keys(ack).filter(k=>ack[k]),notes});
          busy=false;await onBack();if(!readOnly)notice('Documento y verificaciones conservados. La identificación sigue pendiente.');
        }catch(e){busy=false;b.disabled=false;syncStart();if(visible())root.querySelector('[data-pre-error]').textContent=e.message;else notice(e.message);}
        return;
      }
      if(b.hasAttribute('data-pre-retry')&&editable()){ack={};notes={};await check(true);return;}
      if(b.hasAttribute('data-pre-refresh')&&readOnly){await loadSaved(token);return;}
      if(b.dataset.preEvidence){marks=b.dataset.preEvidence;await loadPage(Number(b.dataset.page));root?.querySelector('.pre-viewer')?.scrollIntoView({block:'nearest',behavior:'smooth'});return;}
      if(b.dataset.preZoom){zoom=Math.max(50,Math.min(200,zoom+Number(b.dataset.preZoom)));root.querySelector('[data-pre-paper]').style.setProperty('--pre-zoom',zoom/100);root.querySelector('[data-pre-zoom-value]').textContent=zoom+'%';return;}
      if(b.hasAttribute('data-pre-start')&&enabled()){
        busy=true;syncStart();b.textContent='Iniciando análisis…';const generation=token;
        try{await request(prefix()+'/start',{actor_id:actor(),revision:record.revision,management_revision:current.management.revision,confirmed,acknowledged:Object.keys(ack).filter(k=>ack[k]),notes});if(generation!==token)return;const id=current.id;busy=false;await onStarted(id);}
        catch(e){if(generation===token&&visible()){busy=false;syncStart();b.innerHTML=`Iniciar análisis ${icon('arrow-right')}`;root.querySelector('[data-pre-error]').textContent=e.message;}}
      }
    });
    root.querySelector('#pre-title').focus({preventScroll:true});window.scrollTo(0,0);
    if(readOnly){await loadSaved(generation);return;}
    await loadPage(1);
    if(generation!==token||!visible())return;
    if(editable())await check();else await loadSaved(generation);
  }
  window.addEventListener('pqrs-manager-change',()=>{if(visible()){confirmed=false;renderChecks();root.querySelector('[data-pre-owner]').textContent=(current.management.owner_name||'Sin asignar')+(own()?' (tú)':'');if(editable()&&record.status==='idle')void check();}});
  return {show,leave,visible,busy:()=>busy};
}
