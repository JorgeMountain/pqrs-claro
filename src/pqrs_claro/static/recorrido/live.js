import {createFinal} from './live-final.js';
import {renderAnalysis} from './analysis-progress.js?v=20260911-preview';
import {esc} from './views.js';
import {createProposalPanel} from './live-proposal.js';
import {createPendingActions} from './live-pending.js?v=20260911-predraft';
import {createResponseEditor} from './live-edit.js';
import {identification,responses,supports} from './live-views.js?v=20260911-predraft';
import {bindOriginal,focusOriginal} from './original-viewer.js?v=20260911-scroll';
import {bindSplitPane,focusRequest} from './split-pane.js?v=20260911-scroll';
import {createEvidenceUpload} from '/library-evidence.js';

async function api(path,body,method='POST'){
  const options=body===undefined?{}:{method,body:body instanceof FormData?body:JSON.stringify(body),headers:body instanceof FormData?{}:{'Content-Type':'application/json'}};
  const response=await fetch(path,options);const value=await response.json();
  if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'Revisa los campos y vuelve a intentarlo.');return value;
}
export function createLive({open,close,notice,releaseDemo}){
  let current=null,data=null,job={},mapping={},drafts={},review={},step=1,busy=false,timer,token=0,release=()=>{};
  const state={originalPage:1,originalSelection:null};const view=document.querySelector('#view');
  const editor=createResponseEditor({open,close,notice,getCase:()=>current,onSaved:async row=>{
    if(current?.id!==row.case_id)return;
    review.requests=review.requests.map(r=>r.request_id===row.request_id?row:r);render();
    document.querySelector(`[data-action="live-edit"][data-index="${data.requests.findIndex(r=>r.id===row.request_id)}"]`)?.focus();
  }});
  const final=createFinal({getCase:()=>current,getReview:()=>review,hasChanges:id=>editor.hasChanges(id),open,close,notice,refresh,render,isVisible:()=>Boolean(current)&&step===3,back:()=>{step=2;render();}});
  const path=suffix=>`/api/cases/${current.id}${suffix}`;
  const intake=createEvidenceUpload({open,close,notice,getCase:()=>current,getData:()=>({requests:data?.requests||[]}),render:()=>{},changed:()=>{},onUpdated:async()=>{
    try{await api(path('/preparation'),{version:current.version});await refresh();}catch(error){notice('El archivo se guardó. '+error.message);}
  }});
  const proposals=createProposalPanel({open,close,notice,getCase:()=>current,onSaved:async row=>{
    if(current?.id!==row.case_id)return;
    review.requests=review.requests.map(r=>r.request_id===row.request_id?row:r);render();
  }});
  const pendingActions=createPendingActions({open,close,notice,getCase:()=>current,
    upload:requestId=>intake.uploadForm(requestId,false),onSaved:async row=>{
      if(current?.id!==row.case_id)return;
      review.requests=review.requests.map(r=>r.request_id===row.request_id?row:r);render();
      if(row.pre_draft)await refresh();
    }});
  function render(){
    if(!current)return;const expanded=[...view.querySelectorAll("[data-pending-group][open]")].map(e=>e.dataset.pendingGroup);release();releaseDemo();
    document.querySelector('.steps').hidden=false;document.querySelector('.prototype').hidden=false;
    const locationState=new URL(location.href);locationState.searchParams.set('step',step);history.replaceState(null,'',locationState);
    document.querySelector('#case').classList.remove('active');
    document.querySelector('.prototype').textContent='Expediente guardado · revisa los puntos necesarios; las solicitudes listas se redactan automáticamente.';
    document.querySelector('.prototype-status').textContent='Expediente conectado';
    document.querySelector('.demo-badge').textContent='Gestión de Peticiones';
    document.querySelectorAll('[data-step]').forEach(b=>{b.disabled=busy||(Number(b.dataset.step)>1&&current.status!=='confirmed');if(Number(b.dataset.step)===step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
    if(!current.identification)renderAnalysis(view,current);
    else if(step===1)view.innerHTML=identification(data,state);
    else if(step===2)view.innerHTML=job.status?responses(current,job,mapping,drafts,review):'<h1>Respuestas para revisar</h1><p role="status">Recuperando el avance guardado…</p>';
    else view.replaceChildren(final.view());
    if(current.error&&current.identification)view.insertAdjacentHTML('afterbegin',`<p role="alert" class="alert">${esc(current.error)}</p><button data-action="live-analyze">Reintentar identificación</button>`);
    if(step===1&&data){bindOriginal(state,number=>run(()=>loadPage(number)));release=bindSplitPane();}
    view.querySelectorAll("[data-pending-group]").forEach(e=>e.open=expanded.includes(e.dataset.pendingGroup));
    updateSourcePanel();
    if(busy)view.querySelectorAll('button,input,select').forEach(b=>b.disabled=true);
  }
  function updateSourcePanel(){
    const panel=document.querySelector('#live-source-detail');
    if(!panel||panel.dataset.case!==current?.id)return;
    const finding=mapping.results?.find(f=>f.request_id===panel.dataset.request);
    const state=mapping.request_states?.[panel.dataset.request];
    const searching=mapping.status==='running'||(job.status==='running'&&job.stage==='sources');
    if(!finding&&searching){
      panel.innerHTML=state==='searching'?'<p class="source-loading" role="status"><span class="source-spinner" aria-hidden="true"></span>Buscando fuentes para esta solicitud…</p>':'<p role="status">En espera de un turno para buscar fuentes. El resultado aparecerá aquí.</p>';
      return;
    }
    panel.innerHTML=(finding?.summary?`<p ${finding.status==='error'?'class="alert" role="alert"':''}>${esc(finding.summary)}</p>`:'')+(finding?.supports?.length?supports(finding.supports,current.id):finding?.status==='error'?'':'<p>Todavía no hay pasajes seleccionados para esta solicitud.</p>');
  }
  function adapt(){
    data={...current,...current.identification,original_url:path('/original'),requests:(current.identification?.requests||[]).map(r=>({...r,request_id:r.id,original_marks:r.source_refs.map(ref=>({...ref,rectangles:[]}))})),original_pages:current.pages.map(p=>({...p,width:612,height:792,image:path(`/pages/${p.number}.png`)}))};
  }
  async function loadPage(number=1){
    const id=current.id,version=current.version,selected=data.requests[state.originalSelection];
    const page=await api(path(`/pages/${number}/view`)+(selected?'?request_id='+selected.id:''));
    if(!current||current.id!==id||current.version!==version)return;
    state.originalPage=number;Object.assign(data.original_pages.find(p=>p.number===number),page);
    if(selected)selected.original_marks=page.marks.map(m=>({...m,page:number}));
    render();if(selected)focusOriginal();
  }
  function schedule(){clearTimeout(timer);if(current&&(['reading','identifying'].includes(current.status)||job.status==='running'||review.requests?.some(r=>r.status==='checking')))timer=setTimeout(()=>refresh().catch(e=>{notice(e.message);schedule();}),2000);}
  async function refresh(){
    const id=current.id,sequence=token;
    const next=await api(path(''));if(sequence!==token||current?.id!==id)return;
    if(next.version!==current.version){current=next;adapt();if(step===1&&current.pages.length)await loadPage(state.originalPage);}
    if(current.status==='confirmed'){
      const results=await Promise.all([api(path('/preparation')),api(path('/sources')),api(path('/drafts')),api(path('/review'))]);
      if(sequence!==token||current?.id!==id)return;[job,mapping,drafts,review]=results;
    }
    render();schedule();
  }
  async function run(work){
    if(busy)return;busy=true;render();try{await work();}catch(error){notice(error.message);}finally{busy=false;render();if(step===1&&state.originalSelection!==null)focusOriginal();schedule();}
  }
  async function select(id){
    clearTimeout(timer);const sequence=++token;
    const before=new URL(location.href);const savedStep=before.searchParams.get('case')===id?Number(before.searchParams.get('step')):0;
    const value=await api('/api/cases/'+encodeURIComponent(id));if(sequence!==token)return;
    current=value;final.setCase();job={};mapping={};drafts={};review={};state.originalPage=1;state.originalSelection=null;step=value.status==='confirmed'&&[1,2,3].includes(savedStep)?savedStep:1;adapt();
    const url=new URL(location.href);url.searchParams.set('case',id);history.replaceState(null,'',url);render();
    await refresh();if(step===3)await final.load();if(!savedStep&&job.status==='running'){step=2;render();}if(current?.id===id&&current.pages.length&&step===1)await loadPage(1);
  }
  async function choose(){
    open('Mis expedientes','<div id="live-cases" role="status">Cargando expedientes…</div>');const container=document.querySelector('#live-cases');
    try{const cases=await api('/api/cases');if(!container.isConnected)return;
      container.innerHTML=cases.map(c=>`<button class="case" data-live-case="${esc(c.id)}"><strong>${esc(c.filename)}</strong><span>${c.request_count||0} solicitudes · ${esc(c.status==='confirmed'?'Identificación confirmada':c.status==='needs_review'?'Por revisar':c.status)}</span></button>`).join('')||'<p>Todavía no hay expedientes. Usa «Cargar petición» para comenzar.</p>';
      container.querySelectorAll('[data-live-case]').forEach(b=>b.onclick=()=>{close();run(()=>select(b.dataset.liveCase));});
    }catch(error){if(container.isConnected)container.textContent=error.message;}
  }
  async function upload(file){
    if(!file)return;
    await run(async()=>{const body=new FormData();body.set('file',file);const created=await api('/api/cases',body);await select(created.id);await api(path('/analyze'),{});await refresh();});
  }
  async function collections(){
    const caseId=current.id;
    open('Fuentes de consulta','<div id="live-groups" role="status"><span class="source-loading"><span class="source-spinner" aria-hidden="true"></span>Cargando colecciones…</span></div>');const container=document.querySelector('#live-groups');
    const groups=await api('/api/source-collections?case_id='+caseId);if(!container.isConnected||current?.id!==caseId)return;
    container.innerHTML=`<p>Estas colecciones delimitan los antecedentes que se consultarán para esta petición. Las normas compartidas y los soportes del expediente también se consideran.</p><form id="live-groups-form">${groups.collections.map(c=>`<label class="check"><input type="checkbox" name="collection" value="${esc(c.id)}" ${groups.linked_collection_ids.includes(c.id)?'checked':''}>${esc(c.name||c.id)}</label>`).join('')}<button class="primary">Guardar fuentes de consulta</button></form><p id="live-groups-error" role="alert"></p>`;
    document.querySelector('#live-groups-form').onsubmit=async event=>{event.preventDefault();const form=event.currentTarget;form.querySelector('button').disabled=true;
      try{if(current?.id!==caseId)throw new Error('El expediente cambió.');await api(`/api/cases/${caseId}/source-collections`,{collection_ids:new FormData(form).getAll('collection')},'PUT');close();notice('Fuentes de consulta guardadas.');}catch(e){if(form.isConnected){document.querySelector('#live-groups-error').textContent=e.message;form.querySelector('button').disabled=false;}}
    };
  }
  function correct(){
    const caseId=current.id,version=current.version;
    open('Corregir solicitud',`<form id="live-correction"><label class="field">Solicitud<select id="live-request">${data.requests.map((r,i)=>`<option value="${i}">${esc(r.label)}. ${esc(r.title)}</option>`).join('')}</select></label><label class="field">Título<input id="live-title" required maxlength="240"></label><label class="field">Qué solicita<textarea id="live-description" required maxlength="8000"></textarea></label><p>Se conserva la referencia al documento original.</p><button class="primary">Guardar corrección</button></form><p id="live-correction-error" role="alert"></p>`);
    const selector=document.querySelector('#live-request');const fill=()=>{const r=data.requests[Number(selector.value)];document.querySelector('#live-title').value=r.title;document.querySelector('#live-description').value=r.description;};selector.onchange=fill;fill();
    document.querySelector('#live-correction').onsubmit=async event=>{event.preventDefault();const form=event.currentTarget;form.querySelector('button').disabled=true;
      try{const identification=structuredClone(current.identification);const row=identification.requests[Number(selector.value)];row.title=document.querySelector('#live-title').value;row.description=document.querySelector('#live-description').value;await api(`/api/cases/${caseId}/identification`,{version,identification},'PUT');close();await select(caseId);}catch(e){if(form.isConnected){document.querySelector('#live-correction-error').textContent=e.message;form.querySelector('button').disabled=false;}}
    };
  }
  view.addEventListener('click',e=>{if(!current||busy)return;const b=e.target.closest('[data-action]');if(!b)return;const index=Number(b.dataset.index);
    run(async()=>{switch(b.dataset.action){
      case 'live-confirm':{const result=await api(path('/confirm-and-prepare'),{version:current.version});current=result.case;job=result.preparation;adapt();step=2;await refresh();break;}
      case 'live-resume':await api(path('/preparation'),{version:current.version});step=2;await refresh();break;
      case 'live-analyze':await api(path('/analyze'),{});await refresh();break;
      case 'live-responses':step=2;await refresh();break;
      case 'live-final':step=3;await refresh();await final.load();break;
      case 'original':state.originalSelection=index;await loadPage(data.requests[index].source_refs[0].page);break;
      case 'clear-original':state.originalSelection=null;await loadPage(state.originalPage);break;
      case 'back-to-question':focusRequest(index);break;
      case 'live-collections':await collections();break;
      case 'live-correct':correct();break;
      case 'live-pending':await pendingActions.decide(data.requests[index].id,b.dataset.pending,b.dataset.decision);break;
      case 'live-pending-history':await pendingActions.history(data.requests[index].id);break;
      case 'live-proposal':await proposals.show(data.requests[index].id);break;
      case 'live-edit':await editor.edit(data.requests[index].id);break;
      case 'live-evidence':await intake.uploadForm(data.requests[index].id,false);break;
      case 'live-sources':{open('Fuentes de la solicitud '+data.requests[index].label,`<div id="live-source-detail" data-case="${esc(current.id)}" data-request="${esc(data.requests[index].id)}"></div>`);updateSourcePanel();break;}
    }});
  });
  return {active:()=>Boolean(current),choose,upload,select,go(value){if(busy)return;step=value;render();if(step===3)void run(async()=>{await refresh();await final.load();});},leave(){token++;clearTimeout(timer);release();current=null;data=null;history.replaceState(null,'',location.pathname);document.querySelector('#case').classList.add('active');document.querySelector('.prototype').textContent='Petición de demostración · para trabajar con un documento real, usa «Cargar petición» o «Mis expedientes».';document.querySelector('.demo-badge').textContent='Demo';document.querySelector('.prototype-status').textContent='Demo + biblioteca';},init(){const id=new URL(location.href).searchParams.get('case');return id?run(()=>select(id)):Promise.resolve();}};
}
