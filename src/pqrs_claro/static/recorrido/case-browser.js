import {actor,request as managementRequest,managerOptions,managementDialog} from './management-ui.js?v=phase2';
import {rows,confirmation,title} from './case-browser-views.js?v=inbox3';
import {inboxShell,inboxTable,mineGroups} from './inbox-views.js?v=sidebar1';
import {inboxSections,sectionCases,sectionCounts,caseStep} from './inbox-navigation.js?v=sidebar1';
import {progressDetail,progress} from './inbox-progress.js?v=office-progress1';
import {createReceiptPanel} from './inbox-receipt.js?v=sidebar1';
import {createQueueRefresh} from './queue-refresh.js?v=phase2';
import {createManagerPicker} from './manager-picker.js?v=managers1';

async function api(path,body,method='POST'){
  const response=await fetch('/api/cases'+path,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(data.detail||'No se pudo completar la operación.');return data;
}
const normalize=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
export function createCaseBrowser({container,open,close,notice,onSelect,upload,gmail,onQueueChange=()=>{},onViewChange=()=>{}}){
  let root,active=[],trash=[],tab='mine',page=1,request=0,loading=false,reloadPending=false,loadedOnce=false;
  const size=10;let managers=[],filters=null,scrollPosition=0,poolFilter='all',selectedId=null,panelMode=null,receipts={},panelOpener=null,managerPicker=null;
  const busyReceipt=()=>Object.values(receipts).some(r=>r.busy());
  const manager=()=>managers.find(m=>m.id===actor());
  function syncIdentity(){
    const avatar=document.querySelector('[data-actor-avatar]'),date=document.querySelector('[data-inbox-date]');
    if(avatar)avatar.textContent=manager()?.name?.slice(0,1).toUpperCase()||'—';
    managerPicker?.sync(managers,actor());
    if(date)date.textContent=new Intl.DateTimeFormat('es-CO',{timeZone:'America/Bogota',weekday:'long',day:'numeric',month:'long',year:'numeric'}).format(new Date());
    onQueueChange({active,trash,manager:actor(),loaded:loadedOnce});
  }
  const filterIds=['cases-search','cases-status','cases-origin','cases-sort','cases-manager-filter'];
  const node=selector=>root.querySelector(selector);
  function visible(){return root?.isConnected;}
  const refresh=createQueueRefresh({load,visible,hasWork:()=>[...active,...trash].some(c=>c.processing),
    editing:()=>Boolean(document.querySelector('#drawer')?.open)});
  function paint(){
    if(!visible())return;
    if(loading&&!loadedOnce){
      root.querySelectorAll('[data-active-count],[data-pool-count],[data-unassigned-count],[data-assigned-count],[data-mine-count],[data-trash-count]').forEach(el=>el.textContent='…');
      node('.cases-results').innerHTML='<p class="cases-empty" role="status">Cargando expedientes…</p>';
      node('.cases-results').setAttribute('aria-busy','true');
      node('[data-cases-prev]').disabled=true;node('[data-cases-next]').disabled=true;
      return;
    }
    const focused=globalThis.document?.activeElement?.closest?.('.cases-results button');
    const focusData=focused?{...focused.dataset}:null;
    const query=normalize(node('#cases-search').value),state=node('#cases-status').value,origin=node('#cases-origin').value;
    const source=sectionCases(active,trash,tab,actor()),section=inboxSections[tab]||inboxSections.active;
    let items=source.filter(c=>(tab!=='active'||poolFilter==='all'||(poolFilter==='assigned'?Boolean(c.management.owner_id):!c.management.owner_id))&&(!node('#cases-manager-filter').value||c.management.owner_id===node('#cases-manager-filter').value)&&(!query||normalize([title(c),c.filename,c.case_number,c.internal_number].join(' ')).includes(query))&&(!state||c.management.state===state)&&(!origin||(c.origin_kind==='gmail'?'gmail':'pdf')===origin));
    const order=node('#cases-sort').value;
    filters=Object.fromEntries(filterIds.map(id=>[id,node('#'+id).value]));
    items.sort((a,b)=>order==='name'?title(a).localeCompare(title(b),'es'):(order==='oldest'?1:-1)*String(tab==='trash'?a.deleted_at:a.created_at).localeCompare(String(tab==='trash'?b.deleted_at:b.created_at)));
    const pages=Math.max(1,Math.ceil(items.length/size));page=Math.max(1,Math.min(page,pages));
    const counts=sectionCounts(active,trash,actor()),pool=sectionCases(active,trash,'active',actor());
    node('[data-active-count]').textContent=counts.active;node('[data-pool-count]').textContent=counts.active;
    node('[data-unassigned-count]').textContent=pool.filter(c=>!c.management.owner_id).length;node('[data-assigned-count]').textContent=pool.filter(c=>c.management.owner_id).length;
    node('[data-mine-count]').textContent=counts.mine??'—';node('[data-trash-count]').textContent=counts.trash;
    root.querySelectorAll('[role=tab]').forEach(b=>{b.hidden=!['mine','active'].includes(tab);b.setAttribute('aria-selected',String(b.dataset.casesTab===tab));b.tabIndex=b.dataset.casesTab===tab?0:-1;});
    node('.cases-tabs').setAttribute('role',['mine','active'].includes(tab)?'tablist':'group');
    node('#inbox-results-panel').setAttribute('aria-labelledby',['mine','active'].includes(tab)?'inbox-tab-'+tab:'cases-title');
    node('#cases-title').textContent=section.title;node('[data-inbox-description]').textContent=section.description;
    onViewChange(tab);
    root.querySelectorAll('[data-pool-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.poolFilter===poolFilter)));
    node('.inbox-pool-filters').hidden=tab!=='active';
    node('.inbox-scope-note').textContent=section.description;
    node('.inbox-scope-note').hidden=true;
    node('.cases-trash-note').hidden=tab!=='trash';
    node('.cases-results').setAttribute('aria-busy',String(loading));
    const selected=items.slice((page-1)*size,page*size);
    const personal=['mine','pending','drafts','closed'].includes(tab),emptyTitles={pending:'No tienes pendientes por resolver',drafts:'Todavía no tienes borradores',closed:'Todavía no tienes expedientes finalizados',trash:'La papelera está vacía',unassigned:'No hay coincidencias'};
    const emptyNotes={pending:'Los expedientes que necesiten tu revisión o una acción aparecerán aquí.',drafts:'Aquí aparecerán los oficios cuando hayas llegado al borrador.',closed:'Usa «Finalizar expediente» desde el borrador para conservarlo en esta sección.'};
    node('.cases-results').innerHTML=items.length?(tab==='trash'?rows(selected,true):['mine','closed'].includes(tab)?mineGroups(selected,actor()):inboxTable(selected,actor())):`<div class="cases-empty"><h2>${personal&&!actor()?'Selecciona tu gestor':source.length?'No hay coincidencias':emptyTitles[tab]||'Todavía no hay expedientes'}</h2><p>${personal&&!actor()?'Elige tu nombre en la cabecera para ver tus expedientes.':source.length?'Ajusta o limpia los filtros para ver los expedientes de esta sección.':emptyNotes[tab]||'Puedes tomar un expediente desde el pool del equipo.'}</p>${source.length?'<button data-cases-clear>Limpiar filtros</button>':'<button data-cases-tab="active">Ver pool del equipo</button>'}</div>`;
    updateProgress();
    node('[data-cases-count]').textContent=items.length?`${(page-1)*size+1}–${Math.min(page*size,items.length)} de ${items.length} expedientes`:'0 expedientes';
    node('[data-cases-page]').textContent=`${page} / ${pages}`;
    node('[data-cases-prev]').disabled=page===1;node('[data-cases-next]').disabled=page===pages;
    if(focusData)Array.from(root.querySelectorAll('.cases-results button')).find(b=>!b.disabled&&Object.entries(focusData).every(([key,value])=>b.dataset[key]===value))?.focus({preventScroll:true});
  }
  async function load(automatic=false){
    if(loading){reloadPending=true;return;}
    refresh.stop();let failed=false;
    const sequence=++request,owner=root;loading=true;if(!automatic)node('.cases-error').textContent='';
    node('[data-cases-refresh]').disabled=true;node('.cases-results').setAttribute('aria-busy','true');if(!loadedOnce)paint();
    try{const data=await Promise.all([api(''),api('?deleted=true'),managementRequest('/api/managers')]);if(sequence!==request||owner!==root||!visible())return;[active,trash,managers]=data;loadedOnce=true;document.querySelector('#cases-actor').innerHTML=managerOptions(managers,actor(),'Selecciona tu gestor');const filter=node('#cases-manager-filter').value;node('#cases-manager-filter').innerHTML=managerOptions(managers,filter);paint();syncIdentity();Object.values(receipts).forEach(r=>r.syncManager());}
    catch(error){failed=true;if(owner===root&&visible()){node('.cases-error').textContent=error.message+' Se reintentará la actualización automáticamente.';if(!automatic&&!active.length&&!trash.length)node('.cases-results').innerHTML='<p class="cases-empty">No se pudo actualizar la lista. Puedes pulsar «Actualizar» para reintentar.</p>';}}
    finally{if(sequence===request&&owner===root&&visible()){loading=false;node('[data-cases-refresh]').disabled=false;node('.cases-results').setAttribute('aria-busy','false');if(reloadPending){reloadPending=false;await load(automatic);}else refresh.schedule(failed);}}
  }
  async function restore(c,button){
    button.disabled=true;
    try{await api('/'+c.id+'/restore',{version:c.version,lifecycle_revision:c.lifecycle_revision,management_revision:c.management.revision,confirmed:true});notice('Expediente restaurado. Puedes abrirlo en Todas.');await load();}
    catch(error){if(visible())node('.cases-error').textContent=error.message;}
    finally{if(button.isConnected)button.disabled=false;}
  }
  function remove(c,permanent=false){
    open(permanent?'¿Eliminar definitivamente?':'¿Eliminar este expediente?',confirmation(c,permanent));
    document.querySelector('#drawer').classList.add('cases-delete-window');
    document.querySelector('#drawer .eyebrow').textContent='GESTIÓN DE EXPEDIENTES';
    const button=document.querySelector('#cases-delete-confirm'),cancel=document.querySelector('#cases-delete-cancel'),error=document.querySelector('#cases-delete-error');
    cancel.onclick=close;cancel.focus();
    button.onclick=async()=>{button.disabled=true;cancel.disabled=true;error.textContent='';
      try{await api('/'+c.id+(permanent?'/permanent':''),{version:c.version,lifecycle_revision:c.lifecycle_revision,management_revision:c.management.revision,confirmed:true},'DELETE');close();notice(permanent?'Expediente eliminado definitivamente. Ya puedes importar el correo de nuevo.':'Expediente movido a la papelera. Puedes restaurarlo desde allí.');await load();}
      catch(e){if(error.isConnected)error.textContent=e.message;}
      finally{button.disabled=false;cancel.disabled=false;}
    };
  }
  function bindIdentity(){
    const actorSelect=document.querySelector('#cases-actor');
    actorSelect.onchange=()=>{if(busyReceipt()){actorSelect.value=actor();notice('Espera a que termine la recepción antes de cambiar de gestor.');return;}localStorage.setItem('pqrs-pilot-manager',actorSelect.value);page=1;if(visible())paint();syncIdentity();Object.values(receipts).forEach(r=>r.syncManager());window.dispatchEvent(new Event('pqrs-manager-change'));};
    managerPicker??=createManagerPicker({select:actorSelect,onAdd:addManager});
    managerPicker.close();
  }
  async function initializeIdentity(){
    [active,trash,managers]=await Promise.all([api(''),api('?deleted=true'),managementRequest('/api/managers')]);loadedOnce=true;
    document.querySelector('#cases-actor').innerHTML=managerOptions(managers,actor(),'Selecciona tu gestor');
    bindIdentity();syncIdentity();
  }
  function resetFilters(){filters=null;page=1;scrollPosition=0;poolFilter='all';}
  function navigate(section){
    if(!visible()||!inboxSections[section]||busyReceipt())return false;
    tab=section;resetFilters();for(const id of filterIds)node('#'+id).value=id==='cases-sort'?'recent':'';
    closePanel();paint();node('#cases-title').focus({preventScroll:true});window.scrollTo(0,0);return true;
  }
  async function show({finalizedId,section}={}){
    refresh.stop();loading=false;reloadPending=false;request++;
    if(inboxSections[section]){tab=section;resetFilters();panelMode=null;}
    if(finalizedId){tab='closed';page=1;scrollPosition=0;selectedId=finalizedId;panelMode='progress';filters={'cases-search':'','cases-status':'closed','cases-origin':'','cases-sort':'recent','cases-manager-filter':''};}
    container.innerHTML=inboxShell();root=container.querySelector('.case-browser');receipts={};
    bindIdentity();
    root.addEventListener('keydown',event=>{if(event.key==='Tab'&&!node('.inbox-panel').hidden&&globalThis.matchMedia?.('(max-width:760px)').matches){const focusable=[...node('.inbox-panel').querySelectorAll('button:not(:disabled),input:not(:disabled),a[href],summary')].filter(n=>n.getClientRects().length);const first=focusable[0],last=focusable.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}return;}if(event.key==='Escape'&&!busyReceipt()){closePanel();return;}const b=event.target.closest('[role=tab]');if(!b||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();tab=event.key==='Home'?'mine':event.key==='End'?'active':b.dataset.casesTab==='mine'?'active':'mine';page=1;paint();node('#inbox-tab-'+tab).focus();});
    if(filters){node('#cases-manager-filter').innerHTML=managerOptions(managers,filters['cases-manager-filter']);for(const id of filterIds)node('#'+id).value=filters[id];}
    if(finalizedId){node('#inbox-filters').hidden=false;node('[data-cases-filters]').setAttribute('aria-expanded','true');}
    root.addEventListener('input',event=>{if(event.target.id==='cases-search'){page=1;paint();}});
    root.addEventListener('change',event=>{if(event.target.id==='cases-actor')localStorage.setItem('pqrs-pilot-manager',event.target.value);if(event.target.matches('select')){page=1;paint();}});
    root.addEventListener('click',async event=>{
      const b=event.target.closest('button');if(!b||b.disabled)return;scrollPosition=window.scrollY;
      if(busyReceipt()){notice('Espera a que termine la recepción del documento.');return;}
      if(b.dataset.panelOpen)return showPanel(b.dataset.panelOpen);
      if(b.hasAttribute('data-panel-close')){closePanel();return;}
      if(b.dataset.inboxDetail){selectedId=b.dataset.inboxDetail;return showPanel('progress');}
      if(b.hasAttribute('data-cases-filters')){const filters=node('#inbox-filters');filters.hidden=!filters.hidden;b.setAttribute('aria-expanded',String(!filters.hidden));return;}
      if(b.dataset.poolFilter){poolFilter=b.dataset.poolFilter;page=1;paint();return;}
      if(b.dataset.managementEdit){const c=active.find(c=>c.id===b.dataset.managementEdit);return managementDialog(c,managers,{open,close,reload:load,notice});}
      if(b.dataset.managementAction){
        const c=active.find(c=>c.id===b.dataset.id);b.disabled=true;
        try{if(!actor())throw new Error('Selecciona tu gestor antes de tomar o iniciar un expediente.');
          if(['continue','preanalysis'].includes(b.dataset.managementAction)){if(c.management.owner_id!==actor())throw new Error('Selecciona al gestor responsable o reasigna el expediente desde Detalles y gestión.');await onSelect(c.id,{step:caseStep(c,tab)});}
          else{await managementRequest(`/api/cases/${c.id}/management`,{revision:c.management.revision,actor_id:actor(),action:b.dataset.managementAction});if(b.dataset.managementAction==='start'){selectedId=c.id;await load();showPanel('progress');}else {notice('Expediente asignado. Lo encontrarás en Mi trabajo.');await load();}}
        }catch(e){if(visible())node('.cases-error').textContent=e.message;else notice(e.message);}finally{b.disabled=false;}return;
      }
      if(b.hasAttribute('data-cases-new'))return showPanel('save');
      if(b.hasAttribute('data-cases-refresh'))return load();
      if(b.hasAttribute('data-cases-tab')){tab=b.dataset.casesTab;page=1;paint();return;}
      if(b.hasAttribute('data-cases-clear')){node('#cases-search').value='';node('#cases-status').value='';node('#cases-origin').value='';node('#cases-manager-filter').value='';poolFilter='all';page=1;paint();return;}
      if(b.hasAttribute('data-cases-prev')||b.hasAttribute('data-cases-next')){page+=b.hasAttribute('data-cases-prev')?-1:1;paint();node('#cases-title').focus();return;}
      const id=b.dataset.caseOpen||b.dataset.caseDelete||b.dataset.caseRestore||b.dataset.casePurge,c=[...active,...trash].find(c=>c.id===id);if(!c)return;
      if(b.dataset.caseDelete)return remove(c);
      if(b.dataset.casePurge)return remove(c,true);
      if(b.dataset.caseRestore)return restore(c,b);
      b.disabled=true;try{await onSelect(c.id,{step:caseStep(c,tab)});}catch(e){if(visible())node('.cases-error').textContent=String(e.message);else notice(e.message);}finally{if(b.isConnected)b.disabled=false;}
    });
    if(panelMode)showPanel(panelMode);else{node('.inbox-panel').hidden=true;root.classList.add('panel-closed');}
    if(globalThis.matchMedia?.('(max-width:1050px)').matches){node('.inbox-panel').hidden=true;root.classList.add('panel-closed');}
    if(active.length||trash.length){paint();syncIdentity();}node('#cases-title').focus({preventScroll:true});await load();
    if(finalizedId){
      const completed=active.filter(c=>c.management.owner_id===actor()&&c.management.state==='closed').sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at)));
      const index=completed.findIndex(c=>c.id===finalizedId);if(index>=0){page=Math.floor(index/size)+1;paint();}
      node('.inbox-panel').hidden=true;root.classList.add('panel-closed');
      [...root.querySelectorAll('[data-inbox-detail]')].find(button=>button.dataset.inboxDetail===finalizedId)?.focus({preventScroll:true});
      node('.inbox-group.closed')?.scrollIntoView({block:'start'});
    }else window.scrollTo(0,scrollPosition);
  }
  async function addManager(){
    if(busyReceipt())return;
    open('Añadir gestor al piloto','<form id="manager-add"><label class="field">Nombre<input name="name" required maxlength="100"></label><p role="alert"></p><button class="primary">Guardar gestor</button></form>');
    const form=document.querySelector('#manager-add');form.onsubmit=async event=>{event.preventDefault();form.querySelector('button').disabled=true;try{const m=await managementRequest('/api/managers',{name:form.elements.name.value});localStorage.setItem('pqrs-pilot-manager',m.id);close();if(visible())await load();else{managers=await managementRequest('/api/managers');document.querySelector('#cases-actor').innerHTML=managerOptions(managers,actor());syncIdentity();window.dispatchEvent(new Event('pqrs-manager-change'));}}catch(e){form.querySelector('[role=alert]').textContent=e.message;}finally{form.querySelector('button').disabled=false;}};
  }
  function updateProgress(){
    const slot=node('[data-panel-slot="progress"]'),c=active.find(c=>c.id===selectedId);
    slot.innerHTML=c?progressDetail(c,actor()):'<h2>Seguimiento</h2><p class="muted">Selecciona un expediente de la bandeja para consultar su responsable y su avance.</p>';
  }
  function closePanel(){
    panelMode=null;
    onViewChange(tab);
    node('.inbox-panel').hidden=true;root.classList.add('panel-closed');
    (panelOpener?.isConnected?panelOpener:node('[data-panel-open="progress"]')).focus({preventScroll:true});
  }
  function showPanel(mode='analyze'){
    if(!visible()||busyReceipt())return;
    if(!document.activeElement?.closest?.('.inbox-panel'))panelOpener=document.activeElement;
    panelMode=mode;node('.inbox-panel').hidden=false;node('.inbox-panel').scrollTo?.(0,0);root.classList.remove('panel-closed');
    const mobile=Boolean(globalThis.matchMedia?.('(max-width:760px)').matches);node('.inbox-panel').setAttribute('role',mobile?'dialog':'complementary');node('.inbox-panel').setAttribute('aria-modal',String(mobile));if(mobile)node('[data-panel-close]').focus({preventScroll:true});
    root.querySelectorAll('[data-panel-slot]').forEach(n=>n.hidden=n.dataset.panelSlot!==mode);
    root.querySelectorAll('.inbox-panel-tabs [data-panel-open]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.panelOpen===mode)));
    if(mode==='progress'){updateProgress();return;}
    if(!receipts[mode])receipts[mode]=createReceiptPanel({container:node(`[data-panel-slot="${mode}"]`),mode,upload,gmail,getManager:manager,onSaved:()=>{if(mode==='save'){tab='active';poolFilter='all';}return load();},onComplete:async id=>{selectedId=id;await onSelect(id);}});
    receipts[mode].syncManager();
  }
  return {show,navigate,initializeIdentity,showPanel,visible,busy:busyReceipt,refresh:load,async received(id,mode){if(mode==='analyze'){selectedId=id;await onSelect(id);}else{tab='active';poolFilter='all';await load();}}};
}
