import {documentPanel,identificationCards,divider,responseCards} from './presentation.js';
import {bindSplitPane} from './split-pane.js';
import {createEvidenceUpload} from '../evidence-upload.js';
import {
  el,
  button,
  running,
  statusLabel,
  dateLabel,
  welcome,
  progress,
  original,
  processView,
  metadata,
} from "../ui.js";
import { requestsView, quoteFor } from "../requests.js";
import { createSources } from "../sources.js";
import { createDrafts } from "../drafts.js";
import { createReview } from "../review.js";
import { createOffice } from "../office.js";

const state = {
  config: null,
  cases: [],
  current: null,
  draft: null,
  dirty: false,
  editingId: null,
  selectedId: null,
  page: 1,
  highlight: null,
  busy: false,
  poll: null,
  notice: null,
  conflict: false,
  library: false,
  responses: new URL(location.href).searchParams.get("view") === "drafts",
  reviewing: new URL(location.href).searchParams.get("view") === "review",
  office: new URL(location.href).searchParams.get("view") === "office",
};
const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers:
        options.body instanceof FormData
          ? options.headers
          : { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw new Error(
      "No pudimos conectar con la aplicación. Comprueba que siga abierta y vuelve a intentar.",
    );
  }
  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload?.detail || payload?.error;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (item) =>
                  `${item.loc?.slice(1).join(" · ") || "Dato"}: ${item.msg}`,
              )
              .join(". ")
          : `No se pudo completar la acción (${response.status}).`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function notify(message, kind = "success") {
  state.notice = { message, kind };
  renderNotice();
}
function renderNotice() {
  const node = $("notice");
  node.hidden = !state.notice;
  if (!state.notice) {
    node.replaceChildren();
    return;
  }
  node.className = `notice ${state.notice.kind}`;
  node.setAttribute("role", state.notice.kind === "error" ? "alert" : "status");
  node.replaceChildren(
    button(
      "×",
      () => {
        state.notice = null;
        state.conflict = false;
        renderNotice();
      },
      "quiet",
      { className: "notice-close", "aria-label": "Cerrar aviso" },
    ),
    el("p", {}, state.notice.message),
  );
  if (state.conflict)
    node.append(
      el(
        "div",
        { className: "button-group" },
        button("Descargar mis cambios", downloadDraft, "secondary", {
          className: "button button-secondary button-small",
        }),
        button(
          "Cargar versión guardada",
          () => selectCase(state.current.id),
          "quiet",
          { className: "button button-quiet button-small" },
        ),
      ),
    );
}

async function perform(task) {
  if (state.busy) return;
  state.busy = true;
  render();
  try {
    await task();
  } catch (error) {
    state.conflict = error.status === 409;
    notify(
      state.conflict
        ? "Hay una versión más reciente del expediente. Conservamos tus cambios en esta pantalla. Descárgalos antes de cargar la versión guardada y compararlos."
        : error.message,
      "error",
    );
  } finally {
    state.busy = false;
    render();
    schedulePoll();
  }
}

function discardAllowed() {
  return (
    !state.dirty ||
    window.confirm(
      "Tienes cambios sin guardar. ¿Quieres descartarlos y continuar?",
    )
  );
}
function clearDraft() {
  state.draft = null;
  state.dirty = false;
  state.editingId = null;
  state.conflict = false;
}
function adopt(current, reset = false) {
  state.current = current;
  sources.setCase(current);
  drafts.setCase(current);
  reviews.setCase(current);
  offices.setCase(current);
  if (
    current.status === "confirmed" &&
    (!sources.state.loaded || !sources.state.mapping)
  )
    void sources.load({ quiet: true });
  if (
    current.status === "confirmed" &&
    !drafts.state.loaded &&
    !drafts.state.loading
  )
    void drafts.load({ quiet: true });
  if (
    current.status === "confirmed" &&
    (state.reviewing || state.responses) &&
    !reviews.state?.loaded &&
    !reviews.state?.loading
  )
    void reviews.load({ quiet: true });
  if (
    current.status === "confirmed" &&
    state.office &&
    !offices.state?.loaded &&
    !offices.state?.loading
  )
    void offices.load({ quiet: true });
  if (reset) {
    clearDraft();
    state.page = current.pages?.[0]?.number || 1;
    state.highlight = null;
  }
  if (
    !current.identification?.requests?.some(
      (item) => item.id === state.selectedId,
    )
  )
    state.selectedId = current.identification?.requests?.[0]?.id || null;
  if (reset) {
    const ref = current.identification?.requests?.find(
      (item) => item.id === state.selectedId,
    )?.source_refs?.[0];
    if (ref) {
      state.page = ref.page;
      state.highlight = { ...ref };
    }
  }
}
async function refreshCases() {
  const result = await api("/api/cases");
  state.cases = Array.isArray(result) ? result : result.cases || [];
}

