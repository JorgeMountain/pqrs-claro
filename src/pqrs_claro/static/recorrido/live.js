import {createReviewDraftStore,restoreDraft,draftPreview,draftEnvelope} from './review-drafts.js?v=phase2';
import {createFinal} from './live-document.js?v=phase2';
import {renderAnalysis} from './analysis-progress.js?v=20260911-preview';
import {esc} from './views.js';
import {renderCaseNavigation} from './live-case-navigation.js?v=phase2';
import {createProposalPanel} from './live-proposal.js?v=20260919-supports';
import {createPendingActions} from './live-pending.js?v=20260919-supports';
import {createResponseEditor} from './live-edit.js?v=20260919-supports';
import {identification,responses,supports} from './live-views.js?v=phase2';
import {createIdentificationActions} from './identification-actions.js';
import {bindOriginal,focusOriginal} from './original-viewer.js?v=20260911-scroll';
import {bindSplitPane,focusRequest} from './split-pane.js?v=20260911-scroll';
import {createEvidenceUpload} from '/library-evidence.js';
import {initialReviewSummary,initialRequestContent,initialReady,initialHistory,readInitialDecision,initialConfirmation,updateInitialConfirmation} from './initial-review.js?v=phase2';
import {confirmAndPrepare} from './initial-confirmation.js?v=phase2';

