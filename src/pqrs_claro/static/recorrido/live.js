import {focusStageReview,focusResponse} from './workflow-navigation.js';
import {reviewNavigation,reviewItems,nextReviewIndex,focusReviewPetition,syncReviewNavigation,suggestedReviewer} from './review-navigation.js?v=review-context2';
import {createReviewDraftStore,restoreDraft,draftPreview,draftEnvelope,downloadableDraft} from './review-drafts.js?v=phase2';
import {createFinal} from './live-document.js?v=approval-progress1';
import {renderAnalysis} from './analysis-progress.js?v=20260911-preview';
import {esc} from './views.js';
import {watchPreparation} from './library-progress.js';
import {renderCaseNavigation} from './live-case-navigation.js?v=phase2';
import {createProposalPanel} from './live-proposal.js?v=20260919-supports';
import {createPendingActions} from './live-pending.js?v=pending-guide1';
import {createResponseEditor} from './live-edit.js?v=20260919-supports';
import {identification,responses,supports} from './live-views.js?v=reading-confirmation1';
import {captureRedactionView,restoreRedactionView} from './redaction-workspace.js?v=reading-confirmation1';
import {createIdentificationActions} from './identification-actions.js';
import {bindOriginal,focusOriginal} from './original-viewer.js?v=20260911-scroll';
import {bindSplitPane,focusRequest} from './split-pane.js?v=20260911-scroll';
import {createEvidenceUpload} from '/library-evidence.js?v=pending-guide1';
import {initialReviewSummary,initialRequestContent,initialReady,initialHistory,readInitialDecision,initialConfirmation,updateInitialConfirmation} from './initial-review.js?v=reading-space1';
import {identificationWorkspace,bindIdentificationWorkspace,expedienteHeading,expedienteSteps} from './expediente-workspace.js?v=stage-progress1';
import {confirmAndPrepare} from './initial-confirmation.js?v=redaction-recovery1';
import {pilotReviewControls} from './pilot-review.js?v=pilot1';
import {watchSourceScope,announceScopeReduction} from '/shared/source-scope.js';