async function selectCase(id) {
  if (state.busy || !discardAllowed()) return;
  await perform(async () => {
    const current = await api(`/api/cases/${encodeURIComponent(id)}`);
    adopt(current, true);
    state.library = false;
    state.responses = false;
    state.reviewing = false;
    state.office = false;
    state.notice = null;
    const url = new URL(location.href);
    url.searchParams.set("case", id);
    url.searchParams.delete("view");
    history.replaceState(null, "", url);
  });
}

function newCase() {
  if (state.busy || !discardAllowed()) return;
  clearDraft();
  state.current = null;
  state.sourceDetails=false;
  state.library = false;
  sources.setCase(null);
  drafts.setCase(null);
  reviews.setCase(null);
  offices.setCase(null);
  state.responses = false;
  state.reviewing = false;
  state.office = false;
  state.notice = null;
  const url = new URL(location.href);
  url.searchParams.delete("case");
  url.searchParams.delete("view");
  history.replaceState(null, "", url);
  render();
}

async function upload(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    notify("Selecciona un documento en formato PDF.", "error");
    return;
  }
  if (file.size > (state.config?.max_upload_mb || 20) * 1024 * 1024) {
    notify(
      `El PDF supera el límite de ${state.config?.max_upload_mb || 20} MB.`,
      "error",
    );
    return;
  }
  if (!discardAllowed()) return;
  await perform(async () => {
    const body = new FormData();
    body.append("file", file);
    const created = await api("/api/cases", { method: "POST", body });
    adopt(await api(`/api/cases/${encodeURIComponent(created.id)}`), true);
    const url = new URL(location.href);
    url.searchParams.set("case", created.id);
    history.replaceState(null, "", url);
    await refreshCases();
    notify(
      "Tu documento original está guardado. El siguiente paso es analizar la petición.",
    );
  });
}

async function demo() {
  if (!discardAllowed()) return;
  await perform(async () => {
    const created = await api("/api/cases/demo", {
      method: "POST",
      body: "{}",
    });
    adopt(await api(`/api/cases/${encodeURIComponent(created.id)}`), true);
    const url = new URL(location.href);
    url.searchParams.set("case", created.id);
    history.replaceState(null, "", url);
    await refreshCases();
    notify(
      "Cargamos un documento ficticio. Su identificación se está realizando con IA real.",
    );
  });
}

async function analyze() {
  await perform(async () => {
    const id = encodeURIComponent(state.current.id);
    await api(`/api/cases/${id}/analyze`, { method: "POST", body: "{}" });
    adopt(await api(`/api/cases/${id}`), true);
    state.notice = null;
    await refreshCases();
  });
}

function ensureDraft() {
  if (!state.draft) state.draft = structuredClone(state.current.identification);
}
function markDirty() {
  state.dirty = true;
  if ($("draft-label"))
    $("draft-label").textContent = "Tienes cambios sin guardar.";
  if ($("save-draft")) $("save-draft").disabled = state.busy;
  if ($("confirm-identification")) $("confirm-identification").disabled = true;
}
function edit(id) {
  ensureDraft();
  state.editingId = id;
  state.selectedId = id;
  render();
  document.querySelector(".editor input")?.focus();
}
function editIdentity() {
  ensureDraft();
  render();
  if($("identity-details"))$("identity-details").open = true;
  $("identity-details")?.querySelector("input")?.focus();
}
function cancelEdit() {
  if (!discardAllowed()) return;
  clearDraft();
  render();
}
function finishEdit() {
  state.editingId = null;
  render();
  $(`request-${state.selectedId}`)
    ?.querySelector(".request-select")
    ?.focus({ preventScroll: true });
}

