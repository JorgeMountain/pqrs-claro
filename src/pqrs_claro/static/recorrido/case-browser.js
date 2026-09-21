import {shell,rows,confirmation,status,title} from './case-browser-views.js';

async function api(path,body,method='POST'){
  const response=await fetch('/api/cases'+path,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(data.detail||'No se pudo completar la operación.');return data;
}
const normalize=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
export function createCaseBrowser({container,open,close,notice,onSelect,onNew}){
  let root,active=[],trash=[],tab='active',page=1,request=0,loading=false;
  const size=10;
  const node=selector=>root.querySelector(selector);
  function visible(){return root?.isConnected;}
  function paint(){
    if(!visible())return;
    const query=normalize(node('#cases-search').value),state=node('#cases-status').value,origin=node('#cases-origin').value;
    const source=tab==='trash'?trash:active;
    let items=source.filter(c=>(!query||normalize([title(c),c.filename,c.case_number].join(' ')).includes(query))&&(!state||status(c)[0]===state)&&(!origin||(c.origin_kind==='gmail'?'gmail':'pdf')===origin));
    const order=node('#cases-sort').value;
    items.sort((a,b)=>order==='name'?title(a).localeCompare(title(b),'es'):(order==='oldest'?1:-1)*String(tab==='trash'?a.deleted_at:a.created_at).localeCompare(String(tab==='trash'?b.deleted_at:b.created_at)));
    const pages=Math.max(1,Math.ceil(items.length/size));page=Math.max(1,Math.min(page,pages));
    node('.cases-summary').innerHTML=`<span><strong>${active.length}</strong> expedientes</span><span><strong>${active.filter(c=>status(c)[0]==='review').length}</strong> por revisar</span><span><strong>${active.filter(c=>status(c)[0]==='processing').length}</strong> en proceso</span>`;
    node('[data-active-count]').textContent=active.length;node('[data-trash-count]').textContent=trash.length;
    root.querySelectorAll('[data-cases-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.casesTab===tab)));
    node('.cases-trash-note').hidden=tab!=='trash';
    node('.cases-results').setAttribute('aria-busy',String(loading));
    node('.cases-results').innerHTML=items.length?rows(items.slice((page-1)*size,page*size),tab==='trash'):`<div class="cases-empty"><h2>${source.length?'No hay coincidencias':tab==='trash'?'La papelera está vacía':'Tu primer expediente empieza aquí'}</h2><p>${source.length?'Prueba con otro término o cambia los filtros.':tab==='trash'?'Los expedientes que elimines aparecerán aquí.':'Carga un PDF o importa una petición desde Gmail.'}</p>${source.length?'<button data-cases-clear>Limpiar filtros</button>':tab==='trash'?'':'<button data-cases-new class="primary">Nueva petición</button>'}</div>`;
    node('[data-cases-count]').textContent=items.length?`${(page-1)*size+1}–${Math.min(page*size,items.length)} de ${items.length} expedientes`:'0 expedientes';
    node('[data-cases-page]').textContent=`${page} / ${pages}`;
    node('[data-cases-prev]').disabled=page===1;node('[data-cases-next]').disabled=page===pages;
  }
  async function load(){
    const sequence=++request,owner=root;loading=true;node('.cases-error').textContent='';
    node('[data-cases-refresh]').disabled=true;node('.cases-results').setAttribute('aria-busy','true');
    try{const data=await Promise.all([api(''),api('?deleted=true')]);if(sequence!==request||owner!==root||!visible())return;[active,trash]=data;paint();}
    catch(error){if(owner===root&&visible()){node('.cases-error').textContent=error.message;node('.cases-results').innerHTML='<p class="cases-empty">No se pudo actualizar la lista. Pulsa «Actualizar» para reintentar.</p>';}}
    finally{if(owner===root&&visible()){loading=false;node('[data-cases-refresh]').disabled=false;node('.cases-results').setAttribute('aria-busy','false');}}
  }
  async function restore(c,button){
    button.disabled=true;
    try{await api('/'+c.id+'/restore',{version:c.version,lifecycle_revision:c.lifecycle_revision,confirmed:true});notice('Expediente restaurado. Puedes abrirlo en Expedientes.');await load();}
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
      try{await api('/'+c.id+(permanent?'/permanent':''),{version:c.version,lifecycle_revision:c.lifecycle_revision,confirmed:true},'DELETE');close();notice(permanent?'Expediente eliminado definitivamente. Ya puedes importar el correo de nuevo.':'Expediente movido a la papelera. Puedes restaurarlo desde allí.');await load();}
      catch(e){if(error.isConnected)error.textContent=e.message;}
      finally{button.disabled=false;cancel.disabled=false;}
    };
  }
  async function show(){
    container.innerHTML=shell();root=container.querySelector('.case-browser');tab='active';page=1;
    root.addEventListener('input',event=>{if(event.target.id==='cases-search'){page=1;paint();}});
    root.addEventListener('change',event=>{if(event.target.matches('select')){page=1;paint();}});
    root.addEventListener('click',async event=>{
      const b=event.target.closest('button');if(!b||b.disabled)return;
      if(b.hasAttribute('data-cases-new'))return onNew();
      if(b.hasAttribute('data-cases-refresh'))return load();
      if(b.hasAttribute('data-cases-tab')){tab=b.dataset.casesTab;page=1;paint();return;}
      if(b.hasAttribute('data-cases-clear')){node('#cases-search').value='';node('#cases-status').value='';node('#cases-origin').value='';page=1;paint();return;}
      if(b.hasAttribute('data-cases-prev')||b.hasAttribute('data-cases-next')){page+=b.hasAttribute('data-cases-prev')?-1:1;paint();node('#cases-title').focus();return;}
      const id=b.dataset.caseOpen||b.dataset.caseDelete||b.dataset.caseRestore||b.dataset.casePurge,c=[...active,...trash].find(c=>c.id===id);if(!c)return;
      if(b.dataset.caseDelete)return remove(c);
      if(b.dataset.casePurge)return remove(c,true);
      if(b.dataset.caseRestore)return restore(c,b);
      b.disabled=true;try{await onSelect(c.id);}catch(e){if(visible())node('.cases-error').textContent=String(e.message);else notice(e.message);}finally{if(b.isConnected)b.disabled=false;}
    });
    node('#cases-title').focus();await load();
  }
  return {show};
}
