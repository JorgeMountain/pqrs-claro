import {actor,request as managementRequest,managerOptions,managementDialog,cards,states} from './management-ui.js?v=phase2';
import {shell,rows,confirmation,status,title} from './case-browser-views.js?v=phase2';
import {createQueueRefresh} from './queue-refresh.js?v=phase2';

async function api(path,body,method='POST'){
  const response=await fetch('/api/cases'+path,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(data.detail||'No se pudo completar la operación.');return data;
}
const normalize=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
export function createCaseBrowser({container,open,close,notice,onSelect,onNew}){
  let root,active=[],trash=[],tab='unassigned',page=1,request=0,loading=false;
  const size=10;let managers=[],filters=null,scrollPosition=0;
  const filterIds=['cases-search','cases-status','cases-origin','cases-sort','cases-manager-filter'];
  const node=selector=>root.querySelector(selector);
  function visible(){return root?.isConnected;}
  const refresh=createQueueRefresh({load,visible,hasWork:()=>[...active,...trash].some(c=>c.processing),
    editing:()=>Boolean(document.querySelector('#drawer')?.open)});
  function paint(){
    if(!visible())return;
    const focused=globalThis.document?.activeElement?.closest?.('.cases-results button');
    const focusData=focused?{...focused.dataset}:null;
    const query=normalize(node('#cases-search').value),state=node('#cases-status').value,origin=node('#cases-origin').value;
    const source=tab==='trash'?trash:active;
    let items=source.filter(c=>(tab!=='unassigned'||!c.management.owner_id)&&(tab!=='mine'||Boolean(actor())&&c.management.owner_id===actor())&&(!node('#cases-manager-filter').value||c.management.owner_id===node('#cases-manager-filter').value)&&(!query||normalize([title(c),c.filename,c.case_number,c.internal_number].join(' ')).includes(query))&&(!state||c.management.state===state)&&(!origin||(c.origin_kind==='gmail'?'gmail':'pdf')===origin));
    const order=node('#cases-sort').value;
    filters=Object.fromEntries(filterIds.map(id=>[id,node('#'+id).value]));
    items.sort((a,b)=>order==='name'?title(a).localeCompare(title(b),'es'):(order==='oldest'?1:-1)*String(tab==='trash'?a.deleted_at:a.created_at).localeCompare(String(tab==='trash'?b.deleted_at:b.created_at)));
    const pages=Math.max(1,Math.ceil(items.length/size));page=Math.max(1,Math.min(page,pages));
    node('.cases-summary').innerHTML=`<span><strong>${active.length}</strong> expedientes</span><span><strong>${active.filter(c=>status(c)[0]==='review').length}</strong> por revisar</span><span><strong>${active.filter(c=>status(c)[0]==='processing').length}</strong> en proceso</span>`;
    node('[data-active-count]').textContent=active.length;node('[data-unassigned-count]').textContent=active.filter(c=>!c.management.owner_id).length;node('[data-mine-count]').textContent=active.filter(c=>c.management.owner_id===actor()).length;node('[data-trash-count]').textContent=trash.length;
    root.querySelectorAll('[data-cases-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.casesTab===tab)));
    node('.cases-trash-note').hidden=tab!=='trash';
    node('.cases-results').setAttribute('aria-busy',String(loading));
    node('.cases-results').innerHTML=items.length?(tab==='trash'?rows(items.slice((page-1)*size,page*size),true):cards(items.slice((page-1)*size,page*size))):`<div class="cases-empty"><h2>${source.length?'No hay coincidencias':tab==='trash'?'La papelera está vacía':'Tu primer expediente empieza aquí'}</h2><p>${source.length?'Prueba con otro término o cambia los filtros.':tab==='trash'?'Los expedientes que elimines aparecerán aquí.':'Carga un PDF o importa una petición desde Gmail.'}</p>${source.length?'<button data-cases-clear>Limpiar filtros</button>':tab==='trash'?'':'<button data-cases-new class="primary">Nueva petición</button>'}</div>`;
    node('[data-cases-count]').textContent=items.length?`${(page-1)*size+1}–${Math.min(page*size,items.length)} de ${items.length} expedientes`:'0 expedientes';
    node('[data-cases-page]').textContent=`${page} / ${pages}`;
    node('[data-cases-prev]').disabled=page===1;node('[data-cases-next]').disabled=page===pages;
    if(focusData)Array.from(root.querySelectorAll('.cases-results button')).find(b=>!b.disabled&&Object.entries(focusData).every(([key,value])=>b.dataset[key]===value))?.focus({preventScroll:true});
  }
  async function load(automatic=false){
    if(loading)return;
    refresh.stop();let failed=false;
    const sequence=++request,owner=root;loading=true;node('.cases-error').textContent='';
    node('[data-cases-refresh]').disabled=true;node('.cases-results').setAttribute('aria-busy','true');
    try{const data=await Promise.all([api(''),api('?deleted=true'),managementRequest('/api/managers')]);if(sequence!==request||owner!==root||!visible())return;[active,trash,managers]=data;node('#cases-actor').innerHTML=managerOptions(managers,actor(),'Selecciona tu gestor');const filter=node('#cases-manager-filter').value;node('#cases-manager-filter').innerHTML=managerOptions(managers,filter);paint();}
    catch(error){failed=true;if(owner===root&&visible()){node('.cases-error').textContent=error.message+' Se reintentará la actualización automáticamente.';if(!automatic&&!active.length&&!trash.length)node('.cases-results').innerHTML='<p class="cases-empty">No se pudo actualizar la lista. Puedes pulsar «Actualizar» para reintentar.</p>';}}
    finally{if(sequence===request&&owner===root&&visible()){loading=false;node('[data-cases-refresh]').disabled=false;node('.cases-results').setAttribute('aria-busy','false');refresh.schedule(failed);}}
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
  async function show(){
    refresh.stop();loading=false;request++;
    container.innerHTML=shell();root=container.querySelector('.case-browser');
    if(filters){node('#cases-manager-filter').innerHTML=managerOptions(managers,filters['cases-manager-filter']);for(const id of filterIds)node('#'+id).value=filters[id];}
    root.addEventListener('input',event=>{if(event.target.id==='cases-search'){page=1;paint();}});
    root.addEventListener('change',event=>{if(event.target.id==='cases-actor')localStorage.setItem('pqrs-pilot-manager',event.target.value);if(event.target.matches('select')){page=1;paint();}});
    root.addEventListener('click',async event=>{
      const b=event.target.closest('button');if(!b||b.disabled)return;scrollPosition=window.scrollY;
      if(b.hasAttribute('data-manager-add')){
        open('Añadir gestor al piloto','<form id="manager-add"><label class="field">Nombre<input name="name" required maxlength="100"></label><p role="alert"></p><button class="primary">Guardar gestor</button></form>');
        const form=document.querySelector('#manager-add');form.onsubmit=async event=>{event.preventDefault();form.querySelector('button').disabled=true;try{const manager=await managementRequest('/api/managers',{name:form.elements.name.value});localStorage.setItem('pqrs-pilot-manager',manager.id);close();await load();}catch(e){form.querySelector('[role=alert]').textContent=e.message;}finally{form.querySelector('button').disabled=false;}};return;
      }
      if(b.dataset.managementEdit){const c=active.find(c=>c.id===b.dataset.managementEdit);return managementDialog(c,managers,{open,close,reload:load,notice});}
      if(b.dataset.managementAction){
        const c=active.find(c=>c.id===b.dataset.id);b.disabled=true;
        try{if(!actor())throw new Error('Selecciona tu gestor antes de tomar o iniciar un expediente.');
          if(b.dataset.managementAction==='continue'){if(c.management.owner_id!==actor())throw new Error('Selecciona al gestor responsable o reasigna el expediente desde Detalles y gestión.');await onSelect(c.id);}
          else{await managementRequest(`/api/cases/${c.id}/management`,{revision:c.management.revision,actor_id:actor(),action:b.dataset.managementAction});if(b.dataset.managementAction==='start')await onSelect(c.id);else {notice('Expediente asignado. Lo encontrarás en Mis PQRS.');await load();}}
        }catch(e){if(visible())node('.cases-error').textContent=e.message;else notice(e.message);}finally{b.disabled=false;}return;
      }
      if(b.hasAttribute('data-cases-new'))return onNew();
      if(b.hasAttribute('data-cases-refresh'))return load();
      if(b.hasAttribute('data-cases-tab')){tab=b.dataset.casesTab;page=1;paint();return;}
      if(b.hasAttribute('data-cases-clear')){node('#cases-search').value='';node('#cases-status').value='';node('#cases-origin').value='';node('#cases-manager-filter').value='';page=1;paint();return;}
      if(b.hasAttribute('data-cases-prev')||b.hasAttribute('data-cases-next')){page+=b.hasAttribute('data-cases-prev')?-1:1;paint();node('#cases-title').focus();return;}
      const id=b.dataset.caseOpen||b.dataset.caseDelete||b.dataset.caseRestore||b.dataset.casePurge,c=[...active,...trash].find(c=>c.id===id);if(!c)return;
      if(b.dataset.caseDelete)return remove(c);
      if(b.dataset.casePurge)return remove(c,true);
      if(b.dataset.caseRestore)return restore(c,b);
      b.disabled=true;try{await onSelect(c.id);}catch(e){if(visible())node('.cases-error').textContent=String(e.message);else notice(e.message);}finally{if(b.isConnected)b.disabled=false;}
    });
    node('#cases-title').focus({preventScroll:true});await load();window.scrollTo(0,scrollPosition);
  }
  return {show};
}
