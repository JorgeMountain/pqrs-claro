import {showPetitionUpload} from './petition-upload.js?v=20260916-mail';
import {createGmail} from './gmail-inbox.js?v=20260916-mail';
import {createEvidenceUpload} from './evidence-upload.js';
import {createLibrary} from './library.js?v=20260911-source-spinner';
import {createLive} from './live.js?v=20260919-supports';
import {createCaseBrowser} from './case-browser.js?v=20260919-supports';
import {confirmScope,reopenScope,recordDecision,rejectionForm,scopeStatement} from './quick-confirmation.js';
import {bindSplitPane,focusRequest} from './split-pane.js?v=20260911-scroll';
import './workspace-menu.js';
import {bindOriginal,focusOriginal} from './original-viewer.js?v=20260911-scroll';
import {esc, understanding, responses, office, sourcesView, blocked, paragraphs} from './views.js';
const view=document.querySelector('#view'), drawer=document.querySelector('#drawer'), body=document.querySelector('#drawer-body');
if(!new URLSearchParams(location.search).get('case'))document.querySelector('.prototype').textContent='Petición de demostración · para trabajar con un documento real, usa «Cargar petición» o «Mis expedientes».';
let homeVisible=false;
let data, state={step:1,scenario:'ready',edits:{},confirm:false,approved:false}, busy=false, opener, timer;
const notice=message=>{clearTimeout(timer);document.querySelector('#notice').textContent=message;timer=setTimeout(()=>document.querySelector('#notice').textContent='',4500);};
const library=createLibrary({open,close:()=>drawer.close(),notice});
const evidence=createEvidenceUpload({open,close:()=>drawer.close(),render:()=>render(),notice,getData:()=>data,changed:dirty=>{state.evidenceDirty=dirty;if(dirty)invalidate();}});
let releaseSplitPane=()=>{};
const live=createLive({open,close:()=>drawer.close(),notice,releaseDemo:()=>releaseSplitPane(),showMail:id=>gmail.showCase(id),onBrowse:showCases});
const gmail=createGmail({open,close:()=>drawer.close(),notice,onOpenCase:async id=>{homeVisible=false;showWorkspace();await live.select(id);}});
const caseBrowser=createCaseBrowser({container:view,open,close:()=>drawer.close(),notice,onNew:showHome,onSelect:async id=>{await live.select(id);homeVisible=false;}});
document.querySelector('#gmail-inbox').onclick=()=>gmail.show();
document.querySelector('#live-open').onclick=()=>live.choose();
function showWorkspace(){document.querySelector('.steps').hidden=false;document.querySelector('.prototype').hidden=false;}
function showCases(){
  live.leave();releaseSplitPane();homeVisible=true;if(drawer.open)drawer.close();
  document.querySelector('.steps').hidden=true;document.querySelector('.prototype').hidden=true;
  document.querySelector('.demo-badge').textContent='Gestión de Peticiones';document.querySelector('.prototype-status').textContent='Mis expedientes';
  document.querySelector('#case').classList.remove('active');
  history.replaceState(null,'',location.pathname+'?view=cases');window.scrollTo(0,0);
  return caseBrowser.show();
}
function showHome(){
  live.leave();releaseSplitPane();homeVisible=true;if(drawer.open)drawer.close();
  document.querySelector('.steps').hidden=true;document.querySelector('.prototype').hidden=true;
  document.querySelector('.demo-badge').textContent='Gestión de Peticiones';document.querySelector('.prototype-status').textContent='Inicio';
  document.querySelector('#case').classList.remove('active');
  showPetitionUpload({container:view,gmail:()=>gmail.show(),upload:async file=>{homeVisible=false;showWorkspace();await live.upload(file);if(!live.active()){homeVisible=true;document.querySelector('.steps').hidden=true;document.querySelector('.prototype').hidden=true;}},choose:()=>live.choose(),demo:()=>{live.leave();go(1);}});
  document.querySelector('#main').focus();window.scrollTo(0,0);
}
document.querySelector('#live-new').onclick=showHome;
document.querySelector('#home-logo').onclick=event=>{if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();showHome();};
function render(focus=false){
  if(live.active()||homeVisible)return;
  releaseSplitPane();
  view.innerHTML=state.step===1?understanding(data,state):state.step===2?responses(data,state):office(data,state);
  document.querySelectorAll('[data-step]').forEach(b=>{if(+b.dataset.step===state.step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');b.disabled=busy;});
  if(state.step===1)bindOriginal(state,page=>{state.originalPage=page;render();focusOriginal();});
  releaseSplitPane=bindSplitPane();
  document.querySelectorAll('[data-live-evidence]').forEach(node=>node.innerHTML=evidence.panel(node.dataset.liveEvidence));
  evidence.decorate();
  const scenario=document.querySelector('#scenario');
  if(scenario){scenario.value=state.scenario;scenario.addEventListener('change',()=>{state.scenario=scenario.value;state.scopeDecision=null;invalidate();render();document.querySelector('#scenario').focus();});}
  document.querySelector('#confirm')?.addEventListener('change',e=>{state.confirm=e.target.checked;document.querySelector('#approve').disabled=!state.confirm||blocked(state);});
  document.querySelector('#approve')?.addEventListener('click',()=>{if(state.confirm&&!blocked(state)){state.approved=true;render();notice('Revisión de prueba confirmada.');}});
  if(focus){document.querySelector('#main').focus();window.scrollTo(0,0);}
}
function invalidate(){state.confirm=false;state.approved=false;}
function go(step){if(busy)return;homeVisible=false;showWorkspace();state.step=step;render(true);}
function open(title,html){drawer.classList.remove('petition-upload-window','cases-delete-window');opener=document.activeElement;drawer.querySelector('.eyebrow').textContent=html.includes('id="gmail-panel"')?'PETICIONES POR CORREO':'CONTEXTO DE LA RESPUESTA';document.querySelector('#drawer-title').textContent=title;body.innerHTML=html;drawer.showModal();}
drawer.addEventListener('close',()=>{if(opener?.isConnected&&opener.getClientRects().length)opener.focus();else if(opener?.closest('#workspace-menu'))document.querySelector('#workspace-toggle').focus();else document.querySelector('#main').focus();});
document.querySelector('#close').addEventListener('click',()=>drawer.close());
document.querySelectorAll('[data-step]').forEach(b=>b.addEventListener('click',()=>live.active()?live.go(+b.dataset.step):go(+b.dataset.step)));
document.querySelector('#case').addEventListener('click',()=>{live.leave();go(1);});
document.querySelector('#reset').addEventListener('click',()=>{if(busy)return;live.leave();state={step:1,scenario:'ready',edits:{},confirm:false,approved:false,evidenceDirty:state.evidenceDirty};render(true);notice('Maqueta reiniciada.');});
document.querySelector('#library').addEventListener('click',()=>library.show());
async function prepare(retry=false){
  if(retry){
    busy=true;
    const button=view.querySelector('[data-action="retry"]');
    button.disabled=true;button.textContent='Reintentando análisis de prueba…';
    document.querySelector('#scenario').disabled=true;
    await new Promise(r=>setTimeout(r,1200));
    state.scenario='ready';invalidate();busy=false;render();
    notice('Análisis de prueba completado. Las otras respuestas se conservaron.');
    return;
  }
  busy=true;document.querySelectorAll('[data-step]').forEach(b=>b.disabled=true);
  view.innerHTML=`<div class="heading"><div><p class="eyebrow">${retry?'REINTENTO DE PRUEBA':'PREPARACIÓN DE PRUEBA'}</p><h1>${retry?'Revisando este punto':'Preparando las respuestas'}</h1><p class="muted">Reproducción visual con resultados guardados; no se está consultando una IA.</p></div></div><div class="loading" role="status" aria-live="polite"><progress aria-label="Preparación de prueba" max="3" value="0"></progress><ul><li id="progress-text">Localizando antecedentes para cada solicitud…</li></ul></div>`;
  const stages=['Antecedentes localizados. Comprobando su alcance…','Respuestas reunidas con sus fuentes…','Preparación de prueba completada.'];
  for(let i=0;i<3;i++){await new Promise(r=>setTimeout(r,550));document.querySelector('progress').value=i+1;document.querySelector('#progress-text').textContent=stages[i];}
  busy=false;state.step=2;if(retry)state.scenario='ready';render(true);
}
function edit(i){
  open(`Editar respuesta ${i+1}`,`<p>Los cambios se conservan durante esta sesión de la maqueta. Editar deja pendiente la evaluación de esta respuesta.</p><label class="field">Texto de la respuesta<textarea id="edit-text">${esc(paragraphs(data.requests[i],state,i).join('\n\n'))}</textarea></label><div class="dialog-actions"><button class="primary" id="save-edit">Guardar edición de prueba</button><button id="cancel-edit">Cancelar</button></div><p id="edit-error" role="alert"></p>`);
  document.querySelector('#cancel-edit').addEventListener('click',()=>drawer.close());
  document.querySelector('#save-edit').addEventListener('click',()=>{const text=document.querySelector('#edit-text').value.trim();if(!text){document.querySelector('#edit-error').textContent='Escribe una respuesta antes de guardar.';return;}if(text===data.requests[i].paragraphs.map(p=>p.text).join('\n\n'))delete state.edits[i];else state.edits[i]=text;invalidate();drawer.close();render();notice('Edición guardada en la maqueta.');});
}
function rejectScope(){
  if(state.scenario!=='pending'||state.edits[1])return;
  open('El antecedente no aplica',rejectionForm(esc));
  const form=document.querySelector('#scope-rejection-form');
  const reason=document.querySelector('#scope-rejection-reason');
  const detail=document.querySelector('#scope-rejection-detail');
  reason.addEventListener('change',()=>{const needed=['other','contradiction'].includes(reason.value);document.querySelector('#scope-detail-field').hidden=!needed;detail.required=needed;});
  document.querySelector('#scope-rejection-cancel').addEventListener('click',()=>drawer.close());
  form.addEventListener('submit',event=>{
    event.preventDefault();
    if(!form.reportValidity()||state.scenario!=='pending'||state.edits[1])return;
    if(['other','contradiction'].includes(reason.value)&&detail.value.trim().length<10){document.querySelector('#scope-rejection-error').textContent='Describe la diferencia concreta para orientar la revisión.';return;}
    const note=reason.options[reason.selectedIndex].text+(['other','contradiction'].includes(reason.value)?': '+detail.value.trim():'');
    recordDecision(state,data.requests[1],'not_applicable',note);drawer.close();render();notice('Decisión de prueba registrada. La solicitud sigue pendiente de revisión.');
  });
}
view.addEventListener('click',e=>{
  if(live.active())return;
  const b=e.target.closest('[data-action]');if(!b||busy)return;const i=+b.dataset.index;
  switch(b.dataset.action){
    case 'original':state.originalSelection=i;state.originalPage=data.requests[i].original_marks?.[0]?.page || 1;render();focusOriginal();break;
    case 'clear-original':state.originalSelection=null;render();document.querySelector('#original-title').focus();break;
    case 'back-to-question':focusRequest(i);break;
    case 'prepare':prepare();break;
    case 'responses':go(2);break;
    case 'office':go(3);break;
    case 'sources':open(`Fuentes de la respuesta ${i+1}`,`<p class="muted">Pasajes usados en la demo validada. El documento de salida no muestra estas referencias de trabajo.</p>${sourcesView(data.requests[i].sources)}`);break;
    case 'edit':edit(i);break;
    case 'restore':delete state.edits[i];invalidate();render();notice('Respuesta validada restaurada.');break;
    case 'scope-support':open('Respaldo y alcance de la solicitud 2',`<p>${esc(scopeStatement)}</p><p class="muted">Confirma únicamente su aplicación a esta solicitud; no equivale a autenticar el documento ni aprobar el oficio.</p>${sourcesView(data.requests[1].sources)}`);break;
    case 'scope-confirm':if(confirmScope(state,data.requests[1])){render();notice('Aplicación confirmada en la maqueta. Registro de prueba guardado.');}break;
    case 'scope-reject':rejectScope();break;
    case 'scope-reopen':if(reopenScope(state,data.requests[1])){render();notice('Decisión reabierta. El historial se conserva.');}break;
    case 'retry':prepare(true);break;
    case 'missing':if(evidence.isConnected()){evidence.uploadForm(data.requests[1].request_id);break;}open('Aportar el documento solicitado',`<p><strong>Programa de Mecánica de Máquinas · 2019-2</strong></p><p>En el sistema integrado, aquí se adjuntaría el archivo o se registraría a quién solicitarlo. El pendiente seguiría abierto hasta que el documento se lea y se compruebe su relación con esta solicitud.</p><p class="muted">La maqueta no carga archivos ni da este pendiente por resuelto. Puedes volver a «Demo validada» en el selector para continuar probando.</p>`);break;
  }
});
try{const response=await fetch('./data.json');if(!response.ok)throw new Error('Snapshot unavailable');data=await response.json();if(new URLSearchParams(location.search).get('case'))await live.init();else if(new URLSearchParams(location.search).get('view')==='cases')await showCases();else showHome();if(!live.active())await evidence.connect();}catch{view.innerHTML='<div class="error-page" role="alert"><h1>No se pudo cargar la demostración</h1><p>Recarga la página para volver a intentar abrir los datos de la maqueta.</p><button id="reload">Reintentar</button></div>';document.querySelector('#reload').addEventListener('click',()=>location.reload());document.querySelectorAll('header button,.sidebar button,.steps button').forEach(b=>b.disabled=true);}