function add(parentId = null) {
  ensureDraft();
  const requests = state.draft.requests;
  const parent = requests.find((item) => item.id === parentId);
  const id = `P${Math.max(0, ...requests.map((item) => Number(item.id.slice(1)) || 0)) + 1}`;
  let number = 1;
  while (
    requests.some(
      (item) =>
        item.label === (parent ? `${parent.label}.${number}` : String(number)),
    )
  )
    number++;
  requests.push({
    id,
    label: parent ? `${parent.label}.${number}` : String(number),
    title: "",
    description: "",
    parent_id: parentId,
    source_refs: [],
  });
  state.selectedId = id;
  state.editingId = id;
  markDirty();
  render();
  document.querySelector(".editor input")?.focus();
}
function remove(id) {
  const hasChildren = state.draft.requests.some(
    (item) => item.parent_id === id,
  );
  if (
    !window.confirm(
      hasChildren
        ? "¿Quitar esta solicitud y todos sus apartados? El original se conserva."
        : "¿Quitar esta solicitud de la identificación? El original se conserva.",
    )
  )
    return;
  const removed = new Set([id]);
  let changed = true;
  while (changed) {
    changed = false;
    state.draft.requests.forEach((item) => {
      if (removed.has(item.parent_id) && !removed.has(item.id)) {
        removed.add(item.id);
        changed = true;
      }
    });
  }
  state.draft.requests = state.draft.requests.filter(
    (item) => !removed.has(item.id),
  );
  state.editingId = null;
  state.selectedId = state.draft.requests[0]?.id || null;
  markDirty();
  render();
}

