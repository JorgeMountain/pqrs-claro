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
} from "./ui.js";
import { requestsView, quoteFor } from "./requests.js";
import { createSources } from "./sources.js";

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
  if (
    current.status === "confirmed" &&
    (!sources.state.loaded || !sources.state.mapping)
  )
    void sources.load({ quiet: true });
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
    state.notice = null;
    const url = new URL(location.href);
    url.searchParams.set("case", id);
    history.replaceState(null, "", url);
  });
}

function newCase() {
  if (state.busy || !discardAllowed()) return;
  clearDraft();
  state.current = null;
  state.library = false;
  sources.setCase(null);
  state.notice = null;
  const url = new URL(location.href);
  url.searchParams.delete("case");
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
  $("identity-details").open = true;
  $("identity-details").querySelector("input")?.focus();
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
      "Identificación confirmada y guardada. El siguiente paso es agregar los soportes y buscar fuentes para cada solicitud.",
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
  state.page = ref.page;
  state.highlight = { ...ref };
  renderOriginal();
  const panel = $("original-panel");
  if (window.innerWidth < 1000)
    panel?.scrollIntoView({ behavior: "smooth", block: "start" });
  else
    panel
      ?.querySelector(".line-list .highlight")
      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function showPage(number) {
  state.page = number;
  state.highlight = null;
  renderOriginal();
}
function renderOriginal() {
  if (state.current)
    $("original-panel")?.replaceWith(
      original(state.current, state.page, state.highlight, showPage),
    );
}

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
            },
            el(
              "span",
              { className: "case-item-title" },
              current.subject || current.filename,
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

function render() {
  const processOpen = $("process-details")?.open;
  const identityOpen = $("identity-details")?.open;
  renderSidebar();
  renderNotice();
  const status = state.current?.status;
  const stage =
    status === "confirmed"
      ? 3
      : !status || status === "uploaded"
        ? 0
        : running(status) || status === "error"
          ? 1
          : 2;
  ["step-upload", "step-analyze", "step-review", "step-sources"].forEach(
    (id, index) => {
      $(id).className =
        index < stage ? "done" : index === stage ? "active" : "";
      $(id).setAttribute("aria-current", index === stage ? "step" : "false");
    },
  );
  const configNode = $("connection-state");
  configNode.className = `connection-state ${state.config?.ready ? "ready" : "unavailable"}`;
  configNode.textContent = state.config?.ready
    ? "Análisis con IA disponible"
    : "IA pendiente de configuración";
  const current = state.current;
  const sourcesStage = current?.status === "confirmed";
  document.querySelector(".workspace-heading h1").textContent = state.library
    ? "Biblioteca de fuentes"
    : sourcesStage
      ? "Encontrar el respaldo"
      : "Entender la petición";
  document.querySelector(".page-intro").textContent = state.library
    ? "Organiza los documentos que sirven de consulta y soporte."
    : sourcesStage
      ? "Comprueba qué tenemos para cada solicitud y qué falta aportar."
      : "Identifica qué se solicita y compruébalo con el original.";
  document.querySelector(".journey").hidden = state.library;
  actions.busy = state.busy;
  actions.ready = state.config?.ready;
  if (state.library) $("work-content").replaceChildren(sources.libraryView());
  else if (!current)
    $("work-content").replaceChildren(welcome(state.config, actions));
  else {
    const identity = state.draft || current.identification;
    const main = el(
      "div",
      { className: "case-main" },
      metadata(current, identity),
    );
    if (["needs_review", "confirmed"].includes(current.status) && identity)
      main.append(requestsView(state, actions));
    else main.append(progress(current, actions));
    main.append(processView(current));
    const identificationGrid = el(
      "div",
      { className: "case-grid" },
      main,
      original(current, state.page, state.highlight, showPage),
    );
    const identificationOpen = $("confirmed-identification")?.open;
    $("work-content").replaceChildren(
      el(
        "div",
        { className: "case-topline" },
        el(
          "div",
          {},
          el(
            "p",
            { className: "case-title" },
            identity?.subject || "Petición por identificar",
          ),
          el(
            "p",
            { className: "case-file" },
            `${current.filename} · Versión ${current.version || 1}`,
          ),
        ),
        el(
          "span",
          {
            className: `badge ${running(status) ? "running" : status === "error" ? "error" : ""}`,
          },
          statusLabel(status),
        ),
      ),
      ...(sourcesStage
        ? [
            sources.caseView(),
            el(
              "details",
              {
                className: "confirmed-identification",
                id: "confirmed-identification",
                open: Boolean(identificationOpen),
              },
              el(
                "summary",
                {},
                "Consultar la identificación confirmada y el original",
              ),
              identificationGrid,
            ),
          ]
        : [identificationGrid]),
    );
    if (processOpen && $("process-details")) $("process-details").open = true;
    if (identityOpen && $("identity-details"))
      $("identity-details").open = true;
  }
  if (state.busy)
    $("work-content")
      .querySelectorAll("button,input,textarea,select")
      .forEach((control) => {
        control.disabled = true;
      });
  document.title = state.library
    ? "Biblioteca de fuentes · PQRS Claro"
    : current
      ? `${current.filename} · PQRS Claro`
      : "PQRS Claro · Entender la petición";
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
  $("workspace").focus({ preventScroll: true });
}
const sources = createSources({
  api,
  notify,
  getCase: () => state.current,
  render,
  openLibrary,
  closeLibrary,
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

$("new-case").addEventListener("click", newCase);
$("open-library").addEventListener("click", openLibrary);
$("file-picker").addEventListener("change", (event) => {
  upload(event.target.files[0]);
  event.target.value = "";
});
window.addEventListener("beforeunload", (event) => {
  if (state.dirty) {
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