async function api(path,body,method='POST',cancel){
  const options=body===undefined?{}:{method,body:body instanceof FormData?body:JSON.stringify(body),headers:body instanceof FormData?{}:{'Content-Type':'application/json'}};
  let response;
  const timeout=AbortSignal.timeout(60000);
  try{response=await fetch(path,{...options,signal:cancel?AbortSignal.any([timeout,cancel]):timeout});}
  catch(error){
    if(cancel?.aborted){const aborted=new Error('Consulta cancelada.');aborted.name='AbortError';throw aborted;}
    if(['TimeoutError','AbortError'].includes(error.name))throw new Error('La consulta está tardando más de lo esperado. El avance guardado se conserva; actualiza el estado para recuperarlo.');
    throw error;
  }
  let value=null;
  try{value=await response.json();}catch{value=null;}
  if(!response.ok||!value)throw new Error(typeof value?.detail==='string'?value.detail:'Revisa los campos y vuelve a intentarlo.');
  return value;
}
function runningStages(record, initialStatus, preparation, draftRunning) {
  return [
    record.preanalysis_status==='running',
    Boolean(record.analysis_running || ['reading','identifying'].includes(record.status) || initialStatus==='running'),
    !preparation?.stale && ['starting','running'].includes(preparation?.status),
    Boolean(draftRunning ?? (record.office_progress?.status==='generating')),
  ];
}
export function createLive({open,close,notice,releaseDemo,showMail,onBrowse,onPreanalysis,onPreanalysisNavigation,onWorkCase=()=>{},onFiagaHandoff=null}){
  let current=null,data=null,job={},mapping={},drafts={},review={},step=1,busy=false,timer,token=0,release=()=>{};
  const state={originalPage:1,originalSelection:null,originalZoom:100};const view=document.querySelector('#view');
  let pageRead=0;
  let initialEnabled=false,automaticInitial=false,initial={},initialForm=null,initialActionError='',configLoaded=false;
  const draftStore=createReviewDraftStore(localStorage);
  let reviewCursor=-1,reviewManagers=[];
  let savedDraft=null,draftMessage='',draftProblem=false;
  let refreshing=null,refreshError='',readingError='',confirmingReading=false;
  let selectedResponse=null,finalSummary={},suspended=false,reached=1,redactionPosition=null;
  let selectedChunk=null;
  let savedNavigation=null;
  let resumeRequest=null,partialRedaction=false,previewController=null;
  let correctionNotice=null,redactionSaveError='',savingResponses=false;
  let checkingCorrection=false;
  const initialCache=new Map();
  const fiaga=Boolean(onFiagaHandoff);
  const reviewerName=()=>fiaga?'Administrador':suggestedReviewer(reviewManagers,localStorage.getItem('pqrs-pilot-manager'));
  const draftAvailable=()=>!fiaga||Boolean(review.reading_confirmation?.confirmed);
  const stageKey=id=>'pqrs-stage-'+id;
  function rememberedStage(id){try{return Math.min(3,Math.max(1,Number(localStorage.getItem(stageKey(id)))||1));}catch{return 1;}}
  function rememberStage(value){reached=Math.max(reached,value);try{localStorage.setItem(stageKey(current.id),String(reached));}catch{/* Navigation still works without browser storage. */}}
  function restoredRequest(url,explicitId){
    const sameCase=url.searchParams.get('case')===current.id;
    let candidate=explicitId;
    if(!candidate&&sameCase&&url.searchParams.get('step')==='2'&&url.searchParams.has('request')){
      const version=url.searchParams.get('request_version');
      if(version!==null&&version!==String(current.version))return null;
      candidate=url.searchParams.get('request');
    }else if(!candidate){
      try{
        const saved=JSON.parse(localStorage.getItem('pqrs-response-'+current.id));
        if(saved?.version===current.version)candidate=saved.id;
      }catch{/* A missing or older record starts with the regular view. */}
    }
    return data.requests.find(r=>r.id===candidate)?.id||null;
  }
  async function readSelectedResponse(requestId){
    const scope=token,controller=new AbortController();
    previewController=controller;
    mapping={};drafts={};review={};render();
    try{
      const value=await api(path('/review/requests/'+encodeURIComponent(requestId)+'/preview'),undefined,'GET',controller.signal);
      if(scope!==token||controller.signal.aborted||requestId!==selectedResponse)return;
      if(value.request_id!==requestId)throw new Error('La respuesta recuperada corresponde a otra petición.');
      mapping=value.mapping;drafts=value.drafts;review=value.review;
      render();
    }finally{if(previewController===controller)previewController=null;}
  }
  function navigation(){
    const savedExport=current.office_progress?.status==='ready';
    const written=finalSummary.id===current.id?finalSummary.redactionComplete:savedExport||review.requests?.length>0&&review.requests.length===current.request_count&&review.requests.every(r=>r.paragraphs?.length&&!r.stale);
    const generated=finalSummary.id===current.id?finalSummary.draftComplete:savedExport;
    const historical=(initial.status||current.initial_review_status)==='idle'&&current.saved_stage>=2;
    const draftRunning=finalSummary.id===current.id&&step===3?finalSummary.running:undefined;
    const running=runningStages(current,initial.status||current.initial_review_status,job,draftRunning);
    return {fiaga,running,available:[Boolean(onPreanalysis),true,canNavigate(),canNavigate()&&draftAvailable()],completed:[current.preanalysis_status==='ready',!historical&&!initial.stale&&(Boolean(initial.can_prepare)||reached>=2),fiaga?draftAvailable():Boolean(written),Boolean(generated)],labels:[current.preanalysis_status==='idle'?'Sin registro':'Guardado',historical?'Guardada':initial.stale?'Por actualizar':initialReady(initial)?'Por revisar':'Guardado',reached>=2?'Guardado':'Pendiente',reached>=3?'Guardado':'Pendiente']};
  }
  const savedSteps=nav=>expedienteSteps(0,{navigation:nav,activeLabel:'Consulta guardada'});
  async function refreshSavedNavigation(watch){
    if(!suspended||watch!==savedNavigation||watch.reading)return;
    watch.reading=true;
    const isCurrent=()=>suspended&&watch===savedNavigation&&watch.token===token;
    let running;
    try{
      const snapshot=await api(path(''));
      if(!isCurrent())return;
      if(watch.checking){
        const assessment=await api(path('/review'));
        if(!isCurrent())return;
        watch.checking=assessment.requests?.some(row=>row.status==='checking');
      }
      running=runningStages(snapshot,snapshot.initial_review_status,snapshot.preparation,watch.checking||final.isBusy?.()||undefined);
      watch.retry=false;
    }catch{
      if(!isCurrent())return;
      running=[false,false,false,false];
      watch.retry=true;
    }finally{
      watch.reading=false;
    }
    if(running.some((value,index)=>value!==watch.nav.running[index])){
      watch.nav={...watch.nav,running};
      onPreanalysisNavigation(savedSteps(watch.nav),watch.nav);
    }
    schedule();
  }
  async function showPreanalysis(){
    if(!current||!onPreanalysis)return;
    if(initialForm&&!persistDraft()){draftFeedback();notice(draftMessage);return;}
    redactionPosition=captureRedactionView(view)||redactionPosition;suspended=true;final.hide();release();
    const url=new URL(location.href);url.searchParams.set('view',fiaga?'revision-fiaga':'preanalysis');url.searchParams.set('step','0');history.replaceState(null,'',url);
    const nav=navigation(), markup=savedSteps(nav);
    const watch={nav,token,checking:step===3&&finalSummary.id===current.id&&finalSummary.checking};
    savedNavigation=watch;
    schedule();
    try{await onPreanalysis(current,markup,nav);}
    catch(error){if(watch===savedNavigation&&suspended){savedNavigation=null;suspended=false;render();schedule();notice(error.message);}}
  }
  function navigate(value){
    if(!current||busy||![1,2,3].includes(value)||value>1&&!canNavigate()||value===3&&!draftAvailable())return;
    clearTimeout(timer);savedNavigation=null;step=value;suspended=false;render();
    // Reading another stage never starts a worker or confirms a decision.
    if(step===3)void final.load().catch(error=>notice(error.message));
    else {
      if(step===1?!initial.status:!mapping.status)void refresh().catch(error=>notice(error.message));
      else schedule();
      if(step===1&&current.pages.length)void loadPage(state.originalPage).catch(error=>notice(error.message));
    }
  }
  function finalHeading(){const nav=navigation();return expedienteHeading(current,3,{title:'Borrador del oficio',subtitle:fiaga?'Comprueba la respuesta y los faltantes antes de organizar los trámites.':'Revisa el documento y resuelve los ajustes antes de aprobar.',navigation:nav,canContinue:canNavigate(),showMail:Boolean(showMail),redactionComplete:nav.completed[2],draftComplete:nav.completed[3]}).replace('data-action="live-queue"','data-action="live-responses"').replace('Volver a la bandeja','Volver a redacción');}

  function persistDraft(){
    if(!current||!initialForm)return true;
    try{savedDraft=draftStore.write(current,initial,initialForm);draftProblem=false;draftMessage='Borrador guardado en este navegador. No inicia IA ni confirma la revisión.';return true;}
    catch(error){draftProblem=true;draftMessage=['QuotaExceededError','SecurityError'].includes(error.name)?'El navegador no pudo guardar el borrador. Descarga una copia antes de salir.':error.message||'No se pudo guardar el borrador en este navegador.';return false;}
  }
  function recoverDraft(){
    try{savedDraft=draftStore.read(current.id);const result=restoreDraft(savedDraft,current,initial);initialForm=result.draft;draftMessage=result.message;draftProblem=false;}
    catch{draftProblem=true;draftMessage='No se pudo recuperar el borrador. No se ha eliminado su copia guardada.';}
  }
  function draftFeedback(){if(draftProblem){const options=view.querySelector('.expediente-review-options');if(options)options.open=true;}const status=view.querySelector('[data-draft-status]');if(status){status.textContent=draftMessage;status.setAttribute('role',draftProblem?'alert':'status');}}
  async function config(){
    if(configLoaded)return;
    const settings=await api('/api/config');
    initialEnabled=fiaga||Boolean(settings.initial_review_enabled);
    automaticInitial=Boolean(settings.automatic_initial_review);
    if(!fiaga&&settings.management_enabled){try{reviewManagers=await api('/api/managers');}catch{reviewManagers=[];}}
    configLoaded=true;
  }
  function initialSteps(){
    document.querySelector('[data-step="1"]').innerHTML=`<span>1</span> ${initialEnabled&&current?'Procesar solicitud':'Entender la petición'}`;
  }
  const initialDirty=()=>Boolean(initialForm&&initialForm.case_id===current?.id&&initialForm.revision===initial.revision);
  const closed=()=>current?.management?.state==='closed';
  const workspace=()=>initialEnabled&&Boolean(current?.management);
  const canNavigate=()=>fiaga ? Boolean(initial.can_prepare&&!initial.pilot_bypass_active&&!initial.stale) : closed()||canPrepare()||reached>=2;
  const canPrepare=()=>initial.can_prepare&&(initial.pilot_bypass_active||initialReady(initial)&&!initialDirty());
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
    updateInitialConfirmation(view,initial,initialForm);syncReviewNavigation(view,current,initial,initialForm);
  };
  view.addEventListener('input',rememberDecision);
  view.addEventListener('change',rememberDecision);
  view.addEventListener('submit',event=>{
    if(event.target.id!=='initial-decision-form')return;
    event.preventDefault();
    view.querySelector('[data-action="live-initial-confirm"]')?.click();
  });
  const identificationActions=createIdentificationActions({api,open,close,notice,getCase:()=>current,onSaved:select});
  async function savedResponse(row){
    if(partialRedaction||correctionNotice==='waiting'){
      // A full read already in flight may predate this edit or pending decision.
      token++;
      await refresh();
      return;
    }
    const sequence=token;
    if(!review.requests)return;
    review.requests=review.requests.map(r=>r.request_id===row.request_id?row:r);
    if(review.reading_confirmation)review.reading_confirmation={...review.reading_confirmation,confirmed:false,eligible:false};
    render();
    const refreshed=await api(`/api/cases/${row.case_id}/review`);
    if(current?.id===row.case_id&&sequence===token){review=refreshed;render();}
  }
  const editor=createResponseEditor({open,close,notice,getCase:()=>current,onSaved:async row=>{
    if(current?.id!==row.case_id)return;
    await savedResponse(row);
    document.querySelector(`[data-action="live-edit"][data-index="${data.requests.findIndex(r=>r.id===row.request_id)}"]`)?.focus();
  }});
  window.addEventListener('beforeunload',event=>{
    if((draftProblem&&initialForm)||(fiaga&&current&&editor.hasChanges(current.id))){event.preventDefault();event.returnValue='';}
  });
  const final=createFinal({onFiagaHandoff,getCase:()=>current,getProgress:navigation,getReview:()=>review,hasChanges:id=>editor.hasChanges(id),open,close,notice,refresh,render,isVisible:()=>Boolean(current)&&step===3,back:requestId=>{if(requestId)selectedResponse=requestId;step=2;render();void refresh().catch(error=>notice(error.message));},onFinalized:async(id,management)=>{if(current?.id!==id)return;current.management=management;await onBrowse?.({finalizedId:id});},onStateChange:summary=>{finalSummary=summary;if(current?.id===summary.id&&step===3){const heading=view.querySelector('.expediente-later .expediente-heading');if(heading)heading.outerHTML=finalHeading();}}});
  const path=suffix=>`/api/cases/${current.id}${suffix}`;
  const intake=createEvidenceUpload({open,close,notice,getCase:()=>current,getData:()=>({requests:data?.requests||[]}),render:()=>{},changed:()=>{},onUpdated:async receipt=>{
    const originId=receipt.case_id||current?.id,originVersion=current?.version;
    if(!originId||current?.id!==originId)return;
    try{await api(`/api/cases/${originId}/preparation`,{version:originVersion});if(current?.id===originId)await refresh();}catch(error){notice('El archivo se guardó. '+error.message);}
  }});
  const proposals=createProposalPanel({open,close,notice,getCase:()=>current,onSaved:async row=>{
    if(current?.id!==row.case_id)return;
    await savedResponse(row);
  }});
  const pendingActions=createPendingActions({open,close,notice,getCase:()=>current,onRefresh:refresh,
    getActor:reviewerName,
    upload:(requestId,context)=>{
      const sequence=token;
      return intake.uploadForm(requestId,false,null,null,{...context,isCurrent:()=>sequence===token});
    },onSaved:async row=>{
      if(current?.id!==row.case_id)return;
      await savedResponse(row);
      if(row.pre_draft)await refresh();
    }});
  function render(){
    if(suspended)return;
    if(current)onWorkCase(current);
    if(step!==3)final.hide();
    redactionPosition=captureRedactionView(view)||redactionPosition;
    const redactionView=step===2?redactionPosition:null;
    if(!current)return;const expanded=[...view.querySelectorAll("[data-pending-group][open]")].map(e=>e.dataset.pendingGroup);const initialExpanded=new Map([...view.querySelectorAll('[data-initial-disclosure]')].map(e=>[e.dataset.initialDisclosure,e.open]));release();releaseDemo();initialSteps();
    document.querySelector('.steps').hidden=workspace();document.querySelector('.prototype').hidden=workspace();
    if(workspace())document.body?.classList.add('inbox-page','expediente-page');
    view.setAttribute('aria-busy',String(busy));
    const locationState=new URL(location.href);if(fiaga)locationState.searchParams.set('view','revision-fiaga');else locationState.searchParams.delete('view');locationState.searchParams.set('step',step);
    if(step===2&&selectedResponse){
      locationState.searchParams.set('request',selectedResponse);
      locationState.searchParams.set('request_version',current.version);
    }else{
      locationState.searchParams.delete('request');locationState.searchParams.delete('request_version');
    }
    rememberStage(step);history.replaceState(null,'',locationState);
    document.querySelector('#case').classList.remove('active');
    document.querySelector('.prototype').textContent=initialEnabled?'Expediente guardado · revisa el trámite y las peticiones antes de preparar las respuestas.':'Expediente guardado · revisa los puntos necesarios; las solicitudes listas se redactan automáticamente.';
    document.querySelector('.prototype-status').textContent='Expediente conectado';
    document.querySelector('.demo-badge').textContent='Gestión de Peticiones';
    document.querySelectorAll('[data-step]').forEach(b=>{b.disabled=busy||(Number(b.dataset.step)>1&&current.status!=='confirmed')||(initialEnabled&&[2,3].includes(Number(b.dataset.step))&&!canNavigate());if(Number(b.dataset.step)===step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
    if(workspace()&&step===1)view.innerHTML=identificationWorkspace(data,state,{initial,draft:initialForm,requestContent:current.identification?initialRequestContent(current,initial,initialForm,{workspace:true}):{},confirmation:!closed()?initialConfirmation(current,initial,initialForm,{workspace:true,busy,error:initialActionError,draftMessage,draftProblem,hasPrevious:Boolean(savedDraft),suggestedReviewer:reviewerName()}):'',banner:identificationActions.banner(),showMail:Boolean(showMail),canContinue:canNavigate(),navigation:navigation()});
    else if(!current.identification)renderAnalysis(view,current);
    else if(step===1)view.innerHTML=identificationActions.banner()+identification({...data,initial_review_enabled:initialEnabled,automatic_initial_review:automaticInitial},state,{summary:initialEnabled?initialReviewSummary(current,initial,initialForm,{automatic:automaticInitial})+reviewNavigation(current,initial,initialForm,{cursor:reviewCursor,busy}):'',requestContent:initialEnabled?initialRequestContent(current,initial,initialForm):{},confirmation:initialEnabled&&!closed()?initialConfirmation(current,initial,initialForm,{busy,error:initialActionError,draftMessage,draftProblem,hasPrevious:Boolean(savedDraft),suggestedReviewer:reviewerName()}):'',initial:{...initial,ready:initialReady(initial),can_prepare:canPrepare()}});
else if(step===2){view.innerHTML=workspace()?responses(current,job.status?job:{status:'starting'},mapping,drafts,review,{workspace:true,fiaga,canContinue:canNavigate(),navigation:navigation(),showMail:Boolean(showMail),selectedRequest:selectedResponse,selectedChunk,partialRedaction,correctionNotice,checkingCorrection,saveError:redactionSaveError,savingResponses,hideOutdated:true,refreshError,readingError,confirmingReading,reviewer:reviewerName(),initialPending:(initial.status||current.initial_review_status)==='idle'&&current.saved_stage>=2}):(refreshError?`<div class="alert" role="alert">${esc(refreshError)} <button data-action="live-refresh">Actualizar estado</button></div>`:'')+(job.status?responses(current,job,mapping,drafts,review):'<h1>Redacción de respuestas</h1><p role="status">Recuperando el avance guardado…</p>');}
    else {const paper=final.view();if(workspace()){
      const heading=finalHeading();
      let frame=view.querySelector('.expediente-later');
      if(!frame||!frame.contains(paper)){frame=document.createElement('section');frame.className='expediente-later';frame.innerHTML=heading;frame.append(paper);view.replaceChildren(frame);}
      else frame.querySelector('.expediente-heading').outerHTML=heading;
    }else if(view.firstChild!==paper)view.replaceChildren(paper);}
    if(step===1&&initialEnabled&&!workspace()&&!fiaga)view.insertAdjacentHTML('beforeend',pilotReviewControls(current,initial,{busy}));
    if(!workspace())renderCaseNavigation(view,current,{step,showMail:Boolean(showMail)});
    if(!workspace()&&current.error&&current.identification)view.insertAdjacentHTML('afterbegin',`<p role="alert" class="alert">${esc(current.error)}</p><button data-action="live-analyze">Reintentar identificación</button>`);
    if(step===1&&data){bindOriginal(state,number=>run(()=>loadPage(number,{focusSelection:false})));release=workspace()?bindIdentificationWorkspace(view,current,state):bindSplitPane();}
    view.querySelectorAll("[data-pending-group]").forEach(e=>e.open=expanded.includes(e.dataset.pendingGroup));
    view.querySelectorAll('[data-initial-disclosure]').forEach(e=>{if(initialExpanded.has(e.dataset.initialDisclosure))e.open=initialExpanded.get(e.dataset.initialDisclosure);});
    if(step===2)restoreRedactionView(view,redactionView);
    if(step===1&&initialEnabled&&initialReady(initial)&&!busy)updateInitialConfirmation(view,initial,readInitialDecision(view,current,initial),{saved:canPrepare(),recorded:Boolean(initial.document_decision)&&!initialDirty()});
    updateSourcePanel();
    view.querySelectorAll('[data-closed-case-notice]').forEach(e=>e.remove());
    if(closed()){
      view.insertAdjacentHTML('afterbegin','<p class="alert" role="status" data-closed-case-notice>Expediente finalizado · consulta disponible. Para editar o iniciar otro análisis, reabre la gestión desde «Detalles y gestión» en la bandeja.</p>');
      view.querySelectorAll('input,textarea,select:not(#original-page,[data-review-index],[data-zoom],[data-redaction-document],[data-redaction-passage]),[data-evidence-add]').forEach(e=>e.disabled=true);
      const readActions=new Set(['live-preanalysis','live-queue','live-mail-origin','live-initial','live-initial-history','live-pending-history','live-responses','live-final','live-sources','live-response-return','live-response-return-end','live-stage-actions','original','clear-original','back-to-question','live-review-next','live-identification']);
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
  async function loadPage(number=1,{focusSelection=true}={}){
    const read=++pageRead;
    const id=current.id,version=current.version,selected=data.requests[state.originalSelection];
    const page=await api(path(`/pages/${number}/view`)+(selected?'?request_id='+selected.id:''));
    if(read!==pageRead||!current||current.id!==id||current.version!==version)return;
    state.originalPage=number;Object.assign(data.original_pages.find(p=>p.number===number),page);
    if(selected)selected.original_marks=page.marks.map(m=>({...m,page:number}));
    render();if(selected&&focusSelection)focusOriginal();
  }
  function schedule(){
    clearTimeout(timer);
    if(suspended){
      const watch=savedNavigation;
      if(onPreanalysisNavigation&&watch&&watch.token===token&&!watch.reading&&(watch.retry||watch.nav.running.some(Boolean))){
        timer=setTimeout(()=>refreshSavedNavigation(watch),watch.retry?15000:2000);
      }
      return;
    }
    const retryCorrection=correctionNotice==='waiting'&&step===2&&!suspended&&refreshError;
    if(current&&(retryCorrection||current.analysis_running||['reading','identifying'].includes(current.status)||initial.status==='running'||job.status==='running'||review.requests?.some(r=>r.status==='checking'))){
      timer=setTimeout(()=>refresh().catch(e=>{notice(e.message);schedule();}),refreshError?15000:2000);
    }
  }
  function refresh(opening){
    if(refreshing?.token===token)return refreshing.promise;
    const sequence=token;
    const promise=refreshState(opening).catch(error=>{
      if(current&&sequence===token){checkingCorrection=false;refreshError=error.message;render();schedule();}
      throw error;
    }).finally(()=>{if(refreshing?.token===sequence)refreshing=null;});
    refreshing={token:sequence,promise};return promise;
  }
  async function refreshState(opening){
    const id=current.id,sequence=token;
    if(watchingRedaction()){
      const baseline=scopeWatch.beforeRead(id);
      if(baseline)await baseline;
      if(sequence!==token||current?.id!==id)return;
    }
    const next=opening?.record||await api(path(''));if(sequence!==token||current?.id!==id)return;
    if(suspended){schedule();return;}
    const changedCase=next.version!==current.version;
    if(changedCase){
      current=next;adapt();selectedResponse=null;selectedChunk=null;resumeRequest=null;
      if(step===2){mapping={};drafts={};review={};}
      if(step===1&&current.pages.length)await loadPage(state.originalPage);
    }
    current.analysis_running=next.analysis_running;current.management=next.management;
    current.office_progress=next.office_progress;current.preanalysis_status=next.preanalysis_status;current.initial_review_status=next.initial_review_status;
    data.analysis_running=next.analysis_running;data.management=next.management;
    const reads=[];
    if(current.status==='confirmed'&&!suspended){
      const value=await api(path('/preparation'));if(sequence!==token||current?.id!==id)return;
      if(correctionNotice==='waiting'&&['starting','running'].includes(job.status)&&['ready','waiting_review'].includes(value.status))checkingCorrection=true;
      job=value;render();
    }
    const target=resumeRequest;
    resumeRequest=null;
    if(target&&target===selectedResponse&&workspace()&&current.status==='confirmed'&&step===2&&!suspended&&
        !['running','starting'].includes(job.status)&&(current.saved_stage>=2||['ready','waiting_review'].includes(job.status))){
      partialRedaction=true;
      try{await readSelectedResponse(target);}catch{/* Fall back to the complete projections. */}
      if(sequence!==token||current?.id!==id)return;
    }
    // The active worker validates the saved approval on every stage. Reuse that
    // approval during its run; recompute it when inputs or the job state change.
    if(!opening?.initial&&initialEnabled&&current.identification&&(changedCase||!canPrepare()||job.status!=='running'))reads.push((async()=>{
      let value;try{value=await api(path('/initial-review?compact=true'));}catch(error){if(sequence===token&&current?.id===id&&!initial.status)initial={loadError:error.message};throw error;}if(sequence!==token||current?.id!==id)return;
      const changed=value.revision!==initial.revision;
      initial=value;
      // Library-backed intake reports must pass the current case permissions on every reopen.
      if(value.analysis_scope==='petition_types_v1'&&value.scope?.library_search==='not_requested'
        &&!value.scope.readable_sources&&!value.scope.linked_collections?.length&&!value.selection_basis){
        initialCache.set(id,{version:current.version,value});
      }else initialCache.delete(id);
      if(changed||!initialForm)recoverDraft();if(value.can_prepare)rememberStage(2);render();
    })());
    if(current.status==='confirmed'&&step===2&&!suspended){
      // Draft/review projections each scan the same source catalog. They cannot
      // advance until the source search ends, so do not queue duplicate scans.
      const preparingInputs=job.status==='running'&&['sources','points'].includes(job.stage);
      const reuseMapping=job.status==='running'&&job.stage==='points'&&mapping.status==='ready'&&!mapping.stale&&!changedCase;
      const projections=reuseMapping?[]:[['/sources?compact=true',value=>mapping=value]];
      if(!preparingInputs){
        projections.push(['/drafts',value=>drafts=value]);
        if(!opening?.review||opening.review!==review||correctionNotice==='waiting'||partialRedaction){
          projections.push(['/review',value=>review=value]);
        }
      }
      else {drafts={};review={};}
      const correcting=correctionNotice==='waiting';
      if(correcting||(partialRedaction&&target===selectedResponse)){
        // Publish the complete view together. Mixing partial and full results
        // would briefly misstate pending items or enable the group confirmation.
        reads.push(Promise.all(projections.map(([suffix])=>api(path(suffix)))).then(values=>{
          if(sequence!==token||current?.id!==id)return;
          partialRedaction=false;
          // During a correction publish citations and pending decisions from one
          // completed refresh. A stale map or active preparation cannot end the notice.
          if(correcting){
            const [sources,,newReview]=values;
            if(!['ready','waiting_review'].includes(job.status)||sources?.status!=='ready'||sources.stale||sources.scope_revoked)return;
            if(!newReview?.requests?.length||newReview.stale||newReview.requests.some(row=>row.stale||row.scope_reduced))return;
            correctionNotice='updated';
          }
          projections.forEach(([,assign],i)=>assign(values[i]));render();
        }).catch(error=>{
          // Old details must not linger if a new permission check fails.
          if(sequence===token&&current?.id===id){partialRedaction=false;mapping={};drafts={};review={};render();}
          throw error;
        }));
      }else{
        partialRedaction=false;
        for(const [suffix,assign] of projections){
          reads.push(api(path(suffix)).then(value=>{if(sequence!==token||current?.id!==id)return;assign(value);render();}));
        }
      }
    }
    const results=await Promise.allSettled(reads);
    if(sequence!==token||current?.id!==id)return;
    refreshError=results.find(result=>result.status==='rejected')?.reason?.message||'';
    checkingCorrection=false;
    render();schedule();
  }
  async function run(work){
    if(busy)return;
    const documentFocused=document.activeElement?.closest('.original-viewer,[data-action="original"]');
    const pageControl=document.activeElement?.closest('[data-page-step],#original-page');
    const initialAction=document.activeElement?.closest('[data-action^="live-initial"]')?.dataset.action;
    busy=true;render();
    try{await work();}catch(error){notice(error.message);}
    finally{
      busy=false;render();
      if(step===1&&pageControl){
        const direction=pageControl.dataset.pageStep;
        const button=direction&&view.querySelector(`[data-page-step="${direction}"]:enabled`);
        (button||view.querySelector('#original-page'))?.focus({preventScroll:true});
      }else if(step===1&&documentFocused)focusOriginal();
      else if(initialAction&&!document.querySelector('#drawer')?.open){
        const target=step===1?view.querySelector(`[data-action="${initialAction}"]:not([hidden])`):view.querySelector('h1');
        if(target?.tagName==='H1')target.tabIndex=-1;
        target?.focus({preventScroll:step===1});
      }
      schedule();
    }
  }
  async function select(id,options={}){
    if(current&&initialForm&&!persistDraft()){draftFeedback();notice(draftMessage);return;}
    const opening=current?.id!==id;
    if(opening){reviewCursor=-1;selectedResponse=null;selectedChunk=null;redactionPosition=null;correctionNotice=null;redactionSaveError='';}
    previewController?.abort();
    await config();
    clearTimeout(timer);const sequence=++token;
    const before=new URL(location.href);const savedStep=before.searchParams.get('case')===id?Number(before.searchParams.get('step')):0;
    const value=options.caseRecord?.id===id?options.caseRecord:await api('/api/cases/'+encodeURIComponent(id));if(sequence!==token)return;
    finalSummary={};
    const selectedManager=localStorage.getItem('pqrs-pilot-manager');
    if(!fiaga&&value.management&&selectedManager&&!reviewManagers.some(m=>m.id===selectedManager)){try{reviewManagers=await api('/api/managers');}catch{reviewManagers=[];}if(sequence!==token)return;}
    if(value.management&&(!value.management.owner_id||!value.management.started_at)){await onBrowse();return;}partialRedaction=false;current=value;suspended=false;final.setCase();job=value.preparation||{};mapping={};drafts={};review={};initial=initialCache.get(id)?.version===value.version?initialCache.get(id).value:{};initialForm=null;savedDraft=null;draftMessage='';draftProblem=false;initialActionError='';refreshError='';readingError='';state.originalPage=1;state.originalSelection=null;state.originalZoom=100;reached=value.status==='confirmed'?Math.max(rememberedStage(id),Math.min(3,Number(value.saved_stage)||1),Number(options.step)||1,value.initial_review_status==='approved'||value.preparation?.status&&value.preparation.status!=='idle'?2:1,['ready_review','closed'].includes(value.management?.state)?3:1):1;step=value.status==='confirmed'&&[1,2,3].includes(savedStep)?savedStep:[1,2,3].includes(options.step)?options.step:reached;adapt();
    const openingReads=fiaga?{record:value}:null;
    if(fiaga&&value.status==='confirmed'){
      // Observe changes before reading an intake report or a confirmed answer
      // that can contain quotations from a linked collection.
      await scopeWatch.beforeRead(id);
      if(sequence!==token||current?.id!==id)return;
      const savedInitial=await api(path('/initial-review?compact=true'));
      if(sequence!==token)return;
      initial=savedInitial;
      openingReads.initial=savedInitial;
      recoverDraft();
      // Only a persisted reading can unlock the draft. A positive hint must
      // still pass the current review and source-permission checks.
      const mayHaveReading=value.has_saved_response_reading ?? (value.saved_stage!==0);
      if(canNavigate()&&mayHaveReading){
        const savedReview=await api(path('/review'));
        if(sequence!==token)return;
        review=savedReview;
        openingReads.review=savedReview;
      }
      const available=canNavigate()?(draftAvailable()?3:2):1;
      reached=available;
      step=savedStep||options.step ? Math.min(step,available) : available;
    }else if(fiaga){step=1;reached=1;}
    // An empty Redacción view contains only the petition. Its refresh captures
    // the permission baseline before publishing any saved passages or answers.
    if(!fiaga||step!==2||options.viewPreanalysis||openingReads.review)await scopeWatch.beforeRead(id);
    if(sequence!==token||current?.id!==id)return;
    selectedResponse=restoredRequest(before,options.requestId);
    resumeRequest=opening&&step===2&&!options.viewPreanalysis?selectedResponse:null;
    const url=new URL(location.href);url.searchParams.set('case',id);history.replaceState(null,'',url);
    if(options.viewPreanalysis&&onPreanalysis){await showPreanalysis();return;}
    render();
    if(step===3)void final.load().catch(error=>notice(error.message));
    const loaded=refresh(openingReads).then(async()=>{
      if(current?.id!==id||sequence!==token||suspended)return;
      if(!savedStep&&!options.step&&step===1&&reached>=2){step=reached;render();void refresh().catch(error=>notice(error.message));}
      if(current.pages.length&&step===1)await loadPage(1);
    });
    // Paint the saved stage immediately; background reads do not lock navigation.
    void loaded.catch(error=>notice(error.message));
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
    let groups;
    try{groups=await api('/api/source-collections?case_id='+encodeURIComponent(caseId));}
    catch(error){if(container.isConnected&&current?.id===caseId)container.innerHTML=`<p role="alert">${esc(error.message)}</p>`;return;}
    if(!container.isConnected||current?.id!==caseId)return;
    container.innerHTML=`<p>Estas colecciones delimitan los antecedentes que se consultarán para esta petición. Las normas compartidas y los soportes del expediente también se consideran.</p><p id="live-library-progress" role="status" aria-live="polite">Consultando preparación de la biblioteca…</p><form id="live-groups-form">${groups.collections.map(c=>`<label class="check"><input type="checkbox" name="collection" value="${esc(c.id)}" ${groups.linked_collection_ids.includes(c.id)?'checked':''}>${esc(c.name||c.id)}</label>`).join('')}<button class="primary">Guardar fuentes de consulta</button></form><p id="live-groups-error" role="alert"></p>`;
    void watchPreparation(document.querySelector('#live-library-progress'), api);
    document.querySelector('#live-groups-form').onsubmit=async event=>{event.preventDefault();const form=event.currentTarget;form.querySelector('button').disabled=true;
      try{
        if(current?.id!==caseId)throw new Error('El expediente cambió.');
        const saved=await api(`/api/cases/${caseId}/source-collections`,{collection_ids:new FormData(form).getAll('collection')},'PUT');
        scopeWatch.remember(caseId,saved.collection_ids);
        if(saved.scope_reduced){announceScopeReduction(caseId);discardScope(caseId);}
        if(current?.id!==caseId)return;
        if(form.isConnected)close();
        await refresh();notice('Fuentes de consulta guardadas.');
      }catch(e){if(form.isConnected){document.querySelector('#live-groups-error').textContent=e.message;form.querySelector('button').disabled=false;}else notice(e.message);}
    };
  }
  function discardScope(caseId, corrected=false){
    final.discardScope(caseId);
    editor.discardScope(caseId);
    initialCache.delete(caseId);
    if(current?.id!==caseId)return;
    correctionNotice=corrected?'waiting':null;
    selectedChunk=null;
    checkingCorrection=false;
    // A refresh started before the PUT may finish after the new permissions are saved.
    token++;clearTimeout(timer);previewController?.abort();resumeRequest=null;partialRedaction=false;
    mapping={};drafts={};review={};finalSummary={};refreshError='';
    initial={};
    const drawer=document.querySelector('#drawer');
    if(drawer?.open && (drawer.dataset.initialHistory || drawer.querySelector('#live-source-detail,#live-response-edit,#live-response-loading,#proposal-panel,#pending-loading,#pending-history-loading,.pending-task-context,.pending-success,.source,#pending-decision-form,#pending-fact-form,[data-pending-detail],.redaction-context-request,#evidence-saved'))){
      close();document.querySelector('#drawer-body').replaceChildren();
    }
    render();
    if(step===3&&!suspended)void final.load().catch(error=>notice(error.message));
  }
  const watchingRedaction=()=>Boolean(current&&workspace()&&current.status==='confirmed'&&step===2&&!suspended);
  const scopeWatch=watchSourceScope(caseId=>{
    discardScope(caseId);
    if(current?.id===caseId)void refresh().catch(error=>notice(error.message));
  },{
    getCaseId:()=>current?.id||null,watchRedaction:watchingRedaction,
    read:(id,watching)=>api(`/api/cases/${encodeURIComponent(id)}/source-collections${watching?'?watch_redaction=true':''}`),
    onRedactionChange(caseId,corrected){
      if(current?.id!==caseId||!watchingRedaction())return;
      if(corrected)discardScope(caseId,true);
      else {
        checkingCorrection=correctionNotice==='waiting';
        if(refreshing)token++; // An in-flight read may predate the completed recomputation.
      }
      void refresh().catch(error=>notice(error.message));
    },
  });
  function correct(index=0){
    const caseId=current.id,version=current.version;
    open('Corregir solicitud',`<form id="live-correction"><label class="field">Solicitud<select id="live-request">${data.requests.map((r,i)=>`<option value="${i}">${esc(r.label)}. ${esc(r.title)}</option>`).join('')}</select></label><label class="field">Título<input id="live-title" required maxlength="240"></label><label class="field">Qué solicita<textarea id="live-description" required maxlength="8000"></textarea></label><p>Se conserva la referencia al documento original.</p><div class="dialog-actions"><button type="button" id="live-correction-cancel">Cancelar</button><button class="primary" type="submit">Guardar corrección</button></div></form><p id="live-correction-error" role="alert"></p>`,{eyebrow:'CONTEXTO DE LA PETICIÓN'});
    document.querySelector('#live-correction-cancel').onclick=close;
    const selector=document.querySelector('#live-request');selector.value=String(index);const fill=()=>{const r=data.requests[Number(selector.value)];document.querySelector('#live-title').value=r.title;document.querySelector('#live-description').value=r.description;};selector.onchange=fill;fill();
    document.querySelector('#live-correction').onsubmit=async event=>{event.preventDefault();const form=event.currentTarget;form.querySelector('[type="submit"]').disabled=true;
      try{const identification=structuredClone(current.identification);const row=identification.requests[Number(selector.value)];row.title=document.querySelector('#live-title').value;row.description=document.querySelector('#live-description').value;await api(`/api/cases/${caseId}/identification`,{version,identification},'PUT');close();await select(caseId);}catch(e){if(form.isConnected){document.querySelector('#live-correction-error').textContent=e.message;form.querySelector('[type="submit"]').disabled=false;}}
    };
  }
  view.addEventListener('change',event=>{
    if(fiaga&&step===2&&event.target.matches?.('[data-redaction-document],[data-redaction-passage]')){
      selectedChunk=event.target.value;
      render();
      return;
    }
    if(!event.target.matches?.('[data-review-index]')||event.target.value==='')return;
    reviewCursor=Number(event.target.value);focusReviewPetition(view,reviewCursor);
  });
  view.addEventListener('dragover',event=>{
    const target=event.target.closest?.('[data-redaction-drop]');
    if(!target||closed()||busy)return;event.preventDefault();target.classList.add('is-dragging');
  });
  view.addEventListener('dragleave',event=>event.target.closest?.('[data-redaction-drop]')?.classList.remove('is-dragging'));
  view.addEventListener('drop',event=>{
    const target=event.target.closest?.('[data-redaction-drop]');
    if(!target)return;event.preventDefault();target.classList.remove('is-dragging');
    if(closed()||busy||!current)return;
    const files=event.dataTransfer?.files;
    if(files?.length!==1){notice('Agrega un archivo a la vez para indicar su origen.');return;}
    const request=data.requests[Number(target.dataset.redactionDrop)];
    if(request)void run(()=>intake.uploadForm(request.id,false,null,files[0]));
  });
  view.addEventListener('click',e=>{if(!current||busy||suspended)return;const b=e.target.closest('[data-action]');if(!b||b.disabled)return;
    if(b.dataset.action==='live-stage-actions'){focusStageReview(view);return;}
    if(['live-response-return','live-response-return-end'].includes(b.dataset.action)&&step===2){
      focusResponse(view,b.dataset.requestId);return;
    }
    if(b.dataset.action==='live-save-responses-and-queue'){
      const caseId=current.id;
      redactionSaveError='';savingResponses=true;
      void run(async()=>{
        try{
          await editor.saveAll(caseId);
          if(current?.id===caseId){await onBrowse();notice('Cambios de Redacción guardados.');}
        }catch(error){
          if(current?.id===caseId)redactionSaveError=error.message;
        }finally{savingResponses=false;}
      }).then(()=>view.querySelector('[data-redaction-save-error]')?.focus({preventScroll:true}));
      return;
    }
    if(b.dataset.action==='live-confirm-responses'){
      const caseId=current.id,contentHash=review.reading_confirmation?.content_hash;
      const reviewer=reviewerName()||view.querySelector('#response-reading-actor')?.value.trim();
      if(!reviewer){readingError='Escribe tu nombre para registrar la revisión.';render();view.querySelector('#response-reading-actor')?.focus();return;}
      readingError='';confirmingReading=true;
      void run(async()=>{
        try{
          const value=await api(`/api/cases/${caseId}/review/reading-confirmation`,{content_hash:contentHash,reviewed_by:reviewer,confirmed:true});
          if(current?.id===caseId){review=value;notice('Revisión conjunta guardada.');}
        }catch(error){if(current?.id===caseId)readingError=error.message;}
        finally{confirmingReading=false;}
      }).then(()=>view.querySelector('[data-reading-status]')?.focus({preventScroll:true}));
      return;
    }
    if(b.dataset.action==='live-continue-draft'){
      if(!review.reading_confirmation?.confirmed){notice('Confirma que revisaste todas las respuestas.');return;}
      navigate(3);return;
    }
    if(b.dataset.action==='live-preanalysis'){void showPreanalysis();return;}
    const targetStep={'live-identification':1,'live-responses':2,'live-final':3}[b.dataset.action];
    if(targetStep){navigate(targetStep);return;}const index=Number(b.dataset.index);
    if(b.dataset.action==='live-sources'&&workspace()&&step===2){
      const requestId=data.requests[index]?.id;
      if(!requestId)return;
      const changed=requestId!==selectedResponse;
      if(changed)selectedChunk=null;
      selectedResponse=requestId;
      try{localStorage.setItem('pqrs-response-'+current.id,JSON.stringify({id:requestId,version:current.version}));}catch{/* The URL still preserves this selection. */}
      if(partialRedaction&&changed){
        previewController?.abort();mapping={};drafts={};review={};
      }
      if(changed)resumeRequest=null;
      render();
      const panel=view.querySelector('#redaction-context');
      if(panel){panel.scrollTop=0;panel.querySelector('h2')?.focus({preventScroll:true});panel.scrollIntoView({block:'nearest'});}return;
    }
    if(b.dataset.action==='live-review-next'){
      const items=reviewItems(current,initial,initialForm);
      reviewCursor=nextReviewIndex(items,reviewCursor);
      focusReviewPetition(view,reviewCursor,{reveal:items[reviewCursor]?.attention});return;
    }
    if(b.dataset.action==='live-review-confirm'){
      const title=view.querySelector('#intake-confirmation-title');
      if(title){title.tabIndex=-1;title.focus({preventScroll:true});title.scrollIntoView({block:'center'});}return;
    }
    if(b.dataset.action==='live-initial'){
      const detail=view.querySelector('#initial-review-details');
      if(detail)detail.open=true;
      (detail?.querySelector('summary')||view.querySelector('#intake-summary-title'))?.focus();
      return;
    }
    if(b.dataset.action==='live-initial-route-edit'){
      const key=b.dataset.routeKey;
      if(key==='document'||/^\d+$/.test(key||'')){
        const field=view.querySelector(`[name="route-${key}"]`);
        for(let parent=field?.parentElement;parent&&parent!==view;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}
        field?.focus({preventScroll:true});field?.scrollIntoView({block:'center'});
      }
      return;
    }
    if(b.dataset.action==='live-initial-save'){initialForm=readInitialDecision(view,current,initial);persistDraft();render();draftFeedback();view.querySelector('[data-action="live-initial-save"]')?.focus({preventScroll:true});notice(draftMessage);return;}
    if(b.dataset.action==='live-save-and-queue'){initialForm=readInitialDecision(view,current,initial);if(!persistDraft()){draftFeedback();notice(draftMessage);return;}void onBrowse();return;}
    if(b.dataset.action==='live-initial-draft-preview'){open('Borrador anterior · sin confirmar',draftPreview(savedDraft));return;}
    if(b.dataset.action==='live-initial-draft-download'){
      const copy=initialForm?draftEnvelope(current,initial,initialForm,savedDraft):savedDraft||draftEnvelope(current,initial,readInitialDecision(view,current,initial));
      const url=URL.createObjectURL(new Blob([JSON.stringify(downloadableDraft(copy,current,initial),null,2)],{type:'application/json'}));
      const link=document.createElement('a');link.href=url;link.download=`borrador-${current.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;
    }
    const rawDecision=['live-initial-confirm','live-initial-route'].includes(b.dataset.action)?readInitialDecision(view,current,initial):null;
    const decision=rawDecision;
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
        case 'live-pilot-continue':{
          if(initialForm&&!persistDraft())throw new Error('Guarda o descarga tu borrador antes de continuar.');
          if(!initial.pilot_bypass_active)await api(path('/initial-review/pilot-mode'),{version:current.version,revision:initial.revision,enabled:true},'PUT');
          await refresh();
          await api(path('/preparation'),{version:current.version});step=2;await refresh();break;
        }
        case 'live-pilot-require':{
          await api(path('/initial-review/pilot-mode'),{version:current.version,revision:initial.revision,enabled:false},'PUT');
          await refresh();break;
        }
      case 'live-initial-full':
      case 'live-initial-analyze':{const target=current.id;const next=await api(path('/initial-review/analyze'),{version:current.version,revision:initial.revision||0,mode:b.dataset.action==='live-initial-full'?'full':'incremental'});if(current?.id!==target)break;initial=next;initialForm=null;await refresh();break;}
      case 'live-initial-route':
      case 'live-initial-confirm':{
        if(!decision||!initialReady(initial))break;
        const caseId=current.id;initialActionError='';
        try{
          const result=await confirmAndPrepare({saved:b.dataset.action==='live-initial-confirm'&&canPrepare()?initial:null,decision,report:initial.report,
            save:body=>api(`/api/cases/${caseId}/initial-review/decision`,body,'PUT'),
            onSaved:value=>{try{draftStore.clear(caseId);}catch{notice('La revisión quedó confirmada. No se pudo retirar la copia del borrador de este navegador.');}if(current?.id===caseId){initial=value;initialForm=null;savedDraft=null;draftMessage='';draftProblem=false;}},
            onPreparing:()=>{if(current?.id===caseId){step=2;job={status:'starting'};render();}},
            prepare:async()=>{
              const [latest,existing]=await Promise.all([api(`/api/cases/${caseId}`),api(`/api/cases/${caseId}/preparation`)]);
              if(current?.id===caseId){current=latest;adapt();}
              if(!existing.stale&&['running','ready','waiting_review'].includes(existing.status))return existing;
              return api(`/api/cases/${caseId}/preparation`,{version:latest.version});
            }});
          if(current?.id!==caseId)break;
          if(result.error){refreshError=result.error;job={};token++;void refresh().catch(error=>notice(error.message));break;}
          if(result.prepared){job=result.preparation;step=2;render();void refresh().catch(error=>notice(error.message));}
          else {await refresh();notice('Ruta alternativa guardada. Para preparar respuestas, cambia expresamente las rutas a Continuar y confirma la revisión.');}
        }catch(error){if(current?.id===caseId)initialActionError=error.message;}
        break;
      }
      case 'live-refresh':void refresh().catch(error=>notice(error.message));break;
      case 'live-initial-history':{const sequence=token;const result=await api(path('/initial-review/history'));if(sequence===token){open('Historial del trámite',initialHistory(result.events));document.querySelector('#drawer').dataset.initialHistory='true';}break;}
      case 'live-queue':await onBrowse();break;
      case 'live-mail-origin':await showMail?.(current.id);break;
      case 'live-confirm':{const result=await api(path('/confirm-and-prepare'),{version:current.version});current=result.case;job=result.preparation;adapt();step=initialEnabled?1:2;await refresh();if(initialEnabled)notice('Solicitudes confirmadas. Ya puedes analizar el trámite en el resumen.');break;}
      case 'live-retry-failed':await api(path('/preparation'),{version:current.version,retry_failed_only:true});step=2;await refresh();break;
      case 'live-resume':await api(path('/preparation'),{version:current.version,retry_analysis:b.dataset.retryAnalysis==='true'});step=2;await refresh();break;
      case 'live-analyze':await api(path('/analyze'),{});await refresh();break;
      case 'live-responses':step=initialEnabled&&!canNavigate()?1:2;render();void refresh().catch(error=>notice(error.message));break;
      case 'live-identification':step=1;await refresh();if(current.pages.length)await loadPage(state.originalPage);break;
      case 'live-final':step=3;await refresh();await final.load();break;
      case 'original':state.originalSelection=index;await loadPage(data.requests[index]?.source_refs?.[0]?.page||state.originalPage||1);break;
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
  return {active:()=>Boolean(current),choose,upload,select,go:navigate,resume:navigate,leave(){if(current&&initialForm&&!persistDraft()){draftFeedback();notice(draftMessage);return false;}token++;previewController?.abort();resumeRequest=null;partialRedaction=false;suspended=false;final.hide();clearTimeout(timer);release();document.body?.classList.remove('expediente-page','inbox-page');if(current)onWorkCase(null);current=null;data=null;initialSteps();history.replaceState(null,'',location.pathname);document.querySelector('#case').classList.add('active');document.querySelector('.prototype').textContent='Petición de demostración · para trabajar con un documento real, usa «Cargar petición» o «Mis expedientes».';document.querySelector('.demo-badge').textContent='Demo';document.querySelector('.prototype-status').textContent='Demo + biblioteca';},async init(restore=true){await config();const id=new URL(location.href).searchParams.get('case');return id&&restore?run(()=>select(id)):Promise.resolve();}};
}