function validateDraft() {
  if (!state.draft?.subject?.trim())
    throw new Error("Escribe un asunto para la petición.");
  if (!state.draft.requests.length)
    throw new Error("Agrega al menos una solicitud antes de guardar.");
  for (const request of state.draft.requests) {
    if (
      !request.label?.trim() ||
      !request.title?.trim() ||
      !request.description?.trim()
    )
      throw new Error(
        `Completa el número, título y descripción de la solicitud ${request.label || "nueva"}.`,
      );
    if (!request.source_refs?.length)
      throw new Error(
        `Vincula al menos un fragmento del original a la solicitud ${request.label}.`,
      );
    for (const ref of request.source_refs) {
      const quote = quoteFor(state.current.pages || [], ref);
      if (!quote.trim())
        throw new Error(
          `Revisa la página y las líneas del fragmento en la solicitud ${request.label}.`,
        );
      ref.quote = quote;
    }
  }
  const ordered = [];
  const append = (parentId) =>
    state.draft.requests
      .filter((item) => item.parent_id === parentId)
      .forEach((item) => {
        ordered.push(item);
        append(item.id);
      });
  append(null);
  if (ordered.length !== state.draft.requests.length)
    throw new Error(
      "Revisa la relación entre las solicitudes: todas deben depender de una solicitud principal.",
    );
  state.draft.requests = ordered;
}
async function save() {
  if (!state.dirty) return;
  await perform(async () => {
    validateDraft();
    const current = await api(
      `/api/cases/${encodeURIComponent(state.current.id)}/identification`,
      {
        method: "PUT",
        body: JSON.stringify({
          version: state.current.version,
          identification: state.draft,
        }),
      },
    );
    adopt(current, false);
    clearDraft();
    await refreshCases();
    notify(`Cambios guardados. Estás revisando la versión ${current.version}.`);
  });
}
async function confirm() {
  if (state.dirty) {
    notify("Guarda tus cambios antes de confirmar.", "warning");
    return;
  }
  await perform(async () => {
    const id = encodeURIComponent(state.current.id);
    await api(`/api/cases/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ version: state.current.version }),
    });
    adopt(await api(`/api/cases/${id}`), true);
    await refreshCases();
    notify(
      "Identificación confirmada y guardada. Ahora puedes preparar las respuestas con las fuentes disponibles.",
    );
  });
}

function downloadDraft() {
  const blob = new Blob(
    [
      JSON.stringify(
        {
          case_id: state.current.id,
          base_version: state.current.version,
          identification: state.draft,
        },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  const url = URL.createObjectURL(blob);
  const anchor = el("a", {
    href: url,
    download: `cambios-${state.current.id}.json`,
  });
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function showSource(ref) {
  state.page=ref.page;state.highlight={...ref};render();
  $('original-title')?.focus({preventScroll:true});
}
function showPage(number){state.page=number;state.highlight=null;render();}
function renderOriginal(){render();}

function selectRequest(id) {
  state.selectedId = state.selectedId === id && !state.editingId ? null : id;
  const ref = (state.draft || state.current.identification)?.requests.find(
    (item) => item.id === state.selectedId,
  )?.source_refs?.[0];
  if (ref) {
    state.page = ref.page;
    state.highlight = { ...ref };
  }
  render();
  $(`request-${id}`)
    ?.querySelector(".request-select")
    ?.focus({ preventScroll: true });
}

const actions = {
  pickFile: () => $("file-picker").click(),
  upload,
  demo,
  analyze,
  select: selectRequest,
  edit,
  editIdentity,
  dirty: markDirty,
  cancelEdit,
  finishEdit,
  add,
  remove,
  save,
  confirm,
  source: showSource,
};

function renderSidebar() {
  $("case-count").textContent = state.cases.length;
  $("new-case").disabled = state.busy;
  $("open-library").disabled = state.busy;
  $("open-library").setAttribute(
    "aria-pressed",
    state.library ? "true" : "false",
  );
  $("case-list").replaceChildren(
    ...(state.cases.length
      ? state.cases.map((current) =>
          el(
            "button",
            {
              type: "button",
              className: `case-item ${current.id === state.current?.id ? "active" : ""}`,
              "aria-current": current.id === state.current?.id ? "page" : null,
              onClick: () => selectCase(current.id),
              disabled: state.busy,
              title: current.subject || current.filename,
            },
            el(
              "span",
              { className: "case-item-title" },
              current.subject ||
                current.filename.replace(/_/g, " ").replace(/\.pdf$/i, ""),
            ),
            el(
              "span",
              { className: "case-item-date" },
              dateLabel(current.created_at),
            ),
            el(
              "div",
              { className: "case-item-status" },
              statusLabel(current.status),
            ),
          ),
        )
      : [
          el(
            "p",
            { className: "sidebar-empty" },
            "Tus peticiones aparecerán aquí. Cada expediente conserva su propio avance.",
          ),
        ]),
  );
}

let releaseSplit=()=>{};
function render() {
  const focus=document.activeElement,focusedId=focus?.id,start=focus?.selectionStart,end=focus?.selectionEnd;
  const scroll=document.querySelector('.original-scroll')?.scrollTop;
  releaseSplit();renderSidebar();renderNotice();
  $('validation-banner').hidden=!state.config?.validation_mode;
  const current=state.current, stage=state.office?3:state.responses||state.reviewing?2:1;
  $('connection-state').textContent=state.config?.ready?'IA disponible':'IA pendiente de configuración';
  $('connection-state').className='connection-state '+(state.config?.ready?'ready':'unavailable');
  $('previous-interface').href='/anterior'+(current?'?case='+encodeURIComponent(current.id):'');
  document.querySelectorAll('[data-stage]').forEach(b=>{b.setAttribute('aria-current',Number(b.dataset.stage)===stage?'step':'false');b.disabled=state.busy || (!current&&b.dataset.stage!=='1') || (current?.status!=='confirmed'&&b.dataset.stage!=='1');});
  document.querySelector('.journey').hidden=state.library||!current;
  $('workspace-kicker').textContent=state.library?'FUENTES DE CONSULTA':current?`EXPEDIENTE · PASO ${stage} DE 3`:'INICIO';
  document.querySelector('.workspace-heading h1').textContent=state.library?'Biblioteca de fuentes':!current?'Prepara respuestas con respaldo':stage===1?'Primero, qué nos están solicitando':stage===2?'Respuestas para revisar':'Una respuesta institucional completa';
  document.querySelector('.page-intro').textContent=state.library?'Organiza los documentos de consulta, sus versiones y su procedencia.':!current?'Carga una petición o continúa uno de tus expedientes.':stage===1?'Revisa cada solicitud y consulta el pasaje del documento del que se obtuvo.':stage===2?'Lee la propuesta, consulta el respaldo y atiende cada pendiente en su respuesta.':'Revisa el contenido aprobado y prepara el oficio en Word y PDF.';
  actions.busy=state.busy;actions.ready=state.config?.ready;
  let content;
  if(state.library)content=sources.libraryView();
  else if(!current)content=welcome(state.config,actions);
  else if(stage===1){
    const identification=state.draft||current.identification;
    content=el('div',{},el('div',{className:'case-summary'},el('span',{},current.filename),el('span',{},`${current.request_count} solicitudes · ${statusLabel(current.status)}`)));
    if(identification && ['confirmed','needs_review'].includes(current.status)){
      const cards=state.draft?el('div',{id:'requests-pane',className:'identified-requests'},requestsView(state,actions)):identificationCards(state,{...actions,selectSource:(id,ref)=>{state.selectedId=id;showSource(ref);}});
      content.append(el('div',{className:'understanding-layout'},cards,divider(),documentPanel(state,api,showPage)));
      if(!state.draft){
        if(identification.warnings?.length)content.append(el('details',{},el('summary',{},'Observaciones de identificación'),el('ul',{},identification.warnings.map(w=>el('li',{},typeof w==='string'?w:w.message)))));
        content.append(el('div',{className:'actionbar'},el('p',{},current.status==='confirmed'?'Identificación confirmada y guardada.':'Comprueba que esta lista refleje lo pedido en el documento.'),current.status==='confirmed'?button('Preparar las respuestas →',()=>{openResponses();void prepareResponses();},'primary'):button('Confirmar identificación',confirm,'primary',{id:'confirm-identification',disabled:state.busy}),current.status==='needs_review'?button('Corregir identificación',editIdentity,'quiet'):null));
      }
      content.append(el('details',{},el('summary',{},'Datos y trazabilidad de la identificación'),metadata(current,identification),processView(current)));
    }else content.append(progress(current,actions),documentPanel(state,api,showPage));
  }else if(stage===3)content=offices.view();
  else if(state.reviewing)content=el('div',{},button('← Volver a las respuestas',openResponses,'quiet'),reviews.view());
  else {
    content=responseCards(state,sources,drafts,reviews,{prepare:prepareResponses,upload:id=>intake.uploadForm(id,false),office:openOffice,review:id=>{if(reviews.state)reviews.state.selected=id;openReview();},supports:showSupports});
    const advanced=el('details',{className:'advanced-sources',id:'sources-detail',open:Boolean(state.sourceDetails)},el('summary',{},'Bibliotecas vinculadas, búsqueda y comprobaciones'),sources.caseView());
    advanced.ontoggle=()=>{state.sourceDetails=advanced.open;};content.append(advanced);
  }
  $('work-content').replaceChildren(content);
  if(state.pipelineText)$('work-content').prepend(el('div',{className:'pipeline-status',role:'status'},el('progress',{'aria-label':'Preparación de respuestas'}),state.pipelineText));
  releaseSplit=bindSplitPane();
  if(scroll!=null&&document.querySelector('.original-scroll'))document.querySelector('.original-scroll').scrollTop=scroll;
  if(state.busy)$('work-content').querySelectorAll('button,input,textarea,select').forEach(c=>c.disabled=true);
  document.title=(state.library?'Biblioteca de fuentes':'Gestión de Peticiones');
  if(focusedId){const f=$(focusedId);f?.focus({preventScroll:true});if(start!=null&&f?.setSelectionRange){try{f.setSelectionRange(start,end);}catch{}}}
}

function setResponseStage(value) {
  state.responses = value;
  state.reviewing = false;
  state.office = false;
  state.library = false;
  const url = new URL(location.href);
  if (value) url.searchParams.set("view", "drafts");
  else url.searchParams.delete("view");
  history.replaceState(null, "", url);
  render();
}
function openResponses() {
  setResponseStage(true);
  void reviews.load({quiet:true});
  void sources.load({ quiet: true });
  void drafts.load({ quiet: true });
}
function openSources() {
  state.sourceDetails=true;
  setResponseStage(true);
  void sources.load({ quiet: true });
}
function openReview() {
  state.responses = false;
  state.reviewing = true;
  state.office = false;
  state.library = false;
  const url = new URL(location.href);
  url.searchParams.set("view", "review");
  history.replaceState(null, "", url);
  render();
  void sources.load({ quiet: true });
  void drafts.load({ quiet: true });
  void reviews.load({ quiet: true });
}
function openOffice() {
  state.responses = false;
  state.reviewing = false;
  state.office = true;
  state.library = false;
  const url = new URL(location.href);
  url.searchParams.set("view", "office");
  history.replaceState(null, "", url);
  render();
  void offices.load({ quiet: true });
}

function openLibrary() {
  if (state.busy) return;
  state.library = true;
  sources.setCase(state.current);
  void sources.load();
}
function closeLibrary() {
  state.library = false;
  render();
  if (state.responses) void drafts.load({ quiet: true });
  if (state.reviewing) void reviews.load({ quiet: true });
  if (state.office) void offices.load({ quiet: true });
  $("workspace").focus({ preventScroll: true });
}
const sources = createSources({
  api,
  notify,
  getCase: () => state.current,
  render,
  openLibrary,
  closeLibrary,
  uploadEvidence:previous=>intake.uploadForm('', previous?previous.case_id===null:true, previous),
});
const drafts = createDrafts({
  api,
  notify,
  getCase: () => state.current,
  getSources: () => sources.state.mapping,
  render,
  showSource: (id, ref) => sources.showSource(id, ref),
  back: openSources,
  review: openReview,
});
const reviews = createReview({
  api,
  notify,
  getCase: () => state.current,
  getDrafts: () => drafts.state.run,
  getSources: () => sources.state.mapping,
  render,
  showSource: (id, ref) => sources.showSource(id, ref),
  openSources,
  openLibrary,
  openOffice,
});
const offices = createOffice({
  api,
  notify,
  getCase: () => state.current,
  hasReviewChanges: (caseId) => reviews.hasUnsavedFor(caseId),
  render,
  back: openReview,
});

function schedulePoll() {
  clearTimeout(state.poll);
  if (
    state.cases.some((item) => running(item.status)) ||
    running(state.current?.status)
  )
    state.poll = setTimeout(poll, 1600);
}
async function poll() {
  if (state.busy) {
    schedulePoll();
    return;
  }
  try {
    await refreshCases();
    if (state.current && running(state.current.status) && !state.draft) {
      const requestedId = state.current.id;
      const updated = await api(
        `/api/cases/${encodeURIComponent(requestedId)}`,
      );
      if (state.busy || state.draft || state.current?.id !== requestedId) {
        schedulePoll();
        return;
      }
      adopt(updated);
      if (updated.status === "needs_review")
        notify(
          "La identificación está lista. Revisa las solicitudes y contrástalas con el original.",
        );
      render();
    } else renderSidebar();
  } catch (error) {
    notify(
      `${error.message} El expediente conserva su último avance.`,
      "warning",
    );
  }
  schedulePoll();
}

const drawer=$('drawer');let drawerOpener;
function openPanel(title,html){drawerOpener=document.activeElement;$('drawer-title').textContent=title;$('drawer-body').innerHTML=html;if(!drawer.open)drawer.showModal();}
$('close').onclick=()=>drawer.close();
drawer.addEventListener('close',()=>{if(drawerOpener?.isConnected)drawerOpener.focus();else $('workspace').focus();});
const intake=createEvidenceUpload({open:openPanel,close:()=>drawer.close(),render,notice:notify,getCase:()=>state.current,getData:()=>({requests:(state.current?.identification?.requests||[]).map(r=>({...r,request_id:r.id}))}),changed:()=>{},onUpdated:async receipt=>{
  await sources.load({quiet:true});
  if(state.current?.id===receipt.case_id){await Promise.all([drafts.load({quiet:true}),reviews.load({quiet:true})]);}
}});
async function showSupports(request,supports){
  openPanel('Respaldo de la solicitud '+request.label,'');
  const body=$('drawer-body');body.append(el('p',{},request.description));
  if(!supports.length)body.append(el('p',{},'Todavía no hay pasajes seleccionados para esta solicitud.'));
  for(const support of supports)body.append(el('section',{className:'source'},el('h3',{},support.title),el('p',{},`Versión ${support.version||1} · ${support.location_kind==='section'?'Sección':'Página'} ${support.page}`),el('blockquote',{},support.quote),el('p',{},support.reason||''),button('Abrir fuente y su revisión',()=>{drawer.close();sources.showSource(support.source_id,support);},'quiet')));
}
async function waitStage(path,runningStatus,onValue){
  const deadline=Date.now()+20*60*1000;
  while(Date.now()<deadline){const run=await api(path);onValue(run);render();if(run.status!==runningStatus)return run;await new Promise(r=>setTimeout(r,2000));}
  throw new Error('El proceso continúa guardado. Actualiza el estado para consultar su avance.');
}
async function prepareResponses(){
  if(state.current?.status!=='confirmed')return;
  await perform(async()=>{
    const current=state.current,prefix='/api/cases/'+encodeURIComponent(current.id),body=JSON.stringify({version:current.version});
    try{
      state.pipelineText='Buscando respaldo para las solicitudes…';render();
      await api(prefix+'/sources/search',{method:'POST',body});
      const map=await waitStage(prefix+'/sources','running',run=>{sources.state.mapping=run;state.pipelineText=`Revisando fuentes: ${run.completed_count||0} de ${current.request_count} solicitudes`;});
      if(map.stale||map.status!=='ready')throw new Error(map.error||'Hay errores de análisis por resolver. Consulta el resultado de cada solicitud.');
      const savedReview=await api(prefix+'/review');
      if(!savedReview.requests?.length){
        state.pipelineText='Redactando las respuestas con los pasajes encontrados…';render();
        await api(prefix+'/drafts/generate',{method:'POST',body});
        const run=await waitStage(prefix+'/drafts','running',value=>{drafts.state.run=value;drafts.state.loaded=true;state.pipelineText=`Preparando respuestas: ${value.completed_count||0} de ${current.request_count}`;});
        if(run.stale||!['ready','partial'].includes(run.status)||run.results?.some(r=>r.error))throw new Error(run.error||'Revisa los errores de redacción antes de continuar.');
      }
      await api(prefix+'/review/start',{method:'POST',body});
      await Promise.all([sources.load({quiet:true}),drafts.load({quiet:true}),reviews.load({quiet:true})]);
      notify('Respuestas disponibles para revisión. Los textos previamente editados se conservaron.');
    }finally{state.pipelineText=null;}
  });
}
function setWorkspace(open){$('workspace-menu').hidden=!open;document.body.classList.toggle('workspace-expanded',open);$('workspace-toggle').setAttribute('aria-expanded',String(open));$('workspace-toggle').setAttribute('aria-label',open?'Plegar espacio de trabajo':'Abrir espacio de trabajo');}
$('workspace-toggle').onclick=()=>setWorkspace($('workspace-menu').hidden);
$('workspace-menu').onkeydown=e=>{if(e.key==='Escape'){setWorkspace(false);$('workspace-toggle').focus();}};
document.querySelectorAll('[data-stage]').forEach(b=>b.onclick=()=>{
  if(state.busy||!discardAllowed())return;
  if(b.dataset.stage==='3')openOffice();else if(b.dataset.stage==='2')openResponses();else{state.responses=false;state.reviewing=false;state.office=false;state.library=false;const url=new URL(location.href);url.searchParams.delete('view');history.replaceState(null,'',url);render();}
});

$("new-case").addEventListener("click", newCase);
const sidebarLayout = window.matchMedia("(min-width: 768px)");
$("sidebar-cases").open = sidebarLayout.matches;
sidebarLayout.addEventListener("change", (event) => {
  $("sidebar-cases").open = event.matches;
});
$("open-library").addEventListener("click", openLibrary);
$("file-picker").addEventListener("change", (event) => {
  upload(event.target.files[0]);
  event.target.value = "";
});
window.addEventListener("beforeunload", (event) => {
  if (state.dirty || reviews.hasUnsaved() || offices.hasUnprotectedChanges()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
document.querySelector(".brand").addEventListener("click", (event) => {
  event.preventDefault();
  newCase();
});
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());

async function init() {
  const results = await Promise.allSettled([
    api("/api/config"),
    refreshCases(),
  ]);
  if (results[0].status === "fulfilled") state.config = results[0].value;
  else notify(results[0].reason.message, "error");
  if (results[1].status === "rejected")
    notify(results[1].reason.message, "error");
  const id = new URL(location.href).searchParams.get("case");
  if (id) {
    try {
      adopt(await api(`/api/cases/${encodeURIComponent(id)}`), true);
    } catch (error) {
      notify(error.message, "error");
    }
  }
  render();
  schedulePoll();
}
init();
