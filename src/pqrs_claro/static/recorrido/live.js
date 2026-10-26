import {reviewNavigation,reviewItems,nextReviewIndex,focusReviewPetition,syncReviewNavigation,suggestedReviewer} from './review-navigation.js?v=review-context2';
import {createReviewDraftStore,restoreDraft,draftPreview,draftEnvelope} from './review-drafts.js?v=phase2';
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

async function api(path,body,method='POST'){
  const options=body===undefined?{}:{method,body:body instanceof FormData?body:JSON.stringify(body),headers:body instanceof FormData?{}:{'Content-Type':'application/json'}};
  let response,value;
  try{response=await fetch(path,{...options,signal:AbortSignal.timeout(60000)});value=await response.json();}
  catch(error){if(['TimeoutError','AbortError'].includes(error.name))throw new Error('La consulta está tardando más de lo esperado. El avance guardado se conserva; actualiza el estado para recuperarlo.');throw error;}
  if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'Revisa los campos y vuelve a intentarlo.');return value;
}
export function createLive({open,close,notice,releaseDemo,showMail,onBrowse,onPreanalysis}){
  let current=null,data=null,job={},mapping={},drafts={},review={},step=1,busy=false,timer,token=0,release=()=>{};
  const state={originalPage:1,originalSelection:null,originalZoom:100};const view=document.querySelector('#view');
  let initialEnabled=false,automaticInitial=false,initial={},initialForm=null,initialActionError='',configLoaded=false;
  const draftStore=createReviewDraftStore(localStorage);
  let reviewCursor=-1,reviewManagers=[];
  let savedDraft=null,draftMessage='',draftProblem=false;
  let refreshing=null,refreshError='',readingError='',confirmingReading=false;
  let selectedResponse=null,finalSummary={},suspended=false,reached=1,redactionPosition=null;
  const initialCache=new Map();
  const stageKey=id=>'pqrs-stage-'+id;
  function rememberedStage(id){try{return Math.min(3,Math.max(1,Number(localStorage.getItem(stageKey(id)))||1));}catch{return 1;}}
  function rememberStage(value){reached=Math.max(reached,value);try{localStorage.setItem(stageKey(current.id),String(reached));}catch{/* Navigation still works without browser storage. */}}
  function navigation(){
    const savedExport=current.office_progress?.status==='ready';
    const written=finalSummary.id===current.id?finalSummary.redactionComplete:savedExport||review.requests?.length>0&&review.requests.length===current.request_count&&review.requests.every(r=>r.paragraphs?.length&&!r.stale);
    const generated=finalSummary.id===current.id?finalSummary.draftComplete:savedExport;
    const historical=(initial.status||current.initial_review_status)==='idle'&&current.saved_stage>=2;
    return {available:[Boolean(onPreanalysis),true,canNavigate(),canNavigate()],completed:[current.preanalysis_status==='ready',!historical&&!initial.stale&&(Boolean(initial.can_prepare)||reached>=2),Boolean(written),Boolean(generated)],labels:[current.preanalysis_status==='idle'?'Sin registro':'Guardado',historical?'Guardada':initial.stale?'Por actualizar':initialReady(initial)?'Por revisar':'Guardado',reached>=2?'Guardado':'Pendiente',reached>=3?'Guardado':'Pendiente']};
  }
  async function showPreanalysis(){
    if(!current||!onPreanalysis)return;
    if(initialForm&&!persistDraft()){draftFeedback();notice(draftMessage);return;}
    redactionPosition=captureRedactionView(view)||redactionPosition;suspended=true;final.hide();release();
    const url=new URL(location.href);url.searchParams.set('view','preanalysis');url.searchParams.set('step','0');history.replaceState(null,'',url);
    try{await onPreanalysis(current,expedienteSteps(0,{navigation:navigation(),activeLabel:'Consulta guardada'}),navigation());}
    catch(error){suspended=false;render();notice(error.message);}
  }
  function navigate(value){
    if(!current||busy||![1,2,3].includes(value)||value>1&&!canNavigate())return;
    step=value;suspended=false;render();
    // Reading another stage never starts a worker or confirms a decision.
    if(step===3)void final.load().catch(error=>notice(error.message));
    else {
      if(step===1?!initial.status:!mapping.status)void refresh().catch(error=>notice(error.message));
      else schedule();
      if(step===1&&current.pages.length)void loadPage(state.originalPage).catch(error=>notice(error.message));
    }
  }
  function finalHeading(){const nav=navigation();return expedienteHeading(current,3,{title:'Borrador del oficio',subtitle:'Revisa el documento y resuelve los ajustes antes de aprobar.',navigation:nav,canContinue:canNavigate(),showMail:Boolean(showMail),redactionComplete:nav.completed[2],draftComplete:nav.completed[3]}).replace('data-action="live-queue"','data-action="live-responses"').replace('Volver a la bandeja','Volver a redacción');}

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
  window.addEventListener('beforeunload',event=>{if(draftProblem&&initialForm){event.preventDefault();event.returnValue='';}});
  async function config(){if(configLoaded)return;const settings=await api('/api/config');initialEnabled=Boolean(settings.initial_review_enabled);automaticInitial=Boolean(settings.automatic_initial_review);configLoaded=true;if(settings.management_enabled){try{reviewManagers=await api('/api/managers');}catch{reviewManagers=[];}}}
  function initialSteps(){
    document.querySelector('[data-step="1"]').innerHTML=`<span>1</span> ${initialEnabled&&current?'Procesar solicitud':'Entender la petición'}`;
  }
  const initialDirty=()=>Boolean(initialForm&&initialForm.case_id===current?.id&&initialForm.revision===initial.revision);
  const closed=()=>current?.management?.state==='closed';
  const workspace=()=>initialEnabled&&Boolean(current?.management);
  const canNavigate=()=>closed()||canPrepare()||reached>=2;
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
    review.requests=review.requests.map(r=>r.request_id===row.request_id?row:r);
    if(review.reading_confirmation)review.reading_confirmation={...review.reading_confirmation,confirmed:false,eligible:false};
    render();
    const refreshed=await api(`/api/cases/${row.case_id}/review`);
    if(current?.id===row.case_id){review=refreshed;render();}
  }
  const editor=createResponseEditor({open,close,notice,getCase:()=>current,onSaved:async row=>{
    if(current?.id!==row.case_id)return;
    await savedResponse(row);
    document.querySelector(`[data-action="live-edit"][data-index="${data.requests.findIndex(r=>r.id===row.request_id)}"]`)?.focus();
  }});
  const final=createFinal({getCase:()=>current,getProgress:navigation,getReview:()=>review,hasChanges:id=>editor.hasChanges(id),open,close,notice,refresh,render,isVisible:()=>Boolean(current)&&step===3,back:requestId=>{if(requestId)selectedResponse=requestId;step=2;render();void refresh().catch(error=>notice(error.message));},onFinalized:async(id,management)=>{if(current?.id!==id)return;current.management=management;await onBrowse?.({finalizedId:id});},onStateChange:summary=>{finalSummary=summary;if(current?.id===summary.id&&step===3){const heading=view.querySelector('.expediente-later .expediente-heading');if(heading)heading.outerHTML=finalHeading();}}});
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
  const pendingActions=createPendingActions({open,close,notice,getCase:()=>current,
    getActor:()=>suggestedReviewer(reviewManagers,localStorage.getItem('pqrs-pilot-manager')),
    upload:(requestId,context)=>intake.uploadForm(requestId,false,null,null,context),onSaved:async row=>{
      if(current?.id!==row.case_id)return;
      await savedResponse(row);
      if(row.pre_draft)await refresh();
    }});
  function render(){
    if(suspended)return;
    if(step!==3)final.hide();
    redactionPosition=captureRedactionView(view)||redactionPosition;
    const redactionView=step===2?redactionPosition:null;
    if(!current)return;const expanded=[...view.querySelectorAll("[data-pending-group][open]")].map(e=>e.dataset.pendingGroup);const initialExpanded=new Map([...view.querySelectorAll('[data-initial-disclosure]')].map(e=>[e.dataset.initialDisclosure,e.open]));release();releaseDemo();initialSteps();
    document.querySelector('.steps').hidden=workspace();document.querySelector('.prototype').hidden=workspace();
    if(workspace())document.body?.classList.add('inbox-page','expediente-page');
    view.setAttribute('aria-busy',String(busy));
    const locationState=new URL(location.href);locationState.searchParams.delete('view');locationState.searchParams.set('step',step);rememberStage(step);history.replaceState(null,'',locationState);
    document.querySelector('#case').classList.remove('active');
    document.querySelector('.prototype').textContent=initialEnabled?'Expediente guardado · revisa el trámite y las peticiones antes de preparar las respuestas.':'Expediente guardado · revisa los puntos necesarios; las solicitudes listas se redactan automáticamente.';
    document.querySelector('.prototype-status').textContent='Expediente conectado';
    document.querySelector('.demo-badge').textContent='Gestión de Peticiones';
    document.querySelectorAll('[data-step]').forEach(b=>{b.disabled=busy||(Number(b.dataset.step)>1&&current.status!=='confirmed')||(initialEnabled&&[2,3].includes(Number(b.dataset.step))&&!canNavigate());if(Number(b.dataset.step)===step)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
    if(workspace()&&step===1)view.innerHTML=identificationWorkspace(data,state,{initial,draft:initialForm,requestContent:current.identification?initialRequestContent(current,initial,initialForm,{workspace:true}):{},confirmation:!closed()?initialConfirmation(current,initial,initialForm,{workspace:true,busy,error:initialActionError,draftMessage,draftProblem,hasPrevious:Boolean(savedDraft),suggestedReviewer:suggestedReviewer(reviewManagers,localStorage.getItem('pqrs-pilot-manager'))}):'',banner:identificationActions.banner(),showMail:Boolean(showMail),canContinue:canNavigate(),navigation:navigation()});
    else if(!current.identification)renderAnalysis(view,current);
    else if(step===1)view.innerHTML=identificationActions.banner()+identification({...data,initial_review_enabled:initialEnabled,automatic_initial_review:automaticInitial},state,{summary:initialEnabled?initialReviewSummary(current,initial,initialForm,{automatic:automaticInitial})+reviewNavigation(current,initial,initialForm,{cursor:reviewCursor,busy}):'',requestContent:initialEnabled?initialRequestContent(current,initial,initialForm):{},confirmation:initialEnabled&&!closed()?initialConfirmation(current,initial,initialForm,{busy,error:initialActionError,draftMessage,draftProblem,hasPrevious:Boolean(savedDraft),suggestedReviewer:suggestedReviewer(reviewManagers,localStorage.getItem('pqrs-pilot-manager'))}):'',initial:{...initial,ready:initialReady(initial),can_prepare:canPrepare()}});
    else if(step===2){view.innerHTML=workspace()?responses(current,job.status?job:{status:'starting'},mapping,drafts,review,{workspace:true,canContinue:canNavigate(),navigation:navigation(),showMail:Boolean(showMail),selectedRequest:selectedResponse,refreshError,readingError,confirmingReading,reviewer:suggestedReviewer(reviewManagers,localStorage.getItem('pqrs-pilot-manager')),initialPending:(initial.status||current.initial_review_status)==='idle'&&current.saved_stage>=2}):(refreshError?`<div class="alert" role="alert">${esc(refreshError)} <button data-action="live-refresh">Actualizar estado</button></div>`:'')+(job.status?responses(current,job,mapping,drafts,review):'<h1>Redacción de respuestas</h1><p role="status">Recuperando el avance guardado…</p>');}
    else {const paper=final.view();if(workspace()){
      const heading=finalHeading();
      let frame=view.querySelector('.expediente-later');
      if(!frame||!frame.contains(paper)){frame=document.createElement('section');frame.className='expediente-later';frame.innerHTML=heading;frame.append(paper);view.replaceChildren(frame);}
      else frame.querySelector('.expediente-heading').outerHTML=heading;
    }else if(view.firstChild!==paper)view.replaceChildren(paper);}
    if(step===1&&initialEnabled&&!workspace())view.insertAdjacentHTML('beforeend',pilotReviewControls(current,initial,{busy}));
    if(!workspace())renderCaseNavigation(view,current,{step,showMail:Boolean(showMail)});
    if(!workspace()&&current.error&&current.identification)view.insertAdjacentHTML('afterbegin',`<p role="alert" class="alert">${esc(current.error)}</p><button data-action="live-analyze">Reintentar identificación</button>`);
    if(step===1&&data){bindOriginal(state,number=>run(()=>loadPage(number)));release=workspace()?bindIdentificationWorkspace(view,current,state):bindSplitPane();}
    view.querySelectorAll("[data-pending-group]").forEach(e=>e.open=expanded.includes(e.dataset.pendingGroup));
    view.querySelectorAll('[data-initial-disclosure]').forEach(e=>{if(initialExpanded.has(e.dataset.initialDisclosure))e.open=initialExpanded.get(e.dataset.initialDisclosure);});
    if(step===2)restoreRedactionView(view,redactionView);
    if(step===1&&initialEnabled&&initialReady(initial)&&!busy)updateInitialConfirmation(view,initial,readInitialDecision(view,current,initial),{saved:canPrepare(),recorded:Boolean(initial.document_decision)&&!initialDirty()});
    updateSourcePanel();
    view.querySelectorAll('[data-closed-case-notice]').forEach(e=>e.remove());
    if(closed()){
      view.insertAdjacentHTML('afterbegin','<p class="alert" role="status" data-closed-case-notice>Expediente finalizado · consulta disponible. Para editar o iniciar otro análisis, reabre la gestión desde «Detalles y gestión» en la bandeja.</p>');
      view.querySelectorAll('input,textarea,select:not(#original-page):not([data-review-index]):not([data-zoom]),[data-evidence-add]').forEach(e=>e.disabled=true);
      const readActions=new Set(['live-preanalysis','live-queue','live-mail-origin','live-initial','live-initial-history','live-pending-history','live-responses','live-final','live-sources','original','clear-original','back-to-question','live-review-next','live-identification']);
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
  function schedule(){clearTimeout(timer);if(current&&(current.analysis_running||['reading','identifying'].includes(current.status)||initial.status==='running'||job.status==='running'||review.requests?.some(r=>r.status==='checking')))timer=setTimeout(()=>refresh().catch(e=>{notice(e.message);schedule();}),refreshError?15000:2000);}
  function refresh(){
    if(refreshing?.token===token)return refreshing.promise;
    const sequence=token;
    const promise=refreshState().catch(error=>{
      if(current&&sequence===token){refreshError=error.message;render();schedule();}
      throw error;
    }).finally(()=>{if(refreshing?.token===sequence)refreshing=null;});
    refreshing={token:sequence,promise};return promise;
  }
  async function refreshState(){
    const id=current.id,sequence=token;
    const next=await api(path(''));if(sequence!==token||current?.id!==id)return;
    const changedCase=next.version!==current.version;
    if(changedCase){current=next;adapt();if(step===1&&current.pages.length)await loadPage(state.originalPage);}
    current.analysis_running=next.analysis_running;current.management=next.management;
    data.analysis_running=next.analysis_running;data.management=next.management;
    const reads=[];
    if(current.status==='confirmed'&&!suspended){
      const value=await api(path('/preparation'));if(sequence!==token||current?.id!==id)return;
      job=value;render();
    }
    // The active worker validates the saved approval on every stage. Reuse that
    // approval during its run; recompute it when inputs or the job state change.
    if(initialEnabled&&current.identification&&(changedCase||!canPrepare()||job.status!=='running'))reads.push((async()=>{
      let value;try{value=await api(path('/initial-review?compact=true'));}catch(error){if(sequence===token&&current?.id===id&&!initial.status)initial={loadError:error.message};throw error;}if(sequence!==token||current?.id!==id)return;
      const changed=value.revision!==initial.revision;
      initial=value;initialCache.set(id,{version:current.version,value});if(changed||!initialForm)recoverDraft();if(value.can_prepare)rememberStage(2);render();
    })());
    if(current.status==='confirmed'&&step===2&&!suspended){
      // Draft/review projections each scan the same source catalog. They cannot
      // advance until the source search ends, so do not queue duplicate scans.
      const preparingInputs=job.status==='running'&&['sources','points'].includes(job.stage);
      const reuseMapping=job.status==='running'&&job.stage==='points'&&mapping.status==='ready'&&!mapping.stale&&!changedCase;
      const projections=reuseMapping?[]:[['/sources?compact=true',value=>mapping=value]];
      if(!preparingInputs)projections.push(['/drafts',value=>drafts=value],['/review',value=>review=value]);
      else {drafts={};review={};}
      for(const [suffix,assign] of projections){
        reads.push(api(path(suffix)).then(value=>{if(sequence!==token||current?.id!==id)return;assign(value);render();}));
      }
    }
    const results=await Promise.allSettled(reads);
    if(sequence!==token||current?.id!==id)return;
    refreshError=results.find(result=>result.status==='rejected')?.reason?.message||'';
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
  async function select(id,options={}){
    if(current&&initialForm&&!persistDraft()){draftFeedback();notice(draftMessage);return;}
    if(current?.id!==id){reviewCursor=-1;selectedResponse=null;redactionPosition=null;}
    await config();
    clearTimeout(timer);const sequence=++token;
    const before=new URL(location.href);const savedStep=before.searchParams.get('case')===id?Number(before.searchParams.get('step')):0;
    const value=options.caseRecord?.id===id?options.caseRecord:await api('/api/cases/'+encodeURIComponent(id));if(sequence!==token)return;
    finalSummary={};
    const selectedManager=localStorage.getItem('pqrs-pilot-manager');
    if(value.management&&selectedManager&&!reviewManagers.some(m=>m.id===selectedManager)){try{reviewManagers=await api('/api/managers');}catch{reviewManagers=[];}if(sequence!==token)return;}
    if(value.management&&(!value.management.owner_id||!value.management.started_at)){await onBrowse();return;}current=value;suspended=false;final.setCase();job=value.preparation||{};mapping={};drafts={};review={};initial=initialCache.get(id)?.version===value.version?initialCache.get(id).value:{};initialForm=null;savedDraft=null;draftMessage='';draftProblem=false;initialActionError='';refreshError='';readingError='';state.originalPage=1;state.originalSelection=null;state.originalZoom=100;reached=value.status==='confirmed'?Math.max(rememberedStage(id),Math.min(3,Number(value.saved_stage)||1),Number(options.step)||1,value.initial_review_status==='approved'||value.preparation?.status&&value.preparation.status!=='idle'?2:1,['ready_review','closed'].includes(value.management?.state)?3:1):1;step=value.status==='confirmed'&&[1,2,3].includes(savedStep)?savedStep:[1,2,3].includes(options.step)?options.step:reached;adapt();
    const url=new URL(location.href);url.searchParams.set('case',id);history.replaceState(null,'',url);render();
    if(options.viewPreanalysis){await showPreanalysis();return;}
    if(step===3)void final.load().catch(error=>notice(error.message));
    const loaded=refresh().then(async()=>{
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
    const groups=await api('/api/source-collections?case_id='+caseId);if(!container.isConnected||current?.id!==caseId)return;
    container.innerHTML=`<p>Estas colecciones delimitan los antecedentes que se consultarán para esta petición. Las normas compartidas y los soportes del expediente también se consideran.</p><p id="live-library-progress" role="status" aria-live="polite">Consultando preparación de la biblioteca…</p><form id="live-groups-form">${groups.collections.map(c=>`<label class="check"><input type="checkbox" name="collection" value="${esc(c.id)}" ${groups.linked_collection_ids.includes(c.id)?'checked':''}>${esc(c.name||c.id)}</label>`).join('')}<button class="primary">Guardar fuentes de consulta</button></form><p id="live-groups-error" role="alert"></p>`;
    void watchPreparation(document.querySelector('#live-library-progress'), api);
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
  view.addEventListener('change',event=>{
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
    if(b.dataset.action==='live-confirm-responses'){
      const caseId=current.id,contentHash=review.reading_confirmation?.content_hash;
      const reviewer=suggestedReviewer(reviewManagers,localStorage.getItem('pqrs-pilot-manager'))||view.querySelector('#response-reading-actor')?.value.trim();
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
      selectedResponse=data.requests[index]?.id;render();
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
      const url=URL.createObjectURL(new Blob([JSON.stringify(copy,null,2)],{type:'application/json'}));
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
      case 'live-initial-history':{const result=await api(path('/initial-review/history'));open('Historial del trámite',initialHistory(result.events));break;}
      case 'live-queue':await onBrowse();break;
      case 'live-mail-origin':await showMail?.(current.id);break;
      case 'live-confirm':{const result=await api(path('/confirm-and-prepare'),{version:current.version});current=result.case;job=result.preparation;adapt();step=initialEnabled?1:2;await refresh();if(initialEnabled)notice('Solicitudes confirmadas. Ya puedes analizar el trámite en el resumen.');break;}
      case 'live-retry-failed':await api(path('/preparation'),{version:current.version,retry_failed_only:true});step=2;await refresh();break;
      case 'live-resume':await api(path('/preparation'),{version:current.version,retry_analysis:b.dataset.retryAnalysis==='true'});step=2;await refresh();break;
      case 'live-analyze':await api(path('/analyze'),{});await refresh();break;
      case 'live-responses':step=initialEnabled&&!canNavigate()?1:2;render();void refresh().catch(error=>notice(error.message));break;
      case 'live-identification':step=1;await refresh();if(current.pages.length)await loadPage(state.originalPage);break;
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
  return {active:()=>Boolean(current),choose,upload,select,go:navigate,resume:navigate,leave(){if(current&&initialForm&&!persistDraft()){draftFeedback();notice(draftMessage);return false;}token++;suspended=false;final.hide();clearTimeout(timer);release();document.body?.classList.remove('expediente-page','inbox-page');current=null;data=null;initialSteps();history.replaceState(null,'',location.pathname);document.querySelector('#case').classList.add('active');document.querySelector('.prototype').textContent='Petición de demostración · para trabajar con un documento real, usa «Cargar petición» o «Mis expedientes».';document.querySelector('.demo-badge').textContent='Demo';document.querySelector('.prototype-status').textContent='Demo + biblioteca';},async init(restore=true){await config();const id=new URL(location.href).searchParams.get('case');return id&&restore?run(()=>select(id)):Promise.resolve();}};
}