async function api(path,body,method='POST'){
  const options=body===undefined?{}:{method,body:body instanceof FormData?body:JSON.stringify(body),headers:body instanceof FormData?{}:{'Content-Type':'application/json'}};
  const response=await fetch(path,options);const value=await response.json();
  if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'Revisa los campos y vuelve a intentarlo.');return value;
}
export function createLive({open,close,notice,releaseDemo,showMail,onBrowse}){
  let current=null,data=null,job={},mapping={},drafts={},review={},step=1,busy=false,timer,token=0,release=()=>{};
  const state={originalPage:1,originalSelection:null};const view=document.querySelector('#view');
  let initialEnabled=false,automaticInitial=false,initial={},initialForm=null,initialActionError='',configLoaded=false;
  const draftStore=createReviewDraftStore(localStorage);
  let savedDraft=null,draftMessage='',draftProblem=false;
  function persistDraft(){
    if(!current||!initialForm)return true;
    try{savedDraft=draftStore.write(current,initial,initialForm);draftProblem=false;draftMessage='Borrador guardado en este navegador. No inicia IA ni confirma la revisión.';return true;}
    catch(error){draftProblem=true;draftMessage=['QuotaExceededError','SecurityError'].includes(error.name)?'El navegador no pudo guardar el borrador. Descarga una copia antes de salir.':error.message||'No se pudo guardar el borrador en este navegador.';return false;}
  }
  function recoverDraft(){
    try{savedDraft=draftStore.read(current.id);const result=restoreDraft(savedDraft,current,initial);initialForm=result.draft;draftMessage=result.message;draftProblem=false;}
    catch{draftProblem=true;draftMessage='No se pudo recuperar el borrador. No se ha eliminado su copia guardada.';}
  }
  function draftFeedback(){const status=view.querySelector('[data-draft-status]');if(status){status.textContent=draftMessage;status.setAttribute('role',draftProblem?'alert':'status');}}
  window.addEventListener('beforeunload',event=>{if(draftProblem&&initialForm){event.preventDefault();event.returnValue='';}});
  async function config(){if(configLoaded)return;const settings=await api('/api/config');initialEnabled=Boolean(settings.initial_review_enabled);automaticInitial=Boolean(settings.automatic_initial_review);configLoaded=true;if(initialEnabled&&!document.querySelector('.fiaga-environment')){const banner=document.createElement('div');banner.className='fiaga-environment';banner.textContent=settings.environment_label||'PQRS · revisión inicial y confirmación humana';document.querySelector('header').after(banner);}}
  function initialSteps(){
    document.querySelector('[data-step="1"]').innerHTML=`<span>1</span> ${initialEnabled&&current?'Procesar solicitud':'Entender la petición'}`;
  }
  const initialDirty=()=>Boolean(initialForm&&initialForm.case_id===current?.id&&initialForm.revision===initial.revision);
  const closed=()=>current?.management?.state==='closed';
  const canNavigate=()=>closed()||canPrepare();
  const canPrepare=()=>initialReady(initial)&&initial.can_prepare&&!initialDirty();
  const rememberDecision=event=>{
    if(!current||event.target.form?.id!=='initial-decision-form')return;
    if(event.target.name!=='reviewed-all')view.querySelector('[name="reviewed-all"]').checked=false;
    initialForm=readInitialDecision(view,current,initial);
    persistDraft();draftFeedback();
    initialActionError='';
    view.querySelectorAll('[data-initial-error]').forEach(e=>e.hidden=true);
    view.querySelectorAll('.initial-unsaved').forEach(e=>e.hidden=!initialDirty());
    const summaryStatus=view.querySelector('.intake-summary-heading .initial-state'),summaryText=view.querySelector('.intake-summary-content [role="status"]');
    if(summaryStatus)summaryStatus.textContent='Cambios sin confirmar';
    if(summaryText)summaryText.textContent=draftProblem?'El borrador no se pudo guardar. Conserva una copia antes de salir.':'Tu borrador está guardado en este navegador; todavía no está confirmado.';
    document.querySelectorAll('[data-step="2"],[data-step="3"]').forEach(e=>e.disabled=busy||!canPrepare());
    updateInitialConfirmation(view,initial,initialForm);
  };
  view.addEventListener('input',rememberDecision);
  view.addEventListener('change',rememberDecision);
  view.addEventListener('submit',event=>{
    if(event.target.id!=='initial-decision-form')return;
    event.preventDefault();
    view.querySelector('[data-action="live-initial-confirm"]')?.click();
  });
  const identificationActions=createIdentificationActions({api,open,close,notice,getCase:()=>current,onSaved:select});
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
    if(!current)return;const expanded=[...view.querySelectorAll("[data-pending-group][open]")].map(e=>e.dataset.pendingGroup);const initialExpanded=new Map([...view.querySelectorAll('[data-initial-disclosure]')].map(e=>[e.dataset.initialDisclosure,e.open]));release();releaseDemo();initialSteps();
    document.querySelector('.steps').hidden=false;document.querySelector('.prototype').hidden=false;
    const locationState=new URL(location.href);locationState.searchParams.set('step',step);history.replaceState(null,'',locationState);
    document.querySelector('#case').classList.remove('active');
    document.querySelector('.prototype').textContent=initialEnabled?'Expediente guardado · revisa el trámite y las peticiones antes de preparar las respuestas.':'Expediente guardado · revisa los puntos necesarios; las solicitudes listas se redactan automáticamente.';
    document.querySelector('.prototype-status').textContent='Expediente conectado';
    document.querySelector('.demo-badge').textContent='Gestión de Peticiones';
    document.querySelectorAll('[data-step]').forEach(b=>{b.disabled=busy||(Number(b.dataset.step)>1&&current.status!=='confirmed')||(initialEnabled&&[2,3].includes(Number(b.dataset.step))&&!canNavigate());if(Number(b.dataset.step)===step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
    if(!current.identification)renderAnalysis(view,current);
    else if(step===1)view.innerHTML=identificationActions.banner()+identification({...data,initial_review_enabled:initialEnabled,automatic_initial_review:automaticInitial},state,{summary:initialEnabled?initialReviewSummary(current,initial,initialForm,{automatic:automaticInitial}):'',requestContent:initialEnabled?initialRequestContent(current,initial,initialForm):{},confirmation:initialEnabled&&!closed()?initialConfirmation(current,initial,initialForm,{busy,error:initialActionError,draftMessage,draftProblem,hasPrevious:Boolean(savedDraft)}):'',initial:{...initial,ready:initialReady(initial),can_prepare:canPrepare()}});
    else if(step===2)view.innerHTML=job.status?responses(current,job,mapping,drafts,review):'<h1>Respuestas para revisar</h1><p role="status">Recuperando el avance guardado…</p>';
    else {const paper=final.view();if(view.firstChild!==paper)view.replaceChildren(paper);}
    renderCaseNavigation(view,current,{step,showMail:Boolean(showMail)});
    if(current.error&&current.identification)view.insertAdjacentHTML('afterbegin',`<p role="alert" class="alert">${esc(current.error)}</p><button data-action="live-analyze">Reintentar identificación</button>`);
    if(step===1&&data){bindOriginal(state,number=>run(()=>loadPage(number)));release=bindSplitPane();}
    view.querySelectorAll("[data-pending-group]").forEach(e=>e.open=expanded.includes(e.dataset.pendingGroup));
    view.querySelectorAll('[data-initial-disclosure]').forEach(e=>{if(initialExpanded.has(e.dataset.initialDisclosure))e.open=initialExpanded.get(e.dataset.initialDisclosure);});
    if(step===1&&initialEnabled&&initialReady(initial)&&!busy)updateInitialConfirmation(view,initial,readInitialDecision(view,current,initial),{saved:canPrepare(),recorded:Boolean(initial.document_decision)&&!initialDirty()});
    updateSourcePanel();
    if(closed()){
      view.insertAdjacentHTML('afterbegin','<p class="alert" role="status">Expediente finalizado · consulta disponible. Para editar o iniciar otro análisis, reabre la gestión desde «Detalles y gestión» en la bandeja.</p>');
      view.querySelectorAll('input,textarea,select:not(#original-page),[data-evidence-add]').forEach(e=>e.disabled=true);
      const readActions=new Set(['live-queue','live-mail-origin','live-initial','live-initial-history','live-pending-history','live-responses','live-final','live-sources','original','clear-original','back-to-question']);
      view.querySelectorAll('[data-action]').forEach(e=>{if(!readActions.has(e.dataset.action))e.disabled=true;});
    }
    if(busy)view.querySelectorAll('button,input,select,textarea').forEach(b=>b.disabled=true);
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
  function schedule(){clearTimeout(timer);if(current&&(current.analysis_running||['reading','identifying'].includes(current.status)||initial.status==='running'||job.status==='running'||review.requests?.some(r=>r.status==='checking')))timer=setTimeout(()=>refresh().catch(e=>{notice(e.message);schedule();}),2000);}
  async function refresh(){
    const id=current.id,sequence=token;
    const next=await api(path(''));if(sequence!==token||current?.id!==id)return;
    if(next.version!==current.version){current=next;adapt();if(step===1&&current.pages.length)await loadPage(state.originalPage);}
    current.analysis_running=next.analysis_running;current.management=next.management;
    if(initialEnabled&&current.identification){
      const value=await api(path('/initial-review'));if(sequence!==token||current?.id!==id)return;
      const changed=value.revision!==initial.revision;
      initial=value;if(changed||!initialForm)recoverDraft();if(!canNavigate()&&[2,3].includes(step))step=1;
    }
    if(current.status==='confirmed'){
      const results=await Promise.all([api(path('/preparation')),api(path('/sources')),api(path('/drafts')),api(path('/review'))]);
      if(sequence!==token||current?.id!==id)return;[job,mapping,drafts,review]=results;

    }
    render();schedule();
  }
  async function run(work){
    if(busy)return;
    const documentFocused=document.activeElement?.closest('.original-viewer,[data-action="original"]');
    const initialAction=document.activeElement?.closest('[data-action^="live-initial"]')?.dataset.action;
    busy=true;render();
    try{await work();}catch(error){notice(error.message);}
    finally{
      busy=false;render();
      if(step===1&&documentFocused)focusOriginal();
      else if(initialAction&&!document.querySelector('#drawer')?.open){
        const target=step===1?view.querySelector(`[data-action="${initialAction}"]:not([hidden])`):view.querySelector('h1');
        if(target?.tagName==='H1')target.tabIndex=-1;
        target?.focus({preventScroll:step===1});
      }
      schedule();
    }
  }
  async function select(id){
    if(current&&initialForm&&!persistDraft()){draftFeedback();notice(draftMessage);return;}
    await config();
    clearTimeout(timer);const sequence=++token;
    const before=new URL(location.href);const savedStep=before.searchParams.get('case')===id?Number(before.searchParams.get('step')):0;
    const value=await api('/api/cases/'+encodeURIComponent(id));if(sequence!==token)return;
    if(value.management&&(!value.management.owner_id||!value.management.started_at)){await onBrowse();return;}current=value;final.setCase();job={};mapping={};drafts={};review={};initial={};initialForm=null;savedDraft=null;draftMessage='';draftProblem=false;initialActionError='';state.originalPage=1;state.originalSelection=null;step=value.status==='confirmed'&&[1,2,3].includes(savedStep)?savedStep:1;adapt();
    const url=new URL(location.href);url.searchParams.set('case',id);history.replaceState(null,'',url);render();
    await refresh();if(step===3)await final.load();if(!savedStep&&job.status==='running'&&(!initialEnabled||canPrepare())){step=2;render();}if(current?.id===id&&current.pages.length&&step===1)await loadPage(1);
  }
  async function choose(){
    return onBrowse();
  }
  async function upload(file){
    if(!file)return;
    await run(async()=>{const body=new FormData();body.set('file',file);const created=await api('/api/cases',body);await onBrowse();notice('Expediente recibido. Asígnalo e inicia su gestión desde la bandeja.');});
  }
  async function collections(){
    const caseId=current.id;
    open('Fuentes de consulta','<div id="live-groups" role="status"><span class="source-loading"><span class="source-spinner" aria-hidden="true"></span>Cargando colecciones…</span></div>');const container=document.querySelector('#live-groups');
    const groups=await api('/api/source-collections?case_id='+caseId);if(!container.isConnected||current?.id!==caseId)return;
    container.innerHTML=`<p>Estas colecciones delimitan los antecedentes que se consultarán para esta petición. Las normas compartidas y los soportes del expediente también se consideran.</p><form id="live-groups-form">${groups.collections.map(c=>`<label class="check"><input type="checkbox" name="collection" value="${esc(c.id)}" ${groups.linked_collection_ids.includes(c.id)?'checked':''}>${esc(c.name||c.id)}</label>`).join('')}<button class="primary">Guardar fuentes de consulta</button></form><p id="live-groups-error" role="alert"></p>`;
    document.querySelector('#live-groups-form').onsubmit=async event=>{event.preventDefault();const form=event.currentTarget;form.querySelector('button').disabled=true;
      try{if(current?.id!==caseId)throw new Error('El expediente cambió.');await api(`/api/cases/${caseId}/source-collections`,{collection_ids:new FormData(form).getAll('collection')},'PUT');close();await refresh();notice('Fuentes de consulta guardadas.');}catch(e){if(form.isConnected){document.querySelector('#live-groups-error').textContent=e.message;form.querySelector('button').disabled=false;}}
    };
  }
  function correct(index=0){
    const caseId=current.id,version=current.version;
    open('Corregir solicitud',`<form id="live-correction"><label class="field">Solicitud<select id="live-request">${data.requests.map((r,i)=>`<option value="${i}">${esc(r.label)}. ${esc(r.title)}</option>`).join('')}</select></label><label class="field">Título<input id="live-title" required maxlength="240"></label><label class="field">Qué solicita<textarea id="live-description" required maxlength="8000"></textarea></label><p>Se conserva la referencia al documento original.</p><button class="primary">Guardar corrección</button></form><p id="live-correction-error" role="alert"></p>`);
    const selector=document.querySelector('#live-request');selector.value=String(index);const fill=()=>{const r=data.requests[Number(selector.value)];document.querySelector('#live-title').value=r.title;document.querySelector('#live-description').value=r.description;};selector.onchange=fill;fill();
    document.querySelector('#live-correction').onsubmit=async event=>{event.preventDefault();const form=event.currentTarget;form.querySelector('button').disabled=true;
      try{const identification=structuredClone(current.identification);const row=identification.requests[Number(selector.value)];row.title=document.querySelector('#live-title').value;row.description=document.querySelector('#live-description').value;await api(`/api/cases/${caseId}/identification`,{version,identification},'PUT');close();await select(caseId);}catch(e){if(form.isConnected){document.querySelector('#live-correction-error').textContent=e.message;form.querySelector('button').disabled=false;}}
    };
  }
  view.addEventListener('click',e=>{if(!current||busy)return;const b=e.target.closest('[data-action]');if(!b)return;const index=Number(b.dataset.index);
    if(b.dataset.action==='live-initial'){
      const detail=view.querySelector('#initial-review-details');
      if(detail)detail.open=true;
      (detail?.querySelector('summary')||view.querySelector('#intake-summary-title'))?.focus();
      return;
    }
    if(b.dataset.action==='live-initial-save'){initialForm=readInitialDecision(view,current,initial);persistDraft();render();draftFeedback();view.querySelector('[data-action="live-initial-save"]')?.focus({preventScroll:true});notice(draftMessage);return;}
    if(b.dataset.action==='live-initial-draft-preview'){open('Borrador anterior · sin confirmar',draftPreview(savedDraft));return;}
    if(b.dataset.action==='live-initial-draft-download'){
      const copy=initialForm?draftEnvelope(current,initial,initialForm,savedDraft):savedDraft||draftEnvelope(current,initial,readInitialDecision(view,current,initial));
      const url=URL.createObjectURL(new Blob([JSON.stringify(copy,null,2)],{type:'application/json'}));
      const link=document.createElement('a');link.href=url;link.download=`borrador-${current.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;
    }
    const decision=b.dataset.action==='live-initial-confirm'?readInitialDecision(view,current,initial):null;
    if(decision){
      updateInitialConfirmation(view,initial,decision,{saved:canPrepare()});
      const form=view.querySelector('#initial-decision-form');
      for(const field of form.elements){
        if(field.willValidate&&!field.validity.valid){
          let detail=field.closest('details');
          while(detail){detail.open=true;detail=detail.parentElement.closest('details');}
        }
      }
      if(!form.reportValidity())return;
    }
    run(async()=>{switch(b.dataset.action){
      case 'live-initial-analyze':{const target=current.id;const next=await api(path('/initial-review/analyze'),{version:current.version,revision:initial.revision||0});if(current?.id!==target)break;initial=next;initialForm=null;await refresh();break;}
      case 'live-initial-confirm':{
        if(!decision||!initialReady(initial))break;
        const caseId=current.id;initialActionError='';
        try{
          const result=await confirmAndPrepare({saved:canPrepare()?initial:null,decision,report:initial.report,
            save:body=>api(`/api/cases/${caseId}/initial-review/decision`,body,'PUT'),
            onSaved:value=>{try{draftStore.clear(caseId);}catch{notice('La revisión quedó confirmada. No se pudo retirar la copia del borrador de este navegador.');}if(current?.id===caseId){initial=value;initialForm=null;savedDraft=null;draftMessage='';draftProblem=false;}},
            prepare:async()=>{const latest=await api(`/api/cases/${caseId}`);return api(`/api/cases/${caseId}/preparation`,{version:latest.version});}});
          if(current?.id!==caseId)break;
          if(result.error){initialActionError=result.error;await refresh();break;}
          if(result.prepared){step=2;await refresh();}
          else {await refresh();notice('Decisión guardada. La ruta elegida mantiene el expediente en este paso.');}
        }catch(error){if(current?.id===caseId)initialActionError=error.message;}
        break;
      }
      case 'live-initial-history':{const result=await api(path('/initial-review/history'));open('Historial del trámite',initialHistory(result.events));break;}
      case 'live-queue':await onBrowse();break;
      case 'live-mail-origin':await showMail?.(current.id);break;
      case 'live-confirm':{const result=await api(path('/confirm-and-prepare'),{version:current.version});current=result.case;job=result.preparation;adapt();step=initialEnabled?1:2;await refresh();if(initialEnabled)notice('Solicitudes confirmadas. Ya puedes analizar el trámite en el resumen.');break;}
      case 'live-retry-failed':await api(path('/preparation'),{version:current.version,retry_failed_only:true});step=2;await refresh();break;
      case 'live-resume':await api(path('/preparation'),{version:current.version,retry_analysis:b.dataset.retryAnalysis==='true'});step=2;await refresh();break;
      case 'live-analyze':await api(path('/analyze'),{});await refresh();break;
      case 'live-responses':step=initialEnabled&&!canNavigate()?1:2;await refresh();break;
      case 'live-final':step=3;await refresh();await final.load();break;
      case 'original':state.originalSelection=index;await loadPage(data.requests[index].source_refs[0].page);break;
      case 'clear-original':state.originalSelection=null;await loadPage(state.originalPage);break;
      case 'back-to-question':focusRequest(index);break;
      case 'live-collections':await collections();break;
      case 'live-correct':correct(Number.isInteger(index)?index:0);break;
      case 'live-discard':identificationActions.discard(index);break;
      case 'live-undo-discard':await identificationActions.restore();break;
      case 'live-pending':await pendingActions.decide(data.requests[index].id,b.dataset.pending,b.dataset.decision);break;
      case 'live-pending-history':await pendingActions.history(data.requests[index].id);break;
      case 'live-proposal':await proposals.show(data.requests[index].id);break;
      case 'live-edit':await editor.edit(data.requests[index].id);break;
      case 'live-evidence':await intake.uploadForm(data.requests[index].id,false);break;
      case 'live-sources':{open('Fuentes de la solicitud '+data.requests[index].label,`<div id="live-source-detail" data-case="${esc(current.id)}" data-request="${esc(data.requests[index].id)}"></div>`);updateSourcePanel();break;}
    }});
  });
  return {active:()=>Boolean(current),choose,upload,select,go(value){if(busy)return;step=initialEnabled&&[2,3].includes(value)&&!canNavigate()?1:[1,2,3].includes(value)?value:1;render();if(step===3)void run(async()=>{await refresh();await final.load();});},leave(){if(current&&initialForm&&!persistDraft()){draftFeedback();notice(draftMessage);return false;}token++;clearTimeout(timer);release();current=null;data=null;initialSteps();history.replaceState(null,'',location.pathname);document.querySelector('#case').classList.add('active');document.querySelector('.prototype').textContent='Petición de demostración · para trabajar con un documento real, usa «Cargar petición» o «Mis expedientes».';document.querySelector('.demo-badge').textContent='Demo';document.querySelector('.prototype-status').textContent='Demo + biblioteca';},async init(){await config();const id=new URL(location.href).searchParams.get('case');return id?run(()=>select(id)):Promise.resolve();}};
}
